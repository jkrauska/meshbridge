#!/usr/bin/env python3

"""
Meshtastic Serial Bridge Manager
Interactive tool to discover and bridge serial Meshtastic devices to TCP
"""

import sys
import glob
import subprocess
import signal
import time
import re
from typing import List, Optional

# Try to import meshtastic library
try:
    import meshtastic.serial_interface

    MESHTASTIC_AVAILABLE = True
except ImportError:
    MESHTASTIC_AVAILABLE = False

# Try to import zeroconf for mDNS
try:
    from zeroconf import ServiceInfo, Zeroconf
    import socket

    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False


class Colors:
    """ANSI color codes for terminal output"""

    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"
    BOLD = "\033[1m"


class SerialDevice:
    """Represents a serial device"""

    def __init__(self, path: str, description: str = "", node_name: str = ""):
        self.path = path
        self.description = description
        self.node_name = node_name

    def __str__(self):
        parts = [self.path]
        if self.node_name:
            parts.append(f"{Colors.GREEN}{self.node_name}{Colors.END}")
        if self.description:
            parts.append(self.description)

        if len(parts) > 1:
            return f"{parts[0]} ({', '.join(parts[1:])})"
        return parts[0]


class Bridge:
    """Manages a socat bridge process with optional mDNS announcement"""

    def __init__(self, device: str, port: int, node_id: str = None, baud: int = 115200):
        self.device = device
        self.port = port
        self.node_id = node_id
        self.baud = baud
        self.process: Optional[subprocess.Popen] = None
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None

    def start(self) -> bool:
        """Start the bridge and mDNS announcement"""
        try:
            # Set serial port parameters with stty
            stty_cmd = ["stty", "-f", self.device, str(self.baud), "raw", "-echo"]
            subprocess.run(stty_cmd, check=True, capture_output=True)

            # Start socat bridge
            socat_cmd = [
                "socat",
                "-d",
                "-d",
                f"TCP-LISTEN:{self.port},reuseaddr,fork",
                f"OPEN:{self.device},nonblock=1",
            ]

            self.process = subprocess.Popen(
                socat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )

            # Start mDNS announcement if available
            if ZEROCONF_AVAILABLE and self.node_id:
                self._start_mdns()

            return True
        except Exception as e:
            print(f"{Colors.RED}Error starting bridge: {e}{Colors.END}")
            return False

    def _start_mdns(self):
        """Start mDNS/Zeroconf announcement"""
        try:
            # Extract short node ID (last 4 chars) for hostname
            # e.g., !3c7f9d4e -> 9d4e
            short_id = self.node_id.replace("!", "")[-4:]
            hostname = f"meshtastic_{short_id}.local."

            # Get local IP address
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()

            self.zeroconf = Zeroconf()

            # Register as _meshtastic._tcp.local. service
            self.service_info = ServiceInfo(
                "_meshtastic._tcp.local.",
                f"{hostname[:-7]}._meshtastic._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=self.port,
                properties={
                    "node_id": self.node_id,
                    "device": self.device,
                },
                server=hostname,
            )

            self.zeroconf.register_service(self.service_info)
        except Exception as e:
            # mDNS is optional, don't fail the bridge if it doesn't work
            print(f"{Colors.YELLOW}Warning: mDNS announcement failed: {e}{Colors.END}")

    def stop(self):
        """Stop the bridge and mDNS announcement"""
        # Stop mDNS announcement
        if self.zeroconf and self.service_info:
            try:
                self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
            except Exception:
                pass
            self.zeroconf = None
            self.service_info = None

        # Stop socat process
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def is_running(self) -> bool:
        """Check if bridge is running"""
        return self.process is not None and self.process.poll() is None


def check_dependencies() -> bool:
    """Check if required tools are installed"""
    socat_ok = True
    try:
        subprocess.run(["socat", "-V"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{Colors.RED}Error: socat is not installed{Colors.END}")
        if sys.platform == "darwin":
            print("Install with: brew install socat")
        else:
            print("Install with: apt-get install socat")
        socat_ok = False

    if not MESHTASTIC_AVAILABLE:
        print(
            f"{Colors.YELLOW}Note: meshtastic library not found - device names will not be shown{Colors.END}"
        )
        print("Install with: pip install meshtastic")
        print()

    if not ZEROCONF_AVAILABLE:
        print(
            f"{Colors.YELLOW}Note: zeroconf library not found - mDNS announcements disabled{Colors.END}"
        )
        print("Install with: pip install zeroconf")
        print()

    return socat_ok


def query_meshtastic_info(
    device_path: str, timeout: int = 10, verbose: bool = False
) -> Optional[str]:
    """Try to query the device for its Meshtastic node ID and owner"""
    if not MESHTASTIC_AVAILABLE:
        return None

    try:
        # Temporarily connect to get node info - don't request full nodeDB
        interface = meshtastic.serial_interface.SerialInterface(
            devPath=device_path,
            noProto=False,
            debugOut=None,  # Suppress debug output
            noNodes=True,  # Don't download node database
        )

        # Poll for myInfo with timeout
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Get our node number and owner from myInfo
            if hasattr(interface, "myInfo") and interface.myInfo:
                my_info = interface.myInfo
                if hasattr(my_info, "my_node_num") and my_info.my_node_num:
                    my_node_num = my_info.my_node_num
                    node_id = f"!{my_node_num:08x}"

                    # Try to get owner name from multiple sources
                    owner = None

                    # Check myInfo.user
                    if hasattr(my_info, "user") and my_info.user:
                        if hasattr(my_info.user, "longName") and my_info.user.longName:
                            owner = my_info.user.longName
                        elif (
                            hasattr(my_info.user, "shortName")
                            and my_info.user.shortName
                        ):
                            owner = my_info.user.shortName

                    # Check localConfig.owner if available
                    if (
                        not owner
                        and hasattr(interface, "localNode")
                        and interface.localNode
                    ):
                        if (
                            hasattr(interface.localNode, "owner")
                            and interface.localNode.owner
                        ):
                            owner = interface.localNode.owner
                        elif (
                            hasattr(interface.localNode, "longName")
                            and interface.localNode.longName
                        ):
                            owner = interface.localNode.longName

                    # If we have owner info, return it; otherwise keep polling
                    if owner:
                        interface.close()
                        return f"{node_id} ({owner})"

                    # If we've waited long enough and still no owner, just return the ID
                    if time.time() - start_time > 5:
                        interface.close()
                        return node_id

            time.sleep(0.2)  # Poll every 200ms

        # Close the connection
        interface.close()

        if verbose:
            print(f"{Colors.YELLOW}timeout{Colors.END}", end="", flush=True)

        return None
    except Exception as e:
        if verbose:
            print(f"{Colors.YELLOW}error: {e}{Colors.END}", end="", flush=True)
        return None


def find_serial_devices(
    query_names: bool = True, skip_devices: set = None
) -> List[SerialDevice]:
    """Find potential serial devices"""
    devices = []
    skip_devices = skip_devices or set()

    # Skip devices that match this pattern (likely not Meshtastic)
    # Example: /dev/cu.usbmodemM4AE1CAEMD6 (long alphanumeric suffix)
    skip_pattern = re.compile(r"/dev/cu\.usbmodem[A-Z0-9]{10,}")

    print(f"{Colors.BOLD}Searching for serial devices...{Colors.END}")

    if sys.platform == "darwin":
        # macOS - look for USB serial devices
        patterns = ["/dev/tty.usb*", "/dev/cu.usb*", "/dev/tty.SLAB*", "/dev/cu.SLAB*"]

        for pattern in patterns:
            for path in glob.glob(pattern):
                # Skip devices with active bridges
                if path in skip_devices:
                    print(
                        f"  {path}... {Colors.GREEN}skipped (bridge already active){Colors.END}"
                    )
                    continue

                # Skip devices matching the exclusion pattern
                if skip_pattern.match(path):
                    print(
                        f"  {path}... {Colors.YELLOW}skipped due to excluded pattern match{Colors.END}"
                    )
                    continue

                # Prefer cu.* devices for macOS
                if path.startswith("/dev/cu."):
                    desc = "USB Serial"
                    if "SLAB" in path:
                        desc = "CP210x USB-Serial"
                    elif "usbmodem" in path:
                        desc = "Native USB"
                    elif "usbserial" in path:
                        desc = "USB Serial (CH340/FTDI)"
                    devices.append(SerialDevice(path, desc))
    else:
        # Linux - look for USB serial devices
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]

        for pattern in patterns:
            for path in glob.glob(pattern):
                desc = "USB Serial"
                if "ACM" in path:
                    desc = "Native USB (ACM)"
                elif "USB" in path:
                    desc = "USB Serial Adapter"
                devices.append(SerialDevice(path, desc))

    # Query each device for Meshtastic info
    if query_names and MESHTASTIC_AVAILABLE and devices:
        print(f"\n{Colors.YELLOW}Querying devices for node IDs...{Colors.END}")
        for device in devices:
            print(f"  {device.path}... ", end="", flush=True)
            node_id = query_meshtastic_info(device.path, timeout=10, verbose=True)
            if node_id:
                device.node_name = node_id
                print(f"{Colors.GREEN}{node_id}{Colors.END}")
            else:
                print(f"{Colors.YELLOW}timeout{Colors.END}")
        print()

    return devices


def get_next_available_port(start_port: int = 4403, bridges: List[Bridge] = []) -> int:
    """Find the next available port"""
    used_ports = {b.port for b in bridges if b.is_running()}
    port = start_port
    while port in used_ports:
        port += 1
    return port


def print_header():
    """Print application header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}╔════════════════════════════════════════╗")
    print("║    Meshtastic Serial Bridge Manager    ║")
    print(f"╚════════════════════════════════════════╝{Colors.END}\n")


def print_bridges(bridges: List[Bridge]):
    """Print active bridges"""
    if not bridges:
        return

    active_bridges = [b for b in bridges if b.is_running()]
    if not active_bridges:
        return

    print(f"\n{Colors.BOLD}Active Bridges:{Colors.END}")
    for i, bridge in enumerate(active_bridges, 1):
        node_info = (
            f" ({Colors.GREEN}{bridge.node_id}{Colors.END})" if bridge.node_id else ""
        )
        print(
            f"  {Colors.GREEN}[{i}]{Colors.END} {bridge.device}{node_info} → TCP port {bridge.port}"
        )


def yolo_mode():
    """YOLO mode - automatically bridge the first device found"""
    print(f"{Colors.BOLD}{Colors.CYAN}🚀 YOLO MODE ACTIVE 🚀{Colors.END}\n")

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    bridges: List[Bridge] = []

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print(f"\n\n{Colors.YELLOW}Shutting down bridges...{Colors.END}")
        for bridge in bridges:
            if bridge.is_running():
                bridge.stop()
        print(f"{Colors.GREEN}Done.{Colors.END}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Find devices
    devices = find_serial_devices()

    if not devices:
        print(f"{Colors.RED}No serial devices found.{Colors.END}")
        sys.exit(1)

    # Get first device with a node ID
    device = None
    for d in devices:
        if d.node_name:
            device = d
            break

    if not device:
        print(f"{Colors.RED}No devices with valid node IDs found.{Colors.END}")
        sys.exit(1)

    # Create bridge on default port
    port = 4403
    print(f"\n{Colors.GREEN}Auto-bridging device: {device}{Colors.END}")
    print(f"{Colors.YELLOW}Starting bridge on port {port}...{Colors.END}\n")

    bridge = Bridge(device.path, port, node_id=device.node_name)

    if bridge.start():
        bridges.append(bridge)
        print(f"{Colors.GREEN}✓ Bridge started successfully!{Colors.END}\n")
        print(f"{Colors.BOLD}Connection details:{Colors.END}")
        print(f"  Device: {device}")
        print(f"  TCP Port: {port}")
        print(f"  Connect to: localhost:{port}")

        if ZEROCONF_AVAILABLE and device.node_name:
            short_id = device.node_name.replace("!", "")[-4:]
            print(f"  mDNS: meshtastic_{short_id}.local:{port}")

        print(f"\n{Colors.CYAN}Bridge running. Press Ctrl+C to stop.{Colors.END}\n")

        # Keep running until interrupted
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            signal_handler(None, None)
    else:
        print(f"{Colors.RED}Failed to start bridge{Colors.END}")
        sys.exit(1)


def main():
    """Main application loop"""
    # Check for --yolo flag
    if len(sys.argv) > 1 and sys.argv[1] == "--yolo":
        yolo_mode()
        return

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    bridges: List[Bridge] = []

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print(f"\n\n{Colors.YELLOW}Shutting down bridges...{Colors.END}")
        for bridge in bridges:
            if bridge.is_running():
                bridge.stop()
        print(f"{Colors.GREEN}Done.{Colors.END}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    devices = []  # Cache devices list
    need_scan = True  # Flag to control when to scan

    while True:
        print_header()
        print_bridges(bridges)

        # Only scan when needed
        if need_scan:
            # Find devices, skipping ones with active bridges
            active_device_paths = {b.device for b in bridges if b.is_running()}
            devices = find_serial_devices(skip_devices=active_device_paths)
            need_scan = False  # Don't scan again unless explicitly requested

        if not devices:
            print(f"{Colors.YELLOW}No serial devices found.{Colors.END}")
            print("\nMake sure your Meshtastic device is connected via USB.")
            print(f"\n{Colors.BOLD}Options:{Colors.END}")
            print(f"  {Colors.CYAN}[r]{Colors.END} Refresh / search again")
            print(f"  {Colors.CYAN}[q]{Colors.END} Quit")

            choice = (
                input(f"\n{Colors.BOLD}Choose an option:{Colors.END} ").strip().lower()
            )

            if choice == "q":
                for bridge in bridges:
                    if bridge.is_running():
                        bridge.stop()
                sys.exit(0)
            elif choice == "r":
                need_scan = True
                continue
            else:
                print(f"{Colors.RED}Invalid option{Colors.END}")
                time.sleep(1)
                continue

        # Display devices and check which ones have active bridges
        active_device_paths = {b.device for b in bridges if b.is_running()}

        print(f"\n{Colors.BOLD}Found {len(devices)} device(s):{Colors.END}")
        for i, device in enumerate(devices, 1):
            if device.path in active_device_paths:
                # Find the bridge for this device
                bridge_port = next(
                    (
                        b.port
                        for b in bridges
                        if b.device == device.path and b.is_running()
                    ),
                    None,
                )
                print(
                    f"  {Colors.CYAN}[{i}]{Colors.END} {device} {Colors.GREEN}[Bridge active on port {bridge_port}]{Colors.END}"
                )
            else:
                print(f"  {Colors.CYAN}[{i}]{Colors.END} {device}")

        # Display options
        print(f"\n{Colors.BOLD}Options:{Colors.END}")
        print(f"  {Colors.CYAN}[1-{len(devices)}]{Colors.END} Create bridge for device")
        if bridges:
            print(f"  {Colors.CYAN}[s]{Colors.END} Stop all bridges")
        print(f"  {Colors.CYAN}[r]{Colors.END} Refresh / search again")
        print(f"  {Colors.CYAN}[q]{Colors.END} Quit")

        # Get user choice
        choice = input(f"\n{Colors.BOLD}Choose an option:{Colors.END} ").strip().lower()

        if choice == "q":
            for bridge in bridges:
                if bridge.is_running():
                    bridge.stop()
            sys.exit(0)
        elif choice == "r":
            need_scan = True
            continue
        elif choice == "s" and bridges:
            print(f"\n{Colors.YELLOW}Stopping all bridges...{Colors.END}")
            for bridge in bridges:
                if bridge.is_running():
                    bridge.stop()
            bridges.clear()
            need_scan = True  # Rescan after stopping bridges
            print(f"{Colors.GREEN}All bridges stopped.{Colors.END}")
            time.sleep(1)
            continue
        elif choice.isdigit():
            device_index = int(choice) - 1
            if 0 <= device_index < len(devices):
                device = devices[device_index]

                # Check if this device already has a bridge
                if device.path in active_device_paths:
                    existing_bridge = next(
                        (
                            b
                            for b in bridges
                            if b.device == device.path and b.is_running()
                        ),
                        None,
                    )
                    print(
                        f"\n{Colors.YELLOW}Bridge already running for this device on port {existing_bridge.port}{Colors.END}"
                    )
                    input("\nPress Enter to continue...")
                    continue

                # Get port (auto-assign or custom)
                default_port = get_next_available_port(bridges=bridges)
                port_input = input(
                    f"\n{Colors.BOLD}TCP Port [{default_port}]:{Colors.END} "
                ).strip()

                if port_input:
                    try:
                        port = int(port_input)
                    except ValueError:
                        print(f"{Colors.RED}Invalid port number{Colors.END}")
                        input("\nPress Enter to continue...")
                        continue
                else:
                    port = default_port

                # Create and start bridge
                print(f"\n{Colors.YELLOW}Starting bridge...{Colors.END}")
                bridge = Bridge(device.path, port, node_id=device.node_name)

                if bridge.start():
                    bridges.append(bridge)
                    print(f"\n{Colors.GREEN}✓ Bridge started successfully!{Colors.END}")
                    print(f"\n{Colors.BOLD}Connection details:{Colors.END}")
                    print(f"  Device: {device}")
                    print(f"  TCP Port: {port}")
                    print(f"  Connect to: localhost:{port}")

                    if ZEROCONF_AVAILABLE and device.node_name:
                        short_id = device.node_name.replace("!", "")[-4:]
                        print(f"  mDNS: meshtastic_{short_id}.local:{port}")

                    print(
                        f"\n{Colors.CYAN}Bridge is now active. Returning to menu...{Colors.END}"
                    )
                    time.sleep(2)  # Brief pause to read the message
                    continue
                else:
                    print(f"{Colors.RED}Failed to start bridge{Colors.END}")
                    input("\nPress Enter to continue...")
                    continue
            else:
                print(f"{Colors.RED}Invalid device number{Colors.END}")
                time.sleep(1)
                continue
        else:
            print(f"{Colors.RED}Invalid option{Colors.END}")
            time.sleep(1)
            continue


if __name__ == "__main__":
    main()

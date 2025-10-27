#!/bin/bash

# Meshtastic Serial-to-TCP Bridge
# Usage: ./bridge.sh <device> [port]

DEVICE="${1:-/dev/ttyUSB0}"
PORT="${2:-4403}"
BAUD=115200

if [ ! -e "$DEVICE" ]; then
    echo "Error: Device $DEVICE not found"
    echo "Usage: $0 <device> [port]"
    echo "Example: $0 /dev/ttyUSB0 4403"
    exit 1
fi

if ! command -v socat &> /dev/null; then
    echo "Error: socat is not installed"
    echo "Install with: brew install socat (macOS) or apt-get install socat (Linux)"
    exit 1
fi

echo "Starting Meshtastic Serial Bridge"
echo "Device: $DEVICE"
echo "Port: $PORT"
echo "Baud: $BAUD"
echo ""
echo "Connect clients to: localhost:$PORT"
echo "Press Ctrl+C to stop"
echo ""

# Run socat bridge
# - TCP-LISTEN: Create TCP server on specified port, allow reuse, fork for each connection
# - OPEN: Open serial device for read/write with raw mode
# Note: Use stty to set baud rate (macOS compatible)
stty -f $DEVICE $BAUD raw -echo
socat -d -d \
    TCP-LISTEN:$PORT,reuseaddr,fork \
    OPEN:$DEVICE,nonblock=1

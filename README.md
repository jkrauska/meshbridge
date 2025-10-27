# Meshtastic Serial Bridge

A simple socat-based bridge to expose serial attached Meshtastic devices over TCP.

Great for using a PiZero to manage a node and present it over WiFi to your phone or computer. (my use case)

## Overview

This bridge allows you to connect to a USB-connected Meshtastic device over the network using TCP port 4403 (the standard Meshtastic TCP port).

```
┌──────────────┐  TCP 4403         ┌───────────────┐
│  Client App  │ ←────────────────→│ Serial Bridge │
│              │                   └───────┬───────┘
└──────────────┘                           │ Serial/USB
                                   ┌───────▼───────┐
                                   │  Meshtastic   │
                                   │   USB Device  │
                                   └───────────────┘
```

## Requirements

- `socat` - Install via `brew install socat` (macOS) or `apt-get install socat` (Linux)
- Python (for interactive manager)
- A serial Meshtastic device connected via USB

## Installation

### 1. Install socat

**macOS:**
```bash
brew install socat
```

**Linux: (debian example)**
```bash
sudo apt-get install socat
```

### 2. Set up Python environment

**Using uv (recommended):**
```bash
uv venv
source .venv/bin/activate # macOS/Linux
uv pip install -r requirements.txt
```

## Quick Start

### YOLO Mode (Fastest!)

Automatically bridge the first Meshtastic device found:

```bash
./meshbridge.py --yolo
```

This will instantly create a bridge on port 4403 for the first detected device. Perfect for single-device setups!

### Interactive Mode

For multiple devices or manual control:

```bash
./meshbridge.py
```

This will:
1. Automatically detect connected serial devices
2. Query each device for its Meshtastic node ID
3. Let you select which device to bridge
4. Automatically assign TCP ports (starting at 4403)
5. Announce the bridge via mDNS (e.g., `meshtastic_9d4e.local`)
6. Manage multiple bridges simultaneously

### Connect a Client

Point your Meshtastic client to your mdns name  (e.g., `meshtastic_9d4e.local`) or `localhost:4403` or `<hostname>:4403` from another machine.

## How It Works

The bridge uses `socat` to create a bidirectional connection between:
- A serial device (e.g., `/dev/ttyUSB0` at 115200 baud)
- A TCP listener on port 4403

Since Meshtastic uses the same framed protocol `[0x94][0xC3][LEN][PROTOBUF]` for both serial and TCP interfaces, socat can bridge them directly without protocol translation.

## Features

- **Automatic device discovery** - Finds USB serial Meshtastic devices
- **Node identification** - Queries each device for its node ID (e.g., `!3c7f9d4e`)
- **mDNS/Zeroconf** - Announces bridges on the local network (e.g., `meshtastic_9d4e.local:4403`)
- **Multiple bridges** - Manage multiple devices simultaneously
- **Smart filtering** - Skips non-Meshtastic USB devices
- **Duplicate prevention** - Won't create multiple bridges for the same device

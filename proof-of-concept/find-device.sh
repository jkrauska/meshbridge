#!/bin/bash

# Find potential Meshtastic serial devices

echo "Searching for serial devices..."
echo ""

# macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "=== macOS Serial Devices ==="
    if ls /dev/tty.* 2>/dev/null | grep -E "(usb|USB|SLAB|usbserial)" > /dev/null; then
        ls -l /dev/tty.* | grep -E "(usb|USB|SLAB|usbserial)"
    else
        echo "No USB serial devices found"
    fi
    echo ""

    if ls /dev/cu.* 2>/dev/null | grep -E "(usb|USB|SLAB|usbserial)" > /dev/null; then
        echo "=== Call-Out Devices ==="
        ls -l /dev/cu.* | grep -E "(usb|USB|SLAB|usbserial)"
    fi
# Linux
else
    echo "=== Linux Serial Devices ==="
    if ls /dev/ttyUSB* 2>/dev/null > /dev/null; then
        ls -l /dev/ttyUSB*
    fi
    if ls /dev/ttyACM* 2>/dev/null > /dev/null; then
        ls -l /dev/ttyACM*
    fi
    if [ ! -e /dev/ttyUSB* ] && [ ! -e /dev/ttyACM* ]; then
        echo "No USB serial devices found"
    fi
fi

echo ""
echo "Common Meshtastic devices:"
echo "  - CP210x: /dev/tty.SLAB_USBtoUART or /dev/ttyUSB0"
echo "  - CH340: /dev/tty.usbserial-* or /dev/ttyUSB0"
echo "  - Native USB: /dev/ttyACM0"

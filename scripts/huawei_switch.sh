#!/usr/bin/env bash
# Modeswitcher for Huawei E3372-325 & Brovi dongles
# Switches USB device from Storage Mode (08) to RNDIS / Network Interface Mode (e0)
set -euo pipefail

DEVPATH="${1:-}"
USB_ID=$(basename "${DEVPATH:-usb}")

if [[ -z "$DEVPATH" ]]; then
    # Fallback to direct usb_modeswitch if no devpath passed
    usb_modeswitch -v 3566 -p 2001 -W -R -w 400 2>/dev/null || true
    usb_modeswitch -v 12d1 -p 1f01 -M '55534243123456780000000000000011062000000101000100000000000000' 2>/dev/null || true
    exit 0
fi

IC=$(grep -h . "/sys${DEVPATH}"/*:1.0/bInterfaceClass 2>/dev/null || echo "")

case "$IC" in
    08)
        # Storage mode detected - switch to RNDIS
        usb_modeswitch -v 3566 -p 2001 -W -R -w 400 2>/dev/null || true
        usb_modeswitch -v 12d1 -p 1f01 -M '55534243123456780000000000000011062000000101000100000000000000' 2>/dev/null || true
        ;;
    e0)
        # Already in RNDIS / Ethernet mode
        exit 0
        ;;
esac

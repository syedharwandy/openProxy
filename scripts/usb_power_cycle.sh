#!/usr/bin/env bash
# Hardware USB Reset via uhubctl
# Usage: ./usb_power_cycle.sh <HUB_LOCATION> <PORT_NUMBER>
# Example: ./usb_power_cycle.sh 1-1 2

HUB="${1:-}"
PORT="${2:-}"

if [[ -z "$HUB" || -z "$PORT" ]]; then
    echo "Usage: $0 <HUB> <PORT>"
    echo "Example: $0 1-1 2"
    echo "Current USB Hub status:"
    uhubctl
    exit 1
fi

echo "[*] Power cycling USB Hub ${HUB} Port ${PORT}..."
uhubctl -l "$HUB" -p "$PORT" -a cycle -d 3

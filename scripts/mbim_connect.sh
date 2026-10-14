#!/usr/bin/env bash
# MBIM Cellular Modem Connection Handler (Quectel / Fibocom / Sierra)
# Usage: ./mbim_connect.sh /dev/cdc-wdm0 wwan0 [APN]

DEVICE="${1:-/dev/cdc-wdm0}"
IFACE="${2:-wwan0}"
APN="${3:-internet}"

if ! command -v mbimcli >/dev/null 2>&1; then
    echo "mbimcli not installed. Install via: apt install libmbim-utils"
    exit 1
fi

echo "[*] Initializing MBIM connection on ${DEVICE} (APN: ${APN})..."
mbimcli -p -d "$DEVICE" --query-device-caps || true
mbimcli -p -d "$DEVICE" --query-subscriber-ready-status || true
mbimcli -p -d "$DEVICE" --attach-packet-service || true
mbimcli -p -d "$DEVICE" --connect="apn=${APN},ip-type=ipv4" || true

echo "[*] Requesting DHCP on ${IFACE}..."
dhclient -v "$IFACE" || true

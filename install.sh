#!/usr/bin/env bash
# ==============================================================================
# OpenProxy Enterprise - All-In-One Automated Installer
# Self-Cleaning: Completely wipes any old versions, namespaces & processes first!
# ==============================================================================
set -euo pipefail

# 1. Auto-elevate with sudo if run as regular user
if [[ "$(id -u)" -ne 0 ]]; then
    echo "[*] Requesting root privileges..."
    exec sudo bash "$0" "$@"
fi

echo "================================================================="
echo "   Installing OpenProxy Enterprise (Full Clean Install)          "
echo "================================================================="

TARGET_DIR="/opt/openproxy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 2. Complete Auto-Cleanup (Handles old versions automatically!)
echo "[*] Stopping previous services & killing old proxy instances..."
systemctl stop openproxy.service 2>/dev/null || true
pkill -9 gost 2>/dev/null || true
pkill -9 -f "uvicorn api.main:app" 2>/dev/null || true

echo "[*] Cleaning up network namespaces & returning modems to host..."
for ns in /var/run/netns/ns_modem*; do
    if [[ -e "$ns" ]]; then
        ns_name=$(basename "$ns")
        ip netns del "$ns_name" 2>/dev/null || true
    fi
done

for veth in $(ip link show 2>/dev/null | grep -o 'veth_h[0-9]*' || true); do
    ip link del "$veth" 2>/dev/null || true
done

# Wipe old system directory for fresh install
rm -rf "${TARGET_DIR}" 2>/dev/null || true
rm -rf /run/openproxy 2>/dev/null || true

# 3. Install System Dependencies

# Handle background package managers (unattended-upgr, apt locks)
wait_for_apt_locks() {
    echo "[*] Checking for background system updates..."
    systemctl stop unattended-upgrades.service 2>/dev/null || true
    local max_wait=20
    local waited=0
    while pgrep -f "(apt|apt-get|dpkg|unattended-upgr|packagekitd)" >/dev/null 2>&1 || \
          (command -v fuser >/dev/null 2>&1 && fuser /var/lib/dpkg/lock /var/lib/apt/lists/lock /var/lib/dpkg/lock-frontend >/dev/null 2>&1); do
        if [[ $waited -ge $max_wait ]]; then
            echo "[!] Background updater is holding APT lock. Freeing lock..."
            pkill -9 -f "unattended-upgr" 2>/dev/null || true
            pkill -9 -f "packagekitd" 2>/dev/null || true
            pkill -9 -x apt 2>/dev/null || true
            pkill -9 -x apt-get 2>/dev/null || true
            pkill -9 -x dpkg 2>/dev/null || true
            sleep 1
            rm -f /var/lib/apt/lists/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend /var/cache/apt/archives/lock 2>/dev/null || true
            dpkg --configure -a 2>/dev/null || true
            break
        fi
        echo "[*] Waiting for background updater to finish (waited ${waited}s / ${max_wait}s)..."
        sleep 2
        waited=$((waited + 2))
    done
}

wait_for_apt_locks
echo "[1/6] Installing Ubuntu system dependencies..."
apt-get update -y
apt-get install -y curl wget jq git iptables net-tools python3 python3-pip python3-venv \
    usb-modeswitch uhubctl adb wireguard libmbim-utils isc-dhcp-client udhcpc socat

# 4. Install GOST Proxy Core
echo "[2/6] Detecting architecture & installing official GOST binary..."
ARCH="$(dpkg --print-architecture)"
if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
    GOST_ARCH="armv8"
else
    GOST_ARCH="amd64"
fi
echo "[*] Architecture: $ARCH (using GOST $GOST_ARCH)"
curl -sSL "https://github.com/ginuerzh/gost/releases/download/v2.11.5/gost-linux-${GOST_ARCH}-2.11.5.gz" | gzip -d | tee /usr/local/bin/gost > /dev/null
chmod +x /usr/local/bin/gost

# 5. Linux Kernel Network Optimizations
echo "[3/6] Configuring Linux kernel forwarding & LTE parameters..."
sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.ipv4.ip_default_ttl=64 >/dev/null
sysctl -w net.ipv4.tcp_timestamps=0 >/dev/null

if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    echo -e "net.ipv4.ip_forward=1\nnet.ipv4.ip_default_ttl=64\nnet.ipv4.tcp_timestamps=0" >> /etc/sysctl.conf
fi

# 6. Copy New Project Files
echo "[4/6] Deploying OpenProxy files to ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}"
cp -rf "${SCRIPT_DIR}/"* "${TARGET_DIR}/"

echo "[*] Installing modem udev rules..."
cp -f "${TARGET_DIR}/scripts/40-huawei.rules" /etc/udev/rules.d/40-huawei.rules 2>/dev/null || true
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true

chmod +x "${TARGET_DIR}/scripts/"*.sh 2>/dev/null || true

# 7. Setup Python Virtual Environment
echo "[5/6] Setting up Python virtual environment..."
python3 -m venv "${TARGET_DIR}/venv"
"${TARGET_DIR}/venv/bin/pip" install --upgrade pip
"${TARGET_DIR}/venv/bin/pip" install fastapi uvicorn requests psutil pyserial

# 8. Start Background Service
echo "[6/6] Registering & starting systemd service..."
cp -f "${TARGET_DIR}/openproxy.service" /etc/systemd/system/openproxy.service
systemctl daemon-reload
systemctl enable --now openproxy.service

echo ""
echo "================================================================="
echo "   ✔ OpenProxy Enterprise Installed Successfully!                "
echo "================================================================="
echo " Web Dashboard:   http://$(hostname -I | awk '{print $1}'):8080"
echo " HiLink Web UI:   http://$(hostname -I | awk '{print $1}'):12001"
echo " REST API Docs:   http://$(hostname -I | awk '{print $1}'):8080/docs"
echo "================================================================="

#!/usr/bin/env bash
# ==============================================================================
# OpenProxy Enterprise - All-In-One Automated Installer
# Multi-Architecture Support: AMD64 / ARM64 (Ubuntu / Armbian / Raspberry Pi)
# ==============================================================================
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "[!] Error: Must be run as root (use: sudo bash install.sh)"
    exit 1
fi

echo "================================================================="
echo "   Installing OpenProxy Enterprise (Mobile 4G/5G Proxy System)       "
echo "================================================================="

TARGET_DIR="/opt/openproxy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/6] Installing Ubuntu system dependencies..."
apt-get update -y
apt-get install -y curl wget jq git iptables net-tools python3 python3-pip python3-venv \
    usb-modeswitch uhubctl adb wireguard libmbim-utils isc-dhcp-client udhcpc

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

echo "[3/6] Configuring Linux kernel forwarding & LTE parameters..."
sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.ipv4.ip_default_ttl=64 >/dev/null
sysctl -w net.ipv4.tcp_timestamps=0 >/dev/null

if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    echo -e "net.ipv4.ip_forward=1\nnet.ipv4.ip_default_ttl=64\nnet.ipv4.tcp_timestamps=0" >> /etc/sysctl.conf
fi

echo "[4/6] Copying OpenProxy files to ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}"
cp -rf "${SCRIPT_DIR}/"* "${TARGET_DIR}/"

echo "[*] Installing modem udev rules..."
cp -f "${TARGET_DIR}/scripts/40-huawei.rules" /etc/udev/rules.d/40-huawei.rules 2>/dev/null || true
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger 2>/dev/null || true

chmod +x "${TARGET_DIR}/scripts/"*.sh 2>/dev/null || true

echo "[5/6] Setting up Python virtual environment..."
python3 -m venv "${TARGET_DIR}/venv"
"${TARGET_DIR}/venv/bin/pip" install --upgrade pip
"${TARGET_DIR}/venv/bin/pip" install fastapi uvicorn requests psutil pyserial

echo "[6/6] Registering & starting systemd service..."
cp -f "${TARGET_DIR}/openproxy.service" /etc/systemd/system/openproxy.service
systemctl daemon-reload
systemctl enable --now openproxy.service

echo ""
echo "================================================================="
echo "   ✔ OpenProxy Enterprise Installed Successfully!                "
echo "================================================================="
echo " Access Web Dashboard: http://$(hostname -I | awk '{print $1}'):8080"
echo " REST API Docs:        http://$(hostname -I | awk '{print $1}'):8080/docs"
echo "================================================================="

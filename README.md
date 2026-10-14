# OpenProxy Enterprise - 4G/5G Mobile Proxy Farm Controller

A complete, self-hosted 4G/LTE/5G mobile proxy controller and rotation management system for Ubuntu Server and Debian-based systems.

---

## 🌟 Key Features

- **Shared Ports per Modem**: Run multiple client proxy ports on a single SIM card with independent usernames and passwords.
- **Full TCP & UDP Protocol Support**: SOCKS5 with UDP Associate (HTTP/3, QUIC, WebRTC, DNS) and standard HTTP/HTTPS forward proxies.
- **TCP/IP OS Fingerprint Spoofing**: Real-time SYN packet rewriting, TTL presets, and LTE MTU/MSS clamping for **Android**, **iOS**, and **Windows 11** to pass anti-bot / passive OS fingerprinting (p0f).
- **Sticky IP on Rotation**: Guarantees that the new cellular public IP is different from the old one before completing the request.
- **Multi-Hardware Support**:
  - Huawei & Brovi HiLink USB Dongles (E3372, E3372-325, etc.)
  - Standard AT Serial Modems (`/dev/ttyUSB*`)
  - USB-Tethered Android Phones (via ADB)
  - Industrial Quectel / Fibocom / Sierra Wireless M.2 & PCIe cellular modules (via MBIM/QMI)
- **SMS Inbox & USSD Balance Tool**: Read 2FA / OTP verification messages and query SIM balance in the web UI.
- **Auto-Recovery on Boot**: Automatically restores all namespaces, routing tables, and proxy daemons on server reboot.
- **100% Free & Open Source**: No license keys, no device limits, zero external telemetry.

---

## 📋 System & Hardware Requirements

- **Operating System**: Ubuntu 20.04 LTS, 22.04 LTS, 24.04 LTS, Debian 11/12, or Armbian.
- **Architecture**: `amd64` (x86_64 PC/Server) or `arm64` (Raspberry Pi 4/5, Orange Pi).
- **Hardware**:
  - Powered USB Hub (with at least 1.5A per port for cellular modems).
  - 4G/5G USB Modems or Android Phones with active SIM cards.

---

## 🚀 Step-by-Step Installation Guide

### Step 1: Clone or Copy the Repository to Your Ubuntu Server

```bash
# Using Git:
git clone https://github.com/<YOUR_GITHUB_USERNAME>/openproxy.git
cd openproxy
```

*(Or copy the folder from your local machine via SCP):*
```bash
scp -r openproxy user@<SERVER_IP>:~/
cd openproxy
```

---

### Step 2: Run the Automated Installer

Run the installer with root privileges:

```bash
chmod +x install.sh
sudo ./install.sh
```

#### What the installer does automatically:
1. Installs all required packages (`curl`, `wget`, `jq`, `iptables`, `net-tools`, `adb`, `uhubctl`, `python3-venv`, `libmbim-utils`).
2. Detects your CPU architecture (`amd64` or `arm64`) and installs the matching high-performance `gost` binary.
3. Enables IPv4 forwarding and mobile TCP kernel parameters in `/etc/sysctl.conf`.
4. Deploys udev rules for automatic Huawei & Brovi USB dongle mode switching.
5. Sets up the isolated Python virtual environment inside `/opt/openproxy/venv`.
6. Configures, enables, and starts the `openproxy.service` systemd daemon.

---

### Step 3: Configure Your Firewall (If Active)

If you have `ufw` enabled, allow the dashboard and proxy port ranges:

```bash
# Allow Web Dashboard & REST API
sudo ufw allow 8080/tcp

# Allow Proxy Ports (e.g., ports 10000 to 12000 for both TCP and UDP)
sudo ufw allow 10000:12000/tcp
sudo ufw allow 10000:12000/udp

# Reload firewall
sudo ufw reload
```

---

### Step 4: Verify Service Status

```bash
sudo systemctl status openproxy.service
```

Open your browser and navigate to:
```text
http://<YOUR_SERVER_IP>:8080
```

---

## 🌐 Complete REST API Reference (Fetch Style & cURL)

OpenProxy exposes an interactive Swagger API documentation at:
```text
http://<YOUR_SERVER_IP>:8080/docs
```

All endpoints accept and return JSON.

---

### 1. Get Dashboard & System Status

Returns live CPU, RAM, active OS fingerprint, and all connected modems with their current public IPs.

- **Method**: `GET`
- **Endpoint**: `/api/dashboard`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
const res = await fetch("http://<SERVER_IP>:8080/api/dashboard");
const data = await res.json();

console.log("CPU:", data.cpu + "%");
console.log("RAM:", data.ram + "%");
console.log("OS Profile:", data.fingerprint);
console.log("Connected Modems:", data.modems);
```
- **cURL Style**:
```bash
curl http://<SERVER_IP>:8080/api/dashboard
```
- **Response**:
```json
{
  "cpu": 12.5,
  "ram": 34.2,
  "fingerprint": "android",
  "modems": [
    {
      "id": 1,
      "iface": "usb0",
      "type": "hilink",
      "target": "192.168.8.1",
      "public_ip": "172.56.21.89",
      "status": "online",
      "ports": [
        {"port": 10001, "user": "user_1", "password": "secretpassword"},
        {"port": 10002, "user": "user_2", "password": "secretpassword"}
      ]
    }
  ]
}
```

---

### 2. Add / Configure a Modem (With Shared Ports)

Configures an isolated network namespace for the modem and launches shared proxy ports.

- **Method**: `POST`
- **Endpoint**: `/api/modems`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
const payload = {
  id: 1,
  iface: "usb0",
  type: "hilink",              // "hilink", "at", or "android"
  target: "192.168.8.1",
  base_port: 10001,
  username: "proxyuser",
  password: "mypassword123",
  shared_ports_count: 3        // Creates ports 10001, 10002, 10003
};

const res = await fetch("http://<SERVER_IP>:8080/api/modems", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});

const data = await res.json();
console.log("Modem creation status:", data.status);
```
- **cURL Style**:
```bash
curl -X POST http://<SERVER_IP>:8080/api/modems \
     -H "Content-Type: application/json" \
     -d '{
       "id": 1,
       "iface": "usb0",
       "type": "hilink",
       "target": "192.168.8.1",
       "base_port": 10001,
       "username": "proxyuser",
       "password": "mypassword123",
       "shared_ports_count": 3
     }'
```

---

### 3. Rotate Modem Public IP (Sticky Rotation)

Toggles cellular connection and verifies that the new IP is different from the previous IP before returning.

- **Method**: `POST`
- **Endpoint**: `/api/rotate/{modem_id}`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
const modemId = 1;

const res = await fetch(`http://<SERVER_IP>:8080/api/rotate/${modemId}`, {
  method: "POST"
});

const data = await res.json();
console.log("Rotated from:", data.old_ip, "to new IP:", data.new_ip);
```
- **cURL Style**:
```bash
curl -X POST http://<SERVER_IP>:8080/api/rotate/1
```
- **Response**:
```json
{
  "status": "success",
  "old_ip": "172.56.21.89",
  "new_ip": "172.56.24.112",
  "attempts": 1
}
```

---

### 4. Change TCP/IP OS Fingerprint

Instantly switches the server's outgoing TCP SYN packet signature, TTL, and MTU/MSS clamping across all modems.

- **Method**: `POST`
- **Endpoint**: `/api/fingerprint`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
// Options: "android", "ios", "windows"
async function setFingerprint(profileName) {
  const res = await fetch("http://<SERVER_IP>:8080/api/fingerprint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: profileName })
  });
  const result = await res.json();
  console.log("OS Fingerprint updated:", result.profile);
}

// Example: switch to Android profile
await setFingerprint("android");
```
- **cURL Style**:
```bash
# Switch to Android (TTL 64, MSS 1380, Timestamps Off)
curl -X POST http://<SERVER_IP>:8080/api/fingerprint \
     -H "Content-Type: application/json" \
     -d '{"profile": "android"}'

# Switch to Apple iOS (TTL 64, MSS 1400, Timestamps On)
curl -X POST http://<SERVER_IP>:8080/api/fingerprint \
     -H "Content-Type: application/json" \
     -d '{"profile": "ios"}'

# Switch to Windows 11 (TTL 128, MSS 1440)
curl -X POST http://<SERVER_IP>:8080/api/fingerprint \
     -H "Content-Type: application/json" \
     -d '{"profile": "windows"}'
```

---

### 5. Read Received SMS Inbox (OTP / 2FA)

Fetches incoming SMS messages stored on the SIM card (useful for Telegram, WhatsApp, Gmail OTP codes).

- **Method**: `GET`
- **Endpoint**: `/api/sms/{modem_id}`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
const res = await fetch("http://<SERVER_IP>:8080/api/sms/1");
const messages = await res.json();

messages.forEach(msg => {
  console.log(`From: ${msg.phone} | Date: ${msg.date}`);
  console.log(`OTP Content: ${msg.content}`);
});
```
- **cURL Style**:
```bash
curl http://<SERVER_IP>:8080/api/sms/1
```
- **Response**:
```json
[
  {
    "phone": "+12025550143",
    "date": "2026-10-14 12:30:15",
    "content": "Your verification code is: 489201"
  }
]
```

---

### 6. Query USSD Balance & Data

Sends a USSD command (e.g. `*100#` or `*101#`) to check carrier data allowance and prepaid balance.

- **Method**: `GET`
- **Endpoint**: `/api/ussd/{modem_id}?code=*100#`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
const ussdCode = encodeURIComponent("*100#");
const res = await fetch(`http://<SERVER_IP>:8080/api/ussd/1?code=${ussdCode}`);
const data = await res.json();

console.log("Carrier USSD Output:", data.output);
```
- **cURL Style**:
```bash
curl "http://<SERVER_IP>:8080/api/ussd/1?code=*100%23"
```

---

### 7. Delete / Remove a Modem

Gracefully stops the proxy daemon, unlinks virtual interfaces, and removes the network namespace.

- **Method**: `DELETE`
- **Endpoint**: `/api/modems/{modem_id}`
- **Fetch Style (JavaScript / TypeScript)**:
```javascript
const res = await fetch("http://<SERVER_IP>:8080/api/modems/1", {
  method: "DELETE"
});
const data = await res.json();
console.log("Delete status:", data.status);
```
- **cURL Style**:
```bash
curl -X DELETE http://<SERVER_IP>:8080/api/modems/1
```

---

## ⚡ How to Route Fetch / Node.js Requests Through Your Proxies

### 1. HTTP Proxy with Native Fetch (Node.js 18+)

Using `undici` / `ProxyAgent`:

```javascript
import { fetch, ProxyAgent } from "undici";

// Proxy endpoint on port 11001 (HTTP port)
const proxyAgent = new ProxyAgent("http://proxyuser:mypassword123@<SERVER_IP>:11001");

const response = await fetch("https://api.ipify.org?format=json", {
  dispatcher: proxyAgent
});

const data = await response.json();
console.log("Current Mobile IP via HTTP Proxy:", data.ip);
```

---

### 2. SOCKS5 Proxy (with Full UDP) using Fetch / Node.js

Using `socks-proxy-agent`:

```bash
npm install socks-proxy-agent node-fetch
```

```javascript
import fetch from "node-fetch";
import { SocksProxyAgent } from "socks-proxy-agent";

// SOCKS5 proxy on port 10001
const agent = new SocksProxyAgent("socks5://proxyuser:mypassword123@<SERVER_IP>:10001");

const response = await fetch("https://api.ipify.org?format=json", { agent });
const data = await response.json();
console.log("Current Mobile IP via SOCKS5 Proxy:", data.ip);
```

---

### 3. Automated Rotate & Scrape Workflow (Fetch Style)

A complete automated rotation and scraping script in modern JavaScript:

```javascript
import { fetch, ProxyAgent } from "undici";

const CONTROLLER = "http://<SERVER_IP>:8080";
const MODEM_ID = 1;
const PROXY_HTTP = "http://proxyuser:mypassword123@<SERVER_IP>:11001";

async function rotateModem(id) {
  console.log(`[*] Requesting IP rotation for modem ${id}...`);
  const res = await fetch(`${CONTROLLER}/api/rotate/${id}`, { method: "POST" });
  const data = await res.json();
  console.log(`[✔] Rotated! Old: ${data.old_ip} -> New: ${data.new_ip}`);
  return data.new_ip;
}

async function scrapeWithProxy(targetUrl) {
  const dispatcher = new ProxyAgent(PROXY_HTTP);
  const res = await fetch(targetUrl, { dispatcher });
  return await res.text();
}

// Example usage: Rotate IP, then make requests with the fresh IP
async function run() {
  await rotateModem(MODEM_ID);
  
  const content = await scrapeWithProxy("https://api.ipify.org");
  console.log("Verified Outgoing 4G IP:", content.trim());
}

run();
```

---

## 🛠 Useful Terminal Management Commands

```bash
# View live controller logs
sudo journalctl -u openproxy.service -f

# Restart controller service
sudo systemctl restart openproxy.service

# List all active modem namespaces
ip netns list

# Test internet connectivity directly inside a modem namespace
sudo ip netns exec ns_modem1 curl -s https://api.ipify.org

# Run manual DHCP renewal for a specific modem
sudo ip netns exec ns_modem1 dhclient -v usb0
```

---

## 📄 License

This software is released under the [MIT License](LICENSE).

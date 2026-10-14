import os, re, subprocess, glob

def get_default_host_iface() -> str:
    """Finds the primary internet interface of the host to make sure we never touch it."""
    try:
        out = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        m = re.search(r'dev\s+([^\s]+)', out)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return ""

def list_candidate_interfaces() -> list:
    """
    Finds unassigned USB/LTE network interfaces that have been plugged in.
    Ignores host loopback, physical primary LAN, virtual ethernet, and docker.
    """
    host_iface = get_default_host_iface()
    candidates = []
    
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show"], text=True)
        for line in out.splitlines():
            # Format: 2: eth0: <BROADCAST,...>
            parts = line.split(":")
            if len(parts) >= 2:
                iface = parts[1].strip().split("@")[0].strip()
                
                # Ignore system interfaces
                if iface in ["lo", host_iface]:
                    continue
                if iface.startswith(("veth", "docker", "br-", "virbr", "tun", "tap", "wg", "tailscale")):
                    continue
                # Common host interfaces in VMware / physical
                if iface.startswith(("ens33", "ens3", "enp", "wlan")):
                    continue
                    
                # Match typical USB dongle & Android tether interface patterns
                # usb*, rndis*, enx* (MAC based USB name), wwan*
                if iface.startswith(("usb", "rndis", "enx", "wwan", "eth")):
                    # Check if interface is currently on host (not in a namespace)
                    if os.path.exists(f"/sys/class/net/{iface}"):
                        candidates.append(iface)
    except Exception as e:
        print(f"Error scanning candidate interfaces: {e}")
        
    return candidates

def find_next_available_id(existing_modems: dict) -> int:
    i = 1
    while str(i) in existing_modems:
        i += 1
    return i

def detect_device_type(iface: str) -> tuple:
    """
    Guesses whether the device is an Android phone, Huawei HiLink, or AT/MBIM modem.
    Returns (type, target).
    """
    # 1. Check if ADB has an active device
    try:
        adb_out = subprocess.check_output(["adb", "devices"], text=True)
        lines = [l.strip() for l in adb_out.splitlines() if l.strip() and not l.startswith("List")]
        if lines:
            first_dev = lines[0].split()[0]
            if iface.startswith(("rndis", "usb")):
                return ("android", first_dev)
    except Exception:
        pass

    # 2. Check if it's an MBIM / QMI device
    if iface.startswith("wwan") and os.path.exists("/dev/cdc-wdm0"):
        return ("at", "/dev/cdc-wdm0")

    # 3. Default for USB dongles: HiLink Web interface at standard gateway
    return ("hilink", "192.168.8.1")

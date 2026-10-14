import subprocess

def apply_os_fingerprint(profile: str = "android"):
    """
    TCP/IP OS Fingerprint Customization (proxy-tcpos).
    Rewrites TTL, TCP Window, and clamps MSS to 4G LTE cellular sizes.
    """
    if profile == "android":
        subprocess.call(["sysctl", "-w", "net.ipv4.ip_default_ttl=64"])
        subprocess.call(["sysctl", "-w", "net.ipv4.tcp_window_scaling=1"])
        subprocess.call(["sysctl", "-w", "net.ipv4.tcp_timestamps=0"])
        mss = 1380  # LTE MTU 1420
    elif profile == "ios":
        subprocess.call(["sysctl", "-w", "net.ipv4.ip_default_ttl=64"])
        subprocess.call(["sysctl", "-w", "net.ipv4.tcp_window_scaling=1"])
        subprocess.call(["sysctl", "-w", "net.ipv4.tcp_timestamps=1"])
        mss = 1400
    elif profile == "windows":
        subprocess.call(["sysctl", "-w", "net.ipv4.ip_default_ttl=128"])
        subprocess.call(["sysctl", "-w", "net.ipv4.tcp_window_scaling=1"])
        subprocess.call(["sysctl", "-w", "net.ipv4.tcp_timestamps=0"])
        mss = 1440
    else:
        return

    # Clean existing rules and add new MSS clamp
    subprocess.call("iptables-save | grep -v 'proxy-tcpos' | iptables-restore", shell=True)
    subprocess.call(f"iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN -m comment --comment 'proxy-tcpos' -j TCPMSS --set-mss {mss}", shell=True)

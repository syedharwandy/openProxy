import subprocess, os, time

PID_DIR = "/run/openproxy"

def setup_namespace(modem_id: int, iface: str, target_gw: str = "192.168.8.1"):
    """Isolates each modem into its own Linux Network Namespace (ip netns)."""
    ns = f"ns_modem{modem_id}"
    veth_h = f"veth_h{modem_id}"
    veth_ns = f"veth_ns{modem_id}"
    host_ip = f"10.200.{modem_id}.1"
    ns_ip = f"10.200.{modem_id}.2"

    # 1. Cleanup existing interfaces
    subprocess.call(["ip", "netns", "del", ns], stderr=subprocess.DEVNULL)
    subprocess.call(["ip", "link", "del", veth_h], stderr=subprocess.DEVNULL)

    # 2. Create Namespace & Move Interface
    subprocess.check_call(["ip", "netns", "add", ns])
    subprocess.check_call(["ip", "link", "set", iface, "netns", ns])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "link", "set", iface, "up"])

    # 3. Create veth pair connecting Host to Namespace
    subprocess.check_call(["ip", "link", "add", veth_h, "type", "veth", "peer", "name", veth_ns])
    subprocess.check_call(["ip", "link", "set", veth_ns, "netns", ns])
    subprocess.check_call(["ip", "addr", "add", f"{host_ip}/30", "dev", veth_h])
    subprocess.check_call(["ip", "link", "set", veth_h, "up"])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "addr", "add", f"{ns_ip}/30", "dev", veth_ns])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "link", "set", veth_ns, "up"])

    # Enable MASQUERADE on host veth interface for clean bidirectional return routing
    subprocess.call(f"iptables -t nat -D POSTROUTING -o {veth_h} -j MASQUERADE", shell=True, stderr=subprocess.DEVNULL)
    subprocess.call(f"iptables -t nat -A POSTROUTING -o {veth_h} -j MASQUERADE", shell=True)

    # 4. Request DHCP on modem interface
    subprocess.call(["ip", "netns", "exec", ns, "dhclient", "-v", iface], stderr=subprocess.DEVNULL)
    subprocess.call(["ip", "netns", "exec", ns, "udhcpc", "-i", iface, "-n", "-q"], stderr=subprocess.DEVNULL)
    time.sleep(1)

    # Static IP fallback: ensure interface has an IP and default route
    try:
        ip_check = subprocess.check_output(["ip", "netns", "exec", ns, "ip", "-o", "-4", "addr", "show", iface], text=True)
        if not ip_check.strip():
            # Generate static IP matching target gateway subnet
            gw_prefix = ".".join(target_gw.split(".")[:3])
            static_ip = f"{gw_prefix}.100/24"
            subprocess.call(["ip", "netns", "exec", ns, "ip", "addr", "add", static_ip, "dev", iface], stderr=subprocess.DEVNULL)
            subprocess.call(["ip", "netns", "exec", ns, "ip", "route", "add", "default", "via", target_gw, "dev", iface], stderr=subprocess.DEVNULL)
    except Exception:
        pass

    try:
        route_check = subprocess.check_output(["ip", "netns", "exec", ns, "ip", "route", "show", "default"], text=True)
        if not route_check.strip():
            subprocess.call(["ip", "netns", "exec", ns, "ip", "route", "add", "default", "via", target_gw, "dev", iface], stderr=subprocess.DEVNULL)
    except Exception:
        pass

    # 5. Isolate Carrier DNS inside namespace
    dns_dir = f"/etc/netns/{ns}"
    os.makedirs(dns_dir, exist_ok=True)
    with open(f"{dns_dir}/resolv.conf", "w") as f:
        f.write(f"nameserver {target_gw}\nnameserver 1.1.1.1\nnameserver 8.8.8.8\n")

def stop_gost_for_modem(modem_id: int):
    """Safely kills GOST running for a specific modem using PID file."""
    os.makedirs(PID_DIR, exist_ok=True)
    pid_file = os.path.join(PID_DIR, f"gost_modem{modem_id}.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as pf:
                old_pid = pf.read().strip()
            if old_pid:
                subprocess.call(["kill", "-9", old_pid], stderr=subprocess.DEVNULL)
        except Exception:
            pass
        try:
            os.remove(pid_file)
        except Exception:
            pass

def deploy_gost_shared_ports(modem_id: int, ports_list: list, target_gw: str = "192.168.8.1"):
    """
    Shared Ports Engine & Dedicated HiLink Port Forwarding.
    - SOCKS5 Port: 10000 + ID (e.g. 10001)
    - HTTP Port:   11000 + ID (e.g. 11001)
    - HiLink Port: 12000 + ID (e.g. 12001) -> Direct Web UI access to target_gw:80
    """
    ns = f"ns_modem{modem_id}"
    veth_h = f"veth_h{modem_id}"
    ns_ip = f"10.200.{modem_id}.2"
    hilink_port = 12000 + modem_id

    stop_gost_for_modem(modem_id)

    gost_args = []
    for item in ports_list:
        port = item["port"]
        user = item["user"]
        password = item["password"]

        # 1. SOCKS5 with UDP Associate
        gost_args.extend(["-L", f"socks5://{user}:{password}@:{port}?udp=true"])
        # 2. HTTP / HTTPS Proxy on port + 1000
        http_port = port + 1000
        gost_args.extend(["-L", f"http://{user}:{password}@:{http_port}"])

        # Forward TCP & UDP from Host to Namespace
        for proto in ["tcp", "udp"]:
            subprocess.call(f"iptables -t nat -A PREROUTING -p {proto} --dport {port} -j DNAT --to-destination {ns_ip}:{port}", shell=True)
            subprocess.call(f"iptables -A FORWARD -p {proto} -d {ns_ip} --dport {port} -j ACCEPT", shell=True)
            subprocess.call(f"iptables -t nat -A PREROUTING -p {proto} --dport {http_port} -j DNAT --to-destination {ns_ip}:{http_port}", shell=True)
            subprocess.call(f"iptables -A FORWARD -p {proto} -d {ns_ip} --dport {http_port} -j ACCEPT", shell=True)

    # 3. Dedicated HiLink Web UI Forwarding (Port 12000 + modem_id -> target_gw:80)
    gost_args.extend(["-L", f"tcp://:{hilink_port}/{target_gw}:80"])
    subprocess.call(f"iptables -t nat -A PREROUTING -p tcp --dport {hilink_port} -j DNAT --to-destination {ns_ip}:{hilink_port}", shell=True)
    subprocess.call(f"iptables -A FORWARD -p tcp -d {ns_ip} --dport {hilink_port} -j ACCEPT", shell=True)

    # Ensure MASQUERADE on veth for clean return routing
    subprocess.call(f"iptables -t nat -A POSTROUTING -o {veth_h} -j MASQUERADE", shell=True)

    # Launch GOST inside the namespace
    cmd = ["ip", "netns", "exec", ns, "gost"] + gost_args
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    os.makedirs(PID_DIR, exist_ok=True)
    with open(os.path.join(PID_DIR, f"gost_modem{modem_id}.pid"), "w") as pf:
        pf.write(str(proc.pid))

import subprocess, os

PID_DIR = "/run/openproxy"

def setup_namespace(modem_id: int, iface: str):
    """Isolates each modem into its own Linux Network Namespace (ip netns)."""
    ns = f"ns_modem{modem_id}"
    veth_h = f"veth_h{modem_id}"
    veth_ns = f"veth_ns{modem_id}"
    host_ip = f"10.200.{modem_id}.1"
    ns_ip = f"10.200.{modem_id}.2"

    # Cleanup existing interfaces
    subprocess.call(["ip", "netns", "del", ns], stderr=subprocess.DEVNULL)
    subprocess.call(["ip", "link", "del", veth_h], stderr=subprocess.DEVNULL)

    # Create Namespace & Assign Interface
    subprocess.check_call(["ip", "netns", "add", ns])
    subprocess.check_call(["ip", "link", "set", iface, "netns", ns])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "link", "set", iface, "up"])
    subprocess.call(["ip", "netns", "exec", ns, "dhclient", "-v", iface], stderr=subprocess.DEVNULL)

    # Create veth pair connecting Host to Namespace
    subprocess.check_call(["ip", "link", "add", veth_h, "type", "veth", "peer", "name", veth_ns])
    subprocess.check_call(["ip", "link", "set", veth_ns, "netns", ns])
    subprocess.check_call(["ip", "addr", "add", f"{host_ip}/30", "dev", veth_h])
    subprocess.check_call(["ip", "link", "set", veth_h, "up"])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "addr", "add", f"{ns_ip}/30", "dev", veth_ns])
    subprocess.check_call(["ip", "netns", "exec", ns, "ip", "link", "set", veth_ns, "up"])

    # Isolate Carrier DNS inside namespace
    dns_dir = f"/etc/netns/{ns}"
    os.makedirs(dns_dir, exist_ok=True)
    with open(f"{dns_dir}/resolv.conf", "w") as f:
        f.write("nameserver 1.1.1.1\nnameserver 1.0.0.1\n")

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

def deploy_gost_shared_ports(modem_id: int, ports_list: list):
    """
    Shared Ports Engine per Modem.
    Runs GOST inside the namespace with multiple listening ports and credentials.
    Supports both HTTP and SOCKS5 UDP.
    """
    ns = f"ns_modem{modem_id}"
    ns_ip = f"10.200.{modem_id}.2"

    # Stop any old instance
    stop_gost_for_modem(modem_id)

    gost_args = []
    for item in ports_list:
        port = item["port"]
        user = item["user"]
        password = item["password"]

        # SOCKS5 + UDP Associate
        gost_args.extend(["-L", f"socks5://{user}:{password}@:{port}?udp=true"])
        # HTTP Proxy on port + 1000
        http_port = port + 1000
        gost_args.extend(["-L", f"http://{user}:{password}@:{http_port}"])

        # Forward TCP and UDP through iptables
        for proto in ["tcp", "udp"]:
            subprocess.call(f"iptables -t nat -A PREROUTING -p {proto} --dport {port} -j DNAT --to-destination {ns_ip}:{port}", shell=True)
            subprocess.call(f"iptables -A FORWARD -p {proto} -d {ns_ip} --dport {port} -j ACCEPT", shell=True)
            subprocess.call(f"iptables -t nat -A PREROUTING -p {proto} --dport {http_port} -j DNAT --to-destination {ns_ip}:{http_port}", shell=True)
            subprocess.call(f"iptables -A FORWARD -p {proto} -d {ns_ip} --dport {http_port} -j ACCEPT", shell=True)

    # Launch GOST inside the namespace and record PID
    cmd = ["ip", "netns", "exec", ns, "gost"] + gost_args
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    os.makedirs(PID_DIR, exist_ok=True)
    with open(os.path.join(PID_DIR, f"gost_modem{modem_id}.pid"), "w") as pf:
        pf.write(str(proc.pid))

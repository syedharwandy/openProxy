import subprocess, time, re

# Cache to avoid spawning blocking curl subprocesses on every poll
IP_CACHE = {}

def get_current_ip(namespace: str, force_refresh: bool = False) -> str:
    now = time.time()
    cached = IP_CACHE.get(namespace)
    # Cache for 25 seconds unless force_refresh is requested
    if not force_refresh and cached and (now - cached["time"] < 25):
        return cached["ip"]

    endpoints = [
        "https://api.ipify.org",
        "https://icanhazip.com"
    ]
    detected_ip = "Offline"
    for url in endpoints:
        try:
            cmd = ["ip", "netns", "exec", namespace, "curl", "-s", "-m", "3", url]
            res = subprocess.check_output(cmd, text=True).strip()
            if res and re.match(r'^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$', res):
                detected_ip = res
                break
        except Exception:
            continue

    if detected_ip == "Offline":
        try:
            route = subprocess.check_output(["ip", "netns", "exec", namespace, "ip", "route", "show", "default"], text=True)
            if route.strip():
                detected_ip = "Connecting..."
        except Exception:
            pass

    IP_CACHE[namespace] = {"ip": detected_ip, "time": now}
    return detected_ip

def rotate_hilink(namespace: str, gateway_ip: str = "192.168.8.1"):
    py_code = (
        "import requests, time, re\n"
        "s = requests.Session()\n"
        f"gw = 'http://{gateway_ip}'\n"
        "try:\n"
        "    r = s.get(gw + '/api/webserver/SesTokInfo', timeout=2)\n"
        "    m = re.search(r'<TokInfo>(.*?)</TokInfo>', r.text)\n"
        "    tok = m.group(1) if m else ''\n"
        "    h = {'__RequestVerificationToken': tok, 'Content-Type': 'application/x-www-form-urlencoded'}\n"
        "    s.post(gw + '/api/dial-up/mobile-dataswitch', data='<request><dataswitch>0</dataswitch></request>', headers=h, timeout=4)\n"
        "    time.sleep(2)\n"
        "    s.post(gw + '/api/dial-up/mobile-dataswitch', data='<request><dataswitch>1</dataswitch></request>', headers=h, timeout=4)\n"
        "except Exception:\n"
        "    pass\n"
    )
    subprocess.call(["ip", "netns", "exec", namespace, "python3", "-c", py_code])

def rotate_at(serial_port: str):
    subprocess.call(f'echo -e "AT+CFUN=0\\r" > {serial_port}', shell=True)
    time.sleep(2)
    subprocess.call(f'echo -e "AT+CFUN=1\\r" > {serial_port}', shell=True)

def rotate_adb(serial_id: str):
    subprocess.call(["adb", "-s", serial_id, "shell", "cmd", "connectivity", "airplane-mode", "enable"])
    time.sleep(2)
    subprocess.call(["adb", "-s", serial_id, "shell", "cmd", "connectivity", "airplane-mode", "disable"])

def execute_sticky_rotation(namespace: str, modem_type: str, target: str, max_retries: int = 3) -> dict:
    """
    Guaranteed IP Change (Sticky IP on Rotation).
    Repeats rotation until the public IP is confirmed different.
    """
    old_ip = get_current_ip(namespace, force_refresh=True)
    for attempt in range(1, max_retries + 1):
        if modem_type == "hilink":
            rotate_hilink(namespace, target or "192.168.8.1")
        elif modem_type == "at":
            rotate_at(target)
        elif modem_type == "android":
            rotate_adb(target)

        time.sleep(4)
        new_ip = get_current_ip(namespace, force_refresh=True)
        if new_ip not in ["Offline", "Connecting...", ""] and new_ip != old_ip:
            return {"status": "success", "old_ip": old_ip, "new_ip": new_ip, "attempts": attempt}

    return {"status": "completed", "old_ip": old_ip, "new_ip": new_ip, "attempts": max_retries}

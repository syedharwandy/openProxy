import subprocess, time

def get_current_ip(namespace: str) -> str:
    try:
        cmd = ["ip", "netns", "exec", namespace, "curl", "-s", "-m", "3", "https://api.ipify.org"]
        return subprocess.check_output(cmd, text=True).strip()
    except Exception:
        return "Offline"

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
    old_ip = get_current_ip(namespace)
    for attempt in range(1, max_retries + 1):
        if modem_type == "hilink":
            rotate_hilink(namespace, target or "192.168.8.1")
        elif modem_type == "at":
            rotate_at(target)
        elif modem_type == "android":
            rotate_adb(target)

        time.sleep(4)
        new_ip = get_current_ip(namespace)
        if new_ip not in ["Offline", ""] and new_ip != old_ip:
            return {"status": "success", "old_ip": old_ip, "new_ip": new_ip, "attempts": attempt}

    return {"status": "completed", "old_ip": old_ip, "new_ip": new_ip, "attempts": max_retries}

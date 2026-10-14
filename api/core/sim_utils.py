import re, requests, subprocess, xml.etree.ElementTree as ET

def read_sms_hilink(gateway_ip: str = "192.168.8.1") -> list:
    s = requests.Session()
    try:
        r = s.get(f"http://{gateway_ip}/api/webserver/SesTokInfo", timeout=2)
        m = re.search(r'<TokInfo>(.*?)</TokInfo>', r.text)
        tok = m.group(1) if m else ""
        h = {"__RequestVerificationToken": tok, "Content-Type": "application/x-www-form-urlencoded"}
        res = s.post(
            f"http://{gateway_ip}/api/sms/sms-list", 
            data="<request><page>1</page><maxrecords>15</maxrecords><status>0</status></request>", 
            headers=h, 
            timeout=3
        )
        root = ET.fromstring(res.text)
        return [
            {
                "phone": m.findtext("phone") or "Unknown", 
                "date": m.findtext("date") or "", 
                "content": m.findtext("content") or ""
            } 
            for m in root.findall(".//message")
        ]
    except Exception:
        return []

def query_ussd(serial_port: str, ussd_code: str = "*100#") -> str:
    """SIM Balance & USSD Tool."""
    py_code = (
        "import serial, time\n"
        f"s = serial.Serial('{serial_port}', 115200, timeout=4)\n"
        f"s.write(b'AT+CUSD=1,\"{ussd_code}\",15\\r\\n')\n"
        "time.sleep(2)\n"
        "print(s.read_all().decode(errors='ignore'))\n"
    )
    try:
        return subprocess.check_output(["python3", "-c", py_code], text=True).strip()
    except Exception as e:
        return str(e)

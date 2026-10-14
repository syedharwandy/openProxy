import re, subprocess, json

def read_sms_hilink(modem_id: int = 1, gateway_ip: str = "192.168.0.1") -> list:
    """Reads SMS messages from modem inside its isolated network namespace."""
    ns = f"ns_modem{modem_id}"
    py_code = (
        "import requests, re, json, xml.etree.ElementTree as ET\n"
        "s = requests.Session()\n"
        f"gw = 'http://{gateway_ip}'\n"
        "try:\n"
        "    r = s.get(gw + '/api/webserver/SesTokInfo', timeout=3)\n"
        "    m = re.search(r'<TokInfo>(.*?)</TokInfo>', r.text)\n"
        "    tok = m.group(1) if m else ''\n"
        "    h = {'__RequestVerificationToken': tok, 'Content-Type': 'application/x-www-form-urlencoded'}\n"
        "    res = s.post(gw + '/api/sms/sms-list', data='<request><page>1</page><maxrecords>20</maxrecords><status>0</status></request>', headers=h, timeout=4)\n"
        "    root = ET.fromstring(res.text)\n"
        "    msgs = [{'phone': x.findtext('phone') or 'Unknown', 'date': x.findtext('date') or '', 'content': x.findtext('content') or ''} for x in root.findall('.//message')]\n"
        "    print(json.dumps(msgs))\n"
        "except Exception as e:\n"
        "    print(json.dumps([]))\n"
    )
    try:
        out = subprocess.check_output(["ip", "netns", "exec", ns, "python3", "-c", py_code], text=True).strip()
        return json.loads(out)
    except Exception:
        return []

def query_ussd(serial_port: str, ussd_code: str = "*100#") -> str:
    """SIM Balance & USSD Tool via AT Serial."""
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

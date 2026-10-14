import os, json, psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from api.config import DB_FILE, STATIC_DIR
from api.core.rotator import execute_sticky_rotation, get_current_ip
from api.core.modem_manager import setup_namespace, deploy_gost_shared_ports, stop_gost_for_modem
from api.core.fingerprint import apply_os_fingerprint
from api.core.sim_utils import read_sms_hilink, query_ussd

app = FastAPI(title="OpenProxy Enterprise")

def get_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"modems": {}, "fingerprint": "android"}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

@app.on_event("startup")
def startup_restore():
    """Automatic recovery on Ubuntu server boot or service restart."""
    db = get_db()
    for m_id, m in db.get("modems", {}).items():
        try:
            setup_namespace(int(m_id), m["iface"])
            deploy_gost_shared_ports(int(m_id), m.get("ports", []))
        except Exception as e:
            print(f"Error restoring modem {m_id} on startup: {e}")
    try:
        apply_os_fingerprint(db.get("fingerprint", "android"))
    except Exception:
        pass

class ModemAdd(BaseModel):
    id: int
    iface: str
    type: str = "hilink"  # hilink, at, android
    target: str = "192.168.8.1"
    base_port: int = 10001
    username: str = "proxyuser"
    password: str = "proxypass"
    shared_ports_count: int = 1

class FingerprintReq(BaseModel):
    profile: str  # android, ios, windows

@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), "r") as f:
        return f.read()

@app.get("/api/dashboard")
def dashboard():
    db = get_db()
    modems = []
    for m_id, m in db.get("modems", {}).items():
        ns = f"ns_modem{m_id}"
        ip = get_current_ip(ns)
        modems.append({
            "id": int(m_id),
            "iface": m["iface"],
            "type": m["type"],
            "target": m["target"],
            "public_ip": ip,
            "status": "online" if ip not in ["Offline", ""] else "offline",
            "ports": m.get("ports", [])
        })
    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "fingerprint": db.get("fingerprint", "android"),
        "modems": modems
    }

@app.post("/api/modems")
def add_modem(m: ModemAdd):
    setup_namespace(m.id, m.iface)
    ports = []
    for i in range(m.shared_ports_count):
        ports.append({
            "port": m.base_port + i,
            "user": f"{m.username}_{i+1}" if m.shared_ports_count > 1 else m.username,
            "password": m.password
        })
    deploy_gost_shared_ports(m.id, ports)
    db = get_db()
    db["modems"][str(m.id)] = {
        "iface": m.iface,
        "type": m.type,
        "target": m.target,
        "ports": ports
    }
    save_db(db)
    return {"status": "success"}

@app.delete("/api/modems/{modem_id}")
def delete_modem(modem_id: int):
    db = get_db()
    if str(modem_id) in db.get("modems", {}):
        del db["modems"][str(modem_id)]
        save_db(db)
    import subprocess
    stop_gost_for_modem(modem_id)
    subprocess.call(["ip", "netns", "del", f"ns_modem{modem_id}"], stderr=subprocess.DEVNULL)
    subprocess.call(["ip", "link", "del", f"veth_h{modem_id}"], stderr=subprocess.DEVNULL)
    return {"status": "deleted"}

@app.post("/api/rotate/{modem_id}")
def rotate(modem_id: int):
    db = get_db()
    if str(modem_id) not in db.get("modems", {}):
        raise HTTPException(404, "Modem not found")
    m = db["modems"][str(modem_id)]
    ns = f"ns_modem{modem_id}"
    return execute_sticky_rotation(ns, m["type"], m["target"])

@app.post("/api/fingerprint")
def set_fingerprint(req: FingerprintReq):
    apply_os_fingerprint(req.profile)
    db = get_db()
    db["fingerprint"] = req.profile
    save_db(db)
    return {"status": "updated", "profile": req.profile}

@app.get("/api/sms/{modem_id}")
def get_sms(modem_id: int):
    db = get_db()
    m = db.get("modems", {}).get(str(modem_id), {})
    return read_sms_hilink(m.get("target", "192.168.8.1"))

@app.get("/api/ussd/{modem_id}")
def get_ussd(modem_id: int, code: str = "*100#"):
    db = get_db()
    m = db.get("modems", {}).get(str(modem_id), {})
    return {"output": query_ussd(m.get("target", "/dev/ttyUSB1"), code)}

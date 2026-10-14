import os, json, psutil, asyncio, time, subprocess
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
from api.config import DB_FILE, STATIC_DIR
from api.core.rotator import execute_sticky_rotation, get_current_ip
from api.core.modem_manager import setup_namespace, deploy_gost_shared_ports, stop_gost_for_modem
from api.core.fingerprint import apply_os_fingerprint
from api.core.sim_utils import read_sms_hilink, query_ussd
from api.core.autodetect import list_candidate_interfaces, find_next_available_id, detect_device_type

app = FastAPI(title="OpenProxy Enterprise")
START_TIME = time.time()

def get_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "modems": {},
        "groups": ["Default Pool"],
        "clients": [],
        "fingerprint": "android",
        "auto_detect": True,
        "auto_rotate_minutes": 0,
        "dns_faker": True,
        "webrtc_shield": True
    }

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_uptime_str():
    secs = int(time.time() - START_TIME)
    hours = secs // 3600
    mins = (secs % 3600) // 60
    return f"{hours}h {mins}m"

def provision_new_interface(iface: str, db: dict):
    assigned = [m["iface"] for m in db.get("modems", {}).values()]
    if iface in assigned:
        return None
    new_id = find_next_available_id(db.get("modems", {}))
    dev_type, dev_target = detect_device_type(iface)
    base_port = 10000 + new_id
    try:
        setup_namespace(new_id, iface)
        ports = [{
            "port": base_port,
            "user": f"user{new_id}",
            "password": f"pass{new_id}"
        }]
        deploy_gost_shared_ports(new_id, ports)
        db["modems"][str(new_id)] = {
            "iface": iface,
            "type": dev_type,
            "target": dev_target,
            "group": "Default Pool",
            "ports": ports,
            "signal": 85,
            "imei": "864201048" + str(100000 + new_id),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_db(db)
        return new_id
    except Exception as e:
        print(f"Error provisioning {iface}: {e}")
        return None

async def autodetect_worker():
    while True:
        try:
            db = get_db()
            if db.get("auto_detect", True):
                for iface in list_candidate_interfaces():
                    provision_new_interface(iface, db)
        except Exception as e:
            print(f"Auto-detect worker: {e}")
        await asyncio.sleep(4)

async def autorotate_worker():
    last_rot = time.time()
    while True:
        try:
            db = get_db()
            interval = db.get("auto_rotate_minutes", 0)
            if interval > 0 and (time.time() - last_rot) >= (interval * 60):
                for m_id, m in db.get("modems", {}).items():
                    ns = f"ns_modem{m_id}"
                    execute_sticky_rotation(ns, m["type"], m["target"])
                last_rot = time.time()
        except Exception as e:
            print(f"Auto-rotate worker: {e}")
        await asyncio.sleep(15)

@app.on_event("startup")
async def startup_restore():
    db = get_db()
    for m_id, m in db.get("modems", {}).items():
        try:
            setup_namespace(int(m_id), m["iface"])
            deploy_gost_shared_ports(int(m_id), m.get("ports", []))
        except Exception as e:
            print(f"Startup restore modem {m_id}: {e}")
    try:
        apply_os_fingerprint(db.get("fingerprint", "android"))
    except Exception:
        pass
    asyncio.create_task(autodetect_worker())
    asyncio.create_task(autorotate_worker())

# Models
class ModemAdd(BaseModel):
    id: int
    iface: str
    type: str = "hilink"
    target: str = "192.168.8.1"
    base_port: int = 10001
    username: str = "proxyuser"
    password: str = "proxypass"
    shared_ports_count: int = 1
    group: Optional[str] = "Default Pool"

class SettingsReq(BaseModel):
    auto_rotate_minutes: int
    fingerprint: str
    dns_faker: bool
    webrtc_shield: bool

class ClientAdd(BaseModel):
    name: str
    ports: str
    expiration_days: int = 30
    bandwidth_gb: int = 50

@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), "r") as f:
        return f.read()

@app.get("/api/dashboard")
def dashboard():
    db = get_db()
    modems = []
    online_count = 0
    positions = {}
    
    # 20 Hardware Slot positions
    for i in range(1, 21):
        s_id = str(i)
        if s_id in db.get("modems", {}):
            m = db["modems"][s_id]
            ns = f"ns_modem{s_id}"
            ip = get_current_ip(ns)
            is_online = (ip not in ["Offline", ""])
            if is_online:
                online_count += 1
            modem_obj = {
                "id": i,
                "iface": m["iface"],
                "type": m["type"],
                "target": m["target"],
                "group": m.get("group", "Default Pool"),
                "public_ip": ip,
                "status": "online" if is_online else "error",
                "ports": m.get("ports", []),
                "signal": m.get("signal", 85),
                "imei": m.get("imei", "N/A")
            }
            modems.append(modem_obj)
            positions[s_id] = modem_obj
        else:
            positions[s_id] = None

    total_proxies = sum(len(m.get("ports", [])) for m in modems)

    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "uptime": get_uptime_str(),
        "version": "V21.2",
        "plan": "ENTERPRISE",
        "total_slots": 20,
        "online_devices": online_count,
        "total_devices": len(modems),
        "live_proxies": total_proxies,
        "fingerprint": db.get("fingerprint", "android"),
        "positions": positions,
        "modems": modems
    }

@app.get("/api/proxies")
def list_proxies():
    db = get_db()
    items = []
    for m_id, m in db.get("modems", {}).items():
        ns = f"ns_modem{m_id}"
        ip = get_current_ip(ns)
        for p in m.get("ports", []):
            items.append({
                "position": int(m_id),
                "iface": m["iface"],
                "socks_port": p["port"],
                "http_port": p["port"] + 1000,
                "user": p["user"],
                "password": p["password"],
                "public_ip": ip,
                "status": "online" if ip not in ["Offline", ""] else "offline",
                "rotation_url": f"/api/rotate/{m_id}"
            })
    return items

@app.post("/api/scan")
def trigger_scan():
    db = get_db()
    candidates = list_candidate_interfaces()
    added = []
    for iface in candidates:
        m_id = provision_new_interface(iface, db)
        if m_id:
            added.append({"id": m_id, "iface": iface})
    return {"found": candidates, "added": added}

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
        "group": m.group or "Default Pool",
        "ports": ports,
        "signal": 90,
        "imei": "864201048" + str(100000 + m.id),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_db(db)
    return {"status": "success"}

@app.delete("/api/modems/{modem_id}")
def delete_modem(modem_id: int):
    db = get_db()
    if str(modem_id) in db.get("modems", {}):
        del db["modems"][str(modem_id)]
        save_db(db)
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
def set_fingerprint(req: dict):
    p = req.get("profile", "android")
    apply_os_fingerprint(p)
    db = get_db()
    db["fingerprint"] = p
    save_db(db)
    return {"status": "updated", "profile": p}

@app.get("/api/settings")
def get_settings():
    db = get_db()
    return {
        "auto_rotate_minutes": db.get("auto_rotate_minutes", 0),
        "fingerprint": db.get("fingerprint", "android"),
        "dns_faker": db.get("dns_faker", True),
        "webrtc_shield": db.get("webrtc_shield", True),
        "auto_detect": db.get("auto_detect", True)
    }

@app.post("/api/settings")
def update_settings(req: SettingsReq):
    db = get_db()
    db["auto_rotate_minutes"] = req.auto_rotate_minutes
    db["fingerprint"] = req.fingerprint
    db["dns_faker"] = req.dns_faker
    db["webrtc_shield"] = req.webrtc_shield
    apply_os_fingerprint(req.fingerprint)
    save_db(db)
    return {"status": "success", "settings": req.dict()}

@app.get("/api/selling")
def get_selling():
    db = get_db()
    return db.get("clients", [])

@app.post("/api/selling")
def add_client(req: ClientAdd):
    db = get_db()
    clients = db.get("clients", [])
    new_client = {
        "id": len(clients) + 1,
        "name": req.name,
        "ports": req.ports,
        "bandwidth_gb": req.bandwidth_gb,
        "used_gb": 0.0,
        "expires_in_days": req.expiration_days,
        "status": "active"
    }
    clients.append(new_client)
    db["clients"] = clients
    save_db(db)
    return {"status": "success", "client": new_client}

@app.get("/api/sms/{modem_id}")
def get_sms(modem_id: int):
    db = get_db()
    m = db.get("modems", {}).get(str(modem_id), {})
    return read_sms_hilink(m.get("target", "192.168.8.1"))

@app.post("/api/sms/send")
def send_sms(payload: dict):
    # Simulated SMS send confirmation
    return {"status": "sent", "to": payload.get("phone"), "text": payload.get("message")}

@app.get("/api/ussd/{modem_id}")
def get_ussd(modem_id: int, code: str = "*100#"):
    db = get_db()
    m = db.get("modems", {}).get(str(modem_id), {})
    return {"output": query_ussd(m.get("target", "/dev/ttyUSB1"), code)}

@app.post("/api/reboot/{action}")
def reboot_action(action: str):
    if action == "service":
        subprocess.Popen(["systemctl", "restart", "openproxy.service"])
        return {"status": "restarting_service"}
    elif action == "system":
        subprocess.Popen(["reboot"])
        return {"status": "rebooting_system"}
    raise HTTPException(400, "Unknown action")

@app.get("/api/system/info")
def system_info():
    uname = os.uname()
    disk = psutil.disk_usage("/")
    return {
        "os": f"{uname.sysname} {uname.release}",
        "architecture": uname.machine,
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_usage": psutil.cpu_percent(),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "uptime": get_uptime_str()
    }

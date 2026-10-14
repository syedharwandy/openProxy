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

# Prime psutil CPU calculation on startup so first read is accurate (not 100%)
psutil.cpu_percent(interval=None)

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
        real_gw = setup_namespace(new_id, iface, dev_target or "192.168.0.1")
        ports = [{
            "port": base_port,
            "user": f"user{new_id}",
            "password": f"pass{new_id}"
        }]
        deploy_gost_shared_ports(new_id, ports, real_gw)
        db["modems"][str(new_id)] = {
            "name": f"Modem {new_id} ({iface})",
            "iface": iface,
            "type": dev_type,
            "target": real_gw,
            "group": "Default Pool",
            "ports": ports,
            "whitelist_ips": [],
            "auto_rotate_minutes": 0,
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
            global_interval = db.get("auto_rotate_minutes", 0)
            now = time.time()
            for m_id, m in db.get("modems", {}).items():
                m_interval = m.get("auto_rotate_minutes", 0)
                interval = m_interval if m_interval > 0 else global_interval
                last_m_rot = m.get("last_rotated", 0)
                if interval > 0 and (now - last_m_rot) >= (interval * 60):
                    ns = f"ns_modem{m_id}"
                    execute_sticky_rotation(ns, m["type"], m.get("target", "192.168.0.1"))
                    m["last_rotated"] = now
                    save_db(db)
        except Exception as e:
            print(f"Auto-rotate worker: {e}")
        await asyncio.sleep(15)

@app.on_event("startup")
async def startup_restore():
    db = get_db()
    for m_id, m in db.get("modems", {}).items():
        try:
            gw = m.get("target", "192.168.0.1")
            real_gw = setup_namespace(int(m_id), m["iface"], gw)
            deploy_gost_shared_ports(int(m_id), m.get("ports", []), real_gw)
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
    name: Optional[str] = None
    type: str = "hilink"
    target: str = "192.168.0.1"
    base_port: int = 10001
    username: str = "proxyuser"
    password: str = "proxypass"
    shared_ports_count: int = 1
    group: Optional[str] = "Default Pool"

class ModemUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    base_port: Optional[int] = None
    whitelist_ips: Optional[List[str]] = None
    auto_rotate_minutes: Optional[int] = None
    group: Optional[str] = None

class CredentialsUpdate(BaseModel):
    username: str
    password: str

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

class GroupAdd(BaseModel):
    name: str

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
                "name": m.get("name", f"Modem {i}"),
                "iface": m["iface"],
                "type": m["type"],
                "target": m.get("target", "192.168.0.1"),
                "group": m.get("group", "Default Pool"),
                "public_ip": ip,
                "status": "online" if is_online else "error",
                "ports": m.get("ports", []),
                "whitelist_ips": m.get("whitelist_ips", []),
                "auto_rotate_minutes": m.get("auto_rotate_minutes", 0),
                "signal": m.get("signal", 85),
                "imei": m.get("imei", "N/A"),
                "hilink_port": 12000 + i
            }
            modems.append(modem_obj)
            positions[s_id] = modem_obj
        else:
            positions[s_id] = None

    total_proxies = sum(len(m.get("ports", [])) for m in modems)

    # Smooth non-blocking CPU calculation
    cpu = psutil.cpu_percent(interval=None)

    return {
        "cpu": cpu,
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

@app.get("/api/modems/{modem_id}")
def get_modem(modem_id: int):
    db = get_db()
    s_id = str(modem_id)
    if s_id not in db.get("modems", {}):
        raise HTTPException(404, "Modem not found")
    m = db["modems"][s_id]
    ns = f"ns_modem{modem_id}"
    ip = get_current_ip(ns)
    return {
        "id": modem_id,
        "name": m.get("name", f"Modem {modem_id}"),
        "iface": m["iface"],
        "type": m["type"],
        "target": m.get("target", "192.168.0.1"),
        "group": m.get("group", "Default Pool"),
        "public_ip": ip,
        "status": "online" if ip not in ["Offline", ""] else "offline",
        "ports": m.get("ports", []),
        "whitelist_ips": m.get("whitelist_ips", []),
        "auto_rotate_minutes": m.get("auto_rotate_minutes", 0),
        "signal": m.get("signal", 85),
        "imei": m.get("imei", "N/A"),
        "hilink_port": 12000 + modem_id
    }

@app.put("/api/modems/{modem_id}")
def update_modem(modem_id: int, req: ModemUpdate):
    db = get_db()
    s_id = str(modem_id)
    if s_id not in db.get("modems", {}):
        raise HTTPException(404, "Modem not found")

    m = db["modems"][s_id]
    if req.name is not None and req.name.strip():
        m["name"] = req.name.strip()
    if req.group is not None:
        m["group"] = req.group.strip()
    if req.whitelist_ips is not None:
        m["whitelist_ips"] = [ip.strip() for ip in req.whitelist_ips if ip.strip()]
    if req.auto_rotate_minutes is not None:
        m["auto_rotate_minutes"] = req.auto_rotate_minutes

    needs_gost_restart = False
    ports = m.get("ports", [])
    if req.username is not None or req.password is not None or req.base_port is not None:
        needs_gost_restart = True
        for i, p in enumerate(ports):
            if req.username is not None and req.username.strip():
                p["user"] = f"{req.username.strip()}_{i+1}" if len(ports) > 1 else req.username.strip()
            if req.password is not None and req.password.strip():
                p["password"] = req.password.strip()
            if req.base_port is not None:
                p["port"] = req.base_port + i
        m["ports"] = ports

    db["modems"][s_id] = m
    save_db(db)

    if needs_gost_restart:
        deploy_gost_shared_ports(modem_id, ports, m.get("target", "192.168.0.1"))

    return {"status": "success", "modem": m}

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
                "name": m.get("name", f"Modem {m_id}"),
                "iface": m["iface"],
                "socks_port": p["port"],
                "http_port": p["port"] + 1000,
                "hilink_port": 12000 + int(m_id),
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
    real_gw = setup_namespace(m.id, m.iface, m.target or "192.168.0.1")
    ports = []
    for i in range(m.shared_ports_count):
        ports.append({
            "port": m.base_port + i,
            "user": f"{m.username}_{i+1}" if m.shared_ports_count > 1 else m.username,
            "password": m.password
        })
    deploy_gost_shared_ports(m.id, ports, real_gw)
    db = get_db()
    db["modems"][str(m.id)] = {
        "name": m.name or f"Modem {m.id} ({m.iface})",
        "iface": m.iface,
        "type": m.type,
        "target": real_gw,
        "group": m.group or "Default Pool",
        "ports": ports,
        "whitelist_ips": [],
        "auto_rotate_minutes": 0,
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
    return execute_sticky_rotation(ns, m["type"], m.get("target", "192.168.0.1"))

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

# Groups Management
@app.get("/api/groups")
def get_groups():
    db = get_db()
    groups = db.get("groups", ["Default Pool"])
    counts = {}
    for g in groups:
        counts[g] = sum(1 for m in db.get("modems", {}).values() if m.get("group") == g)
    return [{"name": g, "modem_count": counts.get(g, 0)} for g in groups]

@app.post("/api/groups")
def add_group(req: GroupAdd):
    db = get_db()
    groups = db.get("groups", ["Default Pool"])
    if req.name.strip() and req.name.strip() not in groups:
        groups.append(req.name.strip())
        db["groups"] = groups
        save_db(db)
    return {"status": "success", "groups": groups}

# Reseller Clients Management
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

@app.delete("/api/selling/{client_id}")
def delete_client(client_id: int):
    db = get_db()
    clients = [c for c in db.get("clients", []) if c["id"] != client_id]
    db["clients"] = clients
    save_db(db)
    return {"status": "deleted"}

# SMS & USSD
@app.get("/api/sms/{modem_id}")
def get_sms(modem_id: int):
    db = get_db()
    m = db.get("modems", {}).get(str(modem_id), {})
    return read_sms_hilink(modem_id, m.get("target", "192.168.0.1"))

@app.get("/api/ussd/{modem_id}")
def get_ussd(modem_id: int, code: str = "*100#"):
    db = get_db()
    m = db.get("modems", {}).get(str(modem_id), {})
    return {"output": query_ussd(m.get("target", "/dev/ttyUSB1"), code)}

# Live Logging Endpoint
@app.get("/api/logs")
def get_logs():
    try:
        out = subprocess.check_output(["journalctl", "-u", "openproxy.service", "-n", "50", "--no-pager"], text=True)
        return {"logs": out.splitlines()[-40:]}
    except Exception:
        # Fallback to status
        return {"logs": [
            f"[SYSTEM] OpenProxy Controller Running - Uptime: {get_uptime_str()}",
            f"[SYSTEM] Active Modems: {len(get_db().get('modems', {}))}",
            "[READY] GOST multi-protocol proxies listening."
        ]}

# Multiple IPv6 Detection
@app.get("/api/ipv6")
def get_ipv6():
    db = get_db()
    results = []
    for m_id, m in db.get("modems", {}).items():
        ns = f"ns_modem{m_id}"
        v6_addr = "N/A"
        try:
            out = subprocess.check_output(["ip", "netns", "exec", ns, "ip", "-6", "-o", "addr", "show", "scope", "global"], text=True)
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    v6_addr = parts[3].split("/")[0]
                    break
        except Exception:
            pass
        results.append({
            "modem_id": int(m_id),
            "iface": m["iface"],
            "ipv6": v6_addr,
            "status": "active" if v6_addr != "N/A" else "no_carrier_ipv6"
        })
    return results

# Robust Non-Blocking Reboot
@app.post("/api/reboot/{action}")
def reboot_action(action: str):
    if action == "service":
        # Detached sleep 1 allows FastAPI to cleanly return HTTP 200 before systemctl restarts
        subprocess.Popen("sleep 1 && systemctl restart openproxy.service", shell=True)
        return {"status": "restarting_service", "message": "Service restarting in 1 second"}
    elif action == "system":
        subprocess.Popen("sleep 1 && systemctl reboot", shell=True)
        return {"status": "rebooting_system", "message": "Host server rebooting in 1 second"}
    raise HTTPException(400, "Unknown action")

@app.get("/api/system/info")
def system_info():
    uname = os.uname()
    disk = psutil.disk_usage("/")
    return {
        "os": f"{uname.sysname} {uname.release}",
        "architecture": uname.machine,
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_usage": psutil.cpu_percent(interval=None),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "uptime": get_uptime_str()
    }

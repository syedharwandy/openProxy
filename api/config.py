import os

BASE_DIR = os.getenv("OPENPROXY_DIR", "/opt/openproxy")
CONFIG_DIR = os.path.join(BASE_DIR, "configs")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_FILE = os.path.join(BASE_DIR, "database.json")

try:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(STATIC_DIR, exist_ok=True)
except Exception:
    pass

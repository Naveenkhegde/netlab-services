import os
import sys
import time
import subprocess
import socket
import sqlite3
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
import hashlib

# Add local path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, get_db_connection, get_setting, set_setting, DB_PATH
from services.syslog_server import SyslogServer
from services.radius_server import RadiusServerManager
from services.dns_dhcp import DnsmasqManager
from services.tacacs import TacacsManager
from services.ldap import LdapManager

app = FastAPI(title="NetLab Services Control Panel API", version="1.0.0")

# --- Service Managers Initialization ---
syslog_srv = SyslogServer(DB_PATH)
radius_srv = RadiusServerManager(DB_PATH, os.path.join(os.path.dirname(DB_PATH), "run/dictionary"))
dnsmasq_mgr = DnsmasqManager(DB_PATH, "/etc/netlab/dnsmasq.conf", "/var/lib/misc/dnsmasq.leases")
tacacs_mgr = TacacsManager(DB_PATH, "/etc/netlab/tac_plus.conf")
ldap_mgr = LdapManager(DB_PATH, "/etc/netlab/slapd.conf", "/var/lib/ldap")

# --- Startup Event ---
@app.on_event("startup")
def startup_event():
    # Initialize DB schemas
    init_db()
    
    # Check what services should start based on settings
    if get_setting("syslog_enabled") == "true":
        port = int(get_setting("syslog_port", "514"))
        syslog_srv.port = port
        syslog_srv.start()
        
    if get_setting("radius_enabled") == "true":
        port = int(get_setting("radius_port", "1812"))
        radius_srv.port = port
        radius_srv.start()
        
    if get_setting("dns_enabled") == "true" or get_setting("dhcp_enabled") == "true":
        dnsmasq_mgr.start()
        
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
        
    if get_setting("ldap_enabled") == "true":
        ldap_mgr.start()

# --- Shutdown Event ---
@app.on_event("shutdown")
def shutdown_event():
    print("Shutting down all services...")
    syslog_srv.stop()
    radius_srv.stop()
    dnsmasq_mgr.stop()
    tacacs_mgr.stop()
    ldap_mgr.stop()

def verify_admin(x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")

@app.middleware("http")
async def role_authorization_middleware(request: Request, call_next):
    # Protect POST, DELETE, PUT routes under /api/ (except auth/login)
    if request.method in ["POST", "DELETE", "PUT"] and request.url.path.startswith("/api/"):
        if request.url.path != "/api/auth/login":
            role = request.headers.get("X-User-Role", "viewer")
            if role != "admin":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Permission denied. Admin privilege required."}
                )
    response = await call_next(request)
    return response

# --- Models ---
class LoginRequest(BaseModel):
    username: str
    password: str

class ServiceToggle(BaseModel):
    enabled: bool

class DnsRecordModel(BaseModel):
    hostname: str
    ip_address: str
    record_type: str = "A"

class DnsSettingsModel(BaseModel):
    enabled: bool
    upstream: str

class DhcpSettingsModel(BaseModel):
    enabled: bool
    interface: str
    start: str
    end: str
    netmask: str
    gateway: str
    dns_servers: str
    lease_time: str

class DhcpStaticModel(BaseModel):
    mac_address: str
    ip_address: str
    hostname: Optional[str] = ""

class RadiusClientModel(BaseModel):
    ip_network: str
    shared_secret: str
    name: Optional[str] = ""

class RadiusUserModel(BaseModel):
    username: str
    password: str

class TacacsClientModel(BaseModel):
    ip_network: str
    shared_secret: str
    name: Optional[str] = ""

class TacacsUserModel(BaseModel):
    username: str
    password: str
    privilege: int = Field(default=15, ge=1, le=15)

class LdapSettingsModel(BaseModel):
    enabled: bool
    port: str
    base_dn: str
    root_dn: str
    root_password: str

class LdapUserModel(BaseModel):
    username: str
    password: str
    email: Optional[str] = ""
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""

class LdapGroupModel(BaseModel):
    group_name: str
    description: Optional[str] = ""

class LdapGroupMembersModel(BaseModel):
    usernames: List[str]

# --- Helper Functions ---
def get_system_stats():
    # RAM Usage
    ram_total = 0
    ram_free = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal" in line:
                    ram_total = int(line.split()[1]) * 1024
                elif "MemAvailable" in line:
                    ram_free = int(line.split()[1]) * 1024
                elif "MemFree" in line and ram_free == 0:
                    ram_free = int(line.split()[1]) * 1024
    except Exception:
        pass
        
    ram_used = ram_total - ram_free
    ram_pct = (ram_used / ram_total * 100) if ram_total > 0 else 0
    
    # CPU Usage (loadavg)
    cpu_load = [0.0, 0.0, 0.0]
    try:
        with open("/proc/loadavg", "r") as f:
            cpu_load = [float(x) for x in f.read().split()[:3]]
    except Exception:
        pass
        
    # Disk Usage
    disk_total = 0
    disk_used = 0
    disk_pct = 0
    try:
        stat = os.statvfs('/')
        disk_total = stat.f_blocks * stat.f_frsize
        disk_free = stat.f_bavail * stat.f_frsize
        disk_used = disk_total - disk_free
        disk_pct = (disk_used / disk_total * 100) if disk_total > 0 else 0
    except Exception:
        pass
        
    # Uptime
    uptime_sec = 0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_sec = float(f.readline().split()[0])
    except Exception:
        pass
        
    # IP Addresses
    ips = {}
    try:
        res = subprocess.run(["ip", "-o", "-4", "addr", "list"], stdout=subprocess.PIPE, text=True)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                ifname = parts[1]
                ip_with_mask = parts[3]
                ips[ifname] = ip_with_mask.split('/')[0]
    except Exception:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips["default"] = s.getsockname()[0]
            s.close()
        except Exception:
            ips["localhost"] = "127.0.0.1"
            
    return {
        "cpu_load": cpu_load,
        "ram_total": ram_total,
        "ram_used": ram_used,
        "ram_pct": round(ram_pct, 1),
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_pct": round(disk_pct, 1),
        "uptime": int(uptime_sec),
        "ips": ips
    }

@app.post("/api/auth/login")
def web_login(payload: LoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    p_hash = hashlib.sha256(payload.password.encode()).hexdigest()
    cursor.execute("SELECT role FROM web_users WHERE username=? AND password_hash=?", (payload.username, p_hash))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    return {
        "status": "success",
        "username": payload.username,
        "role": row["role"]
    }

# --- System API ---
@app.get("/api/status")
def get_status():
    stats = get_system_stats()
    
    # Check process states
    return {
        "system": stats,
        "services": {
            "syslog": {
                "enabled": get_setting("syslog_enabled") == "true",
                "running": syslog_srv.running,
                "port": get_setting("syslog_port", "514")
            },
            "dns": {
                "enabled": get_setting("dns_enabled") == "true",
                "running": dnsmasq_mgr.is_running() and get_setting("dns_enabled") == "true",
                "port": "53"
            },
            "dhcp": {
                "enabled": get_setting("dhcp_enabled") == "true",
                "running": dnsmasq_mgr.is_running() and get_setting("dhcp_enabled") == "true",
                "port": "67"
            },
            "radius": {
                "enabled": get_setting("radius_enabled") == "true",
                "running": radius_srv.running,
                "port": get_setting("radius_port", "1812")
            },
            "tacacs": {
                "enabled": get_setting("tacacs_enabled") == "true",
                "running": tacacs_mgr.is_running(),
                "port": get_setting("tacacs_port", "49")
            },
            "ldap": {
                "enabled": get_setting("ldap_enabled") == "true",
                "running": ldap_mgr.is_running(),
                "port": get_setting("ldap_port", "389")
            }
        }
    }

@app.post("/api/services/{name}/toggle")
def toggle_service(name: str, payload: ServiceToggle):
    val = "true" if payload.enabled else "false"
    
    if name == "syslog":
        set_setting("syslog_enabled", val)
        if payload.enabled:
            syslog_srv.port = int(get_setting("syslog_port", "514"))
            success = syslog_srv.start()
            if not success:
                set_setting("syslog_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to bind Syslog port. Are you running as root?")
        else:
            syslog_srv.stop()
            
    elif name == "dns":
        set_setting("dns_enabled", val)
        # Restart/apply dnsmasq
        dnsmasq_mgr.start()
        
    elif name == "dhcp":
        set_setting("dhcp_enabled", val)
        dnsmasq_mgr.start()
        
    elif name == "radius":
        set_setting("radius_enabled", val)
        if payload.enabled:
            radius_srv.port = int(get_setting("radius_port", "1812"))
            success = radius_srv.start()
            if not success:
                set_setting("radius_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to start RADIUS server. Are you running as root?")
        else:
            radius_srv.stop()
            
    elif name == "tacacs":
        set_setting("tacacs_enabled", val)
        if payload.enabled:
            success = tacacs_mgr.start()
            if not success:
                set_setting("tacacs_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to start TACACS+ daemon. Make sure tac_plus binary is installed.")
        else:
            tacacs_mgr.stop()
            
    elif name == "ldap":
        set_setting("ldap_enabled", val)
        if payload.enabled:
            success = ldap_mgr.start()
            if not success:
                set_setting("ldap_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to start OpenLDAP slapd. Make sure slapd binary is installed.")
        else:
            ldap_mgr.stop()
            
    else:
        raise HTTPException(status_code=400, detail="Invalid service name")
        
    return {"status": "success", "enabled": payload.enabled}

# --- DNS API ---
@app.get("/api/dns")
def get_dns_settings():
    conn = get_db_connection()
    records = [dict(r) for r in conn.execute("SELECT * FROM dns_records").fetchall()]
    conn.close()
    return {
        "enabled": get_setting("dns_enabled") == "true",
        "upstream": get_setting("dns_upstream", "8.8.8.8,1.1.1.1"),
        "records": records
    }

@app.post("/api/dns/settings")
def update_dns_settings(payload: DnsSettingsModel):
    set_setting("dns_enabled", "true" if payload.enabled else "false")
    set_setting("dns_upstream", payload.upstream)
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.post("/api/dns/records")
def add_dns_record(payload: DnsRecordModel):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO dns_records (hostname, ip_address, record_type) VALUES (?, ?, ?)",
            (payload.hostname, payload.ip_address, payload.record_type)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Record already exists")
    conn.close()
    
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.delete("/api/dns/records/{hostname}")
def delete_dns_record(hostname: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM dns_records WHERE hostname=?", (hostname,))
    conn.commit()
    conn.close()
    
    dnsmasq_mgr.start()
    return {"status": "success"}

# --- DHCP API ---
@app.get("/api/dhcp")
def get_dhcp_settings():
    conn = get_db_connection()
    static_leases = [dict(r) for r in conn.execute("SELECT * FROM dhcp_static").fetchall()]
    conn.close()
    
    return {
        "enabled": get_setting("dhcp_enabled") == "true",
        "interface": get_setting("dhcp_interface", "eth0"),
        "start": get_setting("dhcp_start", "192.168.1.100"),
        "end": get_setting("dhcp_end", "192.168.1.200"),
        "netmask": get_setting("dhcp_netmask", "255.255.255.0"),
        "gateway": get_setting("dhcp_gateway", "192.168.1.1"),
        "dns_servers": get_setting("dhcp_dns_servers", "8.8.8.8"),
        "lease_time": get_setting("dhcp_lease_time", "12h"),
        "static_leases": static_leases,
        "active_leases": dnsmasq_mgr.get_active_leases() if dnsmasq_mgr.is_running() else []
    }

@app.post("/api/dhcp/settings")
def update_dhcp_settings(payload: DhcpSettingsModel):
    set_setting("dhcp_enabled", "true" if payload.enabled else "false")
    set_setting("dhcp_interface", payload.interface)
    set_setting("dhcp_start", payload.start)
    set_setting("dhcp_end", payload.end)
    set_setting("dhcp_netmask", payload.netmask)
    set_setting("dhcp_gateway", payload.gateway)
    set_setting("dhcp_dns_servers", payload.dns_servers)
    set_setting("dhcp_lease_time", payload.lease_time)
    
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.post("/api/dhcp/static")
def add_dhcp_static(payload: DhcpStaticModel):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO dhcp_static (mac_address, ip_address, hostname) VALUES (?, ?, ?)",
            (payload.mac_address.lower(), payload.ip_address, payload.hostname)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Static MAC or IP already assigned")
    conn.close()
    
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.delete("/api/dhcp/static/{mac_address}")
def delete_dhcp_static(mac_address: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM dhcp_static WHERE mac_address=?", (mac_address.lower(),))
    conn.commit()
    conn.close()
    
    dnsmasq_mgr.start()
    return {"status": "success"}

# --- RADIUS API ---
@app.get("/api/radius")
def get_radius_data():
    conn = get_db_connection()
    clients = [dict(r) for r in conn.execute("SELECT * FROM radius_clients").fetchall()]
    users = [dict(r) for r in conn.execute("SELECT id, username, password FROM radius_users").fetchall()]
    conn.close()
    
    return {
        "enabled": get_setting("radius_enabled") == "true",
        "port": get_setting("radius_port", "1812"),
        "clients": clients,
        "users": users
    }

@app.post("/api/radius/settings")
def update_radius_settings(port: int = Query(1812)):
    set_setting("radius_port", str(port))
    if get_setting("radius_enabled") == "true":
        radius_srv.stop()
        radius_srv.port = port
        radius_srv.start()
    return {"status": "success"}

@app.post("/api/radius/clients")
def add_radius_client(payload: RadiusClientModel):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO radius_clients (ip_network, shared_secret, name) VALUES (?, ?, ?)",
            (payload.ip_network, payload.shared_secret, payload.name)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="RADIUS client IP network already registered")
    conn.close()
    
    radius_srv.refresh()
    return {"status": "success"}

@app.delete("/api/radius/clients/{ip_network}")
def delete_radius_client(ip_network: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM radius_clients WHERE ip_network=?", (ip_network,))
    conn.commit()
    conn.close()
    
    radius_srv.refresh()
    return {"status": "success"}

@app.post("/api/radius/users")
def add_radius_user(payload: RadiusUserModel):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO radius_users (username, password) VALUES (?, ?)",
            (payload.username, payload.password)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="RADIUS user already exists")
    conn.close()
    return {"status": "success"}

@app.delete("/api/radius/users/{username}")
def delete_radius_user(username: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM radius_users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return {"status": "success"}

# --- TACACS+ API ---
@app.get("/api/tacacs")
def get_tacacs_data():
    conn = get_db_connection()
    clients = [dict(r) for r in conn.execute("SELECT * FROM tacacs_clients").fetchall()]
    users = [dict(r) for r in conn.execute("SELECT id, username, password, privilege FROM tacacs_users").fetchall()]
    conn.close()
    
    return {
        "enabled": get_setting("tacacs_enabled") == "true",
        "port": get_setting("tacacs_port", "49"),
        "clients": clients,
        "users": users
    }

@app.post("/api/tacacs/settings")
def update_tacacs_settings(port: int = Query(49), secret: str = Query("tacsecret")):
    set_setting("tacacs_port", str(port))
    set_setting("tacacs_secret", secret)
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

@app.post("/api/tacacs/clients")
def add_tacacs_client(payload: TacacsClientModel):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO tacacs_clients (ip_network, shared_secret, name) VALUES (?, ?, ?)",
            (payload.ip_network, payload.shared_secret, payload.name)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="TACACS+ client network already registered")
    conn.close()
    
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

@app.delete("/api/tacacs/clients/{ip_network}")
def delete_tacacs_client(ip_network: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM tacacs_clients WHERE ip_network=?", (ip_network,))
    conn.commit()
    conn.close()
    
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

@app.post("/api/tacacs/users")
def add_tacacs_user(payload: TacacsUserModel):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO tacacs_users (username, password, privilege) VALUES (?, ?, ?)",
            (payload.username, payload.password, payload.privilege)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="TACACS+ user already exists")
    conn.close()
    
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

@app.delete("/api/tacacs/users/{username}")
def delete_tacacs_user(username: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM tacacs_users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

# --- LDAP API ---
@app.get("/api/ldap")
def get_ldap_data():
    conn = get_db_connection()
    users = [dict(r) for r in conn.execute("SELECT id, username, email, first_name, last_name FROM ldap_users").fetchall()]
    groups_raw = conn.execute("SELECT id, group_name, description FROM ldap_groups").fetchall()
    
    groups = []
    for g in groups_raw:
        # Get members
        members_raw = conn.execute("""
            SELECT u.username FROM ldap_users u
            JOIN ldap_group_members m ON u.id = m.user_id
            WHERE m.group_id = ?
        """, (g['id'],)).fetchall()
        members = [m['username'] for m in members_raw]
        
        groups.append({
            "id": g['id'],
            "group_name": g['group_name'],
            "description": g['description'],
            "members": members
        })
        
    conn.close()
    
    return {
        "enabled": get_setting("ldap_enabled") == "true",
        "port": get_setting("ldap_port", "389"),
        "base_dn": get_setting("ldap_base_dn", "dc=netlab,dc=local"),
        "root_dn": get_setting("ldap_root_dn", "cn=admin,dc=netlab,dc=local"),
        "users": users,
        "groups": groups
    }

@app.post("/api/ldap/settings")
def update_ldap_settings(payload: LdapSettingsModel):
    set_setting("ldap_enabled", "true" if payload.enabled else "false")
    set_setting("ldap_port", payload.port)
    set_setting("ldap_base_dn", payload.base_dn)
    set_setting("ldap_root_dn", payload.root_dn)
    set_setting("ldap_root_password", payload.root_password)
    
    if payload.enabled:
        ldap_mgr.start()
    else:
        ldap_mgr.stop()
        
    return {"status": "success"}

@app.post("/api/ldap/users")
def add_ldap_user(payload: LdapUserModel):
    success, msg = ldap_mgr.add_user(
        payload.username, payload.password, payload.email,
        payload.first_name, payload.last_name
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.delete("/api/ldap/users/{username}")
def delete_ldap_user(username: str):
    success, msg = ldap_mgr.delete_user(username)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.post("/api/ldap/groups")
def add_ldap_group(payload: LdapGroupModel):
    success, msg = ldap_mgr.add_group(payload.group_name, payload.description)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.delete("/api/ldap/groups/{group_name}")
def delete_ldap_group(group_name: str):
    success, msg = ldap_mgr.delete_group(group_name)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.post("/api/ldap/groups/{group_name}/members")
def update_ldap_group_members(group_name: str, payload: LdapGroupMembersModel):
    success, msg = ldap_mgr.update_group_members(group_name, payload.usernames)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

# --- Syslog and Auth Logs API ---
@app.get("/api/syslog")
def get_syslog_messages(
    search: Optional[str] = Query(None),
    severity: Optional[int] = Query(None),
    hostname: Optional[str] = Query(None),
    limit: int = Query(100)
):
    conn = get_db_connection()
    query = "SELECT * FROM syslog_messages WHERE 1=1"
    params = []
    
    if search:
        query += " AND (message LIKE ? OR hostname LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if severity is not None:
        query += " AND severity = ?"
        params.append(severity)
    if hostname:
        query += " AND hostname = ?"
        params.append(hostname)
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    messages = [dict(r) for r in conn.execute(query, params).fetchall()]
    
    # Get distinct hosts for filters
    hosts = [r['hostname'] for r in conn.execute("SELECT DISTINCT hostname FROM syslog_messages").fetchall()]
    conn.close()
    
    return {
        "messages": messages,
        "hosts": hosts
    }

@app.post("/api/syslog/clear")
def clear_syslogs():
    conn = get_db_connection()
    conn.execute("DELETE FROM syslog_messages")
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/logs/auth")
def get_auth_logs(limit: int = Query(100)):
    conn = get_db_connection()
    logs = [dict(r) for r in conn.execute("SELECT * FROM auth_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    conn.close()
    return logs

@app.post("/api/logs/auth/clear")
def clear_auth_logs():
    conn = get_db_connection()
    conn.execute("DELETE FROM auth_logs")
    conn.commit()
    conn.close()
    return {"status": "success"}

# --- Serve Web Frontend ---
# Setup static files directory
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../frontend")

# Serve index.html directly on root
@app.get("/")
def read_root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "Frontend files not found. Build or copy them to fronted/."}

if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")

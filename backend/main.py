import os
import sys
import time
import subprocess
import socket
import sqlite3
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Header, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
import hashlib
import json
import shutil

# Add local path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, get_db_connection, get_setting, set_setting, DB_PATH
from services.ipam import IpamManager
from services.radius_server import RadiusServerManager, send_radius_coa
from services.dns_dhcp import DnsmasqManager
from services.tacacs import TacacsManager
from services.ldap import LdapManager
from services.ntp import NtpManager
from services.tftp import TftpManager
from services.ftp import FtpManager
from services.network_mgr import NetworkInterfaceManager

app = FastAPI(title="NetLab Services Control Panel API", version="1.0.0")

# --- Service Managers Initialization ---
ipam_mgr = IpamManager(DB_PATH)
radius_srv = RadiusServerManager(DB_PATH, os.path.join(os.path.dirname(DB_PATH), "run/dictionary"))
dnsmasq_mgr = DnsmasqManager(DB_PATH, "/etc/netlab/dnsmasq.conf", "/var/lib/misc/dnsmasq.leases")
tacacs_mgr = TacacsManager(DB_PATH, "/etc/netlab/tac_plus.conf")
ldap_mgr = LdapManager(DB_PATH, "/etc/netlab/slapd.conf", "/var/lib/ldap")
ntp_mgr = NtpManager(DB_PATH)
tftp_mgr = TftpManager(DB_PATH)
ftp_mgr = FtpManager(DB_PATH)
net_mgr = NetworkInterfaceManager(DB_PATH)

# --- Startup Event ---
@app.on_event("startup")
def startup_event():
    # Initialize DB schemas
    init_db()
    
    # Check what services should start based on settings
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
        
    if get_setting("ntp_enabled") == "true":
        ntp_mgr.start()
        
    if get_setting("tftp_enabled") == "true":
        tftp_mgr.start()
        
    if get_setting("ftp_enabled") == "true":
        ftp_mgr.start()

# --- Shutdown Event ---
@app.on_event("shutdown")
def shutdown_event():
    print("Shutting down all services...")
    radius_srv.stop()
    dnsmasq_mgr.stop()
    tacacs_mgr.stop()
    ldap_mgr.stop()
    ntp_mgr.stop()
    tftp_mgr.stop()
    ftp_mgr.stop()

def verify_admin(x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")

@app.middleware("http")
async def role_authorization_middleware(request: Request, call_next):
    # Protect POST, DELETE, PUT routes under /api/ (except auth/login)
    if request.method in ["POST", "DELETE", "PUT"] and request.url.path.startswith("/api/"):
        if request.url.path not in ["/api/auth/login", "/api/tacacs/test-authorization", "/api/radius/coa/send"]:
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

class DhcpGlobalSettingsModel(BaseModel):
    interface: str

class DhcpRangeModel(BaseModel):
    name: str
    start_ip: str
    end_ip: str
    netmask: str = "255.255.255.0"
    gateway: Optional[str] = ""
    dns_servers: Optional[str] = ""
    domain_name: Optional[str] = ""
    lease_time: Optional[str] = "12h"
    interface: Optional[str] = ""
    primary_wlc: Optional[str] = ""
    secondary_wlc: Optional[str] = ""
    tertiary_wlc: Optional[str] = ""
    option_43_hex: Optional[str] = ""
    ntp_servers: Optional[str] = ""
    tftp_server: Optional[str] = ""
    custom_options: Optional[str] = ""

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

class InterfaceConfigModel(BaseModel):
    ifname: str
    mode: str = "static"
    ip_address: Optional[str] = ""
    netmask: Optional[str] = "255.255.255.0"
    gateway: Optional[str] = ""
    dns_servers: Optional[str] = ""
    is_up: bool = True

class RadiusClientModel(BaseModel):
    ip_network: str
    shared_secret: str
    name: Optional[str] = ""

class RadiusUserModel(BaseModel):
    username: str
    password: str

class RadiusCoaModel(BaseModel):
    nas_ip: str
    coa_port: int = 3799
    secret: str = "radsecret"
    packet_type: str = "Disconnect-Request"
    user_name: Optional[str] = ""
    calling_station_id: Optional[str] = ""
    vlan_id: Optional[int] = None
    filter_id: Optional[str] = ""

class TacacsClientModel(BaseModel):
    ip_network: str
    shared_secret: str
    name: Optional[str] = ""

class TacacsUserModel(BaseModel):
    username: str
    password: str
    privilege: int = Field(default=15, ge=1, le=15)
    default_action: str = "permit"

class TacacsCmdRuleModel(BaseModel):
    username: str
    command: str
    argument_regex: Optional[str] = ".*"
    action: str = "permit"

class TacacsAuthTestModel(BaseModel):
    username: str
    command: str

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

class NtpSettingsModel(BaseModel):
    enabled: bool
    pools: str

class IpamSubnetModel(BaseModel):
    name: str
    cidr: str
    vlan_id: Optional[int] = None
    vrf: Optional[str] = "default"
    gateway: Optional[str] = ""
    description: Optional[str] = ""

class IpamAddressModel(BaseModel):
    subnet_id: int
    ip_address: str
    status: str = "active"
    hostname: Optional[str] = ""
    mac_address: Optional[str] = ""
    description: Optional[str] = ""

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
            },
            "ntp": {
                "enabled": get_setting("ntp_enabled") == "true",
                "running": ntp_mgr.is_running(),
                "port": "123"
            },
            "tftp": {
                "enabled": get_setting("tftp_enabled") == "true",
                "running": tftp_mgr.is_running(),
                "port": "69"
            },
            "ftp": {
                "enabled": get_setting("ftp_enabled") == "true",
                "running": ftp_mgr.is_running(),
                "port": "21"
            }
        }
    }

@app.post("/api/services/{name}/toggle")
def toggle_service(name: str, payload: ServiceToggle):
    val = "true" if payload.enabled else "false"
    
    if name == "dns":
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
            
    elif name == "ntp":
        set_setting("ntp_enabled", val)
        if payload.enabled:
            success = ntp_mgr.start()
            if not success:
                set_setting("ntp_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to start NTP daemon (chronyd).")
        else:
            ntp_mgr.stop()
            
    elif name == "tftp":
        set_setting("tftp_enabled", val)
        if payload.enabled:
            success = tftp_mgr.start()
            if not success:
                set_setting("tftp_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to start TFTP daemon. Make sure you run as root to bind to port 69.")
        else:
            tftp_mgr.stop()
            
    elif name == "ftp":
        set_setting("ftp_enabled", val)
        if payload.enabled:
            success = ftp_mgr.start()
            if not success:
                set_setting("ftp_enabled", "false")
                raise HTTPException(status_code=500, detail="Failed to start FTP daemon. Make sure you run as root to bind to port 21.")
        else:
            ftp_mgr.stop()
            
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
    ranges = [dict(r) for r in conn.execute("SELECT * FROM dhcp_ranges ORDER BY id ASC").fetchall()]
    static_leases = [dict(r) for r in conn.execute("SELECT * FROM dhcp_static").fetchall()]
    conn.close()
    
    first_range = ranges[0] if ranges else {}
    
    return {
        "enabled": get_setting("dhcp_enabled") == "true",
        "interface": get_setting("dhcp_interface", "eth0"),
        "ranges": ranges,
        "start": first_range.get("start_ip", get_setting("dhcp_start", "192.168.1.100")),
        "end": first_range.get("end_ip", get_setting("dhcp_end", "192.168.1.200")),
        "netmask": first_range.get("netmask", get_setting("dhcp_netmask", "255.255.255.0")),
        "gateway": first_range.get("gateway", get_setting("dhcp_gateway", "192.168.1.1")),
        "dns_servers": first_range.get("dns_servers", get_setting("dhcp_dns_servers", "8.8.8.8")),
        "lease_time": first_range.get("lease_time", get_setting("dhcp_lease_time", "12h")),
        "static_leases": static_leases,
        "active_leases": dnsmasq_mgr.get_active_leases() if dnsmasq_mgr.is_running() else []
    }

@app.post("/api/dhcp/global-settings")
def update_dhcp_global_settings(payload: DhcpGlobalSettingsModel):
    set_setting("dhcp_interface", payload.interface)
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.post("/api/dhcp/ranges")
def add_dhcp_range(payload: DhcpRangeModel):
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO dhcp_ranges (
            name, start_ip, end_ip, netmask, gateway, dns_servers, domain_name, lease_time,
            interface, primary_wlc, secondary_wlc, tertiary_wlc, option_43_hex,
            ntp_servers, tftp_server, custom_options
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload.name, payload.start_ip, payload.end_ip, payload.netmask, payload.gateway,
        payload.dns_servers, payload.domain_name, payload.lease_time, payload.interface,
        payload.primary_wlc, payload.secondary_wlc, payload.tertiary_wlc, payload.option_43_hex,
        payload.ntp_servers, payload.tftp_server, payload.custom_options
    ))
    conn.commit()
    conn.close()
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.put("/api/dhcp/ranges/{range_id}")
def update_dhcp_range(range_id: int, payload: DhcpRangeModel):
    conn = get_db_connection()
    conn.execute("""
        UPDATE dhcp_ranges SET
            name=?, start_ip=?, end_ip=?, netmask=?, gateway=?, dns_servers=?, domain_name=?,
            lease_time=?, interface=?, primary_wlc=?, secondary_wlc=?, tertiary_wlc=?,
            option_43_hex=?, ntp_servers=?, tftp_server=?, custom_options=?
        WHERE id=?
    """, (
        payload.name, payload.start_ip, payload.end_ip, payload.netmask, payload.gateway,
        payload.dns_servers, payload.domain_name, payload.lease_time, payload.interface,
        payload.primary_wlc, payload.secondary_wlc, payload.tertiary_wlc, payload.option_43_hex,
        payload.ntp_servers, payload.tftp_server, payload.custom_options, range_id
    ))
    conn.commit()
    conn.close()
    dnsmasq_mgr.start()
    return {"status": "success"}

@app.delete("/api/dhcp/ranges/{range_id}")
def delete_dhcp_range(range_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM dhcp_ranges WHERE id=?", (range_id,))
    conn.commit()
    conn.close()
    dnsmasq_mgr.start()
    return {"status": "success"}

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
    
    conn = get_db_connection()
    ranges = conn.execute("SELECT id FROM dhcp_ranges ORDER BY id ASC LIMIT 1").fetchall()
    if ranges:
        conn.execute("""
            UPDATE dhcp_ranges SET start_ip=?, end_ip=?, netmask=?, gateway=?, dns_servers=?, lease_time=? WHERE id=?
        """, (payload.start, payload.end, payload.netmask, payload.gateway, payload.dns_servers, payload.lease_time, ranges[0]['id']))
    else:
        conn.execute("""
            INSERT INTO dhcp_ranges (name, start_ip, end_ip, netmask, gateway, dns_servers, lease_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("Default Scope", payload.start, payload.end, payload.netmask, payload.gateway, payload.dns_servers, payload.lease_time))
    conn.commit()
    conn.close()
    
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

@app.post("/api/radius/coa/send")
def send_coa_packet(payload: RadiusCoaModel):
    res = send_radius_coa(
        nas_ip=payload.nas_ip,
        coa_port=payload.coa_port,
        secret=payload.secret,
        packet_type=payload.packet_type,
        user_name=payload.user_name,
        calling_station_id=payload.calling_station_id,
        vlan_id=payload.vlan_id,
        filter_id=payload.filter_id
    )
    return res

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
            "INSERT INTO tacacs_users (username, password, privilege, default_action) VALUES (?, ?, ?, ?)",
            (payload.username, payload.password, payload.privilege, payload.default_action)
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
    conn.execute("DELETE FROM tacacs_cmd_rules WHERE username=?", (username,))
    conn.commit()
    conn.close()
    
    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

# --- TACACS+ Command Authorization Rules API ---
@app.get("/api/tacacs/rules")
def get_tacacs_rules(username: Optional[str] = Query(None)):
    conn = get_db_connection()
    if username:
        rules = [dict(r) for r in conn.execute("SELECT * FROM tacacs_cmd_rules WHERE username=? ORDER BY id ASC", (username,)).fetchall()]
    else:
        rules = [dict(r) for r in conn.execute("SELECT * FROM tacacs_cmd_rules ORDER BY id ASC").fetchall()]
    conn.close()
    return rules

@app.post("/api/tacacs/rules")
def add_tacacs_rule(payload: TacacsCmdRuleModel, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO tacacs_cmd_rules (username, command, argument_regex, action) VALUES (?, ?, ?, ?)",
        (payload.username, payload.command, payload.argument_regex or ".*", payload.action)
    )
    conn.commit()
    conn.close()

    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

@app.delete("/api/tacacs/rules/{rule_id}")
def delete_tacacs_rule(rule_id: int, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    
    conn = get_db_connection()
    conn.execute("DELETE FROM tacacs_cmd_rules WHERE id=?", (rule_id,))
    conn.commit()
    conn.close()

    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()
    return {"status": "success"}

@app.post("/api/tacacs/test-authorization")
def test_tacacs_authorization(payload: TacacsAuthTestModel):
    return tacacs_mgr.test_authorization(payload.username, payload.command)

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
# --- NTP API ---
@app.get("/api/ntp")
def get_ntp_status():
    return {
        "enabled": get_setting("ntp_enabled") == "true",
        "pools": get_setting("ntp_pools", "pool.ntp.org iburst"),
        "stats": ntp_mgr.get_stats()
    }

@app.post("/api/ntp/settings")
def update_ntp_settings(payload: NtpSettingsModel):
    val = "true" if payload.enabled else "false"
    set_setting("ntp_enabled", val)
    set_setting("ntp_pools", payload.pools)
    
    if payload.enabled:
        success = ntp_mgr.start()
        if not success:
            set_setting("ntp_enabled", "false")
            raise HTTPException(status_code=500, detail="Failed to start NTP daemon (chronyd).")
    else:
        ntp_mgr.stop()
        
    return {"status": "success", "message": "NTP configuration updated."}

# --- File Manager API ---
SHARE_DIR = "/var/lib/netlab/files"

@app.get("/api/files")
def list_files():
    os.makedirs(SHARE_DIR, exist_ok=True)
    files = []
    try:
        for entry in os.scandir(SHARE_DIR):
            if entry.is_file():
                stat = entry.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                files.append({
                    "name": entry.name,
                    "size": stat.st_size,
                    "modified": mtime
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan directory: {e}")
    files.sort(key=lambda x: x["name"])
    return files

@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)):
    os.makedirs(SHARE_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename)
    if not safe_name or safe_name in [".", ".."]:
        raise HTTPException(status_code=400, detail="Invalid filename")
        
    target_path = os.path.join(SHARE_DIR, safe_name)
    try:
        with open(target_path, "wb") as f:
            while content := await file.read(1024 * 1024):
                f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
        
    return {"status": "success", "message": f"File '{safe_name}' uploaded successfully."}

@app.delete("/api/files/{filename}")
def delete_file(filename: str):
    safe_name = os.path.basename(filename)
    target_path = os.path.join(SHARE_DIR, safe_name)
    
    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    try:
        os.remove(target_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")
        
    return {"status": "success", "message": f"File '{safe_name}' deleted successfully."}

@app.get("/api/files/download/{filename}")
def download_file(filename: str):
    safe_name = os.path.basename(filename)
    target_path = os.path.join(SHARE_DIR, safe_name)
    
    if not os.path.exists(target_path) or not os.path.isfile(target_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(path=target_path, filename=safe_name, media_type="application/octet-stream")

def restart_all_services():
    radius_srv.stop()
    dnsmasq_mgr.stop()
    tacacs_mgr.stop()
    ldap_mgr.stop()
    ntp_mgr.stop()
    tftp_mgr.stop()
    ftp_mgr.stop()

    if get_setting("radius_enabled") == "true":
        radius_srv.port = int(get_setting("radius_port", "1812"))
        radius_srv.start()

    if get_setting("dns_enabled") == "true" or get_setting("dhcp_enabled") == "true":
        dnsmasq_mgr.start()

    if get_setting("tacacs_enabled") == "true":
        tacacs_mgr.start()

    if get_setting("ldap_enabled") == "true":
        ldap_mgr.start()

    if get_setting("ntp_enabled") == "true":
        ntp_mgr.start()

    if get_setting("tftp_enabled") == "true":
        tftp_mgr.start()

    if get_setting("ftp_enabled") == "true":
        ftp_mgr.start()

# --- Network Interfaces API ---
@app.get("/api/network/interfaces")
def get_network_interfaces():
    return net_mgr.get_interfaces()

@app.post("/api/network/interfaces")
def update_network_interface(payload: InterfaceConfigModel, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")

    success = net_mgr.apply_interface_config(
        ifname=payload.ifname,
        mode=payload.mode,
        ip_address=payload.ip_address,
        netmask=payload.netmask,
        gateway=payload.gateway,
        dns_servers=payload.dns_servers,
        is_up=payload.is_up
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to apply network interface configuration.")
    return {"status": "success"}

# --- Backup & Restore & Config JSON API ---
@app.get("/api/backup/export")
def export_backup(x_user_role: str = Header(default="viewer")):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Database file not found.")
    return FileResponse(path=DB_PATH, filename="netlab_backup.db", media_type="application/x-sqlite3")

@app.get("/api/config/export/json")
def export_config_json(x_user_role: str = Header(default="viewer")):
    conn = get_db_connection()
    tables = [
        "settings", "dns_records", "dhcp_ranges", "dhcp_static",
        "radius_clients", "radius_users", "tacacs_clients", "tacacs_users", "tacacs_cmd_rules",
        "ldap_users", "ldap_groups", "interface_configs", "ipam_subnets", "ipam_addresses"
    ]
    export_data = {}
    for table in tables:
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            export_data[table] = [dict(r) for r in rows]
        except Exception:
            export_data[table] = []
    conn.close()

    return Response(
        content=json.dumps(export_data, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=netlab_config.json"}
    )

@app.post("/api/config/import/json")
async def import_config_json(file: UploadFile = File(...), x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")

    content = await file.read()
    try:
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON configuration file: {e}")

    conn = get_db_connection()
    cursor = conn.cursor()

    if "settings" in data and isinstance(data["settings"], list):
        for s in data["settings"]:
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (s["key"], s["value"]))

    if "dns_records" in data and isinstance(data["dns_records"], list):
        cursor.execute("DELETE FROM dns_records")
        for rec in data["dns_records"]:
            cursor.execute("INSERT INTO dns_records (hostname, ip_address, record_type) VALUES (?, ?, ?)",
                           (rec["hostname"], rec["ip_address"], rec.get("record_type", "A")))

    if "dhcp_ranges" in data and isinstance(data["dhcp_ranges"], list):
        cursor.execute("DELETE FROM dhcp_ranges")
        for r in data["dhcp_ranges"]:
            cursor.execute("""
                INSERT INTO dhcp_ranges (name, start_ip, end_ip, netmask, gateway, dns_servers, domain_name, lease_time, interface, primary_wlc, secondary_wlc, tertiary_wlc, option_43_hex, ntp_servers, tftp_server, custom_options)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["name"], r["start_ip"], r["end_ip"], r.get("netmask", "255.255.255.0"),
                r.get("gateway", ""), r.get("dns_servers", ""), r.get("domain_name", ""),
                r.get("lease_time", "12h"), r.get("interface", ""), r.get("primary_wlc", ""),
                r.get("secondary_wlc", ""), r.get("tertiary_wlc", ""), r.get("option_43_hex", ""),
                r.get("ntp_servers", ""), r.get("tftp_server", ""), r.get("custom_options", "")
            ))

    if "dhcp_static" in data and isinstance(data["dhcp_static"], list):
        cursor.execute("DELETE FROM dhcp_static")
        for s in data["dhcp_static"]:
            cursor.execute("INSERT INTO dhcp_static (mac_address, ip_address, hostname) VALUES (?, ?, ?)",
                           (s["mac_address"], s["ip_address"], s.get("hostname", "")))

    if "radius_clients" in data and isinstance(data["radius_clients"], list):
        cursor.execute("DELETE FROM radius_clients")
        for c in data["radius_clients"]:
            cursor.execute("INSERT INTO radius_clients (ip_network, shared_secret, name) VALUES (?, ?, ?)",
                           (c["ip_network"], c["shared_secret"], c.get("name", "")))

    if "radius_users" in data and isinstance(data["radius_users"], list):
        cursor.execute("DELETE FROM radius_users")
        for u in data["radius_users"]:
            cursor.execute("INSERT INTO radius_users (username, password) VALUES (?, ?)",
                           (u["username"], u["password"]))

    if "tacacs_clients" in data and isinstance(data["tacacs_clients"], list):
        cursor.execute("DELETE FROM tacacs_clients")
        for c in data["tacacs_clients"]:
            cursor.execute("INSERT INTO tacacs_clients (ip_network, shared_secret, name) VALUES (?, ?, ?)",
                           (c["ip_network"], c["shared_secret"], c.get("name", "")))

    if "tacacs_users" in data and isinstance(data["tacacs_users"], list):
        cursor.execute("DELETE FROM tacacs_users")
        for u in data["tacacs_users"]:
            cursor.execute("INSERT INTO tacacs_users (username, password, privilege, default_action) VALUES (?, ?, ?, ?)",
                           (u["username"], u["password"], u.get("privilege", 15), u.get("default_action", "permit")))

    if "tacacs_cmd_rules" in data and isinstance(data["tacacs_cmd_rules"], list):
        cursor.execute("DELETE FROM tacacs_cmd_rules")
        for r in data["tacacs_cmd_rules"]:
            cursor.execute("INSERT INTO tacacs_cmd_rules (username, command, argument_regex, action) VALUES (?, ?, ?, ?)",
                           (r["username"], r["command"], r.get("argument_regex", ".*"), r.get("action", "permit")))

    if "interface_configs" in data and isinstance(data["interface_configs"], list):
        for ic in data["interface_configs"]:
            cursor.execute("""
                INSERT OR REPLACE INTO interface_configs (ifname, mode, ip_address, netmask, gateway, dns_servers, is_up)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ic["ifname"], ic.get("mode", "static"), ic.get("ip_address", ""), ic.get("netmask", "255.255.255.0"),
                  ic.get("gateway", ""), ic.get("dns_servers", ""), 1 if ic.get("is_up", True) else 0))

    if "ipam_subnets" in data and isinstance(data["ipam_subnets"], list):
        cursor.execute("DELETE FROM ipam_subnets")
        for sub in data["ipam_subnets"]:
            cursor.execute("""
                INSERT INTO ipam_subnets (id, name, cidr, vlan_id, vrf, gateway, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (sub["id"], sub["name"], sub["cidr"], sub.get("vlan_id"), sub.get("vrf", "default"), sub.get("gateway", ""), sub.get("description", "")))

    if "ipam_addresses" in data and isinstance(data["ipam_addresses"], list):
        cursor.execute("DELETE FROM ipam_addresses")
        for addr in data["ipam_addresses"]:
            cursor.execute("""
                INSERT INTO ipam_addresses (id, subnet_id, ip_address, status, hostname, mac_address, description, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (addr["id"], addr["subnet_id"], addr["ip_address"], addr.get("status", "active"), addr.get("hostname", ""), addr.get("mac_address", ""), addr.get("description", ""), addr.get("last_seen")))

    conn.commit()
    conn.close()

    restart_all_services()
    return {"status": "success", "message": "Configuration successfully imported and services restarted."}

@app.post("/api/backup/import")
async def import_backup(file: UploadFile = File(...), x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")

    content = await file.read()
    if not content.startswith(b'SQLite format 3\x00'):
        raise HTTPException(status_code=400, detail="Invalid file format. Must be an SQLite 3 database file.")

    temp_db_path = DB_PATH + ".temp"
    try:
        with open(temp_db_path, "wb") as f:
            f.write(content)

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        if not cursor.fetchone():
            conn.close()
            os.remove(temp_db_path)
            raise HTTPException(status_code=400, detail="Invalid configuration database: 'settings' table is missing.")
        conn.close()
    except Exception as e:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
        raise HTTPException(status_code=400, detail=f"Failed to validate database file: {str(e)}")

    try:
        shutil.copy2(temp_db_path, DB_PATH)
        os.remove(temp_db_path)
        restart_all_services()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore database: {str(e)}")
        
    return {"status": "success", "message": "Configuration database restored successfully. Services restarted."}

# --- IPAM (IP Address Management) API ---
@app.get("/api/ipam/subnets")
def get_ipam_subnets():
    return ipam_mgr.get_subnets()

@app.post("/api/ipam/subnets")
def add_ipam_subnet(payload: IpamSubnetModel, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    try:
        subnet_id = ipam_mgr.add_subnet(
            name=payload.name,
            cidr=payload.cidr,
            vlan_id=payload.vlan_id,
            vrf=payload.vrf,
            gateway=payload.gateway,
            description=payload.description
        )
        return {"status": "success", "id": subnet_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/ipam/subnets/{subnet_id}")
def delete_ipam_subnet(subnet_id: int, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    ipam_mgr.delete_subnet(subnet_id)
    return {"status": "success"}

@app.get("/api/ipam/subnets/{subnet_id}/addresses")
def get_ipam_subnet_addresses(subnet_id: int):
    res = ipam_mgr.get_subnet_addresses(subnet_id)
    if not res:
        raise HTTPException(status_code=404, detail="Subnet not found.")
    return res

@app.post("/api/ipam/addresses")
def save_ipam_address(payload: IpamAddressModel, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    ipam_mgr.set_address(
        subnet_id=payload.subnet_id,
        ip_address=payload.ip_address,
        status=payload.status,
        hostname=payload.hostname,
        mac_address=payload.mac_address,
        description=payload.description
    )
    return {"status": "success"}

@app.delete("/api/ipam/addresses/{address_id}")
def delete_ipam_address(address_id: int, x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    ipam_mgr.delete_address(address_id)
    return {"status": "success"}

@app.post("/api/ipam/sync")
def sync_ipam_services(x_user_role: str = Header(default="viewer")):
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Permission denied. Admin privilege required.")
    
    conn = get_db_connection()
    dhcp_static = [dict(r) for r in conn.execute("SELECT * FROM dhcp_static").fetchall()]
    conn.close()

    active_leases = dnsmasq_mgr.get_active_leases()
    ifaces = net_mgr.get_interfaces()

    count = ipam_mgr.sync_from_services(
        dhcp_static_leases=dhcp_static,
        active_dhcp_leases=active_leases,
        interface_configs=ifaces
    )
    return {"status": "success", "synced_count": count, "message": f"Successfully auto-discovered & synced {count} IP allocations into IPAM."}

@app.get("/api/ipam/search")
def search_ipam(q: str = Query("")):
    if not q:
        return []
    return ipam_mgr.search(q)

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

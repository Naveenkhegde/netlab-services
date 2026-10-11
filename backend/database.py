import sqlite3
import os
import hashlib


DEFAULT_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "netlab.db"))
DB_PATH = os.environ.get("NETLAB_DB_PATH", DEFAULT_DB)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    # Create DNS records table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dns_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT NOT NULL UNIQUE,
        ip_address TEXT NOT NULL,
        record_type TEXT NOT NULL DEFAULT 'A'
    )
    """)
    
    # Create DHCP static leases table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dhcp_static (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mac_address TEXT NOT NULL UNIQUE,
        ip_address TEXT NOT NULL UNIQUE,
        hostname TEXT
    )
    """)
    
    # Create DHCP ranges/scopes table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dhcp_ranges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        start_ip TEXT NOT NULL,
        end_ip TEXT NOT NULL,
        netmask TEXT NOT NULL DEFAULT '255.255.255.0',
        gateway TEXT,
        dns_servers TEXT,
        domain_name TEXT,
        lease_time TEXT DEFAULT '12h',
        interface TEXT,
        primary_wlc TEXT,
        secondary_wlc TEXT,
        tertiary_wlc TEXT,
        option_43_hex TEXT,
        ntp_servers TEXT,
        tftp_server TEXT,
        custom_options TEXT
    )
    """)
    # Create Network Interfaces configuration table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS interface_configs (
        ifname TEXT PRIMARY KEY,
        mode TEXT NOT NULL DEFAULT 'static',
        ip_address TEXT,
        netmask TEXT DEFAULT '255.255.255.0',
        gateway TEXT,
        dns_servers TEXT,
        is_up INTEGER DEFAULT 1
    )
    """)

    # Create RADIUS clients table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS radius_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_network TEXT NOT NULL UNIQUE,
        shared_secret TEXT NOT NULL,
        name TEXT
    )
    """)
    
    # Create RADIUS users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS radius_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    """)
    
    # Create TACACS+ clients table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tacacs_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_network TEXT NOT NULL UNIQUE,
        shared_secret TEXT NOT NULL,
        name TEXT
    )
    """)
    
    # Create TACACS+ users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tacacs_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        privilege INTEGER NOT NULL DEFAULT 15,
        default_action TEXT NOT NULL DEFAULT 'permit'
    )
    """)
    try:
        cursor.execute("ALTER TABLE tacacs_users ADD COLUMN default_action TEXT NOT NULL DEFAULT 'permit'")
    except Exception:
        pass
    
    # Create TACACS+ command authorization rules table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tacacs_cmd_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        command TEXT NOT NULL,
        argument_regex TEXT NOT NULL DEFAULT '.*',
        action TEXT NOT NULL CHECK(action IN ('permit', 'deny'))
    )
    """)
    
    # Create LDAP users table (local sync/cache, real entries in OpenLDAP)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ldap_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        email TEXT,
        first_name TEXT,
        last_name TEXT
    )
    """)
    
    # Create LDAP groups table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ldap_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT NOT NULL UNIQUE,
        description TEXT
    )
    """)
    
    # Create LDAP group members table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ldap_group_members (
        group_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (group_id, user_id),
        FOREIGN KEY (group_id) REFERENCES ldap_groups(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES ldap_users(id) ON DELETE CASCADE
    )
    """)
    
    # Create IPAM Subnets table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ipam_subnets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        cidr TEXT NOT NULL UNIQUE,
        vlan_id INTEGER,
        vrf TEXT,
        gateway TEXT,
        description TEXT
    )
    """)
    
    # Create IPAM Addresses table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ipam_addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subnet_id INTEGER NOT NULL,
        ip_address TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'available',
        hostname TEXT,
        mac_address TEXT,
        description TEXT,
        last_seen DATETIME,
        FOREIGN KEY(subnet_id) REFERENCES ipam_subnets(id) ON DELETE CASCADE,
        UNIQUE(subnet_id, ip_address)
    )
    """)

    # Create Auth logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auth_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        service TEXT, -- 'RADIUS' or 'TACACS' or 'LDAP'
        username TEXT,
        client_ip TEXT,
        status TEXT, -- 'Accepted' or 'Rejected'
        message TEXT
    )
    """)

    # Create Web UI Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS web_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'viewer'))
    )
    """)
    
    # Insert default settings if they don't exist
    default_settings = {
        "dns_enabled": "false",
        "dns_upstream": "8.8.8.8,1.1.1.1",
        "dhcp_enabled": "false",
        "dhcp_interface": "eth0",
        "dhcp_start": "192.168.1.100",
        "dhcp_end": "192.168.1.200",
        "dhcp_netmask": "255.255.255.0",
        "dhcp_gateway": "192.168.1.1",
        "dhcp_dns_servers": "192.168.1.2",
        "dhcp_lease_time": "12h",
        "radius_enabled": "false",
        "radius_port": "1812",
        "radius_secret": "radsecret",
        "tacacs_enabled": "false",
        "tacacs_port": "49",
        "tacacs_secret": "tacsecret",
        "ldap_enabled": "false",
        "ldap_port": "389",
        "ldap_base_dn": "dc=netlab,dc=local",
        "ldap_root_dn": "cn=admin,dc=netlab,dc=local",
        "ldap_root_password": "adminpassword",
        "ntp_enabled": "false",
        "ntp_pools": "pool.ntp.org iburst",
        "tftp_enabled": "false",
        "ftp_enabled": "false"
    }
    
    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))
        
    # Insert default web users if they don't exist
    # Hashed passwords for default credentials: netlab
    default_hash = hashlib.sha256(b"netlab").hexdigest()
    cursor.execute("INSERT OR IGNORE INTO web_users (username, password_hash, role) VALUES (?, ?, ?)", ("admin", default_hash, "admin"))
    cursor.execute("INSERT OR IGNORE INTO web_users (username, password_hash, role) VALUES (?, ?, ?)", ("viewer", default_hash, "viewer"))
        
    # Auto-migrate single DHCP settings to dhcp_ranges table if empty
    cursor.execute("SELECT COUNT(*) FROM dhcp_ranges")
    if cursor.fetchone()[0] == 0:
        cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'dhcp_%'")
        s_map = {row['key']: row['value'] for row in cursor.fetchall()}
        cursor.execute("""
            INSERT INTO dhcp_ranges (name, start_ip, end_ip, netmask, gateway, dns_servers, lease_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "Default Scope",
            s_map.get("dhcp_start", "192.168.1.100"),
            s_map.get("dhcp_end", "192.168.1.200"),
            s_map.get("dhcp_netmask", "255.255.255.0"),
            s_map.get("dhcp_gateway", "192.168.1.1"),
            s_map.get("dhcp_dns_servers", "192.168.1.2"),
            s_map.get("dhcp_lease_time", "12h")
        ))

    # Auto-seed default IPAM subnet if empty
    cursor.execute("SELECT COUNT(*) FROM ipam_subnets")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO ipam_subnets (name, cidr, vlan_id, vrf, gateway, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Default Management Subnet", "192.168.1.0/24", 1, "default", "192.168.1.1", "Primary Network Lab Management Subnet"))

    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()

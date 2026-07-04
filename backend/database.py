import sqlite3
import os
import hashlib


DB_PATH = os.environ.get("NETLAB_DB_PATH", "netlab.db")

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
        privilege INTEGER NOT NULL DEFAULT 15
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
    
    # Create Syslog messages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS syslog_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        severity INTEGER,
        facility INTEGER,
        hostname TEXT,
        message TEXT
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
        "syslog_enabled": "true",
        "syslog_port": "514"
    }
    
    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))
        
    # Insert default web users if they don't exist
    # Hashed passwords for default credentials: netlab
    default_hash = hashlib.sha256(b"netlab").hexdigest()
    cursor.execute("INSERT OR IGNORE INTO web_users (username, password_hash, role) VALUES (?, ?, ?)", ("admin", default_hash, "admin"))
    cursor.execute("INSERT OR IGNORE INTO web_users (username, password_hash, role) VALUES (?, ?, ?)", ("viewer", default_hash, "viewer"))
        
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

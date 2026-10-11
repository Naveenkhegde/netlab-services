import ipaddress
import sqlite3
import datetime

class IpamManager:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_subnets(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM ipam_subnets ORDER BY id ASC")
        subnets_raw = [dict(r) for r in cursor.fetchall()]
        
        results = []
        for s in subnets_raw:
            subnet_id = s["id"]
            cidr = s["cidr"]
            
            total_ips = 0
            usable_ips = 0
            try:
                net = ipaddress.IPv4Network(cidr, strict=False)
                total_ips = net.num_addresses
                usable_ips = total_ips - 2 if total_ips > 2 else total_ips
            except Exception:
                pass

            cursor.execute("""
                SELECT status, COUNT(*) as cnt 
                FROM ipam_addresses 
                WHERE subnet_id = ? 
                GROUP BY status
            """, (subnet_id,))
            
            counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            allocated_cnt = counts.get("active", 0) + counts.get("dhcp", 0) + counts.get("dhcp_static", 0) + counts.get("reserved", 0)
            available_cnt = usable_ips - allocated_cnt if usable_ips >= allocated_cnt else 0

            usage_pct = round((allocated_cnt / usable_ips * 100), 1) if usable_ips > 0 else 0

            results.append({
                **s,
                "total_ips": total_ips,
                "usable_ips": usable_ips,
                "allocated_ips": allocated_cnt,
                "available_ips": available_cnt,
                "active_ips": counts.get("active", 0),
                "dhcp_ips": counts.get("dhcp", 0) + counts.get("dhcp_static", 0),
                "reserved_ips": counts.get("reserved", 0),
                "usage_pct": usage_pct
            })
            
        conn.close()
        return results

    def add_subnet(self, name, cidr, vlan_id=None, vrf=None, gateway=None, description=None):
        # Validate CIDR
        net = ipaddress.IPv4Network(cidr.strip(), strict=False)
        normalized_cidr = str(net)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ipam_subnets (name, cidr, vlan_id, vrf, gateway, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, normalized_cidr, vlan_id, vrf, gateway, description))
        subnet_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Auto-register gateway if specified
        if gateway:
            try:
                gw_ip = ipaddress.IPv4Address(gateway.strip())
                if gw_ip in net:
                    self.set_address(subnet_id, str(gw_ip), "reserved", hostname="Default Gateway", description="Subnet Default Gateway")
            except Exception:
                pass

        return subnet_id

    def delete_subnet(self, subnet_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ipam_addresses WHERE subnet_id = ?", (subnet_id,))
        cursor.execute("DELETE FROM ipam_subnets WHERE id = ?", (subnet_id,))
        conn.commit()
        conn.close()
        return True

    def get_subnet_addresses(self, subnet_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM ipam_subnets WHERE id = ?", (subnet_id,))
        subnet_row = cursor.fetchone()
        if not subnet_row:
            conn.close()
            return None

        subnet_dict = dict(subnet_row)
        cidr = subnet_dict["cidr"]

        cursor.execute("SELECT * FROM ipam_addresses WHERE subnet_id = ? ORDER BY id ASC", (subnet_id,))
        saved_addrs = {r["ip_address"]: dict(r) for r in cursor.fetchall()}
        conn.close()

        addr_list = []
        try:
            net = ipaddress.IPv4Network(cidr, strict=False)
            hosts = list(net.hosts()) if net.num_addresses > 2 else list(net)
            
            for h in hosts:
                ip_str = str(h)
                if ip_str in saved_addrs:
                    addr_list.append(saved_addrs[ip_str])
                else:
                    addr_list.append({
                        "id": None,
                        "subnet_id": subnet_id,
                        "ip_address": ip_str,
                        "status": "available",
                        "hostname": "",
                        "mac_address": "",
                        "description": "",
                        "last_seen": None
                    })
        except Exception as err:
            print(f"Error parsing IPAM subnet address range {cidr}: {err}")

        return {
            "subnet": subnet_dict,
            "addresses": addr_list
        }

    def set_address(self, subnet_id, ip_address, status, hostname="", mac_address="", description=""):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO ipam_addresses (subnet_id, ip_address, status, hostname, mac_address, description, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subnet_id, ip_address) DO UPDATE SET
                status = excluded.status,
                hostname = COALESCE(NULLIF(excluded.hostname, ''), ipam_addresses.hostname),
                mac_address = COALESCE(NULLIF(excluded.mac_address, ''), ipam_addresses.mac_address),
                description = COALESCE(NULLIF(excluded.description, ''), ipam_addresses.description),
                last_seen = excluded.last_seen
        """, (subnet_id, ip_address, status, hostname or "", mac_address or "", description or "", now_str))

        conn.commit()
        conn.close()
        return True

    def delete_address(self, address_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ipam_addresses WHERE id = ?", (address_id,))
        conn.commit()
        conn.close()
        return True

    def sync_from_services(self, dhcp_static_leases=None, active_dhcp_leases=None, interface_configs=None):
        """Auto-discovers IPs from DHCP leases, DHCP static bindings, and network interface configs."""
        subnets = self.get_subnets()
        if not subnets:
            return 0

        synced_count = 0

        # Helper to match IP to a subnet ID
        def find_subnet_id(ip_str):
            try:
                ip_obj = ipaddress.IPv4Address(ip_str)
                for s in subnets:
                    net_obj = ipaddress.IPv4Network(s["cidr"], strict=False)
                    if ip_obj in net_obj:
                        return s["id"]
            except Exception:
                pass
            return None

        # 1. Sync Network Interfaces
        if interface_configs:
            for iface in interface_configs:
                ip_val = iface.get("ip_address") or iface.get("current_ip")
                if ip_val:
                    sid = find_subnet_id(ip_val)
                    if sid:
                        self.set_address(sid, ip_val, "active", hostname=f"Interface {iface.get('ifname', '')}", mac_address=iface.get("mac", ""), description="NetLab Appliance Interface")
                        synced_count += 1

        # 2. Sync DHCP Static Leases
        if dhcp_static_leases:
            for lease in dhcp_static_leases:
                ip_val = lease.get("ip_address")
                if ip_val:
                    sid = find_subnet_id(ip_val)
                    if sid:
                        self.set_address(sid, ip_val, "dhcp_static", hostname=lease.get("hostname", ""), mac_address=lease.get("mac_address", ""), description="DHCP Static Reservation")
                        synced_count += 1

        # 3. Sync Active DHCP Leases
        if active_dhcp_leases:
            for lease in active_dhcp_leases:
                ip_val = lease.get("ip_address")
                if ip_val:
                    sid = find_subnet_id(ip_val)
                    if sid:
                        self.set_address(sid, ip_val, "dhcp", hostname=lease.get("hostname", ""), mac_address=lease.get("mac_address", ""), description="Active DHCP Dynamic Lease")
                        synced_count += 1

        return synced_count

    def search(self, query):
        q = f"%{query.strip()}%"
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT a.*, s.name as subnet_name, s.cidr as subnet_cidr
            FROM ipam_addresses a
            JOIN ipam_subnets s ON a.subnet_id = s.id
            WHERE a.ip_address LIKE ? OR a.hostname LIKE ? OR a.mac_address LIKE ? OR a.description LIKE ? OR s.name LIKE ? OR s.cidr LIKE ?
            ORDER BY a.ip_address ASC
            LIMIT 100
        """, (q, q, q, q, q, q))
        
        results = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return results

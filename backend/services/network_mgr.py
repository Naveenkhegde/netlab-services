import os
import json
import subprocess
import ipaddress
import sqlite3
import shutil

class NetworkInterfaceManager:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_interfaces(self):
        sys_ifaces = {}
        
        # 1. Attempt ip -j addr show (JSON output)
        try:
            out = subprocess.check_output(["ip", "-j", "addr", "show"], text=True, stderr=subprocess.DEVNULL)
            data = json.loads(out)
            for item in data:
                ifname = item.get("ifname")
                if not ifname or ifname == "lo" or ifname.startswith(("veth", "docker", "virbr", "gns3tap")):
                    continue
                mac = item.get("address", "")
                flags = item.get("flags", [])
                operstate = item.get("operstate", "DOWN")
                is_up = "UP" in flags or operstate == "UP"

                ipv4_addrs = []
                netmask = "255.255.255.0"
                for a in item.get("addr_info", []):
                    if a.get("family") == "inet":
                        ip_val = a.get("local")
                        prefix = a.get("prefixlen", 24)
                        ipv4_addrs.append(ip_val)
                        try:
                            netmask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
                        except Exception:
                            pass

                sys_ifaces[ifname] = {
                    "ifname": ifname,
                    "mac": mac,
                    "is_up": is_up,
                    "operstate": operstate,
                    "current_ip": ipv4_addrs[0] if ipv4_addrs else "",
                    "current_netmask": netmask if ipv4_addrs else "",
                    "mode": "static",
                    "ip_address": ipv4_addrs[0] if ipv4_addrs else "",
                    "netmask": netmask if ipv4_addrs else "255.255.255.0",
                    "gateway": "",
                    "dns_servers": ""
                }
        except Exception:
            pass

        # 2. Fallback: Parse standard ip addr show (without -j) & /sys/class/net for BusyBox / Alpine Linux
        if not sys_ifaces:
            ifnames = set()
            if os.path.exists("/sys/class/net"):
                for name in os.listdir("/sys/class/net"):
                    if name != "lo" and not name.startswith(("veth", "docker", "virbr", "gns3tap")):
                        ifnames.add(name)

            try:
                out = subprocess.check_output(["ip", "addr", "show"], text=True, stderr=subprocess.DEVNULL)
                current_if = None
                for line in out.splitlines():
                    if line and line[0].isdigit():
                        parts = line.split(":")
                        if len(parts) >= 2:
                            current_if = parts[1].strip()
                            if current_if != "lo" and not current_if.startswith(("veth", "docker", "virbr", "gns3tap")):
                                ifnames.add(current_if)
                                is_up = "UP" in line
                                if current_if not in sys_ifaces:
                                    sys_ifaces[current_if] = {
                                        "ifname": current_if,
                                        "mac": "-",
                                        "is_up": is_up,
                                        "operstate": "UP" if is_up else "DOWN",
                                        "current_ip": "",
                                        "current_netmask": "255.255.255.0",
                                        "mode": "static",
                                        "ip_address": "",
                                        "netmask": "255.255.255.0",
                                        "gateway": "",
                                        "dns_servers": ""
                                    }
                    elif current_if and current_if in sys_ifaces:
                        line_str = line.strip()
                        if line_str.startswith("link/ether"):
                            mac_parts = line_str.split()
                            if len(mac_parts) >= 2:
                                sys_ifaces[current_if]["mac"] = mac_parts[1]
                        elif line_str.startswith("inet "):
                            inet_parts = line_str.split()
                            if len(inet_parts) >= 2:
                                cidr = inet_parts[1]
                                if "/" in cidr:
                                    ip_val, prefix = cidr.split("/")
                                    sys_ifaces[current_if]["current_ip"] = ip_val
                                    sys_ifaces[current_if]["ip_address"] = ip_val
                                    try:
                                        netmask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
                                        sys_ifaces[current_if]["current_netmask"] = netmask
                                        sys_ifaces[current_if]["netmask"] = netmask
                                    except Exception:
                                        pass
                                else:
                                    sys_ifaces[current_if]["current_ip"] = cidr
                                    sys_ifaces[current_if]["ip_address"] = cidr
            except Exception:
                pass

            for ifname in ifnames:
                if ifname not in sys_ifaces:
                    sys_ifaces[ifname] = {
                        "ifname": ifname,
                        "mac": "-",
                        "is_up": False,
                        "operstate": "DOWN",
                        "current_ip": "",
                        "current_netmask": "255.255.255.0",
                        "mode": "static",
                        "ip_address": "",
                        "netmask": "255.255.255.0",
                        "gateway": "",
                        "dns_servers": ""
                    }

        # 3. Merge with saved database configuration
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM interface_configs")
            rows = cursor.fetchall()
            for r in rows:
                ifname = r["ifname"]
                if ifname in sys_ifaces:
                    sys_ifaces[ifname]["mode"] = r["mode"] or sys_ifaces[ifname]["mode"]
                    if r["ip_address"]:
                        sys_ifaces[ifname]["ip_address"] = r["ip_address"]
                    if r["netmask"]:
                        sys_ifaces[ifname]["netmask"] = r["netmask"]
                    sys_ifaces[ifname]["gateway"] = r["gateway"] or ""
                    sys_ifaces[ifname]["dns_servers"] = r["dns_servers"] or ""
                    sys_ifaces[ifname]["is_up"] = bool(r["is_up"])
                else:
                    sys_ifaces[ifname] = {
                        "ifname": ifname,
                        "mac": "-",
                        "is_up": bool(r["is_up"]),
                        "operstate": "DOWN",
                        "current_ip": r["ip_address"] or "",
                        "current_netmask": r["netmask"] or "255.255.255.0",
                        "mode": r["mode"],
                        "ip_address": r["ip_address"] or "",
                        "netmask": r["netmask"] or "255.255.255.0",
                        "gateway": r["gateway"] or "",
                        "dns_servers": r["dns_servers"] or ""
                    }
            conn.close()
        except Exception as err:
            print(f"Error reading interface_configs table: {err}")

        return list(sys_ifaces.values())

    def apply_interface_config(self, ifname, mode, ip_address, netmask, gateway, dns_servers, is_up=True):
        # 1. Save to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO interface_configs (ifname, mode, ip_address, netmask, gateway, dns_servers, is_up)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ifname, mode, ip_address, netmask, gateway, dns_servers, 1 if is_up else 0))
        conn.commit()
        conn.close()

        # 2. Execute Linux networking commands
        try:
            if not is_up:
                subprocess.run(["ip", "link", "set", "dev", ifname, "down"], check=False)
                return True

            subprocess.run(["ip", "link", "set", "dev", ifname, "up"], check=False)

            if mode == "dhcp":
                subprocess.run(["ip", "addr", "flush", "dev", ifname], check=False)
                if shutil.which("udhcpc"):
                    subprocess.Popen(["udhcpc", "-i", ifname, "-b", "-q"])
                elif shutil.which("dhclient"):
                    subprocess.Popen(["dhclient", "-nw", ifname])
            elif mode == "static" and ip_address:
                try:
                    prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
                except Exception:
                    prefixlen = 24
                
                subprocess.run(["ip", "addr", "flush", "dev", ifname], check=False)
                subprocess.run(["ip", "addr", "add", f"{ip_address}/{prefixlen}", "dev", ifname], check=False)

                if gateway:
                    subprocess.run(["ip", "route", "replace", "default", "via", gateway, "dev", ifname], check=False)

                if dns_servers:
                    try:
                        resolv_lines = []
                        for dns in dns_servers.split(","):
                            dns = dns.strip()
                            if dns:
                                resolv_lines.append(f"nameserver {dns}")
                        if resolv_lines:
                            with open("/etc/resolv.conf", "w") as f:
                                f.write("\n".join(resolv_lines) + "\n")
                    except Exception as err:
                        print(f"Could not update /etc/resolv.conf: {err}")

            self.update_etc_network_interfaces()
        except Exception as err:
            print(f"Error applying network interface configuration for {ifname}: {err}")

        return True

    def update_etc_network_interfaces(self):
        conf_file = "/etc/network/interfaces"
        if not os.path.exists(conf_file) and not os.access("/etc/network", os.W_OK):
            return

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM interface_configs")
            configs = cursor.fetchall()
            conn.close()

            lines = [
                "# Managed by NetLab Services Control Panel",
                "auto lo",
                "iface lo inet loopback",
                ""
            ]

            for cfg in configs:
                ifname = cfg["ifname"]
                mode = cfg["mode"]
                lines.append(f"auto {ifname}")
                if mode == "dhcp":
                    lines.append(f"iface {ifname} inet dhcp")
                else:
                    lines.append(f"iface {ifname} inet static")
                    if cfg["ip_address"]:
                        lines.append(f"    address {cfg['ip_address']}")
                    if cfg["netmask"]:
                        lines.append(f"    netmask {cfg['netmask']}")
                    if cfg["gateway"]:
                        lines.append(f"    gateway {cfg['gateway']}")
                lines.append("")

            with open(conf_file, "w") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as err:
            print(f"Could not update /etc/network/interfaces: {err}")

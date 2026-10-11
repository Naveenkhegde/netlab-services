import os
import threading
import sqlite3
from pyrad import dictionary, server, packet

# Simple standard dictionary to save to disk if not exists
DICTIONARY_CONTENT = """
ATTRIBUTE	User-Name		1	string
ATTRIBUTE	User-Password		2	string
ATTRIBUTE	CHAP-Password		3	octets
ATTRIBUTE	NAS-IP-Address		4	ipaddr
ATTRIBUTE	NAS-Port		5	integer
ATTRIBUTE	Service-Type		6	integer
ATTRIBUTE	Framed-Protocol		7	integer
ATTRIBUTE	Framed-IP-Address	8	ipaddr
ATTRIBUTE	Reply-Message		18	string
ATTRIBUTE	NAS-Identifier		32	string
ATTRIBUTE	State			24	octets
ATTRIBUTE	Class			25	octets
ATTRIBUTE	Session-Timeout		27	integer
ATTRIBUTE	Termination-Action	28	integer
ATTRIBUTE	Called-Station-Id	30	string
ATTRIBUTE	Calling-Station-Id	31	string
ATTRIBUTE	NAS-Port-Type		61	integer
ATTRIBUTE	Port-Limit		62	integer
ATTRIBUTE	Login-LAT-Port		63	string
"""

class LabRadiusServer(server.Server):
    def __init__(self, db_path, dict_path, host="0.0.0.0", port=1812):
        self.db_path = db_path
        self.dict_path = dict_path
        self.host = host
        self.port = port
        self.thread = None
        self.running = False
        
        # Ensure dictionary exists
        if not os.path.exists(dict_path):
            os.makedirs(os.path.dirname(dict_path), exist_ok=True)
            with open(dict_path, "w") as f:
                f.write(DICTIONARY_CONTENT.strip())
                
        self.dict = dictionary.Dictionary(dict_path)
        # Bind to socket using pyrad's constructor
        super().__init__(addresses=[host], authport=port, acctport=port + 1, dict=self.dict)
        self.refresh_clients()

    def refresh_clients(self):
        # Read from SQLite and update pyrad hosts mapping
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT ip_network, shared_secret FROM radius_clients")
        rows = cursor.fetchall()
        conn.close()
        
        self.hosts = {}
        # Also always add localhost
        self.hosts["127.0.0.1"] = server.RemoteHost("127.0.0.1", b"radsecret", "localhost")
        
        for ip_network, secret in rows:
            # Note: pyrad checks pkt.source[0] (which is the string IP address) against hosts keys.
            # For network subnets, pyrad does a basic lookup. To support subnets easily, we can add
            # individual hosts or handle IP network matching.
            # Pyrad's standard library expects exact matches or resolving hostname. 
            # In GNS3, usually devices have specific IPs, but if user enters a range or subnet,
            # we can register the exact string they typed, or expand it.
            # Let's register it directly. We can write a custom IP matcher if needed, but 
            # standard registration is fine for GNS3 nodes.
            self.hosts[ip_network] = server.RemoteHost(ip_network, secret.encode('utf-8'), ip_network)

    def HandleAuthPacket(self, pkt):
        # Extract user details
        username = pkt.get("User-Name", [""])[0]
        if isinstance(username, bytes):
            username = username.decode('utf-8', errors='ignore')
            
        client_ip = pkt.source[0]
        print(f"RADIUS auth request for '{username}' from {client_ip}")
        
        # Decrypt password
        clear_password = ""
        try:
            if "User-Password" in pkt:
                raw_pwd = pkt["User-Password"][0]
                clear_password = pkt.PwDecrypt(raw_pwd)
                if isinstance(clear_password, bytes):
                    clear_password = clear_password.decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"RADIUS password decryption failed: {e}")

        # Check in DB
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM radius_users WHERE username=?", (username,))
        row = cursor.fetchone()
        
        reply = self.CreateReplyPacket(pkt)
        status = "Rejected"
        msg = "Invalid credentials"
        
        if row and row[0] == clear_password:
            reply.code = packet.AccessAccept
            status = "Accepted"
            msg = "Authentication successful"
        else:
            reply.code = packet.AccessReject
            
        # Log to DB
        cursor.execute(
            "INSERT INTO auth_logs (timestamp, service, username, client_ip, status, message) VALUES (DATETIME('now'), 'RADIUS', ?, ?, ?, ?)",
            (username, client_ip, status, msg)
        )
        conn.commit()
        conn.close()
        
        self.SendReplyPacket(pkt.fd, reply)

    def HandleAcctPacket(self, pkt):
        # Just accept accounting packets
        reply = self.CreateReplyPacket(pkt)
        reply.code = packet.AccountingResponse
        self.SendReplyPacket(pkt.fd, reply)

class RadiusServerManager:
    def __init__(self, db_path, dict_path, host="0.0.0.0", port=1812):
        self.db_path = db_path
        self.dict_path = dict_path
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self.running = False

    def start(self):
        if self.running:
            return True
        try:
            self.server = LabRadiusServer(self.db_path, self.dict_path, self.host, self.port)
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            print(f"RADIUS server manager started on {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"RADIUS Server failed to start: {e}")
            self.running = False
            self.server = None
            return False

    def _run(self):
        while self.running:
            try:
                # pyrad Server.Run is blocking, it handles selects inside.
                # To break out, we might close sockets or check running state.
                self.server.Run()
            except Exception as e:
                if self.running:
                    print(f"RADIUS Server Run error: {e}")
                    break

    def stop(self):
        if not self.running:
            return
        self.running = False
        # We need to close pyrad server sockets to unblock the Run select loop
        if self.server:
            # Pyrad opens sockets in self.server.fd. We can close them.
            try:
                for fd in getattr(self.server, "fd", []):
                    fd.close()
            except Exception:
                pass
            self.server = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def refresh(self):
        if self.server:
            self.server.refresh_clients()

import socket
import struct
import hashlib
import time

def send_radius_coa(nas_ip, coa_port=3799, secret="radsecret", packet_type="Disconnect-Request", user_name="", calling_station_id="", vlan_id=None, filter_id=""):
    """
    Sends RFC 3576 RADIUS CoA (Code 43) or Disconnect-Request (Code 40) packet to NAS IP.
    """
    code_map = {
        "Disconnect-Request": 40,
        "CoA-Request": 43
    }
    code = code_map.get(packet_type, 40)
    identifier = int(time.time() * 1000) % 256

    # Build TLV Attributes
    attrs = bytearray()
    
    if user_name:
        b = user_name.encode('utf-8')
        attrs += struct.pack("BB", 1, 2 + len(b)) + b # User-Name (Attr 1)
        
    if calling_station_id:
        b = calling_station_id.encode('utf-8')
        attrs += struct.pack("BB", 31, 2 + len(b)) + b # Calling-Station-Id (Attr 31)

    if filter_id:
        b = filter_id.encode('utf-8')
        attrs += struct.pack("BB", 11, 2 + len(b)) + b # Filter-Id (Attr 11)

    if vlan_id is not None and str(vlan_id).strip():
        try:
            vid = int(vlan_id)
            # Tunnel-Type (Attr 64) = 13 (VLAN)
            attrs += struct.pack("BB", 64, 6) + struct.pack("!I", 13)
            # Tunnel-Medium-Type (Attr 65) = 6 (802)
            attrs += struct.pack("BB", 65, 6) + struct.pack("!I", 6)
            # Tunnel-Private-Group-Id (Attr 81) = vlan_id string
            vb = str(vid).encode('utf-8')
            attrs += struct.pack("BB", 81, 2 + len(vb)) + vb
        except Exception:
            pass

    # Calculate packet length: 20 bytes header + len(attrs)
    pkt_len = 20 + len(attrs)

    # 16-byte zeroes for Authenticator calculation
    dummy_auth = b"\x00" * 16
    header_raw = struct.pack("!BBH", code, identifier, pkt_len) + dummy_auth + attrs

    # MD5 Request Authenticator = MD5(Code + ID + Length + 16 zero bytes + Attributes + Secret)
    authenticator = hashlib.md5(header_raw + secret.encode('utf-8')).digest()

    full_pkt = struct.pack("!BBH", code, identifier, pkt_len) + authenticator + attrs

    # Send via UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)

    try:
        start_time = time.time()
        sock.sendto(full_pkt, (nas_ip, coa_port))
        data, addr = sock.recvfrom(2048)
        rtt_ms = round((time.time() - start_time) * 1000, 1)

        if len(data) >= 20:
            res_code, res_id, res_len = struct.unpack("!BBH", data[:4])
            res_type_map = {
                41: "Disconnect-ACK",
                42: "Disconnect-NAK",
                44: "CoA-ACK",
                45: "CoA-NAK"
            }
            res_name = res_type_map.get(res_code, f"Unknown Response Code ({res_code})")
            is_ack = res_code in [41, 44]

            return {
                "status": "SUCCESS" if is_ack else "REJECTED",
                "response_type": res_name,
                "response_code": res_code,
                "nas_ip": nas_ip,
                "port": coa_port,
                "rtt_ms": rtt_ms,
                "message": f"Received {res_name} from {nas_ip}:{coa_port} in {rtt_ms}ms."
            }
        else:
            return {
                "status": "ERROR",
                "response_type": "Invalid Response",
                "nas_ip": nas_ip,
                "port": coa_port,
                "rtt_ms": rtt_ms,
                "message": "Malformed RADIUS response packet received."
            }
    except socket.timeout:
        return {
            "status": "TIMEOUT",
            "response_type": "No Response",
            "nas_ip": nas_ip,
            "port": coa_port,
            "rtt_ms": 3000,
            "message": f"Timeout waiting for CoA response from {nas_ip}:{coa_port}. Ensure NAS is configured for RADIUS Dynamic Authorization (port {coa_port})."
        }
    except Exception as err:
        return {
            "status": "ERROR",
            "response_type": "Socket Error",
            "nas_ip": nas_ip,
            "port": coa_port,
            "rtt_ms": 0,
            "message": str(err)
        }
    finally:
        sock.close()

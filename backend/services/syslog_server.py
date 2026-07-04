import socket
import threading
import re
import sqlite3
import os
from datetime import datetime

class SyslogServer:
    def __init__(self, db_path, host="0.0.0.0", port=514):
        self.db_path = db_path
        self.host = host
        self.port = port
        self.socket = None
        self.thread = None
        self.running = False

    def start(self):
        if self.running:
            return
        
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind((self.host, self.port))
            print(f"Syslog server listening on {self.host}:{self.port}")
        except Exception as e:
            print(f"Syslog Server failed to bind to {self.host}:{self.port}: {e}")
            self.running = False
            return False

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.socket:
            # Send a dummy packet to unblock recvfrom
            try:
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                temp_sock.sendto(b"<0>shutdown", ("127.0.0.1", self.port))
                temp_sock.close()
            except Exception:
                pass
            self.socket.close()
            self.socket = None
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def _run(self):
        while self.running:
            try:
                data, addr = self.socket.recvfrom(2048)
                if not self.running:
                    break
                self._process_message(data, addr[0])
            except Exception as e:
                if self.running:
                    print(f"Syslog Server receive error: {e}")

    def _process_message(self, data, client_ip):
        try:
            msg = data.decode("utf-8", errors="ignore").strip()
        except Exception:
            msg = str(data)

        # Ignore empty or shutdown messages
        if not msg or msg == "shutdown":
            return

        pri = 13  # Default: user.notice (Facility 1, Severity 5) -> PRI = 1*8 + 5 = 13
        facility = 1
        severity = 5
        hostname = client_ip
        body = msg

        # Try parsing PRI (e.g. <30> or <189>)
        match = re.match(r"^<(\d+)>(.*)", msg)
        if match:
            pri = int(match.group(1))
            facility = pri // 8
            severity = pri % 8
            body = match.group(2).strip()

        # Try parsing syslog timestamp and hostname
        # Standard BSD format: Mmm dd hh:mm:ss hostname message
        bsd_match = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+([^\s]+)\s+(.*)", body)
        if bsd_match:
            hostname = bsd_match.group(2)
            body = bsd_match.group(3)
        else:
            # RFC 5424 format (starts with version number e.g., 1)
            # 1 2003-10-11T22:14:15.003Z mymachine.example.com ...
            rfc_match = re.match(r"^\d+\s+[^\s]+\s+([^\s]+)\s+(.*)", body)
            if rfc_match:
                hostname = rfc_match.group(1)
                body = rfc_match.group(2)

        # Store in DB
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO syslog_messages (timestamp, severity, facility, hostname, message) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), severity, facility, hostname, body)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to write syslog to DB: {e}")

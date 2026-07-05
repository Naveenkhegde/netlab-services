import os
import threading
from tftpy import TftpServer
from database import get_setting

class TftpManager:
    def __init__(self, db_path, root_dir="/var/lib/netlab/files"):
        self.db_path = db_path
        self.root_dir = root_dir
        self.server = None
        self.thread = None
        self.running = False

    def is_running(self):
        return self.running

    def _run_server(self):
        try:
            self.server = TftpServer(self.root_dir)
            # Standard TFTP port is 69
            self.server.listen('0.0.0.0', 69)
        except Exception as e:
            print(f"[TFTP] Server error: {e}")
        finally:
            self.running = False

    def start(self):
        if self.running:
            return True
            
        os.makedirs(self.root_dir, exist_ok=True)
        self.running = True
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        if not self.running:
            return True
            
        self.running = False
        try:
            if self.server:
                # Force shut down tftpy server
                self.server.stop(now=True)
        except Exception:
            pass
        return True

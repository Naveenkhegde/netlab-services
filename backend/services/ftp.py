import os
import threading
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from database import get_setting

class FtpManager:
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
            authorizer = DummyAuthorizer()
            # Add anonymous write/read access
            authorizer.add_anonymous(self.root_dir, perm='elradfmwMT')
            # Add root user matching local credentials
            authorizer.add_user('root', 'netlab', self.root_dir, perm='elradfmwMT')
            authorizer.add_user('admin', 'netlab', self.root_dir, perm='elradfmwMT')

            handler = FTPHandler
            handler.authorizer = authorizer
            handler.banner = "NetLab Services FTP Server ready."

            # Standard FTP port is 21
            self.server = FTPServer(('0.0.0.0', 21), handler)
            self.server.serve_forever()
        except Exception as e:
            print(f"[FTP] Server error: {e}")
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
                self.server.close_all()
        except Exception:
            pass
        return True

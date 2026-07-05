import os
import subprocess
import shutil
from database import get_setting, set_setting

class NtpManager:
    def __init__(self, db_path, config_path="/etc/chrony/chrony.conf"):
        self.db_path = db_path
        self.config_path = config_path

    def is_running(self):
        try:
            # Check if chronyd process is active
            result = subprocess.run(["pgrep", "chronyd"], capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False

    def get_stats(self):
        stats = {
            "synchronized": False,
            "stratum": 0,
            "reference_id": "None",
            "system_time": "Unknown",
            "sources": []
        }
        
        if not self.is_running():
            return stats
            
        try:
            # Parse chronyc tracking info
            track_res = subprocess.run(["chronyc", "tracking"], capture_output=True, text=True)
            if track_res.returncode == 0:
                for line in track_res.stdout.splitlines():
                    if "Leap status" in line and "Normal" in line:
                        stats["synchronized"] = True
                    elif "Stratum" in line:
                        stats["stratum"] = int(line.split()[-1])
                    elif "Reference ID" in line:
                        ref_parts = line.split()
                        if len(ref_parts) >= 3:
                            stats["reference_id"] = " ".join(ref_parts[2:])
                            
            # Parse chronyc sources info
            src_res = subprocess.run(["chronyc", "sources"], capture_output=True, text=True)
            if src_res.returncode == 0:
                for line in src_res.stdout.splitlines():
                    if line.startswith("^") or line.startswith("?"):
                        parts = line.split()
                        if len(parts) >= 6:
                            stats["sources"].append({
                                "state": parts[0][1], # '*' is current best, '+' is candidate, etc.
                                "name": parts[1],
                                "stratum": parts[2],
                                "last_rx": parts[4]
                            })
        except Exception:
            pass
            
        return stats

    def write_config(self):
        pools_str = get_setting("ntp_pools", "pool.ntp.org iburst")
        pools = [p.strip() for p in pools_str.split(",") if p.strip()]
        
        config_lines = []
        for pool in pools:
            config_lines.append(f"pool {pool}")
            
        config_lines.extend([
            "driftfile /var/lib/chrony/chrony.drift",
            "makestep 1.0 3",
            "rtcsync",
            "allow 0.0.0.0/0",
            "local stratum 10"  # Allows acting as server offline
        ])
        
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            f.write("\n".join(config_lines) + "\n")

    def start(self):
        self.write_config()
        try:
            # Alpine uses OpenRC chronyd service
            if shutil.which("rc-service"):
                subprocess.run(["rc-service", "chronyd", "restart"], check=True)
            else:
                # Fallback for standard systemctl or direct invocation
                subprocess.run(["chronyd", "-f", self.config_path], check=True)
            return True
        except Exception:
            return False

    def stop(self):
        try:
            if shutil.which("rc-service"):
                subprocess.run(["rc-service", "chronyd", "stop"], check=True)
            else:
                subprocess.run(["pkill", "chronyd"])
            return True
        except Exception:
            return False

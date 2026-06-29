from datetime import datetime, timezone
from sentinel import api

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("capacity.log") or not lines: 
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)

        for line in lines:
            line = line.strip()
            if not line or line.startswith("df:"): 
                continue

            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                continue
                
            # Ignorovani formatovacich oddelovacu z noveho orchestratoru
            if line.startswith("Checking node:") or line.startswith("---"): 
                continue

            if not active_server: 
                continue

            try:
                parts = line.split()
                # Ocekavany format z df -hl: Filesystem Size Used Avail Use% Mounted on
                mount_point = parts[-1]
                usage_pct = parts[-2]
                
                key = f"DISK_FULL|{active_server}|{mount_point}"
                
                # Vzdy reportovat, jadro updatuje cas a deduplikuje
                api.report_problem(key, {
                    "status": "active",
                    "last_line": f"Local disk capacity warning on {mount_point}: {usage_pct} used.",
                    "channel_type": "infra",
                    "host": active_server,
                    "cluster": infra_label,
                    "log_file": file_path,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0
                })
            except (IndexError, ValueError):
                continue

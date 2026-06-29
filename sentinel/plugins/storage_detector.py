from datetime import datetime, timezone
from sentinel import api

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("storage.log") or not lines: 
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)
        
        # Agregator pro multiline vystupy ze zpool status -x
        zfs_reports = {}

        for line in lines:
            line = line.strip()
            if not line: 
                continue

            # Context switch (rozpozna hlavicku "SERVER: <hostname>")
            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                if active_server not in zfs_reports:
                    zfs_reports[active_server] = []
                continue

            # Ochrana proti pripadnym formatovacim oddelovacum z jine verze
            if line.startswith("Checking node:") or line.startswith("---"): 
                continue

            if not active_server: 
                continue

            # Ukladame radky (bud "STATUS: HEALTHY" nebo "pool: tank state: DEGRADED...")
            zfs_reports[active_server].append(line)

        # Hromadne vyhodnoceni pro kazdy server
        for server, data_lines in zfs_reports.items():
            key = f"ZFS_ISSUE|{server}"
            
            # Pokud orchestrator zapsal STATUS: HEALTHY, okamzite zavirame incident
            if any("STATUS: HEALTHY" in l for l in data_lines):
                api.resolve_problem(key)
            
            # Pokud status neni zdravy a existuji data, mame degradovane pole
            elif data_lines:
                # Spojime vsechny radky chyby do jednoho prehledneho stringu
                error_msg = " | ".join(data_lines)
                
                # Zastropujeme delku, aby to nerozhodilo frontend (UI)
                if len(error_msg) > 300:
                    error_msg = error_msg[:297] + "..."
                    
                # Hlasime problem (API si samo poradi s rotaci casu diky missing_count: 0)
                api.report_problem(key, {
                    "status": "active",
                    "last_line": f"ZFS Critical: {error_msg}",
                    "channel_type": "infra",
                    "severity": "CRITICAL",
                    "host": server,
                    "cluster": infra_label,
                    "log_file": file_path,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0
                })

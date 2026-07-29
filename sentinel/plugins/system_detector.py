from datetime import datetime, timezone
from sentinel import api

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("system.log") or not lines: 
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)
        
        # Agregator pro dany beh detektoru
        incidents = {}

        for line in lines:
            line = line.strip()
            if not line or line.startswith("--"): 
                continue

            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                continue
                
            if line.startswith("Checking node:") or line.startswith("---"): 
                continue

            if not active_server: 
                continue

            line_lower = line.lower()

            # 1. Whitelist
            if "nas326" in line_lower or "kauditd_printk_skb" in line_lower:
                continue

            # Rozrazeni typu problemu
            issue_type = None
            severity_prefix = ""
            channel = "infra"

            if "out of memory" in line_lower or "killed process" in line_lower:
                issue_type = "OOM_KILL"
                severity_prefix = "CRITICAL: OOM Killer invoked:"
                channel = "clusters"
            elif "kernel panic" in line_lower or "softlockup" in line_lower or "hard lockup" in line_lower:
                issue_type = "KERNEL_PANIC"
                severity_prefix = "CRITICAL: Kernel event:"
                channel = "root"
            elif any(err in line_lower for err in ["crit", "alert", "emerg", "error", "fail", "timeout", "denied", "not permitted"]):
                issue_type = "SYS_ERR"
                severity_prefix = "System anomaly detected:"
                channel = "infra"

            # Agregace
            if issue_type:
                key = f"{issue_type}|{active_server}"
                if key not in incidents:
                    incidents[key] = {
                        "count": 1,
                        "line": line,
                        "prefix": severity_prefix,
                        "channel": channel,
                        "host": active_server
                    }
                else:
                    incidents[key]["count"] += 1
                    incidents[key]["line"] = line # Udrzujeme posledni zaznamenanou chybu na serveru

        # 2. Hromadne odeslani az na konci (1 event = 1 server = 1 API call)
        for key, data in incidents.items():
            count = data["count"]
            raw_msg = data["line"]
            
            if count > 1:
                final_msg = f"{data['prefix']} ({count}x událostí) Poslední: {raw_msg}"
            else:
                final_msg = f"{data['prefix']} {raw_msg}"

            api.report_problem(key, {
                "status": "active",
                "last_value": count,
                "last_line": final_msg,
                "channel_type": data["channel"],
                "host": data["host"],
                "cluster": infra_label,
                "log_file": file_path,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "missing_count": 0
            })

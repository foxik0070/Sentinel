import re
import os
import json
from datetime import datetime, timezone
from sentinel import api
from sentinel import config

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)
        self.baseline_file = os.path.join(getattr(config, 'LOG_DIR', '/var/log/sentinel/logs'), "ports_baseline.json")
        self.baselines = self._load_baselines()

    def _load_baselines(self):
        if os.path.exists(self.baseline_file):
            try:
                with open(self.baseline_file, 'r') as f:
                    return json.load(f)
            except: pass
        return {}

    def _save_baselines(self):
        try:
            with open(self.baseline_file, 'w') as f:
                json.dump(self.baselines, f)
        except: pass

    def process(self, lines, file_path):
        if not file_path.endswith("ports.log") or not lines: 
            return

        active_server = None
        server_lines = []
        infra_label = api.get_infrastructure_label(file_path)
        changed = False

        def evaluate_server_ports(server, log_lines):
            nonlocal changed
            if not server or not log_lines: return
                
            ports_found = re.findall(r"(?::|\]:)(\d+)\s+", " ".join(log_lines))
            current_ports = ",".join(sorted(list(set(ports_found))))
            
            if not current_ports: return

            key = f"PORTS|{server}"

            if server in self.baselines:
                old_ports = self.baselines[server]
                
                if old_ports != current_ports:
                    # Vypocet rozdilu (Diference)
                    old_set = set(old_ports.split(",")) if old_ports else set()
                    new_set = set(current_ports.split(",")) if current_ports else set()
                    
                    added = new_set - old_set
                    removed = old_set - new_set
                    
                    changes_msg = []
                    if added:
                        changes_msg.append(f"Added: {','.join(sorted(added))}")
                    if removed:
                        changes_msg.append(f"Removed: {','.join(sorted(removed))}")
                        
                    diff_str = " | ".join(changes_msg)
                    
                    # POPLACH - Porty se zmenily
                    msg = f"Security: Port list changed on {server}. {diff_str}"
                    
                    api.report_problem(key, {
                        "status": "active",
                        "last_line": msg,
                        "channel_type": "security",
                        "severity": "WARNING",
                        "host": server,
                        "cluster": infra_label,
                        "log_file": file_path,
                        "known_ports": current_ports,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                    
                    self.baselines[server] = current_ports
                    changed = True
                else:
                    # Port list is stable — resolve any stale change alert
                    prev = api.get_problem(key)
                    if prev and prev.get("status") == "active":
                        api.resolve_problem(key)
            else:
                self.baselines[server] = current_ports
                changed = True

        for line in lines:
            line = line.strip()
            if not line: continue

            if line.startswith("SERVER:"):
                evaluate_server_ports(active_server, server_lines)
                active_server = line.split("SERVER:")[1].strip()
                server_lines = []
                continue

            if line.startswith("Checking node:") or line.startswith("---"): 
                continue

            if active_server:
                server_lines.append(line)

        evaluate_server_ports(active_server, server_lines)
        
        if changed:
            self._save_baselines()

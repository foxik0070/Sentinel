from datetime import datetime, timezone
from sentinel import api

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("audit.log") or not lines: 
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)

        for line in lines:
            line = line.strip()
            if not line: 
                continue

            # Context switch
            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                continue

            if not active_server: 
                continue

            # Process pending apt updates
            if line.startswith("UPDATES:"):
                try:
                    update_count = int(line.split(":", 1)[1].strip())
                    key = f"SEC_UPDATE|{active_server}"
                    if update_count > 0:
                        api.report_problem(key, {
                            "status": "active",
                            "last_value": update_count,
                            "last_line": f"Pending security updates: {update_count} packages available.",
                            "channel_type": "security",
                            "host": active_server,
                            "cluster": infra_label,
                            "log_file": file_path,
                            "last_seen": datetime.now(timezone.utc).isoformat(),
                            "missing_count": 0
                        })
                    else:
                        api.mark_resolved(key)
                except ValueError:
                    pass

            # Process debsecan high vulnerabilities
            elif line.startswith("VULN:"):
                try:
                    vuln_count = int(line.split(":", 1)[1].strip())
                    key = f"CVE_HIGH|{active_server}"
                    if vuln_count > 0:
                        api.report_problem(key, {
                            "status": "active",
                            "last_value": vuln_count,
                            "last_line": f"High risk vulnerabilities detected: {vuln_count} items.",
                            "channel_type": "security",
                            "host": active_server,
                            "cluster": infra_label,
                            "log_file": file_path,
                            "last_seen": datetime.now(timezone.utc).isoformat(),
                            "missing_count": 0
                        })
                    else:
                        api.mark_resolved(key)
                except ValueError:
                    pass

            # Process reboot required flag
            elif line.upper().startswith("REBOOT:"):
                key = f"REBOOT_REQ|{active_server}"
                if "REQUIRED" in line.upper() and "NOT" not in line.upper():
                    api.report_problem(key, {
                        "status": "active",
                        "last_value": 1,
                        "last_line": "System reboot required.",
                        "channel_type": "infra",
                        "host": active_server,
                        "cluster": infra_label,
                        "log_file": file_path,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                else:
                    api.mark_resolved(key)

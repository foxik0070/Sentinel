from datetime import datetime, timezone
from sentinel import api

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        infra_label = api.get_infrastructure_label(file_path)
        
        for line in lines:
            l = line.strip()
            if not l: continue
            
            problem_found = False
            severity = "WARNING"
            event_type = "Security Alert"
            
            # --- DETEKCE ÚTOKŮ A SELHÁNÍ ---
            if "Failed password" in l or "Invalid user" in l or "authentication failure" in l.lower():
                problem_found = True
                event_type = "Auth Failure / Brute-force"
            
            elif "sudo" in l and "COMMAND=" in l and "incorrect password" in l:
                problem_found = True
                severity = "CRITICAL"
                event_type = "Sudo Abuse (Wrong Password)"

            # --- NOVÉ: DETEKCE SYSTÉMOVÝCH ZMĚN (INSTALLS) ---
            # Zachytí: apt-get install, dnf install, yum install, atd.
            elif "COMMAND=" in l and ("install" in l or "remove" in l or "purge" in l) and "root" in l:
                problem_found = True
                severity = "INFO" # Nebo WARNING, pokud je to v prostředí zakázáno
                event_type = "System Software Modification"
                
            elif "POSSIBLE BREAK-IN ATTEMPT" in l:
                problem_found = True
                severity = "CRITICAL"
                event_type = "Network Break-in Attempt"
                
            if problem_found:
                key = f"SEC|{infra_label}|{hash(l)}"
                
                api.report_problem(key, {
                    "status": "active",
                    "last_line": l,
                    "channel_type": "security",
                    "severity": severity,
                    "host": infra_label,
                    "cluster": infra_label,
                    "log_file": file_path,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0
                })
                
                # Odeslání k AI pro analýzu, co se vlastně instalovalo
                api.enqueue_ai_task(f"Prověř tento příkaz: {l}", channel="security")
                
                # Teams notifikace s barvou podle priority
                color = "#dc3545" if severity == "CRITICAL" else "#17a2b8"
                teams_msg = f"<h3 style='color:{color}'>🛡️ {event_type}</h3><b>Host:</b> {infra_label}<br><b>Log:</b> <code>{l}</code>"
                api.notify_teams(teams_msg, "security")
                
                api.log(f"Security event [{event_type}] on {infra_label}")

from datetime import datetime, timezone
from sentinel import api, config

# Seznam serveru, u kterych je normalni stav "vypnuto".
# Prepsatelny pres config.yaml (lifecycle.default_down_servers) — bez toho by se
# vyrazeny stroj musel dopisovat do kodu a do te doby by donekonecna alertoval.
DEFAULT_DOWN_SERVERS = {
    "ai", "analyzer", "F2-210", "NAS325", "NAS326",
    "proxmox03", "proxmox04", "proxmox05", "QNAP_TS_410",
    "rpi_wifi", "rpizero",
    # Vyrazene 2026-06 — pres dva mesice neodpovidaji na ICMP a alert jen sumel.
    "rpizero2", "jellyfin-zatisi", "navidrome-zatisi", "server-zatisi",
}


def _down_servers() -> set:
    extra = getattr(config, 'DEFAULT_DOWN_SERVERS', None)
    if extra:
        return DEFAULT_DOWN_SERVERS | {str(s).strip() for s in extra if str(s).strip()}
    return DEFAULT_DOWN_SERVERS

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("availability.log") or not lines: 
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)

        for line in lines:
            line = line.strip()
            if not line: 
                continue

            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                continue

            if not active_server: 
                continue
                
            # Ignorovani formatovacich oddelovacu
            if line.startswith("Checking node:") or line.startswith("---"): 
                continue

            # --- OBRACENA LOGIKA PRO DEFAULT-OFFLINE SERVERY ---
            if active_server in _down_servers():
                key = f"UNEXPECTED_UP|{active_server}"
                
                if "STATUS: UP" in line:
                    api.report_problem(key, {
                        "status": "active",
                        "last_line": f"Server {active_server} se necekane probudil (je UP).",
                        "channel_type": "info",
                        "severity": "INFO",
                        "host": active_server,
                        "cluster": infra_label,
                        "log_file": file_path,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                elif "HOST_DOWN" in line:
                    # Explicitni resolve je zde v poradku pro rychlejsi vycisteni
                    api.resolve_problem(key)

            # --- NORMALNI LOGIKA PRO VSECHNY OSTATNI SERVERY ---
            else:
                key = f"DOWN|{active_server}"

                if "HOST_DOWN" in line:
                    api.report_problem(key, {
                        "status": "active",
                        "last_line": f"Critical: Node {active_server} is unreachable via ICMP.",
                        "channel_type": "infra",
                        "severity": "CRITICAL",
                        "host": active_server,
                        "cluster": infra_label,
                        "log_file": file_path,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                elif "STATUS: UP" in line:
                    api.resolve_problem(key)

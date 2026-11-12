import fnmatch
from datetime import datetime, timezone
from sentinel import api, config

WARN_LIMIT = 75.0
CRIT_LIMIT = 85.0

def _has_own_sensor(server: str) -> bool:
    """Patří host do `temperature_hosts`? Prázdný seznam = všichni."""
    allowed = getattr(config, 'TEMPERATURE_HOSTS', None) or []
    return not allowed or any(fnmatch.fnmatch(server, p) for p in allowed)


class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("temperature.log") or not lines: 
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)

        for line in lines:
            line = line.strip()
            if not line: 
                continue

            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                if not _has_own_sensor(active_server):
                    # Host čte cizí čidlo (kontejner na hypervizoru) — nesbírat,
                    # a co po něm zbylo z dřívějška, uzavřít, ať to nevisí.
                    for k in (f"TEMP_HIGH|{active_server}",
                              f"TELEMETRY_ANOMALY|Hardware|temp.{active_server}"):
                        if api.get_problem(k):
                            api.resolve_problem(k)
                    active_server = None
                continue

            # Ignorovani balastu z orchestratoru
            if line.startswith("Checking node:") or line.startswith("---"): 
                continue

            if not active_server: 
                continue

            try:
                raw_val = int(line)
                # Prevod tisicin stupnu Celsia (bezny linux sysfs vystup) na normalni stupne
                temp_c = raw_val / 1000.0 if raw_val > 1000 else float(raw_val)
                
                # Zaznam pro grafy a analytiku
                api.save_telemetry_snapshot("Hardware", {f"temp.{active_server}": temp_c})

                key = f"TEMP_HIGH|{active_server}"
                
                if temp_c >= CRIT_LIMIT:
                    api.report_problem(key, {
                        "status": "active",
                        "last_line": f"CRITICAL: Overheating detected: {temp_c:.1f}C",
                        "channel_type": "infra",
                        "severity": "CRITICAL",
                        "host": active_server,
                        "cluster": infra_label,
                        "log_file": file_path,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                
                elif temp_c >= WARN_LIMIT:
                    api.report_problem(key, {
                        "status": "active",
                        "last_line": f"Warning: High temperature: {temp_c:.1f}C",
                        "channel_type": "info",
                        "severity": "WARNING",
                        "host": active_server,
                        "cluster": infra_label,
                        "log_file": file_path,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                else:
                    # Pokud teplota klesla pod limity, pokusime se problem vyresit
                    api.resolve_problem(key)

            except (ValueError, TypeError):
                continue

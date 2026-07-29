import json
from datetime import datetime, timezone
from sentinel import api
from sentinel import config as _cfg_mod

def _t(key, default):
    """Číst threshold z config.yaml ha_thresholds sekce, s fallbackem na default."""
    return _cfg_mod.HA_THRESHOLDS.get(key, default)

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("homeassistant.log") or len(lines) < 2: 
            return
        
        # Flexibilnejsi osetreni pocatku dat
        start_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("SERVER: HomeAssistant"):
                start_idx = i
                break
                
        if start_idx == -1: 
            return

        try:
            raw_json = "".join(lines[start_idx+1:])
            entities = json.loads(raw_json)
        except json.JSONDecodeError:
            return

        telemetry_data = {}
        infra_label = api.get_infrastructure_label(file_path)
        
        for entity in entities:
            entity_id = entity.get("entity_id", "").lower()
            state_val = str(entity.get("state")).lower()
            friendly_name = entity.get("attributes", {}).get("friendly_name", entity_id)
            friendly_name_lower = friendly_name.lower()
            
            # ---------------------------------------------------------
            # 1. IGNOROVANE STAVY A SENZORY
            # ---------------------------------------------------------
            if state_val in ["unknown", "unavailable", "none", "null"]:
                continue
            if "threshold" in entity_id:
                continue
            if "nas326" in entity_id:
                continue
                
            # ---------------------------------------------------------
            # 2. DETEKCE TEXTOVYCH STAVU
            # ---------------------------------------------------------
            if entity_id.startswith("update.") and state_val == "on":
                key = f"HA_UPDATE|{entity_id}"
                api.report_problem(key, {
                    "status": "active",
                    "last_line": f"Dostupna aktualizace: {friendly_name}",
                    "channel_type": "info",
                    "severity": "INFO",
                    "host": "HomeAssistant",
                    "cluster": infra_label,
                    "log_file": file_path,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0
                })
                    
            elif "backup" in entity_id and state_val == "failed":
                key = f"HA_BACKUP_FAIL|{entity_id}"
                api.report_problem(key, {
                    "status": "active",
                    "last_line": f"Selhani zalohovani HA: {friendly_name}",
                    "channel_type": "infra",
                    "severity": "CRITICAL",
                    "host": "HomeAssistant",
                    "cluster": infra_label,
                    "log_file": file_path,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0
                })

            # ---------------------------------------------------------
            # 3. KONTROLA CISELNYCH HODNOT A PRAVIDEL
            # ---------------------------------------------------------
            try:
                numeric_val = float(state_val)
                telemetry_data[entity_id] = numeric_val
                
                is_problem = False
                severity = "WARNING"
                channel = "infra"
                msg = ""
                
                if "_battery_plus_" in entity_id and numeric_val < _t("battery_low_pct", 30.0):
                    is_problem, severity, msg = True, "WARNING", f"Slaba baterie ({numeric_val}%): {friendly_name}"

                elif "temp" in entity_id and any(x in entity_id for x in ["hdd", "ssd", "nvme", "disk"]) and numeric_val > _t("disk_temp_critical_c", 70.0):
                    is_problem, severity, msg = True, "CRITICAL", f"Kriticka teplota disku ({numeric_val}C): {friendly_name}"

                elif "temp" in entity_id and ("proxmox" in entity_id or "nas" in entity_id) and numeric_val > _t("server_temp_critical_c", 60.0):
                    is_problem, severity, msg = True, "CRITICAL", f"Prehrivani serveru ({numeric_val}C): {friendly_name}"

                elif "temp" in entity_id and ("rpi" in entity_id or "octoprint" in entity_id) and numeric_val > _t("rpi_temp_warning_c", 60.0):
                    if "tool" not in entity_id and "bed" not in entity_id:
                        is_problem, severity, msg = True, "WARNING", f"Vysoka teplota RPi desky ({numeric_val}C): {friendly_name}"

                elif ("voltage" in entity_id or "napeti" in entity_id) and not any(x in entity_id or x in friendly_name_lower for x in ["battery", "bater"]):
                    if numeric_val <= 0 or numeric_val < _t("voltage_min_v", 220.0):
                        is_problem, severity, msg = True, "CRITICAL", f"Podpeti nebo vypadek v siti ({numeric_val} V): {friendly_name}"

                elif "current" in entity_id or "proud" in entity_id:
                    if numeric_val > _t("current_max_a", 8.0):
                        is_problem, severity, msg = True, "WARNING", f"Vysoky odber proudu ({numeric_val} A): {friendly_name}"

                elif "obico" in entity_id and "failure" in entity_id and numeric_val > _t("print_failure_pct", 60.0):
                    is_problem, severity, channel, msg = True, "CRITICAL", "3dprint", f"AI zjistila pravdepodobne selhani 3D tisku ({numeric_val} % jistota)!"

                if is_problem:
                    key = f"HA_ALERT|{entity_id}"
                    api.report_problem(key, {
                        "status": "active",
                        "last_line": msg,
                        "channel_type": channel,
                        "severity": severity,
                        "host": "HomeAssistant",
                        "cluster": infra_label,
                        "log_file": file_path,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0
                    })
                        
            except ValueError:
                continue 

        if telemetry_data:
            api.save_telemetry_snapshot("HomeAssistant", telemetry_data)

from datetime import datetime, timezone
from sentinel import api
from sentinel import state
from sentinel import config

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def process(self, lines, file_path):
        if not file_path.endswith("services.log") or not lines:
            return

        active_server = None
        infra_label = api.get_infrastructure_label(file_path)
        reported_keys = set()
        seen_servers = set()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                seen_servers.add(active_server)
                continue

            if line.startswith("Checking node:") or line.startswith("---"):
                continue

            if not active_server:
                continue

            try:
                parts = line.split()
                service_name = parts[0]

                if not service_name.endswith(".service"):
                    continue

                if service_name in getattr(config, 'IGNORED_FAILED_SERVICES', []):
                    continue

                key = f"SERVICE_FAILED|{active_server}|{service_name}"
                reported_keys.add(key)

                api.report_problem(key, {
                    "status": "active",
                    "last_line": f"Systemd service failed: {service_name} on {active_server}",
                    "channel_type": "infra",
                    "severity": "WARNING",
                    "host": active_server,
                    "cluster": infra_label,
                    "log_file": file_path,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0
                })
            except IndexError:
                continue

        # Resolve SERVICE_FAILED issues for servers in this scan that are no longer failing
        for server in seen_servers:
            prefix = f"SERVICE_FAILED|{server}|"
            try:
                conn = state._get_conn()
                rows = conn.execute(
                    "SELECT key FROM problems WHERE key LIKE ? AND status='active'",
                    (prefix + '%',)
                ).fetchall()
                conn.close()
                for (existing_key,) in rows:
                    if existing_key not in reported_keys:
                        api.resolve_problem(existing_key)
            except Exception:
                pass

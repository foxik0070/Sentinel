import os
import re
from datetime import datetime, timezone
from collections import defaultdict
from sentinel import api

class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)

    def _is_private_ip(self, ip):
        """
        Filtruje lokalni a homelab adresy pred false-positives.
        RFC 1918 + loopback.
        """
        if ip.startswith(("127.", "192.168.", "10.")):
            return True
        if ip.startswith("172."):
            try:
                parts = ip.split(".")
                second_octet = int(parts[1])
                return 16 <= second_octet <= 31
            except (IndexError, ValueError):
                pass
        return False

    def process(self, lines, file_path):
        if not lines: 
            return

        filename = os.path.basename(file_path).lower()
        if "secure" not in filename and "security" not in filename: 
            return

        ip_re = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})')
        server_metrics = defaultdict(lambda: defaultdict(int))
        active_server = None
        infra_label = api.get_infrastructure_label(file_path)

        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Context switch z noveho orchestratoru
            if line.startswith("SERVER:"):
                active_server = line.split("SERVER:")[1].strip()
                continue
                
            if line.startswith("Checking node:") or line.startswith("---"): 
                continue
                
            if not active_server: continue

            # Vyhledani IP adresy v radku
            m_ip = ip_re.search(line)
            if m_ip:
                ip = m_ip.group(1)
                # Zapocitame pouze verejne IP adresy utocniku
                if not self._is_private_ip(ip):
                    server_metrics[active_server][ip] += 1

        # Vyhodnoceni nasbiranych metrik
        for server, attackers in server_metrics.items():
            # Zajimaji nas pouze IP, ze kterych bylo minimalne 5 pokusu (prevence nahodneho preklepu hesla)
            significant = {ip: count for ip, count in attackers.items() if count >= 5}
            
            if not significant:
                continue

            total_ips = len(significant)
            sorted_ips = sorted(significant.items(), key=lambda x: x[1], reverse=True)
            
            summary_parts = [f"{ip} ({count}x)" for ip, count in sorted_ips[:3]]
            compiled_last_line = f"{total_ips} unbanned public IPs brute-forcing SSH: " + " | ".join(summary_parts)
            
            if len(sorted_ips) > 3:
                compiled_last_line += f" ... and {len(sorted_ips) - 3} more"

            key = f"SECURE_ATTACK_UNBANNED|{server}"

            # Vzdy reportujeme pro update last_seen a timekeeping
            api.report_problem(key, {
                "status": "active",
                "last_value": total_ips,
                "last_line": compiled_last_line,
                "channel_type": "security",
                "host": server,
                "cluster": infra_label,
                "log_file": file_path,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "missing_count": 0
            })

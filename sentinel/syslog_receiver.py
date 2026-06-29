"""
082: Syslog UDP receiver — přijímá RFC3164/5424 syslog zprávy a ukládá jako Sentinel issues.

Konfigurace v config.yaml:
    syslog_receiver:
      enabled: true
      port: 514          # UDP port (< 1024 vyžaduje root nebo cap_net_bind_service)
      host: "0.0.0.0"
      channel: "infra"   # výchozí kanál pro zprávy
"""
import socket
import threading
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.syslog")

# RFC3164: <PRI>MONTH DAY HH:MM:SS HOSTNAME TAG: MSG
_RFC3164 = re.compile(
    r'^<(\d+)>(\w{3}\s+\d+\s+\d+:\d+:\d+)\s+(\S+)\s+(\S+?):\s*(.*)',
    re.DOTALL
)
# RFC5424: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID [SD] MSG
_RFC5424 = re.compile(
    r'^<(\d+)>(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+\S+\s+\S+\s+(?:\[.*?\]|-)\s*(.*)',
    re.DOTALL
)

_SEVERITY_NAMES = {0:'EMERG',1:'ALERT',2:'CRIT',3:'ERR',4:'WARNING',5:'NOTICE',6:'INFO',7:'DEBUG'}
_FACILITY_NAMES = {0:'kern',1:'user',2:'mail',3:'daemon',4:'auth',5:'syslog',
                   6:'lpr',7:'news',8:'uucp',16:'local0',17:'local1',18:'local2',
                   19:'local3',20:'local4',21:'local5',22:'local6',23:'local7'}


def _parse(raw: bytes) -> dict:
    try:
        msg = raw.decode('utf-8', errors='replace').strip()
    except Exception:
        return {}
    pri = fac = sev = 1
    m = _RFC5424.match(msg)
    if m:
        pri = int(m.group(1))
        fac, sev = pri >> 3, pri & 7
        return {
            'facility': _FACILITY_NAMES.get(fac, str(fac)),
            'severity': sev,
            'sev_name': _SEVERITY_NAMES.get(sev, 'INFO'),
            'timestamp': m.group(3),
            'hostname': m.group(4),
            'app': m.group(5),
            'message': m.group(6).strip(),
            'raw': msg[:500],
        }
    m = _RFC3164.match(msg)
    if m:
        pri = int(m.group(1))
        fac, sev = pri >> 3, pri & 7
        return {
            'facility': _FACILITY_NAMES.get(fac, str(fac)),
            'severity': sev,
            'sev_name': _SEVERITY_NAMES.get(sev, 'INFO'),
            'timestamp': m.group(2),
            'hostname': m.group(3),
            'app': m.group(4).rstrip(':'),
            'message': m.group(5).strip(),
            'raw': msg[:500],
        }
    # Fallback — plain text
    return {'facility': 'user', 'severity': 5, 'sev_name': 'NOTICE',
            'hostname': 'unknown', 'app': 'syslog', 'message': msg[:300], 'raw': msg[:500]}


def start_syslog_receiver():
    """Spustí Syslog UDP receiver pokud je povolen v konfiguraci."""
    from . import config, state
    cfg = getattr(config, 'SYSLOG_RECEIVER', {})
    if not cfg.get('enabled'):
        return None

    port = int(cfg.get('port', 514))
    host = cfg.get('host', '0.0.0.0')
    channel = cfg.get('channel', 'infra')
    # Minimální severity pro uložení (0=EMERG, 5=NOTICE, 6=INFO)
    min_sev = int(cfg.get('min_severity', 4))  # default: WARNING a kritičtější

    def _run():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.settimeout(2.0)
            logger.info(f"Syslog UDP receiver started on {host}:{port} (min_severity={_SEVERITY_NAMES.get(min_sev, min_sev)})")
        except Exception as e:
            logger.error(f"Syslog receiver failed to bind {host}:{port}: {e}")
            return

        from . import state as _state
        while not _state.shutdown_event.is_set():
            try:
                data, addr = sock.recvfrom(4096)
                parsed = _parse(data)
                if not parsed:
                    continue
                sev = parsed.get('severity', 6)
                if sev > min_sev:
                    continue  # Příliš nízká závažnost
                host_src = parsed.get('hostname') or addr[0]
                app = parsed.get('app', 'syslog')
                msg = parsed.get('message', '')[:300]
                sev_name = parsed.get('sev_name', 'INFO')
                key = f"SYSLOG|{host_src}|{app}"
                payload = {
                    'status': 'active',
                    'channel_type': channel,
                    'host': host_src,
                    'plugin_name': f'syslog_{app}',
                    'last_line': f"[{sev_name}] {app}: {msg}",
                    'last_seen': datetime.now(timezone.utc).isoformat(),
                    'source': 'syslog_udp',
                }
                _state.save_problem(key, payload)
            except socket.timeout:
                continue
            except Exception as e:
                if not _state.shutdown_event.is_set():
                    logger.warning(f"Syslog receiver error: {e}")

        sock.close()
        logger.info("Syslog receiver stopped.")

    t = threading.Thread(target=_run, daemon=True, name="SyslogReceiver")
    t.start()
    return t

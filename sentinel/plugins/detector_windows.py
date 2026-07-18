"""
detector_windows_hpc — Windows Event Log + WMI monitoring
Zpracovává JSONL zapsané /api/ingest/windows do windows-{host}.log
"""
import json
import time
from datetime import datetime, timezone
from sentinel import api

# Event ID skupiny
_LOGIN_OK    = {4624, 4648, 4672}
_LOGIN_FAIL  = {4625}
_LOGOUT      = {4634}
_PERF_IDS    = {9001, 9002, 9003}

# Výchozí thresholdy (přepsatelné z config params)
_DEF = {
    'failed_login_warn': 5,
    'failed_login_crit': 20,
    'cpu_warn':  90,
    'ram_warn':  90,
    'disk_warn': 90,
    'disk_crit': 97,
}


class Detector(api.BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)
        p = config_params or {}
        self._t = {k: int(p.get(k, v)) for k, v in _DEF.items()}
        # host → {ip → {count, last}}
        self._fail: dict[str, dict] = {}
        # host → {drive → last_pct}
        self._perf: dict[str, dict] = {}
        # okno pro brute-force (sekund)
        self._window = 600

    def process(self, lines, file_path):
        now = time.time()
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except Exception:
                continue

            host     = ev.get('_host') or ev.get('host', 'unknown')
            event_id = int(ev.get('event_id', 0))
            source   = ev.get('source', '')
            level    = (ev.get('level') or '').lower()
            data     = ev.get('data') or {}
            ts       = ev.get('ts', datetime.now(timezone.utc).isoformat())

            if source == 'Performance' and event_id in _PERF_IDS:
                self._handle_perf(host, event_id, data, ts)

            elif source == 'System' and level in ('critical', 'error'):
                self._handle_system(host, ev, ts)

            elif source == 'Security':
                if event_id in _LOGIN_FAIL:
                    self._handle_fail(host, data, ts, now)
                elif event_id in _LOGIN_OK:
                    self._handle_login(host, data, ts)

    # --- handlers ---

    def _handle_perf(self, host, event_id, data, ts):
        pct   = float(data.get('value', 0))
        t     = self._t
        state = self._perf.setdefault(host, {})

        if event_id == 9001:  # CPU
            key = f"PERF|WIN|{host}|CPU"
            if pct >= t['cpu_warn']:
                sev = 'CRITICAL' if pct >= 97 else 'WARNING'
                api.report_problem(key, {
                    'status': 'active', 'severity': sev,
                    'last_line': f"CPU {pct}%",
                    'channel_type': 'performance', 'host': host, 'cluster': 'WINDOWS',
                    'last_seen': ts,
                })
            else:
                api.report_problem(key, {'status': 'resolved', 'last_seen': ts})

        elif event_id == 9002:  # RAM
            key = f"PERF|WIN|{host}|RAM"
            if pct >= t['ram_warn']:
                sev = 'CRITICAL' if pct >= 97 else 'WARNING'
                api.report_problem(key, {
                    'status': 'active', 'severity': sev,
                    'last_line': f"RAM {pct}% ({data.get('total_mb', '?')} MB celkem)",
                    'channel_type': 'performance', 'host': host, 'cluster': 'WINDOWS',
                    'last_seen': ts,
                })
            else:
                api.report_problem(key, {'status': 'resolved', 'last_seen': ts})

        elif event_id == 9003:  # Disk
            drive = data.get('drive', '?')
            key   = f"PERF|WIN|{host}|DISK|{drive}"
            if pct >= t['disk_crit']:
                sev = 'CRITICAL'
            elif pct >= t['disk_warn']:
                sev = 'WARNING'
            else:
                sev = None
            if sev:
                api.report_problem(key, {
                    'status': 'active', 'severity': sev,
                    'last_line': f"Disk {drive} {pct}% ({data.get('total_gb', '?')} GB)",
                    'channel_type': 'performance', 'host': host, 'cluster': 'WINDOWS',
                    'last_seen': ts,
                })
            else:
                api.report_problem(key, {'status': 'resolved', 'last_seen': ts})

    def _handle_system(self, host, ev, ts):
        msg     = ev.get('message', '')[:200]
        eid     = ev.get('event_id', '?')
        src     = ev.get('source', 'System')
        is_bsod = 'BugCheck' in src or 'LiveKernelEvent' in msg or eid in (1001, 1003, 41)
        prefix  = 'BSOD' if is_bsod else 'SYSERR'
        key     = f"{prefix}|WIN|{host}"
        api.report_problem(key, {
            'status': 'active', 'severity': 'CRITICAL' if is_bsod else 'WARNING',
            'last_line': f"[{src}] EventID={eid}: {msg}",
            'channel_type': 'security', 'host': host, 'cluster': 'WINDOWS',
            'last_seen': ts,
        })
        if is_bsod:
            api.notify_teams(
                f"<b>BSOD / Kernel Crash — {host}</b><br>Source: {src}<br>{msg}",
                "security"
            )

    def _handle_fail(self, host, data, ts, now):
        ip  = data.get('IpAddress') or data.get('WorkstationName') or 'unknown'
        rec = self._fail.setdefault(host, {})
        entry = rec.setdefault(ip, {'count': 0, 'first': now})
        entry['count'] += 1
        entry['last']   = now

        # Pročisti staré záznamy mimo okno
        rec = {k: v for k, v in rec.items() if now - v['first'] < self._window}
        self._fail[host] = rec

        total = sum(v['count'] for v in rec.values())
        t     = self._t
        if total < t['failed_login_warn']:
            return

        sev = 'CRITICAL' if total >= t['failed_login_crit'] else 'WARNING'
        top = sorted(rec.items(), key=lambda kv: kv[1]['count'], reverse=True)[:3]
        top_str = ', '.join(f"{k}({v['count']})" for k, v in top)
        key = f"SECURITY|WIN|{host}|FAILEDLOGIN"
        api.report_problem(key, {
            'status': 'active', 'severity': sev,
            'last_line': f"{total} selhání / 10 min — top: {top_str}",
            'channel_type': 'security', 'host': host, 'cluster': 'WINDOWS',
            'last_seen': ts,
        })

    def _handle_login(self, host, data, ts):
        user = data.get('TargetUserName') or data.get('SubjectUserName') or '?'
        ip   = data.get('IpAddress') or data.get('WorkstationName') or '?'
        # Logon type 10 = RemoteInteractive (RDP) — zajímavé pro audit
        ltype = str(data.get('LogonType', ''))
        if ltype in ('10', '3'):
            api.add_root_audit('WINDOWS', ip)

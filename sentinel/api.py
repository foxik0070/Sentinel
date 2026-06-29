import os
import fnmatch
from . import config, state, utils
from .plugins.base import BaseDetector

"""
Sentinel API v2026.05.002
This module provides a safe, agnostic interface for all plugins.
Optimized to support both legacy and concurrent plugin execution matrix.
"""

def get_infrastructure_label(path: str) -> str:
    """
    Determines the infrastructure label based on the file path
    and the patterns defined in config.yaml.
    """
    fname = os.path.basename(path).upper()
    for mapping in config.INFRASTRUCTURE_MAPPING:
        pattern = mapping.get("pattern", "").upper()
        if fnmatch.fnmatch(fname, pattern):
            return mapping.get("name", "UNKNOWN")
    return "UNKNOWN"

def _is_false_positive(data: dict) -> bool:
    """Returns True if the problem matches a stored false-positive pattern."""
    import fnmatch
    import sqlite3
    from .state_base import DB_FILE as DB_PATH
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        rows = conn.execute(
            "SELECT id, host_pattern, msg_pattern FROM false_positive_patterns WHERE plugin_name=? OR plugin_name='*'",
            (data.get('plugin_name', ''),)
        ).fetchall()
        conn.close()
        host = data.get('host', '')
        msg = data.get('last_line', '')
        for fp_id, host_pat, msg_pat in rows:
            if fnmatch.fnmatch(host, host_pat) and fnmatch.fnmatch(msg, msg_pat):
                # Increment hit counter
                try:
                    c2 = sqlite3.connect(DB_PATH, timeout=5)
                    c2.execute("UPDATE false_positive_patterns SET hit_count=hit_count+1 WHERE id=?", (fp_id,))
                    c2.commit(); c2.close()
                except Exception:
                    pass
                return True
    except Exception:
        pass
    return False

def report_problem(key: str, data: dict):
    """Saves or updates a problem record in the SQLite database."""
    if _is_false_positive(data):
        log(f"Suppressed false positive: {key}")
        return
    is_new = state.save_problem(key, data)
    log(f"Plugin reported {'new ' if is_new else ''}issue: {key}")
    if is_new:
        from . import actions as _actions
        _actions.maybe_suggest_remediation(key, data)
        # 164: Auto-duplicate detection (string similarity against active issues)
        if getattr(config, 'AUTO_DUPLICATE_ENABLED', True):
            _check_duplicate(key, data)
        # 173: Secret scanner
        _check_secrets(key, data)
        # 160: Auto-severity classification via LLM (async, only if no severity set)
        if getattr(config, 'AUTO_SEVERITY_ENABLED', False) and not data.get('severity'):
            _enqueue_severity_classify(key, data)

# 173: Secret scanner patterns
_SECRET_PATTERNS = [
    (r'(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S{8,}', 'password/secret'),
    (r'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}', 'JWT token'),
    (r'(?i)(bearer|authorization)\s+[A-Za-z0-9._~+/-]{20,}', 'bearer token'),
    (r'[A-Za-z0-9]{32,}', None),  # generic long token — lower priority
]

def _check_secrets(key: str, data: dict):
    """173: Scan last_line for credential/secret patterns → auto-tag + bump severity."""
    import re as _re
    msg = (data.get('last_line') or '')
    if not msg:
        return
    for pattern, label in _SECRET_PATTERNS[:-1]:  # skip generic long token
        if _re.search(pattern, msg):
            state.add_issue_tag(key, 'contains-secret', 'system')
            # Ensure severity is at least high
            try:
                conn = state._get_conn()
                sev_order = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
                row = conn.execute("SELECT severity FROM problems WHERE key=?", (key,)).fetchone()
                cur = (row[0] or '').lower() if row else ''
                if sev_order.get(cur, 0) < sev_order['high']:
                    conn.execute("UPDATE problems SET severity='high' WHERE key=?", (key,))
                    conn.commit()
                conn.close()
            except Exception:
                pass
            log(f"Secret pattern detected in issue {key}: {label}")
            break

def _check_duplicate(key: str, data: dict):
    """Flag new issue as possible-duplicate if similar to an existing active issue (difflib)."""
    msg = (data.get('last_line') or '').strip()
    plugin = data.get('plugin_name', '')
    if not msg or len(msg) < 20 or not plugin:
        return
    try:
        from difflib import SequenceMatcher
        conn = state._get_conn()
        rows = conn.execute(
            "SELECT key, last_line FROM problems WHERE plugin_name=? AND status='active' AND key!=? LIMIT 50",
            (plugin, key)
        ).fetchall()
        conn.close()
        for row_key, row_msg in rows:
            if row_msg and SequenceMatcher(None, msg[:200], (row_msg or '')[:200]).ratio() > 0.82:
                state.add_issue_tag(key, 'possible-duplicate', 'system')
                log(f"Auto-tagged {key} as possible-duplicate of {row_key}")
                break
    except Exception as e:
        log(f"_check_duplicate error: {e}")

def _enqueue_severity_classify(key: str, data: dict):
    """Enqueue a short LLM call to auto-classify severity of a new issue."""
    plugin = data.get('plugin_name', '?')
    host = data.get('host', '?')
    msg = (data.get('last_line') or '')[:200]
    prompt = (
        f"Classify the severity of this system alert as exactly one word.\n"
        f"Alert: [{plugin}] {host}: {msg}\n"
        f"Reply with only one word from: critical, high, medium, low"
    )
    state.enqueue_message(
        prompt,
        channel=data.get('channel_type', 'infra'),
        msg_type="problem",
        context={"source": "severity_classify", "problem_key": key}
    )

def mark_resolved(key: str):
    """Marks an active problem as resolved."""
    state.mark_resolved(key)

def resolve_problem(key: str):
    """
    CRITICAL FIX: Explicit alias wrapper for mark_resolved 
    to support modern thread-safe detectors architecture.
    """
    state.mark_resolved(key)

def get_problem(key: str) -> dict:
    """Retrieves an existing problem by its unique key."""
    return state.get_problem(key)

def enqueue_ai_task(text: str, channel: str = "default", msg_type: str = "problem", context: dict = None):
    """Sends log text to the AI queue for asynchronous analysis."""
    state.enqueue_message(text, channel, msg_type, context)

def notify_teams(message: str, channel: str):
    """Sends a formatted message to MS Teams via the configured webhook."""
    utils.send_to_teams(message, channel)

def notify_webhook(event: str, data: dict):
    """Sends a structured event to the generic webhook if configured."""
    utils.send_webhook({"event": event, "instance": getattr(__import__('sentinel.config', fromlist=['config']), 'INSTANCE_NAME', ''), **data})

def log(msg: str):
    """Writes a message to the internal Sentinel log."""
    utils.log_message(msg)

def _reverse_dns(ip: str, timeout: float = 2.0) -> str:
    """Best-effort reverse DNS, bounded so a slow resolver can't block the caller beyond `timeout`."""
    import socket
    import threading
    result = {}
    def _lookup():
        try:
            result['host'] = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass
    th = threading.Thread(target=_lookup, daemon=True)
    th.start()
    th.join(timeout)
    return result.get('host', '')

def add_root_audit(server: str, ip: str):
    """Records an active root session into root_audit.
    Idempotent: keeps ONE active record per server+ip session (no duplicate every poll cycle).
    Resolves IP via reverse DNS so the audit shows who/where, not just the bare IP."""
    from .state_base import DB_FILE as DB_PATH
    import sqlite3
    from datetime import datetime, timezone
    try:
        display = ip
        if ip and ip != "unknown":
            host = _reverse_dns(ip)
            if host and host != ip:
                display = f"{ip} ({host})"
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(DB_PATH, timeout=5)
        # Dedup: only insert if no active record already exists for this server+ip
        existing = conn.execute(
            "SELECT 1 FROM root_audit WHERE server=? AND (ip=? OR ip LIKE ?) AND is_active=1 LIMIT 1",
            (server, ip, ip + ' (%')
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO root_audit (server, ip, connected_at, is_active) VALUES (?, ?, ?, 1)",
                (server, display, now)
            )
            conn.commit()
        conn.close()
    except Exception as e:
        log(f"add_root_audit error: {e}")

def save_telemetry(metric: str, value: float, category: str = "general"):
    """Adds a telemetry point to the async buffer (non-blocking). Preferred over save_telemetry_snapshot."""
    from . import state
    try:
        state.save_telemetry(metric, value, category)
    except Exception as e:
        log(f"API Error saving telemetry: {e}")

def save_telemetry_snapshot(metric_or_category, value_or_dict, category="general"):
    """Saves telemetry data to DB for graphs and predictions. Supports both calling syntaxes."""
    from . import state
    try:
        if isinstance(value_or_dict, dict):
            state.save_telemetry_snapshot(metric_or_category, value_or_dict)
        else:
            state.save_telemetry_snapshot(category, {str(metric_or_category): float(value_or_dict)})
    except Exception as e:
        log(f"API Error saving telemetry: {e}")

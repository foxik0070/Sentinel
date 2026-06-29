import threading
import logging
import sqlite3
import json
import os
import time
import secrets
from queue import Queue
from datetime import datetime, timezone, timedelta
from . import config
from . import utils
from .state_base import logger, db_lock, _get_conn, DB_FILE, shutdown_event

# ── Telemetry batch buffer (127) ────────────────────────────────────────────
_telemetry_buffer: list = []          # [(ts, category, metric, value), ...]
_telemetry_buffer_lock = threading.Lock()
_TELEMETRY_FLUSH_INTERVAL = 5         # seconds


def _telemetry_flush_loop():
    """Background thread: flush buffered telemetry to DB every N seconds."""
    import time as _t
    while not shutdown_event.is_set():
        _t.sleep(_TELEMETRY_FLUSH_INTERVAL)
        _flush_telemetry_buffer()


def _flush_telemetry_buffer():
    with _telemetry_buffer_lock:
        if not _telemetry_buffer:
            return
        rows = _telemetry_buffer[:]
        _telemetry_buffer.clear()
    with db_lock:
        try:
            conn = _get_conn()
            conn.executemany(
                "INSERT INTO telemetry (timestamp, category, metric, value) VALUES (?,?,?,?)", rows
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"_flush_telemetry_buffer: {e}")
            # Put rows back on failure
            with _telemetry_buffer_lock:
                _telemetry_buffer[:0] = rows


_ANOMALY_MIN_SAMPLES = 30   # potřebujeme aspoň 30 vzorků pro spolehlivé σ
_ANOMALY_SIGMA = 3.0        # práh: >3σ od průměru = anomálie
_anomaly_cooldown: dict = {}  # key → timestamp posledního alertu (throttle 1h)

def save_telemetry_snapshot(category, data_dict):
    # 371: save_telemetry() (single-metric) uses _telemetry_buffer for batching.
    # save_telemetry_snapshot() writes directly for anomaly detection compatibility.
    anomalies = []
    with db_lock:
        try:
            conn = _get_conn()
            ts = datetime.now(timezone.utc).isoformat()
            data_to_insert = []

            for key, value in data_dict.items():
                try:
                    val_float = float(value)
                    data_to_insert.append((ts, category, key, val_float))
                except (ValueError, TypeError):
                    continue

            if data_to_insert:
                conn.executemany(
                    "INSERT INTO telemetry (timestamp, category, metric, value) VALUES (?,?,?,?)",
                    data_to_insert
                )
                conn.commit()

                # Anomaly detection — check each new value against last 24h history
                import time as _time
                now_ts = _time.time()
                for (_, cat, metric, val) in data_to_insert:
                    cooldown_key = f"{cat}|{metric}"
                    if now_ts - _anomaly_cooldown.get(cooldown_key, 0) < 3600:
                        continue
                    rows = conn.execute(
                        "SELECT value FROM telemetry WHERE category=? AND metric=? "
                        "AND timestamp > datetime('now','-24 hours') ORDER BY timestamp DESC LIMIT 288",
                        (cat, metric)
                    ).fetchall()
                    if len(rows) < _ANOMALY_MIN_SAMPLES:
                        continue
                    vals = [r[0] for r in rows]
                    mean = sum(vals) / len(vals)
                    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
                    sigma = variance ** 0.5
                    if sigma < 1e-6:
                        continue
                    if abs(val - mean) > _ANOMALY_SIGMA * sigma:
                        direction = "↑" if val > mean else "↓"
                        anomalies.append((cat, metric, val, mean, sigma, direction))
                        _anomaly_cooldown[cooldown_key] = now_ts

            conn.close()
        except Exception as e:
            logger.error(f"Failed to save telemetry: {e}")

    # Report anomalies outside db_lock to avoid deadlock
    for (cat, metric, val, mean, sigma, direction) in anomalies:
        try:
            short = metric.split('.')[-1][:40]
            msg = f"Telemetry anomálie {direction}: {short} = {val:.2f} (průměr {mean:.2f}, σ={sigma:.2f})"
            anom_key = f"TELEMETRY_ANOMALY|{cat}|{metric}"
            save_problem(anom_key, {
                "status": "active",
                "channel_type": "infra",
                "host": cat,
                "last_line": msg,
                "plugin_name": "telemetry_anomaly",
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "missing_count": 0,
            })
        except Exception as e:
            logger.error(f"Anomaly report error: {e}")

    # Telemetry alerting rules (fixed thresholds from config)
    _telem_rules = getattr(config, 'TELEMETRY_ALERTS', [])
    if _telem_rules and data_to_insert:
        import fnmatch as _fnm
        for (_, cat, metric, val) in data_to_insert:
            for rule in _telem_rules:
                if not isinstance(rule, dict): continue
                if not _fnm.fnmatch(metric, rule.get('metric', '*')): continue
                triggered = False
                if 'above' in rule and val > float(rule['above']): triggered = True
                if 'below' in rule and val < float(rule['below']): triggered = True
                if not triggered: continue
                cooldown_key = f"TALERT|{metric}"
                import time as _time2
                if _time2.time() - _anomaly_cooldown.get(cooldown_key, 0) < 3600: continue
                _anomaly_cooldown[cooldown_key] = _time2.time()
                ch = rule.get('channel', 'infra')
                direction = 'above' if 'above' in rule else 'below'
                threshold = rule.get('above', rule.get('below'))
                msg = f"Telemetry threshold [{direction} {threshold}]: {metric} = {val:.2f}"
                try:
                    save_problem(f"TALERT|{cat}|{metric}", {
                        "status": "active", "channel_type": ch, "host": cat,
                        "last_line": msg, "plugin_name": "telemetry_alert",
                        "last_seen": datetime.now(timezone.utc).isoformat(), "missing_count": 0,
                    })
                except Exception as _e: logger.error(f"telemetry_alert: {_e}")
                break  # Jedno pravidlo na metriku za iteraci

    # InfluxDB export (non-blocking)
    _influx = getattr(config, 'INFLUXDB', {})
    if _influx.get('url') and _influx.get('token') and data_to_insert:
        threading.Thread(target=_write_influxdb, args=(list(data_to_insert),), daemon=True).start()

def _write_influxdb(records: list):
    """Zapíše telemetrii do InfluxDB v line protocol formátu."""
    try:
        influx = getattr(config, 'INFLUXDB', {})
        url = influx.get('url', '').rstrip('/')
        token = influx.get('token', '')
        org = influx.get('org', 'sentinel')
        bucket = influx.get('bucket', 'sentinel')
        lines = []
        for (ts, category, metric, value) in records:
            safe_metric = metric.replace(' ', '_').replace(',', '\\,').replace('=', '\\=')
            safe_cat = category.replace(' ', '_').replace(',', '\\,').replace('=', '\\=')
            lines.append(f"sentinel,category={safe_cat} {safe_metric}={value}")
        payload = '\n'.join(lines)
        import urllib.request as _ur
        req = _ur.Request(
            f"{url}/api/v2/write?org={org}&bucket={bucket}&precision=s",
            data=payload.encode(),
            headers={"Authorization": f"Token {token}", "Content-Type": "text/plain; charset=utf-8"},
            method='POST'
        )
        _ur.urlopen(req, timeout=5)
    except Exception as e:
        logger.debug(f"InfluxDB write: {e}")

def get_metric_history(metric_name, limit=288):
    try:
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM telemetry WHERE metric=? ORDER BY timestamp DESC LIMIT ?", (metric_name, limit))
            rows = c.fetchall()
            return [r[0] for r in rows][::-1]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        return []

def prune_telemetry(days=2):
    limit_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    deleted_total = 0
    batch_size = 1000
    
    while True:
        with db_lock:
            try:
                conn = _get_conn()
                c = conn.execute(
                    f"""DELETE FROM telemetry 
                        WHERE rowid IN (
                            SELECT rowid FROM telemetry 
                            WHERE timestamp < ? 
                            LIMIT {batch_size}
                        )""", 
                    (limit_date,)
                )
                deleted_count = c.rowcount
                conn.commit()
                conn.close()
                deleted_total += deleted_count
                
                if deleted_count == 0:
                    break
            except Exception as e:
                logger.error(f"Problem during batched prune_telemetry: {e}")
                return False
        time.sleep(0.1) 
        
    if deleted_total > 0:
        logger.info(f"Pruned {deleted_total} telemetry records older than {days} days.")
        # 367: VACUUM po >10k prune
        if deleted_total > 10000:
            try:
                run_db_vacuum()
            except Exception as _ve:
                logger.warning(f"post-prune VACUUM: {_ve}")
    return True


def prune_issue_history(days: int = 90) -> int:
    """366: Prune old issue_history records older than N days.
    Also triggers VACUUM if >10k rows deleted (367).
    """
    limit_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    deleted = 0
    batch_size = 1000
    while True:
        with db_lock:
            try:
                conn = _get_conn()
                c = conn.execute(
                    """DELETE FROM issue_history WHERE rowid IN (
                        SELECT rowid FROM issue_history
                        WHERE resolved_at < ? LIMIT ?)""",
                    (limit_date, batch_size)
                )
                n = c.rowcount
                conn.commit()
                conn.close()
                deleted += n
                if n == 0:
                    break
            except Exception as e:
                logger.error(f"prune_issue_history: {e}")
                return deleted
        time.sleep(0.05)
    if deleted > 0:
        logger.info(f"prune_issue_history: deleted {deleted} records older than {days} days")
        # 367: VACUUM po >10k prune
        if deleted > 10000:
            try:
                run_db_vacuum()
            except Exception as _ve:
                logger.warning(f"post-prune_issue_history VACUUM: {_ve}")
    return deleted


def aggregate_telemetry(raw_after_hours: int = 24) -> int:
    """Aggregate raw telemetry older than N hours into one row per metric per hour (avg).

    Reduces DB size significantly for high-frequency metrics while keeping history.
    Returns count of metric-hours compressed.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=raw_after_hours)).strftime('%Y-%m-%dT%H:00:00')
    with db_lock:
        try:
            conn = _get_conn()
            # Find metric+hour buckets with more than one raw row
            pairs = conn.execute("""
                SELECT metric, strftime('%Y-%m-%dT%H:00:00', timestamp) AS hour,
                       COUNT(*) AS cnt,
                       AVG(CAST(value AS REAL)) AS avg_val,
                       category
                FROM telemetry
                WHERE timestamp < ?
                GROUP BY metric, hour
                HAVING cnt > 1
            """, (cutoff,)).fetchall()

            compressed = 0
            for metric, hour, cnt, avg_val, category in pairs:
                # Remove all raw rows for this bucket
                conn.execute(
                    "DELETE FROM telemetry WHERE metric=? AND strftime('%Y-%m-%dT%H:00:00', timestamp)=?",
                    (metric, hour)
                )
                # Insert single averaged row with timestamp = start of hour
                val = round(avg_val, 3) if avg_val is not None else None
                conn.execute(
                    "INSERT INTO telemetry (timestamp, category, metric, value) VALUES (?, ?, ?, ?)",
                    (hour, category, metric, val)
                )
                compressed += 1

            conn.commit()
            conn.close()
            if compressed:
                logger.info(f"aggregate_telemetry: compressed {compressed} metric-hours (cutoff={cutoff})")
            return compressed
        except Exception as e:
            logger.error(f"aggregate_telemetry error: {e}")
            return 0

def prune_expired_actions():
    with db_lock:
        try:
            conn = _get_conn()
            limit = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
            conn.execute("UPDATE actions SET status='expired' WHERE status='pending' AND created_at < ?", (limit,))
            conn.commit()
            conn.close()
        except: pass

def create_pending_action(problem_key, cluster, node, command, reason,
                          mode="dry_run", risk_score=0, risk_reasons=None, raw_line=None):
    new_id = None
    with db_lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            c.execute("SELECT id FROM actions WHERE problem_key=? AND status='pending'", (problem_key,))
            if c.fetchone():
                conn.close()
                return None
            created_at = datetime.now(timezone.utc).isoformat()
            reasons_json = json.dumps(risk_reasons or [])
            c.execute('''INSERT INTO actions
                         (problem_key, cluster, node, command, reason, status, created_at,
                          mode, risk_score, risk_reasons, raw_line)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (problem_key, cluster, node, command, reason, "pending", created_at,
                       mode, int(risk_score), reasons_json, raw_line))
            new_id = c.lastrowid
            conn.commit()
            conn.close()
        except: return None
    if new_id:
        log_action_event(new_id, "created", actor="ai",
                         risk_score=risk_score,
                         details={"mode": mode, "reasons": risk_reasons or [],
                                  "command": command, "node": node, "cluster": cluster})
    return new_id

def get_pending_actions():
    # Pozn.: prune_expired_actions() se ZÁMĚRNĚ nevolá zde — byl to zápis pod db_lock
    # na hot read-path (každý /status poll), což způsobovalo kontenci s agent ingestem
    # a zatuhnutí webu. Expiraci řeší background action_cleanup_loop (každých 60s).
    actions = []
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM actions WHERE status='pending' ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        for row in rows: 
            actions.append(dict(row))
    except: pass
    return actions

def get_action(action_id):
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM actions WHERE id=?", (action_id,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except: return None

def list_actions(status=None, mode=None, limit=200):
    """JSON-safe list of actions filtered by status/mode (both optional).

    risk_reasons is parsed back into a Python list.
    """
    prune_expired_actions()
    out = []
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        where, args = [], []
        if status:
            where.append("status=?"); args.append(status)
        if mode:
            where.append("mode=?"); args.append(mode)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        args.append(int(limit))
        c.execute(f"SELECT * FROM actions {clause} ORDER BY created_at DESC LIMIT ?", args)
        for row in c.fetchall():
            d = dict(row)
            try:
                d["risk_reasons"] = json.loads(d.get("risk_reasons") or "[]")
            except Exception:
                d["risk_reasons"] = []
            out.append(d)
        conn.close()
    except Exception as e:
        logger.error(f"DB Error list_actions: {e}")
    return out


def log_action_event(action_id, event, actor=None, risk_score=None, details=None):
    """Append a state-transition record for an action.

    event values used in code: 'created', 'dry_run_completed', 'reviewed',
    'rejected', 'executed', 'failed'.
    """
    try:
        details_json = json.dumps(details) if details is not None else None
    except Exception:
        details_json = str(details)
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO action_audit (action_id, event, actor, at, risk_score, details) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (int(action_id), str(event), actor,
                 datetime.now(timezone.utc).isoformat(),
                 int(risk_score) if risk_score is not None else None,
                 details_json),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error log_action_event: {e}")
            return False


def get_action_audit(action_id, limit=200):
    """Read audit trail for one action, oldest first."""
    out = []
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM action_audit WHERE action_id=? ORDER BY at ASC LIMIT ?",
                  (int(action_id), int(limit)))
        for row in c.fetchall():
            d = dict(row)
            if d.get("details"):
                try: d["details"] = json.loads(d["details"])
                except Exception: pass
            out.append(d)
        conn.close()
    except Exception as e:
        logger.error(f"DB Error get_action_audit: {e}")
    return out


def mark_action_reviewed(action_id, reviewed_by):
    """Mark a dry-run action as human-reviewed (no execution)."""
    changed = 0
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            cur = conn.execute(
                "UPDATE actions SET status='reviewed', executed_at=?, executed_by=? "
                "WHERE id=? AND status='pending'",
                (now, reviewed_by, action_id),
            )
            changed = cur.rowcount
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Error mark_action_reviewed: {e}")
            return False
    if changed > 0:
        log_action_event(action_id, "reviewed", actor=reviewed_by)
    return changed > 0


def set_dry_run_output(action_id, output):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE actions SET dry_run_output=? WHERE id=?", (output, action_id))
            conn.commit()
            conn.close()
            return True
        except: return False

def update_action_status(action_id, status, output="", executed_by=None):
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE actions SET status=?, output=?, executed_at=?, executed_by=? WHERE id=?", 
                         (status, output, now, executed_by, action_id))
            if status == "executed":
                cur = conn.execute("SELECT problem_key FROM actions WHERE id=?", (action_id,))
                row = cur.fetchone()
                if row and row[0]:
                    pk = row[0]
                    cur.execute("SELECT details FROM problems WHERE key=?", (pk,))
                    pr = cur.fetchone()
                    if pr:
                        d = json.loads(pr[0]) if pr[0] else {}
                        d["status"] = "validating"
                        d["last_seen"] = now
                        conn.execute("UPDATE problems SET status='validating', last_seen=?, details=? WHERE key=?", (now, json.dumps(d), pk))
                        conn.execute("UPDATE actions SET status='validating_fix' WHERE problem_key=? AND status='pending' AND id != ?", (pk, action_id))
            conn.commit()
            conn.close()
            return True
        except: return False

def has_pending_action_for_key(problem_key: str) -> bool:
    """Return True if a pending/reviewing action already exists for this problem key."""
    try:
        with db_lock:
            conn = _get_conn()
            try:
                row = conn.execute(
                    "SELECT 1 FROM actions WHERE problem_key=? AND status IN ('pending', 'reviewing') LIMIT 1",
                    (problem_key,)
                ).fetchone()
                return row is not None
            finally:
                conn.close()
    except Exception:
        return False

def _archive_problem(conn, key):
    """Copy problem to issue_history before deletion."""
    try:
        row = conn.execute(
            "SELECT channel_type, host, details, last_seen FROM problems WHERE key=?", (key,)
        ).fetchone()
        if not row: return
        ch, host, details_json, last_seen = row
        now = datetime.now(timezone.utc).isoformat()
        det = json.loads(details_json) if details_json else {}
        conn.execute(
            "INSERT INTO issue_history (key, channel_type, host, plugin_name, last_line, last_seen, resolved_at) VALUES (?,?,?,?,?,?,?)",
            (key, ch, host or det.get('host'), det.get('plugin_name'), det.get('last_line'), last_seen, now)
        )
    except Exception as e:
        logger.debug(f"_archive_problem: {e}")

def mark_resolved(key):
    """Resolve and immediately delete the problem record (only active issues matter)."""
    with db_lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            _archive_problem(conn, key)
            c.execute("UPDATE actions SET status='resolved_auto' WHERE problem_key=? AND status='pending'", (key,))
            c.execute("DELETE FROM problems WHERE key=?", (key,))
            conn.commit()
            conn.close()
            return True
        except: return False

def delete_problem(key):
    with db_lock:
        try:
            conn = _get_conn()
            _archive_problem(conn, key)
            conn.execute("DELETE FROM problems WHERE key=?", (key,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_problem: {e}")
            return False

def get_problem(key):
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM problems WHERE key=?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            d = dict(row)
            if d['details']: 
                try: d.update(json.loads(d['details']))
                except: pass
            del d['details']
            return d
        return None
    except: return None

def save_problem(key, data):
    if 'plugin_name' not in data:
        import inspect
        try:
            stack = inspect.stack()
            caller_frame = stack[2] 
            module = inspect.getmodule(caller_frame[0])
            data['plugin_name'] = module.__name__.split('.')[-1] if module else "system"
        except:
            data['plugin_name'] = "unknown"

    if not data.get('last_line') or data.get('last_line').strip() == "":
        return False

    plugin = data['plugin_name'].upper()
    channel = data.get('channel_type', 'general').upper()
    host = data.get('host', 'unknown')
    msg = data.get('last_line', '')

    is_new_issue = False 

    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            details_json = json.dumps(data)
            
            c = conn.cursor()
            c.execute("SELECT status FROM problems WHERE key=?", (key,))
            row = c.fetchone()
            is_new = True
            if row and row[0] in ['active', 'validating']:
                is_new = False
            
            is_new_issue = is_new  
           
            conn.execute("""
                INSERT INTO problems (key, status, channel_type, last_seen, missing_count, details, snoozed_until, plugin_name, host, last_line, occurrence_count, first_seen)
                VALUES (?, 'active', ?, ?, 0, ?, NULL, ?, ?, ?, 1, ?)
                ON CONFLICT(key) DO UPDATE SET
                    status='active',
                    channel_type=excluded.channel_type,
                    last_seen=excluded.last_seen,
                    details=excluded.details,
                    snoozed_until=NULL,
                    plugin_name=excluded.plugin_name,
                    host=excluded.host,
                    last_line=excluded.last_line,
                    occurrence_count=CASE WHEN problems.status IN ('active','validating') THEN problems.occurrence_count+1 ELSE 1 END,
                    first_seen=CASE WHEN problems.first_seen IS NULL THEN excluded.first_seen ELSE problems.first_seen END
            """, (key, channel, now, details_json, data['plugin_name'], host, msg, now))
 
            conn.commit()
            conn.close()
            
            if is_new:
                logger.info(f"!!! ISSUE CAPTURED !!! [{plugin}] {host}: {msg}")

                # Check per-detector notify flag (default True)
                _det_notify = True
                for _det in getattr(config, 'DETECTORS', []):
                    if _det.get('plugin') == plugin:
                        _det_notify = _det.get('notify', True)
                        break
                # Normalize channel to known categories (info/clusters → infra)
                _ch_norm = channel.lower()
                _ch_norm = {'info': 'infra', 'clusters': 'infra'}.get(_ch_norm, _ch_norm)
                # Check per-channel notify flag (stored in DB settings)
                _ch_val = None
                try:
                    from .state_agents import get_setting as _gs
                    _ch_val = _gs(f'notify_channel.{_ch_norm}')
                except Exception:
                    pass
                _ch_notify = (_ch_val != '0')

                if _det_notify and _ch_notify:
                    if getattr(config, 'HA_ENABLED', False):
                        try:
                            ha_msg = f"{host}: {msg}"
                            ha_title = f"Sentinel Issue [{plugin}]"
                            threading.Thread(target=utils.send_ha_alert, args=(ha_msg, ha_title), daemon=True).start()
                        except: pass

                    utils.mqtt_manager.publish("alerts/new", {
                        "host": host,
                        "plugin": plugin,
                        "channel": channel,
                        "message": msg,
                        "severity": "CRITICAL" if channel in ['SECURITY', 'ROOT'] else "WARNING"
                    })

        except Exception as e:
            logger.error(f"DB Error in save_problem: {e}")

    # Recurring issue detection: occurrence_count >= 3 within 24h → tag + bump severity
    if not is_new_issue:
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT occurrence_count, first_seen, severity FROM problems WHERE key=?", (key,)
            ).fetchone()
            if row:
                occ, first_seen_str, cur_sev = row
                if occ and occ >= 3 and first_seen_str:
                    fs = datetime.fromisoformat(first_seen_str)
                    if fs.tzinfo is None:
                        fs = fs.replace(tzinfo=timezone.utc)
                    age_h = (datetime.now(timezone.utc) - fs).total_seconds() / 3600
                    if age_h <= 24:
                        # Přidat recurring tag (pokud ještě nemá)
                        exists = conn.execute(
                            "SELECT 1 FROM issue_tags WHERE problem_key=? AND lower(tag)='recurring'", (key,)
                        ).fetchone()
                        if not exists:
                            conn.execute(
                                "INSERT INTO issue_tags (problem_key, tag, created_by) VALUES (?,?,?)",
                                (key, 'recurring', 'system')
                            )
                            conn.commit()
                        # Bump severity pokud ještě není high/critical
                        sev_order = {'': 0, None: 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
                        if sev_order.get(cur_sev, 0) < sev_order.get('high', 3):
                            conn.execute("UPDATE problems SET severity='high' WHERE key=?", (key,))
                            conn.commit()
            conn.close()
        except Exception as _re:
            logger.debug(f"recurring detection: {_re}")

    # 425: Issue lifecycle webhooks + 415: Gitea sync
    if is_new_issue:
        try:
            from .state_base import _issue_lifecycle_callbacks
            for cb in _issue_lifecycle_callbacks:
                try:
                    cb('ISSUE_CREATED', {**data, 'key': key})
                except Exception:
                    pass
        except Exception:
            pass

    # Auto-tag: apply matching rules from config (outside db_lock, non-critical)
    if is_new_issue:
        try:
            import fnmatch as _fnmatch
            for rule in getattr(config, 'AUTO_TAGS', []):
                if not isinstance(rule, dict):
                    continue
                rule_plugin = rule.get('plugin', '*')
                rule_host = rule.get('host', '*')
                rule_channel = rule.get('channel', '*')
                tag = rule.get('tag', '').strip()
                if not tag:
                    continue
                if (_fnmatch.fnmatch(data.get('plugin_name', ''), rule_plugin) and
                        _fnmatch.fnmatch(host, rule_host) and
                        _fnmatch.fnmatch(channel.lower(), rule_channel.lower())):
                    add_issue_tag(key, tag, 'auto')
        except Exception as _e:
            logger.debug(f"auto_tag error: {_e}")

        # Auto-remediation: one-shot for services_detector and storage_detector
        _plugin_name = data.get('plugin_name', '')
        if _plugin_name in ('services_detector', 'storage_detector', 'availability_detector'):
            threading.Thread(
                target=_try_auto_remediate,
                args=(key, host, _plugin_name, msg, data),
                daemon=True,
                name=f"AutoRem-{key[:30]}"
            ).start()

    return is_new_issue

def _try_auto_remediate(key: str, host: str, plugin: str, msg: str, data: dict):
    """Pokusí se jednou automaticky opravit známé problémy (service fail, mount fail).
    Zavolá run_ssh_command_real z actions.py. Výsledek zapíše do auto_remediation_log.
    Na selhání vytvoří nové issue s prefixem AUTOFAIL."""
    if has_auto_remediation_attempted(key):
        return
    try:
        from sentinel import actions as _actions
        from sentinel import safety as _safety

        # Určit příkaz k spuštění
        command = None
        if plugin == 'services_detector':
            # Extrahovat název service z last_line nebo klíče
            import re as _re
            m = _re.search(r'(\S+\.service)', msg)
            if not m:
                # Zkus klíč: SERVICE_FAILED|host|service.service
                parts = key.split('|')
                if len(parts) >= 3 and parts[2].endswith('.service'):
                    service = parts[2]
                else:
                    return
            else:
                service = m.group(1)
            command = f"systemctl restart {service}"

        elif plugin == 'storage_detector':
            command = "mount -a"

        elif plugin == 'availability_detector':
            return  # Nelze automaticky opravit

        if not command:
            return

        # Zkontrolovat allowlist — musí existovat povolený vzor
        allowed = check_command_allowed(command)
        if not allowed or not allowed.get('auto_execute'):
            logger.debug(f"AutoRem: příkaz '{command}' není v allowlistu s auto_execute=1, přeskakuji")
            return

        # Zkontrolovat safety classifier
        if _safety.is_blocked(command):
            logger.debug(f"AutoRem: příkaz '{command}' zablokován safety klasifikátorem")
            return

        logger.info(f"[AutoRem] Spouštím: {command} na {host}")
        success, output = _actions.run_ssh_command_real(host, command)
        log_auto_remediation(key, command, host, success, output)

        if success:
            logger.info(f"[AutoRem] ✓ Úspěch: {command} na {host}")
            # Přejít do stavu 'validating' — watchdog potvrdí
            with db_lock:
                try:
                    conn = _get_conn()
                    conn.execute("UPDATE problems SET status='validating' WHERE key=?", (key,))
                    conn.commit()
                    conn.close()
                except Exception: pass
        else:
            logger.warning(f"[AutoRem] ✗ Selhání: {command} na {host}: {output[:200]}")
            # Vytvořit issue pro selhání auto-remediace
            fail_key = f"AUTOFAIL|{key}"
            fail_msg = f"Auto-remediation SELHALO [{plugin}] {host}: příkaz '{command}' → {output[:120]}"
            save_problem(fail_key, {
                "status": "active",
                "last_line": fail_msg,
                "channel_type": data.get('channel_type', 'infra'),
                "plugin_name": "auto_remediation",
                "host": host,
                "severity": "critical",
                "missing_count": 0,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "autofail": True,
                "original_key": key,
                "tried_command": command,
            })
    except Exception as e:
        logger.error(f"_try_auto_remediate error: {e}")

def save_telemetry(metric, value, category="general"):
    # 127: Buffered single-metric insert (no anomaly detection needed for single values)
    try:
        val_float = float(value)
        ts = datetime.now(timezone.utc).isoformat()
        with _telemetry_buffer_lock:
            _telemetry_buffer.append((ts, category, metric, val_float))
    except (ValueError, TypeError):
        pass

def _get_suppress_rules() -> list:
    """Vrátí aktivní (nevypršelá) suppression pravidla jako list dict."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT host_pattern, plugin_pattern FROM suppress_rules "
            "WHERE expires_at IS NULL OR expires_at > datetime('now')"
        ).fetchall()
        conn.close()
        return [{'host': r[0], 'plugin': r[1]} for r in rows]
    except:
        return []

def _is_suppressed(host: str, plugin: str, rules: list) -> bool:
    import fnmatch
    for r in rules:
        if fnmatch.fnmatch(host or '', r['host']) and fnmatch.fnmatch(plugin or '', r['plugin']):
            return True
    return False

def get_active_issues(include_snoozed: bool = False):
    issues = []
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if include_snoozed:
            c.execute("SELECT * FROM problems WHERE status IN ('active', 'validating', 'acknowledged')")
        else:
            c.execute(
                "SELECT * FROM problems WHERE status IN ('active', 'validating', 'acknowledged') "
                "AND (snoozed_until IS NULL OR snoozed_until <= datetime('now'))"
            )
        rows = c.fetchall()
        conn.close()
        suppress = _get_suppress_rules()
        for row in rows:
            d = dict(row)
            # Save authoritative column values before details merge
            col_channel    = d.get('channel_type')
            col_plugin     = d.get('plugin_name')
            col_host       = d.get('host')
            col_last_line  = d.get('last_line')
            if d.get('details'):
                try: d.update(json.loads(d['details']))
                except: pass
            # Restore columns as authoritative (override whatever was in details JSON)
            if col_channel:   d['channel_type'] = col_channel
            if col_plugin:    d['plugin_name']  = col_plugin
            if col_host:      d['host']         = col_host
            if col_last_line: d['last_line']    = col_last_line
            del d['details']
            if suppress and _is_suppressed(d.get('host', ''), d.get('plugin_name', ''), suppress):
                continue
            issues.append(d)
    except: pass
    return issues


def get_snoozed_count() -> int:
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM problems WHERE status IN ('active', 'validating') "
                "AND snoozed_until IS NOT NULL AND snoozed_until > datetime('now')"
            ).fetchone()
            return row[0] if row else 0
    except:
        return 0


def snooze_problem(key: str, hours: int):
    until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE problems SET snoozed_until=? WHERE key=?", (until, key))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error snooze_problem: {e}")
            return False


def unsnooze_problem(key: str):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE problems SET snoozed_until=NULL WHERE key=?", (key,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error unsnooze_problem: {e}")
            return False

def get_recent_issues(limit: int = 8) -> list:
    """Returns the most recently updated active/validating issues."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT key, channel_type, last_seen, details
                FROM problems
                WHERE status IN ('active', 'validating')
                ORDER BY last_seen DESC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
            result = []
            for r in rows:
                d = {}
                try: d = json.loads(r['details'] or '{}')
                except Exception: pass
                result.append({
                    "key": r['key'],
                    "channel": r['channel_type'] or 'GENERAL',
                    "plugin": d.get('plugin_name', '?'),
                    "host": d.get('host', r['key'].split('|')[1] if '|' in r['key'] else '?'),
                    "last_line": d.get('last_line', ''),
                    "ts": r['last_seen'],
                })
            return result
        except Exception as e:
            logger.error(f"DB Error get_recent_issues: {e}")
            return []

def get_queue_depth() -> int:
    with db_lock:
        try:
            conn = _get_conn()
            r = conn.execute("SELECT COUNT(*) FROM task_queue WHERE status='pending'").fetchone()
            conn.close()
            return r[0] if r else 0
        except Exception:
            return 0

def get_queue_items(limit=50) -> list:
    with db_lock:
        try:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, priority, payload, status, created_at, worker_id FROM task_queue "
                "WHERE status IN ('pending','processing') ORDER BY priority DESC, created_at ASC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            result = []
            for row in rows:
                try:
                    p = json.loads(row["payload"]) if row["payload"] else {}
                except Exception:
                    p = {}
                ctx = p.get("context") or {}
                result.append({
                    "id": row["id"],
                    "priority": row["priority"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "worker_id": row["worker_id"],
                    "type": p.get("type", ""),
                    "channel": p.get("channel", ""),
                    "host": ctx.get("host", ctx.get("agent_id", "")),
                    "text": (p.get("text") or "")[:80],
                })
            return result
        except Exception:
            return []

def get_issue_comments(problem_key: str) -> list:
    with db_lock:
        try:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, author, text, created_at FROM issue_comments WHERE problem_key=? ORDER BY created_at ASC",
                (problem_key,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"DB Error get_issue_comments: {e}")
            return []

def add_issue_comment(problem_key: str, author: str, text: str) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO issue_comments (problem_key, author, text) VALUES (?,?,?)",
                (problem_key, author, text)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error add_issue_comment: {e}")
            return False

def delete_issue_comment(comment_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM issue_comments WHERE id=?", (comment_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_issue_comment: {e}")
            return False

def get_comment_counts() -> dict:
    """Returns {problem_key_b64: count} for all keys with at least 1 comment."""
    import base64 as _b64
    with db_lock:
        try:
            conn = _get_conn()
            rows = conn.execute(
                "SELECT problem_key, COUNT(*) FROM issue_comments GROUP BY problem_key"
            ).fetchall()
            conn.close()
            return {_b64.b64encode(r[0].encode()).decode(): r[1] for r in rows}
        except Exception as e:
            logger.error(f"DB Error get_comment_counts: {e}")
            return {}

# ── Config History ────────────────────────────────────────────────────────────

def save_config_snapshot(content: str):
    """Uloží snapshot config.yaml do DB, drží max 5 posledních."""
    import hashlib as _hl
    content_hash = _hl.md5(content.encode()).hexdigest()
    with db_lock:
        try:
            conn = _get_conn()
            # Nekládat duplicitu (stejný hash)
            exists = conn.execute(
                "SELECT 1 FROM config_history WHERE content_hash=? ORDER BY timestamp DESC LIMIT 1",
                (content_hash,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO config_history (content, content_hash) VALUES (?,?)",
                    (content, content_hash)
                )
                # Prune — ponechat max 5
                conn.execute(
                    "DELETE FROM config_history WHERE id NOT IN "
                    "(SELECT id FROM config_history ORDER BY timestamp DESC LIMIT 5)"
                )
                conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"save_config_snapshot: {e}")

def get_config_history() -> list:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, timestamp, content_hash FROM config_history ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        conn.close()
        return [{"id": r[0], "timestamp": r[1], "hash": r[2]} for r in rows]
    except Exception as e:
        logger.error(f"get_config_history: {e}")
        return []

def get_config_snapshot(snapshot_id: int) -> str | None:
    try:
        conn = _get_conn()
        row = conn.execute("SELECT content FROM config_history WHERE id=?", (snapshot_id,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"get_config_snapshot: {e}")
        return None

# ── DB Vacuum ─────────────────────────────────────────────────────────────────

def run_db_vacuum():
    """Spustí VACUUM na SQLite DB pro uvolnění fragmentovaného prostoru."""
    try:
        conn = _get_conn()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.close()
        logger.info("DB VACUUM dokončen")
    except Exception as e:
        logger.error(f"run_db_vacuum: {e}")

# ── Session Management ────────────────────────────────────────────────────────

def session_register(session_uuid: str, username: str, role: str, ip: str, user_agent: str):
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO active_sessions (session_uuid, username, role, ip, user_agent, created_at, last_seen) VALUES (?,?,?,?,?,?,?)",
                (session_uuid, username, role, ip, user_agent[:200], now, now)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"session_register: {e}")

def session_touch(session_uuid: str):
    try:
        conn = _get_conn()
        conn.execute("UPDATE active_sessions SET last_seen=datetime('now') WHERE session_uuid=?", (session_uuid,))
        conn.commit()
        conn.close()
    except Exception: pass

def session_remove(session_uuid: str):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM active_sessions WHERE session_uuid=?", (session_uuid,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"session_remove: {e}")

def list_sessions() -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, session_uuid, username, role, ip, user_agent, created_at, last_seen "
            "FROM active_sessions ORDER BY last_seen DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"list_sessions: {e}")
        return []

def revoke_session(session_id: int) -> str | None:
    """Smaže session z DB a vrátí session_uuid pro blacklist."""
    with db_lock:
        try:
            conn = _get_conn()
            row = conn.execute("SELECT session_uuid FROM active_sessions WHERE id=?", (session_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM active_sessions WHERE id=?", (session_id,))
                conn.commit()
                conn.close()
                return row[0]
            conn.close()
        except Exception as e:
            logger.error(f"revoke_session: {e}")
        return None

def prune_stale_sessions(hours: int = 24):
    """Odstraní sessions neaktivní déle než N hodin."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM active_sessions WHERE last_seen < datetime('now', ?)", (f'-{hours} hours',))
            conn.commit()
            conn.close()
        except Exception: pass

# ── Issue Assignee ─────────────────────────────────────────────────────────────

def assign_issue(key: str, username: str) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            # ensure column exists (migration guard)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(problems)").fetchall()}
            if 'assigned_to' not in cols:
                conn.execute("ALTER TABLE problems ADD COLUMN assigned_to TEXT DEFAULT NULL")
            conn.execute("UPDATE problems SET assigned_to=? WHERE key=?", (username or None, key))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"assign_issue: {e}")
            return False

# ── SSH Execute Log ────────────────────────────────────────────────────────────

def log_ssh_execute(hostname: str, command: str, actor: str, success: bool, output: str):
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO ssh_execute_log (hostname, command, actor, success, output) VALUES (?,?,?,?,?)",
            (hostname, command, actor, 1 if success else 0, (output or '')[:8000])  # 047: zvýšen limit
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"log_ssh_execute: {e}")

def get_ssh_history(hostname: str, limit: int = 30) -> list:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT command, actor, executed_at, success, output FROM ssh_execute_log "
            "WHERE hostname=? ORDER BY executed_at DESC LIMIT ?",
            (hostname, limit)
        ).fetchall()
        conn.close()
        return [{"command": r[0], "actor": r[1], "at": r[2], "success": bool(r[3]), "output": r[4]} for r in rows]
    except Exception as e:
        logger.error(f"get_ssh_history: {e}")
        return []

# ── Issue Merge ────────────────────────────────────────────────────────────────

def merge_issues(primary_key: str, linked_key: str, actor: str) -> bool:
    """linked_key se nastaví merged_into=primary_key a status='resolved'."""
    if primary_key == linked_key:
        return False
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE problems SET merged_into=?, status='resolved', acknowledged_by=? WHERE key=?",
                (primary_key, actor, linked_key)
            )
            conn.commit()
            conn.close()
            logger.info(f"[merge] {linked_key} → {primary_key} by {actor}")
            return True
        except Exception as e:
            logger.error(f"merge_issues: {e}")
            return False

# ── Issue Triage ───────────────────────────────────────────────────────────────

_SEV_SCORE = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, None: 0, '': 0}

def get_triage_issues() -> list:
    """Vrátí aktivní issues seřazené podle urgency score (severity × SLA vypršení)."""
    issues = get_active_issues()
    sla_rules = getattr(config, 'SLA_RULES', {})
    now_utc = datetime.now(timezone.utc)
    scored = []
    for i in issues:
        sev_s = _SEV_SCORE.get((i.get('severity') or '').lower(), 0)
        sla_s = 0
        ch = (i.get('channel_type') or '').lower()
        if ch in sla_rules:
            try:
                fs = datetime.fromisoformat(i.get('first_seen') or i.get('last_seen', ''))
                if fs.tzinfo is None: fs = fs.replace(tzinfo=timezone.utc)
                age_h = (now_utc - fs).total_seconds() / 3600
                sla_h = sla_rules[ch]
                ratio = age_h / sla_h
                sla_s = min(int(ratio * 3), 5)  # 0–5
            except Exception: pass
        occ = min((i.get('occurrence_count') or 1) // 3, 3)
        urgency = sev_s * 3 + sla_s * 2 + occ
        i['urgency_score'] = urgency
        scored.append(i)
    scored.sort(key=lambda x: -x['urgency_score'])
    return scored

# ── Agent Thresholds ───────────────────────────────────────────────────────────

def get_agent_thresholds(hostname: str) -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM agent_thresholds WHERE hostname=? ORDER BY created_at ASC", (hostname,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_agent_thresholds: {e}")
        return []

def set_agent_threshold(hostname: str, metric_pattern: str, above=None, below=None,
                        channel: str = 'agent', created_by: str = '') -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO agent_thresholds (hostname, metric_pattern, above, below, channel, created_by) VALUES (?,?,?,?,?,?)",
                (hostname, metric_pattern, above, below, channel, created_by)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"set_agent_threshold: {e}")
            return False

def delete_agent_threshold(threshold_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM agent_thresholds WHERE id=?", (threshold_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"delete_agent_threshold: {e}")
            return False

def check_agent_thresholds(hostname: str, metrics_dict: dict):
    """Evaluate per-agent threshold rules against incoming metric values.
    Creates an issue when a threshold is exceeded; resolves it when OK again.
    Skips rules whose metric_pattern doesn't match any key in metrics_dict."""
    import fnmatch as _fnm
    try:
        rules = get_agent_thresholds(hostname)
    except Exception:
        return
    for rule in rules:
        pattern = rule.get('metric_pattern', '*')
        above   = rule.get('above')
        below   = rule.get('below')
        channel = rule.get('channel') or 'agent'
        rid     = rule.get('id')
        unique_key = f"THRESH|{hostname}|{rid}"

        matched_metric = None
        val_f = None
        for metric, val in metrics_dict.items():
            if _fnm.fnmatch(metric, pattern):
                try:
                    val_f = float(val)
                    matched_metric = metric
                    break
                except (ValueError, TypeError):
                    continue
        if matched_metric is None:
            continue  # metric absent from payload — leave issue state unchanged

        triggered = False
        direction = ''
        thresh_val = None
        if above is not None and val_f > float(above):
            triggered = True
            direction = 'above'
            thresh_val = above
        elif below is not None and val_f < float(below):
            triggered = True
            direction = 'below'
            thresh_val = below

        if triggered:
            msg = f"Threshold [{direction} {thresh_val}]: {matched_metric} = {val_f:.2f}"
            try:
                save_problem(unique_key, {
                    "status": "active",
                    "channel_type": channel,
                    "host": hostname,
                    "last_line": msg,
                    "plugin_name": "agent_threshold",
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "missing_count": 0,
                })
            except Exception as e:
                logger.error(f"check_agent_thresholds save_problem: {e}")
        else:
            try:
                mark_resolved(unique_key)
            except Exception:
                pass

# ── Agent Config Push ──────────────────────────────────────────────────────────

def push_agent_config(hostname: str, cfg: dict) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO agent_config_queue (hostname, config_json) VALUES (?,?)",
                (hostname, json.dumps(cfg))
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"push_agent_config: {e}")
            return False

def get_pending_agent_config(hostname: str) -> dict | None:
    """Vrátí nejnovější nedoručenou konfiguraci pro agenta a označí ji jako doručenou."""
    with db_lock:
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT id, config_json FROM agent_config_queue WHERE hostname=? AND delivered_at IS NULL ORDER BY created_at DESC LIMIT 1",
                (hostname,)
            ).fetchone()
            if not row:
                conn.close()
                return None
            cfg = json.loads(row[1])
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE agent_config_queue SET delivered_at=? WHERE id=?", (now, row[0]))
            conn.commit()
            conn.close()
            return cfg
        except Exception as e:
            logger.error(f"get_pending_agent_config: {e}")
            return None

# ── Health Snapshots ───────────────────────────────────────────────────────────

def save_health_snapshot(score: int, issues_count: int, agents_online: int, agents_total: int):
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO health_snapshots (score, issues_count, agents_online, agents_total) VALUES (?,?,?,?)",
            (score, issues_count, agents_online, agents_total)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"save_health_snapshot: {e}")

def get_health_history(days: int = 7) -> list:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT timestamp, score, issues_count, agents_online, agents_total FROM health_snapshots "
            "WHERE timestamp >= datetime('now',?) ORDER BY timestamp ASC",
            (f'-{days} days',)
        ).fetchall()
        conn.close()
        return [{"ts": r[0], "score": r[1], "issues": r[2], "online": r[3], "total": r[4]} for r in rows]
    except Exception as e:
        logger.error(f"get_health_history: {e}")
        return []

def prune_health_snapshots(days: int = 30):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM health_snapshots WHERE timestamp < datetime('now',?)", (f'-{days} days',))
            conn.commit()
            conn.close()
        except Exception: pass

# ── Custom Patterns ────────────────────────────────────────────────────────────

def get_custom_patterns() -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM custom_patterns ORDER BY name ASC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_custom_patterns: {e}")
        return []

def add_custom_pattern(name: str, plugin: str, pattern: str, channel: str = 'agent', created_by: str = '') -> bool:
    import re as _re
    try: _re.compile(pattern)
    except Exception: return False
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO custom_patterns (name, plugin, pattern, channel, created_by) VALUES (?,?,?,?,?)",
                (name.strip(), plugin.strip(), pattern.strip(), channel.strip(), created_by)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"add_custom_pattern: {e}")
            return False

def delete_custom_pattern(pattern_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM custom_patterns WHERE id=?", (pattern_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"delete_custom_pattern: {e}")
            return False

def toggle_custom_pattern(pattern_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE custom_patterns SET enabled=1-enabled WHERE id=?", (pattern_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"toggle_custom_pattern: {e}")
            return False

# ── Comment Templates ──────────────────────────────────────────────────────────

def get_comment_templates() -> list:
    try:
        conn = _get_conn()
        rows = conn.execute("SELECT id, name, text, created_by FROM comment_templates ORDER BY name ASC").fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "text": r[2], "created_by": r[3]} for r in rows]
    except Exception as e:
        logger.error(f"get_comment_templates: {e}")
        return []

def add_comment_template(name: str, text: str, created_by: str = '') -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("INSERT INTO comment_templates (name, text, created_by) VALUES (?,?,?)", (name.strip(), text.strip(), created_by))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"add_comment_template: {e}")
            return False

def delete_comment_template(template_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM comment_templates WHERE id=?", (template_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"delete_comment_template: {e}")
            return False

# ── Sentinel Error Log ─────────────────────────────────────────────────────────

def log_sentinel_error(source: str, message: str, level: str = 'ERROR', traceback: str = None):
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO sentinel_errors (source, level, message, traceback) VALUES (?,?,?,?)",
            (source[:64], level, message[:1000], (traceback or '')[:2000])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Nesmí hodit výjimku — volá se z error handlerů

def get_sentinel_errors(limit: int = 50) -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, timestamp, source, level, message FROM sentinel_errors ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_sentinel_errors: {e}")
        return []

def prune_sentinel_errors(days: int = 7):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM sentinel_errors WHERE timestamp < datetime('now', ?)", (f'-{days} days',))
            conn.commit()
            conn.close()
        except Exception: pass

# ── Host Heatmap ───────────────────────────────────────────────────────────────

def get_host_heatmap(days: int = 7) -> list:
    """Vrátí matici {host, day, count} pro posledních N dní."""
    try:
        conn = _get_conn()
        rows = conn.execute("""
            SELECT host, strftime('%Y-%m-%d', last_seen) as day, COUNT(*) as cnt
            FROM problems
            WHERE last_seen >= datetime('now', ?)
              AND host IS NOT NULL AND host != '' AND host != 'unknown'
            GROUP BY host, day
            ORDER BY host, day
        """, (f'-{days} days',)).fetchall()
        conn.close()
        return [{"host": r[0], "day": r[1], "count": r[2]} for r in rows]
    except Exception as e:
        logger.error(f"get_host_heatmap: {e}")
        return []

# ── Issue Acknowledge ──────────────────────────────────────────────────────────

def acknowledge_issue(key: str, actor: str) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE problems SET status='acknowledged', acknowledged_by=?, acknowledged_at=? WHERE key=? AND status IN ('active','validating')",
                (actor, now, key)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error acknowledge_issue: {e}")
            return False

def unacknowledge_issue(key: str) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "UPDATE problems SET status='active', acknowledged_by=NULL, acknowledged_at=NULL WHERE key=? AND status='acknowledged'",
                (key,)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error unacknowledge_issue: {e}")
            return False

# ── API Keys ───────────────────────────────────────────────────────────────────

import hashlib as _hashlib

def _hash_api_key(raw_key: str) -> str:
    return _hashlib.sha256(raw_key.encode()).hexdigest()

def create_api_key(name: str, scope: str = 'read', expires_at=None, created_by: str = '') -> str:
    """Creates a new API key, returns the raw token (shown only once)."""
    import secrets as _sec
    raw = _sec.token_hex(32)
    key_hash = _hash_api_key(raw)
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO api_keys (name, key_hash, scope, expires_at, created_by) VALUES (?,?,?,?,?)",
                (name, key_hash, scope, expires_at, created_by)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Error create_api_key: {e}")
            return ''
    return raw

def list_api_keys() -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, scope, expires_at, created_by, created_at, last_used FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB Error list_api_keys: {e}")
        return []

def delete_api_key(key_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_api_key: {e}")
            return False

def verify_api_key(raw_key: str) -> dict | None:
    """Returns key record if valid and not expired, else None. Updates last_used."""
    key_hash = _hash_api_key(raw_key)
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id, name, scope, expires_at FROM api_keys WHERE key_hash=?", (key_hash,)
        ).fetchone()
        if not row:
            conn.close()
            return None
        # Check expiry
        if row[3]:
            try:
                exp = datetime.fromisoformat(row[3])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp:
                    conn.close()
                    return None
            except Exception:
                pass
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE api_keys SET last_used=? WHERE id=?", (now, row[0]))
        conn.commit()
        conn.close()
        return {"id": row[0], "name": row[1], "scope": row[2]}
    except Exception as e:
        logger.error(f"DB Error verify_api_key: {e}")
        return None

# ── Issue Timeline ─────────────────────────────────────────────────────────────

def get_issue_timeline(problem_key: str) -> list:
    """Vrátí chronologický seznam událostí pro issue (komentáře + auto-remediace + status změny)."""
    events = []
    try:
        conn = _get_conn()
        # Komentáře
        rows = conn.execute(
            "SELECT 'comment' as type, author, text as detail, created_at FROM issue_comments WHERE problem_key=? ORDER BY created_at ASC",
            (problem_key,)
        ).fetchall()
        for r in rows:
            events.append({"type": r[0], "actor": r[1], "detail": r[2], "at": r[3]})
        # Auto-remediace
        rows = conn.execute(
            "SELECT 'auto_remediation' as type, host, command, attempted_at, success, output FROM auto_remediation_log WHERE problem_key=? ORDER BY attempted_at ASC",
            (problem_key,)
        ).fetchall()
        for r in rows:
            events.append({"type": r[0], "actor": f"auto ({r[1]})", "detail": f"{'✓' if r[4] else '✗'} {r[2]}: {(r[5] or '')[:100]}", "at": r[3]})
        # Action audit (propojeno přes problem_key v actions)
        rows = conn.execute(
            "SELECT 'action' as type, aa.actor, aa.event || ': ' || COALESCE(a.command,'?') as detail, aa.at "
            "FROM action_audit aa JOIN actions a ON a.id=aa.action_id WHERE a.problem_key=? ORDER BY aa.at ASC",
            (problem_key,)
        ).fetchall()
        for r in rows:
            events.append({"type": r[0], "actor": r[1] or 'system', "detail": r[2], "at": r[3]})
        # Acknowledge info ze sloupce
        row = conn.execute(
            "SELECT acknowledged_by, acknowledged_at FROM problems WHERE key=? AND acknowledged_by IS NOT NULL",
            (problem_key,)
        ).fetchone()
        if row and row[1]:
            events.append({"type": "acknowledged", "actor": row[0], "detail": "Issue potvrzeno (acknowledged)", "at": row[1]})
        # Tagy
        rows = conn.execute(
            "SELECT 'tag' as type, created_by, tag, created_at FROM issue_tags WHERE problem_key=? ORDER BY created_at ASC",
            (problem_key,)
        ).fetchall()
        for r in rows:
            events.append({"type": r[0], "actor": r[1] or 'auto', "detail": f"Tag přidán: #{r[2]}", "at": r[3]})
        conn.close()
        events.sort(key=lambda e: e.get('at') or '')
    except Exception as e:
        logger.error(f"DB Error get_issue_timeline: {e}")
    return events

# ── Issue Severity ─────────────────────────────────────────────────────────────

_VALID_SEVERITIES = {'low', 'medium', 'high', 'critical'}

def set_issue_severity(key: str, severity: str) -> bool:
    if severity not in _VALID_SEVERITIES and severity != '':
        return False
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE problems SET severity=? WHERE key=?", (severity or None, key))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error set_issue_severity: {e}")
            return False

# ── Auto-remediation ───────────────────────────────────────────────────────────

def has_auto_remediation_attempted(problem_key: str) -> bool:
    """Returns True if auto-remediation was already attempted for this issue key."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT 1 FROM auto_remediation_log WHERE problem_key=? LIMIT 1", (problem_key,)
        ).fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logger.error(f"has_auto_remediation_attempted: {e}")
        return True  # Safe default: don't retry on DB error

def log_auto_remediation(problem_key: str, command: str, host: str, success: bool, output: str):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO auto_remediation_log (problem_key, command, host, success, output) VALUES (?,?,?,?,?)",
                (problem_key, command, host, 1 if success else 0, output[:2000])
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"log_auto_remediation: {e}")

# ── Issue Tags ─────────────────────────────────────────────────────────────────

def get_issue_tags(problem_key: str) -> list:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, tag, created_by, created_at FROM issue_tags WHERE problem_key=? ORDER BY created_at ASC",
            (problem_key,)
        ).fetchall()
        conn.close()
        return [{"id": r[0], "tag": r[1], "created_by": r[2], "created_at": r[3]} for r in rows]
    except Exception as e:
        logger.error(f"DB Error get_issue_tags: {e}")
        return []

def add_issue_tag(problem_key: str, tag: str, created_by: str = '') -> bool:
    tag = tag.strip()[:32]
    if not tag:
        return False
    with db_lock:
        try:
            conn = _get_conn()
            # Prevent duplicate tags on same issue
            exists = conn.execute(
                "SELECT 1 FROM issue_tags WHERE problem_key=? AND lower(tag)=lower(?)",
                (problem_key, tag)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO issue_tags (problem_key, tag, created_by) VALUES (?,?,?)",
                    (problem_key, tag, created_by)
                )
                conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error add_issue_tag: {e}")
            return False

def delete_issue_tag(tag_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM issue_tags WHERE id=?", (tag_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_issue_tag: {e}")
            return False

def get_all_tags() -> list:
    """Returns all distinct tags with usage counts, sorted by count desc."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM issue_tags GROUP BY lower(tag) ORDER BY cnt DESC"
        ).fetchall()
        conn.close()
        return [{"tag": r[0], "count": r[1]} for r in rows]
    except Exception as e:
        logger.error(f"DB Error get_all_tags: {e}")
        return []

def get_tag_counts() -> dict:
    """Returns {problem_key_b64: [tag, ...]} for all tagged issues."""
    import base64 as _b64
    try:
        conn = _get_conn()
        rows = conn.execute("SELECT problem_key, tag FROM issue_tags ORDER BY problem_key, created_at").fetchall()
        conn.close()
        result: dict = {}
        for key, tag in rows:
            kb64 = _b64.b64encode(key.encode()).decode()
            result.setdefault(kb64, []).append(tag)
        return result
    except Exception as e:
        logger.error(f"DB Error get_tag_counts: {e}")
        return {}

# ── Agent issue lookup ─────────────────────────────────────────────────────────


# ── TOTP 2FA (346) ────────────────────────────────────────────────────────────

def totp_get(username: str) -> dict | None:
    """Vrátí TOTP záznam pro uživatele nebo None."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM user_totp WHERE username=?", (username,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"totp_get: {e}")
        return None


def totp_setup(username: str) -> str:
    """Vygeneruje nový TOTP secret (disabled dokud nepotvrdí). Vrátí secret."""
    import pyotp
    secret = pyotp.random_base32()
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO user_totp (username, totp_secret, enabled) VALUES (?,?,0) "
                "ON CONFLICT(username) DO UPDATE SET totp_secret=excluded.totp_secret, enabled=0",
                (username, secret)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"totp_setup: {e}")
    return secret


def totp_enable(username: str, code: str) -> bool:
    """Ověří TOTP kód a aktivuje 2FA. Vrátí True při úspěchu."""
    record = totp_get(username)
    if not record:
        return False
    try:
        import pyotp
        if not pyotp.TOTP(record['totp_secret']).verify(code, valid_window=1):
            return False
        with db_lock:
            conn = _get_conn()
            conn.execute("UPDATE user_totp SET enabled=1 WHERE username=?", (username,))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        logger.error(f"totp_enable: {e}")
        return False


def totp_disable(username: str) -> bool:
    """Deaktivuje 2FA pro uživatele."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM user_totp WHERE username=?", (username,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"totp_disable: {e}")
            return False


def totp_verify(username: str, code: str) -> bool:
    """Ověří TOTP kód. Vrátí True pokud 2FA není aktivní nebo je kód správný."""
    record = totp_get(username)
    if not record or not record.get('enabled'):
        return True
    try:
        import pyotp
        return pyotp.TOTP(record['totp_secret']).verify(code, valid_window=1)
    except Exception as e:
        logger.error(f"totp_verify: {e}")
        return False


def get_resolution_time_stats(days: int = 30) -> list:
    """258: Průměrná doba řešení issue per plugin (z issue_history)."""
    try:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT plugin_name,
                       COUNT(*) as count,
                       AVG((julianday(resolved_at) - julianday(first_seen)) * 24) as avg_hours,
                       MIN((julianday(resolved_at) - julianday(first_seen)) * 24) as min_hours,
                       MAX((julianday(resolved_at) - julianday(first_seen)) * 24) as max_hours
                FROM issue_history
                WHERE resolved_at >= datetime('now', ?)
                  AND first_seen IS NOT NULL
                  AND plugin_name IS NOT NULL
                GROUP BY plugin_name
                ORDER BY avg_hours DESC
                LIMIT 20
            """, (f'-{days} days',)).fetchall()
        return [{"plugin": r[0], "count": r[1],
                 "avg_h": round(r[2] or 0, 1),
                 "min_h": round(r[3] or 0, 1),
                 "max_h": round(r[4] or 0, 1)} for r in rows]
    except Exception as e:
        logger.warning(f"get_resolution_time_stats: {e}")
        return []


def get_flapping_issues(days: int = 7, min_count: int = 3) -> list:
    """259: Top flapping issues — issues co se nejčastěji opakují v issue_history."""
    try:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT host, plugin_name, COUNT(*) as flap_count,
                       MAX(resolved_at) as last_resolved
                FROM issue_history
                WHERE resolved_at >= datetime('now', ?)
                  AND plugin_name IS NOT NULL
                GROUP BY host, plugin_name
                HAVING flap_count >= ?
                ORDER BY flap_count DESC
                LIMIT 20
            """, (f'-{days} days', min_count)).fetchall()
        return [{"host": r[0], "plugin": r[1],
                 "count": r[2], "last_resolved": r[3]} for r in rows]
    except Exception as e:
        logger.warning(f"get_flapping_issues: {e}")
        return []


def get_alert_fatigue_stats(days: int = 30) -> list:
    """260: Alert fatigue — pluginy s nejvíce FP."""
    try:
        with _get_conn() as conn:
            rows = conn.execute("""
                SELECT plugin_name, COUNT(*) as fp_count,
                       MAX(created_at) as last_fp
                FROM false_positive_patterns
                WHERE created_at >= datetime('now', ?)
                  AND plugin_name IS NOT NULL
                GROUP BY plugin_name
                ORDER BY fp_count DESC
                LIMIT 15
            """, (f'-{days} days',)).fetchall()
        return [{"plugin": r[0], "fp_count": r[1], "last_fp": r[2]} for r in rows]
    except Exception as e:
        logger.warning(f"get_alert_fatigue_stats: {e}")
        return []


def get_user_last_login(username: str) -> str | None:
    """262: Vrátí timestamp posledního přihlášení uživatele."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(last_seen) FROM active_sessions WHERE username=?",
                (username,)
            ).fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"get_user_last_login: {e}")
        return None

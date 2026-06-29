import logging
import threading
import sqlite3
import re
import secrets
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, g
from ..auth import requires_auth, int_param, _hw_sessions, _hw_sessions_lock, _hw_get_session
from .. import state, config, utils, actions

logger = logging.getLogger("sentinel.chat")

# 240: Validace hostname — povoleny jen bezpečné znaky
_HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$')

def _valid_hostname(h: str) -> bool:
    return bool(h and _HOSTNAME_RE.match(h) and '..' not in h)


def create_blueprint(service):
    bp = Blueprint('agents', __name__)

    @bp.route('/api/v1/issues', methods=['GET'])
    @requires_auth
    def api_v1_issues_json():
        """Nativní JSON endpoint pro Android aplikaci vracející surové incidenty z DB."""
        all_active = state.get_active_issues()

        # Odfiltrujeme ignorované klíče přesně jako u Web UI
        visible_active = [
            i for i in all_active
            if i.get('key') not in service.ignored_issues
            and (g.user_role in ['admin', 'superadmin'] or i.get('channel_type', '').lower() != 'root')
        ]

        # Vyčistíme objekty tak, aby přesně pasovaly do IssueModel.fromJson ve Flutteru
        payload = []
        for issue in visible_active:
            payload.append({
                "key": issue.get("key", ""),
                "status": issue.get("status", "active"),

                "channel_type": issue.get("channel_type", "infra"),
                "channelType": issue.get("channel_type", "infra"),

                "last_seen": issue.get("last_seen", ""),
                "lastSeen": issue.get("last_seen", ""),

                "missing_count": issue.get("missing_count", 0),
                "missingCount": issue.get("missing_count", 0),

                "host": issue.get("host", "Unknown"),
                "cluster": issue.get("cluster", "HOME"),

                "log_file": issue.get("plugin_name", "generic"),
                "logFile": issue.get("plugin_name", "generic"),

                "last_line": issue.get("last_line", ""),
                "lastLine": issue.get("last_line", ""),

                "severity": "CRITICAL" if issue.get("channel_type") in ['security', 'root'] else "WARNING"
            })

        return jsonify({"status": "ok", "issues": payload})

    @bp.route('/api/agents/list', methods=['GET'])
    @requires_auth
    def api_agents_list():
        """Returns JSON list of registered agents for the UI layout (tokens NEVER exposed)."""
        agents = state.get_all_agents()
        # Security: strip tokens before returning to frontend
        for agent in agents:
            agent.pop('token', None)
        return jsonify({"status": "ok", "agents": agents})

    @bp.route('/api/agents/register', methods=['POST'])
    @requires_auth
    def api_agents_register():
        """Generates a secure token and registers/updates an agent."""
        if g.user_role != 'superadmin':
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

        data = request.json or {}
        hostname = data.get('hostname', '').strip()
        web_ui_url = data.get('web_ui_url', '').strip()
        category = data.get('category', '').strip() or None
        if not hostname:
            return jsonify({"status": "error", "message": "Missing hostname"}), 400

        # Generate secure 32-byte alphanumeric token
        new_token = secrets.token_hex(32)
        if state.register_new_agent(hostname, new_token, category=category, web_ui_url=web_ui_url):
            return jsonify({"status": "ok", "token": new_token, "hostname": hostname})
        return jsonify({"status": "error", "message": "Database write failed"}), 500

    @bp.route('/api/agents/delete', methods=['POST'])
    @requires_auth
    def api_agents_delete():
        """Removes an agent entry from the control center."""
        if g.user_role != 'superadmin':
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

        data = request.json or {}
        hostname = data.get('hostname', '').strip()
        if state.delete_agent(hostname):
            return jsonify({"status": "ok"})
        return jsonify({"status": "error", "message": "Deletion failed"}), 500

    @bp.route('/api/agents/ignore_offline', methods=['POST'])
    @requires_auth
    def api_agents_ignore_offline():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        data = request.json or {}
        hostname = data.get('hostname', '').strip()
        ignore   = bool(data.get('ignore', False))
        if not hostname:
            return jsonify({"status": "error", "message": "Missing hostname"}), 400
        if state.set_agent_ignore_offline(hostname, ignore):
            return jsonify({"status": "ok", "hostname": hostname, "ignore_offline": ignore})
        return jsonify({"status": "error", "message": "Update failed"}), 500

    @bp.route('/api/agents/<hostname>/maintenance', methods=['POST'])
    @requires_auth
    def api_agent_set_maintenance(hostname):
        """Set/clear maintenance mode for an agent. Body: {minutes: N} or {clear: true}."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        body = request.get_json(silent=True) or {}
        if body.get('clear'):
            until_str = None
            minutes = 0
        else:
            minutes = int(body.get('minutes', 60))
            until_str = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute("UPDATE agents SET maintenance_until=? WHERE hostname=?", (until_str, hostname))
                    conn.commit()
                finally:
                    conn.close()
            # Notifikace při vstupu do maintenance
            if minutes > 0:
                _mnt_msg = f"🔧 Agent '{hostname}' vstupuje do maintenance na {minutes} min."
                threading.Thread(target=service._send_notification,
                                 args=("maintenance", "agent", hostname, _mnt_msg),
                                 daemon=True).start()
            return jsonify({"status": "ok", "hostname": hostname, "maintenance_until": until_str})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/agents/group/<group_name>/maintenance', methods=['POST'])
    @requires_auth
    def api_group_set_maintenance(group_name):
        """Set/clear maintenance for all agents in a group."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        body = request.get_json(silent=True) or {}
        if body.get('clear') or int(body.get('minutes', 60)) == 0:
            until_str = None
        else:
            minutes = int(body.get('minutes', 60))
            until_str = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute("UPDATE agents SET maintenance_until=? WHERE agent_group=?", (until_str, group_name))
                    affected = conn.execute("SELECT changes()").fetchone()[0]
                    conn.commit()
                finally:
                    conn.close()
            service.log_event("group_maintenance", f"group={group_name} minutes={body.get('minutes',0)}", user=g.username)
            return jsonify({"status": "ok", "group": group_name, "affected": affected, "maintenance_until": until_str})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/agents/<hostname>/group', methods=['POST'])
    @requires_auth
    def api_agent_set_group(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        group = (request.get_json(silent=True) or {}).get('group', '').strip() or None
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute("UPDATE agents SET agent_group=? WHERE hostname=?", (group, hostname))
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({"status": "ok", "hostname": hostname, "group": group})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/agents/detail', methods=['GET'])
    @requires_auth
    def api_agents_groups():
        """Returns distinct agent groups for filtering."""
        try:
            conn = state._get_conn()
            rows = conn.execute(
                "SELECT DISTINCT agent_group FROM agents WHERE agent_group IS NOT NULL ORDER BY agent_group"
            ).fetchall()
            conn.close()
            return jsonify({"groups": [r[0] for r in rows]})
        except Exception as e:
            return jsonify({"groups": [], "error": str(e)})

    @bp.route('/api/agents/<hostname>/detail', methods=['GET'])
    @requires_auth
    def api_agent_detail(hostname):
        agents = state.get_all_agents()
        agent = next((a for a in agents if a['hostname'] == hostname), None)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        agent.pop('token', None)

        # Active issue count + recent issues for this agent
        all_active = state.get_active_issues()
        agent_issues = [i for i in all_active if hostname in (i.get('host') or '')]
        recent = sorted(agent_issues, key=lambda i: i.get('last_seen', ''), reverse=True)[:10]

        # Resolved issues count (last 7 days)
        try:
            with state.db_lock:
                conn = state._get_conn()
                since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                row = conn.execute(
                    "SELECT COUNT(*) FROM problems WHERE host=? AND status='resolved' AND last_seen>=?",
                    (hostname, since)
                ).fetchone()
                resolved_7d = row[0] if row else 0
                conn.close()
        except Exception:
            resolved_7d = 0

        return jsonify({
            "status": "ok",
            "agent": agent,
            "active_issues": len(agent_issues),
            "resolved_7d": resolved_7d,
            "recent_issues": recent,
            "labels": state.get_agent_labels(hostname),
            "heartbeat_timeout": agent.get("heartbeat_timeout"),
        })

    @bp.route('/api/agents/<hostname>/notes', methods=['POST'])
    @requires_auth
    def api_agent_notes(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        data = request.get_json(silent=True) or {}
        notes = (data.get('notes') or '').strip()[:500]
        try:
            with state.db_lock:
                conn = state._get_conn()
                conn.execute("UPDATE agents SET notes=? WHERE hostname=?", (notes, hostname))
                conn.commit()
                conn.close()
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/agents/<hostname>/heartbeat-timeout', methods=['GET'])
    @requires_auth
    def api_agent_hb_timeout_get(hostname):
        with state.db_lock:
            conn = state._get_conn()
            row = conn.execute("SELECT heartbeat_timeout FROM agents WHERE hostname=?", (hostname,)).fetchone()
            conn.close()
        val = row[0] if row else None
        return jsonify({"hostname": hostname, "heartbeat_timeout": val,
                        "global_default": getattr(config, 'AGENT_HEARTBEAT_TIMEOUT', 180)})

    @bp.route('/api/agents/<hostname>/heartbeat-timeout', methods=['POST'])
    @requires_auth
    def api_agent_hb_timeout_set(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.get_json(silent=True) or {}
        val = d.get('timeout')  # None = reset to global default
        if val is not None:
            try:
                val = int(val)
                if not (30 <= val <= 86400):
                    return jsonify({"error": "timeout musí být 30–86400 sekund"}), 400
            except (ValueError, TypeError):
                return jsonify({"error": "Neplatná hodnota"}), 400
        with state.db_lock:
            conn = state._get_conn()
            conn.execute("UPDATE agents SET heartbeat_timeout=? WHERE hostname=?", (val, hostname))
            conn.commit()
            conn.close()
        return jsonify({"status": "ok", "hostname": hostname, "heartbeat_timeout": val})

    @bp.route('/api/agents/<hostname>/labels', methods=['GET'])
    @requires_auth
    def api_agent_labels_get(hostname):
        return jsonify({"labels": state.get_agent_labels(hostname)})

    @bp.route('/api/agents/<hostname>/labels', methods=['POST'])
    @requires_auth
    def api_agent_labels_set(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        data = request.get_json(silent=True) or {}
        labels = data.get('labels', {})
        if not isinstance(labels, dict):
            return jsonify({"error": "labels must be an object"}), 400
        # Sanitize: string keys and values, max 20 pairs, key/value max 64 chars
        clean = {str(k)[:64]: str(v)[:64] for k, v in list(labels.items())[:20]}
        ok = state.set_agent_labels(hostname, clean)
        return jsonify({"status": "ok" if ok else "error", "labels": clean})

    @bp.route('/api/agents/<hostname>/regenerate-token', methods=['POST'])
    @requires_auth
    def api_agent_regenerate_token(hostname):
        if g.user_role != 'superadmin':
            return jsonify({"error": "Superadmin only"}), 403
        new_token = secrets.token_hex(32)
        try:
            with state.db_lock:
                conn = state._get_conn()
                conn.execute("UPDATE agents SET token=? WHERE hostname=?", (new_token, hostname))
                conn.commit()
                conn.close()
            service.log_event("agent_token_regen", f"Token regenerated for {hostname}", user=g.username)
            return jsonify({"status": "ok", "token": new_token})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/agents/<hostname>/health_history', methods=['GET'])
    @requires_auth
    def api_agent_health_history(hostname):
        """144: Daily issue counts per agent for the last N days (used as health sparkline)."""
        days = min(int(request.args.get('days', 30)), 90)
        try:
            conn = state._get_conn()
            rows = conn.execute("""
                SELECT strftime('%Y-%m-%d', last_seen) as day, COUNT(*) as cnt
                FROM problems
                WHERE host=? AND last_seen >= datetime('now', ?)
                GROUP BY day
                UNION ALL
                SELECT strftime('%Y-%m-%d', resolved_at) as day, COUNT(*) as cnt
                FROM issue_history
                WHERE host=? AND resolved_at >= datetime('now', ?)
                GROUP BY day
            """, (hostname, f'-{days} days', hostname, f'-{days} days')).fetchall()
            conn.close()
            # Aggregate by day
            from collections import defaultdict as _dd
            from datetime import date as _date, timedelta as _td
            agg = _dd(int)
            for day, cnt in rows:
                if day: agg[day] += cnt
            # Fill missing days with 0
            today = _date.today()
            result = []
            for i in range(days - 1, -1, -1):
                d = (today - _td(days=i)).isoformat()
                result.append({'day': d, 'count': agg.get(d, 0)})
            return jsonify({"hostname": hostname, "history": result})
        except Exception as e:
            return jsonify({"hostname": hostname, "history": [], "error": str(e)})

    @bp.route('/api/agents/<hostname>/ping', methods=['POST'])
    @requires_auth
    def api_agent_ping(hostname):
        """143: Ping/port-check an agent IP from the Sentinel server."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        import socket as _sock, subprocess as _sp, time as _t
        # Get agent IP from DB
        conn = state._get_conn()
        row = conn.execute("SELECT ip FROM agents WHERE hostname=?", (hostname,)).fetchone()
        conn.close()
        ip = row[0] if row and row[0] else hostname
        results = {}
        # TCP port checks (fast, no root needed)
        for port, name in [(22, 'SSH'), (80, 'HTTP'), (443, 'HTTPS')]:
            try:
                t0 = _t.monotonic()
                s = _sock.create_connection((ip, port), timeout=2)
                rtt = round((_t.monotonic() - t0) * 1000, 1)
                s.close()
                results[name] = {'open': True, 'rtt_ms': rtt}
            except Exception:
                results[name] = {'open': False}
        # ICMP ping (may fail without root — best-effort)
        ping_ok = None
        try:
            r = _sp.run(['ping', '-c', '1', '-W', '2', ip],
                        capture_output=True, timeout=5)
            ping_ok = r.returncode == 0
        except Exception:
            pass
        return jsonify({"hostname": hostname, "ip": ip, "icmp": ping_ok, "ports": results})

    @bp.route('/api/agents/<hostname>/packages', methods=['POST'])
    @requires_auth
    def api_agent_packages(hostname):
        """146: Query installed packages via SSH (dpkg/rpm). Read-only, no allowlist check needed."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        filter_q = (request.json or {}).get('filter', '').strip().lower()

        # Try dpkg first, fallback to rpm
        cmd = (
            "dpkg-query -W -f='${Package}\\t${Version}\\n' 2>/dev/null | head -500 || "
            "rpm -qa --queryformat '%{NAME}\\t%{VERSION}-%{RELEASE}\\n' 2>/dev/null | head -500"
        )
        try:
            ok, out = actions.run_ssh_command_real(hostname, cmd)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        packages = []
        for line in (out or '').splitlines():
            parts = line.split('\t', 1)
            if len(parts) == 2:
                name, version = parts[0].strip(), parts[1].strip()
                if name and (not filter_q or filter_q in name.lower()):
                    packages.append({"name": name, "version": version})
        packages.sort(key=lambda p: p["name"])
        return jsonify({"hostname": hostname, "packages": packages, "total": len(packages), "ok": ok})

    @bp.route('/api/agents/<hostname>/issues', methods=['GET'])
    @requires_auth
    def api_agent_issues(hostname):
        issues = state.get_agent_issues(hostname)
        return jsonify({"hostname": hostname, "count": len(issues), "issues": issues})

    @bp.route('/api/agents/<hostname>/telemetry', methods=['GET'])
    @requires_auth
    def api_agent_telemetry(hostname):
        days = min(int(request.args.get('days', 3)), 30)
        try:
            conn = state._get_conn()
            rows = conn.execute(
                "SELECT timestamp, category, metric, value FROM telemetry "
                "WHERE (metric LIKE ? OR category LIKE ?) AND timestamp >= datetime('now',?) "
                "ORDER BY timestamp DESC LIMIT 500",
                (f'%{hostname}%', f'%{hostname}%', f'-{days} days')
            ).fetchall()
            conn.close()
            return jsonify({"hostname": hostname, "telemetry": [
                {"ts": r[0], "category": r[1], "metric": r[2], "value": r[3]} for r in rows
            ]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/agents/<hostname>/ssh_history', methods=['GET'])
    @requires_auth
    def api_agent_ssh_history(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        limit = min(int(request.args.get('limit', 30)), 100)
        return jsonify({"hostname": hostname, "history": state.get_ssh_history(hostname, limit)})

    @bp.route('/api/agents/<hostname>/ssh_history/<int:record_id>', methods=['GET'])
    @requires_auth
    def api_agent_ssh_record(hostname, record_id):
        """047: Vrátí úplný výstup jednoho SSH záznamu."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        with state.db_lock:
            conn = state._get_conn()
            row = conn.execute(
                "SELECT id, command, actor, executed_at, success, output FROM ssh_execute_log "
                "WHERE id=? AND hostname=?", (record_id, hostname)
            ).fetchone()
            conn.close()
        if not row:
            return jsonify({"error": "Záznam nenalezen"}), 404
        return jsonify({"id": row[0], "command": row[1], "actor": row[2],
                        "executed_at": row[3], "success": bool(row[4]), "output": row[5]})

    @bp.route('/api/agents/<hostname>/thresholds', methods=['GET'])
    @requires_auth
    def api_agent_thresholds_get(hostname):
        return jsonify({"thresholds": state.get_agent_thresholds(hostname)})

    @bp.route('/api/agents/<hostname>/thresholds', methods=['POST'])
    @requires_auth
    def api_agent_thresholds_add(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        ok = state.set_agent_threshold(
            hostname, d.get('metric_pattern', ''),
            above=d.get('above'), below=d.get('below'),
            channel=d.get('channel', 'agent'), created_by=g.username
        )
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/agents/thresholds/<int:tid>', methods=['DELETE'])
    @requires_auth
    def api_agent_thresholds_delete(tid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_agent_threshold(tid)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/agents/<hostname>/config', methods=['POST'])
    @requires_auth
    def api_agent_config_push(hostname):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        cfg = request.json or {}
        if not cfg:
            return jsonify({"error": "Prázdná konfigurace"}), 400
        ok = state.push_agent_config(hostname, cfg)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/agents/compare', methods=['GET'])
    @requires_auth
    def api_agents_compare():
        """040: Vrátí telemetrii dvou agentů pro srovnávací view."""
        a = request.args.get('a', '').strip()
        b = request.args.get('b', '').strip()
        days = min(int(request.args.get('days', 3)), 30)
        if not a or not b:
            return jsonify({"error": "Parametry a= a b= jsou povinné"}), 400
        try:
            conn = state._get_conn()
            result = {}
            for host in (a, b):
                rows = conn.execute(
                    "SELECT metric, timestamp, value FROM telemetry "
                    "WHERE (metric LIKE ? OR category LIKE ?) "
                    "AND timestamp >= datetime('now', ?) "
                    "ORDER BY metric, timestamp ASC",
                    (f'%{host}%', f'%{host}%', f'-{days} days')
                ).fetchall()
                # Grupuj per metrika
                metrics = {}
                for metric, ts, val in rows:
                    metrics.setdefault(metric, []).append({"ts": ts, "v": val})
                result[host] = metrics
            conn.close()
            # Najdi společné metriky
            common = set(result.get(a, {}).keys()) & set(result.get(b, {}).keys())
            return jsonify({"agent_a": a, "agent_b": b, "days": days,
                            "data": result, "common_metrics": sorted(common)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/agents/health', methods=['GET'])
    @requires_auth
    def api_agents_health():
        return jsonify({"agents": state.get_agent_health()})

    @bp.route('/api/agents/<hostname>/health-score-legacy', methods=['GET'])
    @requires_auth
    def api_agent_health_score_legacy(hostname):
        """039: Vrátí health score + breakdown pro jednoho agenta (legacy — viz /health_score)."""
        agents = state.get_agent_health()
        ag = next((a for a in agents if a['hostname'] == hostname), None)
        if not ag:
            return jsonify({"error": "Agent not found"}), 404
        score = ag.get('health_score', 0)
        breakdown = {
            "status": ag.get('status'),
            "lag_ms": ag.get('last_data_lag_ms'),
            "alerts_24h": ag.get('alerts_24h', 0),
            "alerts_7d": ag.get('alerts_7d', 0),
            "maintenance": bool(ag.get('maintenance_until')),
        }
        grade = "A" if score >= 80 else ("B" if score >= 60 else ("C" if score >= 40 else "D"))
        return jsonify({"hostname": hostname, "score": score, "grade": grade, "breakdown": breakdown})

    # --- SENTINEL-ALERT NETWORK ---

    @bp.route('/api/sentinel-alerts/list', methods=['GET'])
    @requires_auth
    def api_sentinel_alerts_list():
        """List all sentinel-alert agents and their status."""
        agents_data = []
        try:
            logger.debug("api_sentinel_alerts_list: starting")
            with state.db_lock:
                conn = state._get_conn()
                try:
                    logger.debug("api_sentinel_alerts_list: db connected")
                    c = conn.execute(
                        "SELECT hostname, status, last_seen, token, ignore_offline, notes FROM agents WHERE category='alert' ORDER BY hostname"
                    )
                    rows = c.fetchall()
                    logger.debug(f"api_sentinel_alerts_list: found {len(rows)} agents")
                    for hostname, db_status, last_seen, token, ignore_offline, notes in rows:
                        online = False
                        if db_status == 'ONLINE' and last_seen:
                            try:
                                clean = last_seen.replace('Z', '+00:00')
                                dt = datetime.fromisoformat(clean)
                                delta = (datetime.now(timezone.utc) - dt).total_seconds()
                                online = delta <= 180
                            except Exception:
                                pass
                        c2 = conn.execute(
                            "SELECT COUNT(*) FROM problems WHERE key LIKE ? AND status IN ('active', 'validating')",
                            (f"AGENT|{hostname}|%",)
                        )
                        cnt = c2.fetchone()
                        active_issues = cnt[0] if cnt else 0
                        agents_data.append({
                            "hostname":       hostname,
                            "online":         online,
                            "last_seen":      last_seen,
                            "active_issues":  active_issues,
                            "has_token":      bool(token),
                            "ignore_offline": bool(ignore_offline),
                            "web_ui_url":     notes or '',
                        })
                finally:
                    conn.close()
            logger.debug(f"api_sentinel_alerts_list: returning {len(agents_data)} agents")
        except Exception as e:
            logger.exception(f"sentinel-alerts list error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

        ingest_url = request.host_url.rstrip('/') + "/api/v1/agent/ingest"
        return jsonify({
            "status": "ok",
            "agents": agents_data,
            "ingest_url": ingest_url
        })

    @bp.route('/api/sentinel-alert/<hostname>/revoke-token', methods=['POST'])
    @requires_auth
    def revoke_sentinel_alert_token(hostname):
        """Regenerate token for a sentinel-alert agent (old token immediately invalid)."""
        if g.user_role != 'superadmin':
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        if not (hostname.startswith('sentinel-alert') or hostname == 'sentinel-alert'):
            return jsonify({"status": "error", "message": "Invalid hostname"}), 400
        try:
            new_token = secrets.token_hex(32)
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute("UPDATE agents SET token = ? WHERE hostname = ?", (new_token, hostname))
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({"status": "ok", "token": new_token})
        except Exception as e:
            logger.error(f"revoke token error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/sentinel-alert/<hostname>/set-url', methods=['POST'])
    @requires_auth
    def set_sentinel_alert_url(hostname):
        """Update web_ui_url (stored in notes) for a sentinel-alert agent."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        data = request.json or {}
        url = (data.get('url') or '').strip()
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute("UPDATE agents SET notes = ? WHERE hostname = ? AND category = 'alert'", (url, hostname))
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    # --- SENTINEL HW DEVICES ---

    @bp.route('/api/sentinel-hw/list', methods=['GET'])
    @requires_auth
    def api_sentinel_hw_list():
        """List all registered Sentinel HW devices (hostname prefix sentinel-hw-)."""
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.row_factory = sqlite3.Row
                    c = conn.execute(
                        "SELECT hostname, status, last_seen, token, notes, ignore_offline FROM agents "
                        "WHERE category='hw' ORDER BY hostname"
                    )
                    rows = c.fetchall()
                finally:
                    conn.close()

            devices = []
            for row in rows:
                last = row['last_seen'] or ''
                active_issues = 0
                try:
                    with state.db_lock:
                        conn2 = state._get_conn()
                        try:
                            c2 = conn2.execute(
                                "SELECT COUNT(*) FROM problems WHERE status='active' AND key LIKE ?",
                                (f'%{row["hostname"]}%',)
                            )
                            active_issues = c2.fetchone()[0]
                        finally:
                            conn2.close()
                except Exception:
                    pass
                devices.append({
                    'hostname':       row['hostname'],
                    'status':         row['status'] or 'UNKNOWN',
                    'online':         (row['status'] or '') == 'ONLINE',
                    'last_seen':      last,
                    'active_issues':  active_issues,
                    'has_token':      bool(row['token']),
                    'web_ui_url':     row['notes'] or '',
                    'ignore_offline': bool(row['ignore_offline']),
                })

            return jsonify({'status': 'ok', 'devices': devices})
        except Exception as e:
            logger.exception(f"sentinel-hw list error: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @bp.route('/api/sentinel-hw/register', methods=['POST'])
    @requires_auth
    def api_sentinel_hw_register():
        """Register a new Sentinel HW device. Stores web_ui_url in notes field."""
        if g.user_role != 'superadmin':
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        data = request.json or {}
        hostname = (data.get('hostname') or '').strip()
        web_ui_url = (data.get('web_ui_url') or '').strip()
        if not hostname:
            return jsonify({'status': 'error', 'message': 'hostname required'}), 400
        try:
            token = secrets.token_hex(32)
            now = datetime.utcnow().isoformat()
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute(
                        "INSERT INTO agents (hostname, token, registered_at, last_seen, status, notes, category) "
                        "VALUES (?, ?, ?, ?, 'ONLINE', ?, 'hw') "
                        "ON CONFLICT(hostname) DO UPDATE SET token=excluded.token, notes=excluded.notes, category='hw'",
                        (hostname, token, now, now, web_ui_url)
                    )
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({'status': 'ok', 'hostname': hostname, 'token': token})
        except Exception as e:
            logger.exception(f"sentinel-hw register error: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @bp.route('/api/sentinel-hw/<hostname>/revoke-token', methods=['POST'])
    @requires_auth
    def api_sentinel_hw_revoke_token(hostname):
        if g.user_role != 'superadmin':
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        try:
            new_token = secrets.token_hex(32)
            with state.db_lock:
                conn = state._get_conn()
                try:
                    # Verify hostname is a registered hw device
                    if not conn.execute("SELECT 1 FROM agents WHERE hostname=? AND category='hw'", (hostname,)).fetchone():
                        return jsonify({'status': 'error', 'message': 'Invalid hostname'}), 400
                    conn.execute("UPDATE agents SET token = ? WHERE hostname = ?", (new_token, hostname))
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({'status': 'ok', 'token': new_token})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @bp.route('/api/sentinel-hw/<hostname>/live', methods=['GET'])
    @requires_auth
    def api_sentinel_hw_live(hostname):
        """Proxy /api/live from the HW device's web_ui_url to avoid browser CORS issues."""
        import requests as _requests
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    row = conn.execute(
                        "SELECT notes FROM agents WHERE hostname = ? AND category = 'hw'", (hostname,)
                    ).fetchone()
                finally:
                    conn.close()
            if row is None:
                return jsonify({'status': 'error', 'message': 'Invalid hostname'}), 400
            if not row or not row[0]:
                return jsonify({'status': 'error', 'message': 'No web_ui_url configured'}), 404
            web_ui_url = row[0].rstrip('/')

            with _hw_sessions_lock:
                sess = _hw_sessions.get(hostname)

            if sess is None:
                sess = _hw_get_session(web_ui_url, hostname)
                with _hw_sessions_lock:
                    _hw_sessions[hostname] = sess

            r = sess.get(f"{web_ui_url}/api/live", timeout=5)
            data = r.json()
            if data.get('error') == 'not logged in' or r.status_code == 401:
                # Session expired — re-login once
                sess = _hw_get_session(web_ui_url, hostname)
                with _hw_sessions_lock:
                    _hw_sessions[hostname] = sess
                r = sess.get(f"{web_ui_url}/api/live", timeout=5)
                data = r.json()
            return jsonify(data)
        except _requests.exceptions.Timeout:
            return jsonify({'status': 'error', 'message': 'timeout'}), 504
        except _requests.exceptions.ConnectionError as e:
            return jsonify({'status': 'error', 'message': f'unreachable: {e}'}), 502
        except Exception as e:
            logger.error(f"sentinel-hw live proxy error: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @bp.route('/api/sentinel-hw/<hostname>/delete', methods=['POST'])
    @requires_auth
    def api_sentinel_hw_delete(hostname):
        if g.user_role != 'superadmin':
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        if not hostname.startswith('sentinel-hw-'):
            return jsonify({'status': 'error', 'message': 'Invalid hostname'}), 400
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute("DELETE FROM agents WHERE hostname = ?", (hostname,))
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    # --- HAILO OLLAMA MODEL SWITCHER ---

    @bp.route('/api/hailo-ollama/status', methods=['GET'])
    @requires_auth
    def api_hailo_ollama_status():
        import requests as _requests
        import os
        enabled = config.HAILO_OLLAMA_ENABLED
        available = []
        reachable = False
        if enabled:
            try:
                base = config.HAILO_OLLAMA_URL.replace('/v1/chat/completions', '').replace('/api/generate', '')
                r = _requests.get(f"{base}/api/tags", timeout=4)
                if r.ok:
                    available = [m['name'] for m in r.json().get('models', [])]
                    reachable = True
            except Exception:
                pass
        return jsonify({
            'enabled': enabled,
            'model': config.HAILO_OLLAMA_MODEL,
            'url': config.HAILO_OLLAMA_URL,
            'available_models': available,
            'reachable': reachable,
            'npu_active': (os.path.exists('/dev/hailo0') or os.path.exists('/sys/module/hailo1x_pci')),
        })

    @bp.route('/api/hailo-ollama/model', methods=['POST'])
    @requires_auth
    def api_hailo_ollama_set_model():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        model = (request.json or {}).get('model', '').strip()
        if not model:
            return jsonify({'status': 'error', 'message': 'model required'}), 400
        config.HAILO_OLLAMA_MODEL = model
        logger.info(f"hailo-ollama model switched to: {model}")
        # Persist to config.yaml so the change survives restart
        try:
            cfg_path = str(config.CONFIG_PATH)
            with open(cfg_path) as f:
                raw = f.read()
            import re as _re
            # Replace the model line inside the hailo_ollama block
            raw = _re.sub(
                r'(hailo_ollama:(?:\n[ \t]+\S[^\n]*)*?\n[ \t]+model:[ \t]*)[^\n]+',
                lambda m: m.group(1) + model,
                raw, count=1
            )
            with open(cfg_path, 'w') as f:
                f.write(raw)
        except Exception as e:
            logger.warning(f"Failed to persist model to config: {e}")
        return jsonify({'status': 'ok', 'model': model})

    # --- LIVE AGENT INGEST API (Called by external daemons) ---

    @bp.route('/api/v1/agent/ingest', methods=['POST'])
    def agent_ingest_payload():
        try:
            client_ip = request.remote_addr
            if not utils.security.check_rate_limit(client_ip, 'ingest'):
                return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429

            token = request.headers.get('Authorization', '')
            if token.startswith('Bearer '):
                token = token[7:]

            try:
                data = request.get_json(silent=True) or {}
            except Exception:
                data = {}
            if not isinstance(data, dict):
                return jsonify({"status": "error", "message": "Invalid payload"}), 400

            hostname = (data.get("hostname") or "").strip()
            if not hostname or not token:
                return jsonify({"status": "unauthorized"}), 401

            # Auto-registration pokud token odpovídá AUTO_REGISTER_TOKEN
            _auto_reg_token = getattr(config, 'AUTO_REGISTER_TOKEN', '')
            if _auto_reg_token and token == _auto_reg_token:
                existing = state.get_all_agents()
                if not any(a['hostname'] == hostname for a in existing):
                    new_token = secrets.token_hex(32)
                    state.register_new_agent(hostname, new_token)
                    logger.info(f"[auto-register] Agent '{hostname}' auto-registrován")
                # Po auto-registraci použít uložený token
                token = state._get_conn().execute(
                    "SELECT token FROM agents WHERE hostname=?", (hostname,)
                ).fetchone()
                if token: token = token[0]
                else: return jsonify({"status": "unauthorized"}), 401

            if not state.verify_agent_token(hostname, token):
                logger.warning(f"[-] Neautorizovaný pokus o přístup agenta: {hostname}")
                return jsonify({"status": "unauthorized"}), 401

            # --- AKTUALIZACE HEARTBEATU AGENTA (Logujeme pouze PRVNÍ připojení) ---
            try:
                with state.db_lock:
                    conn = state._get_conn()
                    try:
                        c_status = conn.execute("SELECT status FROM agents WHERE hostname = ?", (hostname,)).fetchone()
                        was_online = c_status and c_status[0] == 'ONLINE'

                        now_str = datetime.now(timezone.utc).isoformat()
                        conn.execute("UPDATE agents SET last_seen = ?, status = 'ONLINE' WHERE hostname = ?", (now_str, hostname))

                        # Zaloguje se POUZE pokud byl agent předtím offline (první spojení)
                        if not was_online:
                            logger.info(f"[+] Agent '{hostname}' se úspěšně PŘIPOJIL a je ONLINE.")
                    finally:
                        conn.close()
            except Exception as hb_err:
                logger.error(f"Chyba při aktualizaci heartbeatu pro {hostname}: {hb_err}")

            state.update_agent_ip(hostname, request.remote_addr)

            # Vypočítat data lag (ms) pokud agent posílá timestamp vzniku dat
            try:
                _dt = data.get('data_timestamp') or data.get('timestamp')
                if _dt:
                    _agent_ts = datetime.fromisoformat(str(_dt).replace('Z', '+00:00'))
                    _now_ts = datetime.now(timezone.utc)
                    if _agent_ts.tzinfo is None:
                        _agent_ts = _agent_ts.replace(tzinfo=timezone.utc)
                    _lag_ms = int((_now_ts - _agent_ts).total_seconds() * 1000)
                    if 0 <= _lag_ms < 86400000:  # sanity: max 24h
                        state.update_agent_lag(hostname, _lag_ms)
            except Exception:
                pass

            # Zachytit verzi agenta z payload (top-level nebo agent_core_updater event)
            try:
                _ver = (data.get('version') or data.get('agent_sha') or '').strip()
                if not _ver:
                    for _ev in (data.get("events", []) or []):
                        _plug = _ev.get("plugin", "").lower()
                        if _plug == 'agent_core_updater':
                            _m = re.search(r'[a-f0-9]{7,40}', _ev.get("message", ""))
                            if _m:
                                _ver = _m.group(0)
                                break
                if _ver:
                    with state.db_lock:
                        _vc = state._get_conn()
                        _vc.execute("UPDATE agents SET agent_version=? WHERE hostname=?", (_ver[:40], hostname))
                        _vc.commit()
                        _vc.close()
            except Exception:
                pass

            # Kontrola maintenance mode — pokud aktivní, přeskočit ukládání alertů
            _in_maintenance = False
            try:
                with state.db_lock:
                    _mc = state._get_conn()
                    _mrow = _mc.execute("SELECT maintenance_until FROM agents WHERE hostname=?", (hostname,)).fetchone()
                    _mc.close()
                if _mrow and _mrow[0]:
                    _mu = datetime.fromisoformat(_mrow[0])
                    if _mu.tzinfo is None:
                        _mu = _mu.replace(tzinfo=timezone.utc)
                    _in_maintenance = _mu > datetime.now(timezone.utc)
            except Exception:
                pass

            # 141 — process optional raw metrics from agent payload
            _agent_metrics = data.get("metrics")
            if isinstance(_agent_metrics, dict) and _agent_metrics:
                try:
                    state.save_telemetry_snapshot(hostname, _agent_metrics)
                    state.check_agent_thresholds(hostname, _agent_metrics)
                except Exception as _me:
                    logger.error(f"agent metrics processing error ({hostname}): {_me}")

            events_list = data.get("events", []) or data.get("alerts", [])

            for alert in events_list:
                p_check = alert.get("plugin", alert.get("check_name", "")).lower()
                status = alert.get("status", "active")
                msg_text = alert.get("message", "")

                # Určení vizuálního kanálu — exact whitelist, ne substring
                SECURITY_PLUGINS = {
                    "port_security", "vulnerability_scan", "fail2ban", "fail2ban_honeypot", "sentinel_alert_ping",
                    "agent_security_vulnerability_scan", "agent_security_firewall_fail2ban",
                }
                ROOT_PLUGINS = {"root_monitor", "agent_security_root_monitor"}
                if p_check in ROOT_PLUGINS:
                    assigned_channel = 'root'
                elif p_check.startswith('sentinel_alert_') or p_check in SECURITY_PLUGINS:
                    assigned_channel = 'security'
                else:
                    assigned_channel = 'agent'

                # --- FILTR LOGOVÁNÍ: Ignorujeme stavy OK a RESOLVED, logujeme pouze SKUTEČNÉ ISSUE ---
                if status.lower() not in ["ok", "resolved"]:
                    logger.info(f"[!] Agent '{hostname}' hlásí ISSUE -> [{assigned_channel.upper()}] | Plugin: {p_check} | Status: {status} | Msg: {msg_text}")

                # --- ROOT AUDIT ZÁPIS ---
                try:
                    if assigned_channel == 'root':
                        with state.db_lock:
                            conn = state._get_conn()
                            try:
                                now = datetime.now(timezone.utc).isoformat()
                                is_active = (status.lower() != "ok" and status.lower() != "resolved")

                                if is_active:
                                    sessions = msg_text.split(" | ")
                                    conn.execute("UPDATE root_audit SET disconnected_at = ?, is_active = 0 WHERE server = ? AND is_active = 1", (now, hostname))

                                    for s_msg in sessions:
                                        # Prefer valid IPv4, then hostname (letter-led), reject timestamps
                                        _ip = "Neznámá IP"
                                        _m = re.search(r'from (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', s_msg)
                                        if _m:
                                            _ip = _m.group(1)
                                        else:
                                            _m = re.search(r'from ([a-zA-Z][\w\.\-]*)', s_msg)
                                            if _m and not _m.group(1).startswith('tmux'):
                                                _ip = _m.group(1)
                                        conn.execute("INSERT INTO root_audit (server, ip, connected_at, is_active) VALUES (?, ?, ?, 1)", (hostname, _ip, now))
                                else:
                                    conn.execute("UPDATE root_audit SET disconnected_at = ?, is_active = 0 WHERE server = ? AND is_active = 1", (now, hostname))
                            finally:
                                conn.close()
                except Exception as audit_err:
                    logger.error(f"Chyba v root auditu: {audit_err}")

                # --- ULOŽENÍ NEBO VYŘEŠENÍ INCIDENTU ---
                unique_key = f"AGENT|{hostname}|{p_check}"

                if _in_maintenance and status.lower() not in ["ok", "resolved"]:
                    continue  # Maintenance mode — přeskočit uložení alertu

                if status.lower() in ["ok", "resolved"]:
                    state.mark_resolved(unique_key)
                    if assigned_channel == 'security':
                        threading.Thread(
                            target=service._send_notification,
                            args=(unique_key + "|resolved", assigned_channel, hostname,
                                  f"✅ VYŘEŠENO [{p_check.upper()}] {hostname}: {msg_text}"),
                            daemon=True
                        ).start()
                else:
                    incident_payload = {
                        "status": status,
                        "channel_type": assigned_channel,
                        "host": hostname,
                        "last_line": msg_text,
                        "plugin_name": p_check,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "details": alert
                    }
                    is_new = state.save_problem(unique_key, incident_payload)
                    if is_new:
                        actions.maybe_suggest_remediation(unique_key, incident_payload)
                        if assigned_channel in ('security', 'root', 'clusters'):
                            threading.Thread(
                                target=service._send_notification,
                                args=(unique_key, assigned_channel, hostname, msg_text),
                                daemon=True
                            ).start()

                # Živé odeslání socketu do UI
                try:
                    service.socketio.emit('new_alert', {
                        "key": unique_key,
                        "channel": assigned_channel,
                        "status": status
                    })
                except Exception: pass

            # Auto-resolve issues no longer reported by this agent
            current_keys = {
                f"AGENT|{hostname}|{e.get('plugin', e.get('check_name', '')).lower()}"
                for e in events_list
                if e.get('status', 'active').lower() not in ['ok', 'resolved']
            }
            resolved_keys = state.reconcile_agent_issues(hostname, current_keys)
            for rkey in resolved_keys:
                try:
                    service.socketio.emit('issue_resolved', {"key": rkey, "auto": True})
                except Exception: pass
                # Notify on auto-resolved security issues
                try:
                    _rch = rkey.split('|')[2] if rkey.count('|') >= 2 else ''
                    if not _rch:
                        _rc = state._get_conn()
                        _rrow = _rc.execute("SELECT channel_type FROM problems WHERE key=?", (rkey,)).fetchone()
                        _rc.close()
                        _rch = (_rrow[0] if _rrow else '').lower()
                    if _rch == 'security':
                        threading.Thread(
                            target=service._send_notification,
                            args=(rkey + "|resolved", 'security', hostname,
                                  f"✅ VYŘEŠENO [auto] {hostname}: {rkey.split('|')[1] if '|' in rkey else rkey}"),
                            daemon=True
                        ).start()
                except Exception: pass

            pending_cfg = state.get_pending_agent_config(hostname)
            resp = {"status": "success", "processed": len(events_list)}
            if pending_cfg:
                resp["config_update"] = pending_cfg
            return jsonify(resp), 200

        except Exception as global_err:
            logger.error(f"Kritická chyba v ingest endpointu: {global_err}")
            return jsonify({"status": "error", "message": str(global_err)}), 500

    # ── Network Topology (120) ────────────────────────────────────────────────

    @bp.route('/api/topology/data', methods=['GET'])
    @requires_auth
    def api_topology_data():
        """Vrátí topologická data (nodes + edges) pro vizualizaci."""
        import json as _json
        from .. import topology as _topo
        with state.db_lock:
            conn = state._get_conn()
            try:
                rows = conn.execute(
                    "SELECT hostname, status, ip_addresses, agent_group, ignore_offline FROM agents"
                ).fetchall()
            finally:
                conn.close()
        agents = [{"hostname": r[0], "status": r[1], "ip_addresses": r[2], "agent_group": r[3]} for r in rows]
        result = _topo.build_topology(agents, config.TOPOLOGY_CFG)
        return jsonify(result)

    # ── Geo Map (118) ─────────────────────────────────────────────────────────
    _geo_cache = {}  # ip → {lat, lon, country, city, ts}

    @bp.route('/api/agents/geomap', methods=['GET'])
    @requires_auth
    def api_agents_geomap():
        """Vrátí geo pozice agentů dle jejich IP adres."""
        import json as _json, time as _time, ipaddress as _ip, urllib.request as _ur
        PRIV_RANGES = [_ip.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','169.254.0.0/16','::1/128','fc00::/7')]

        def _is_private(addr):
            try:
                a = _ip.ip_address(addr.split(':')[0])
                return any(a in net for net in PRIV_RANGES)
            except Exception:
                return True

        def _geoip(ip):
            now = _time.time()
            if ip in _geo_cache and now - _geo_cache[ip].get('ts', 0) < 3600:
                return _geo_cache[ip]
            try:
                with _ur.urlopen(f'http://ip-api.com/json/{ip}?fields=status,country,countryCode,city,lat,lon', timeout=4) as resp:
                    d = _json.loads(resp.read())
                if d.get('status') == 'success':
                    result = {'lat': d['lat'], 'lon': d['lon'], 'country': d.get('country',''), 'city': d.get('city',''), 'code': d.get('countryCode',''), 'ts': now}
                    _geo_cache[ip] = result
                    return result
            except Exception:
                pass
            return None

        with state.db_lock:
            conn = state._get_conn()
            try:
                rows = conn.execute(
                    "SELECT hostname, status, ip_addresses, ignore_offline FROM agents ORDER BY status DESC"
                ).fetchall()
            finally:
                conn.close()

        results = []
        for hostname, status, ip_json, ignore_offline in rows:
            try:
                ips = _json.loads(ip_json or '[]')
            except Exception:
                ips = []
            public_ips = [ip for ip in ips if not _is_private(ip)]
            priv_ips = [ip for ip in ips if _is_private(ip)]
            geo = None
            used_ip = None
            for ip in public_ips:
                geo = _geoip(ip)
                if geo:
                    used_ip = ip
                    break
            results.append({
                'hostname': hostname,
                'status': status,
                'ip': used_ip or (ips[0] if ips else ''),
                'private': not bool(public_ips),
                'geo': geo,
                'ignore_offline': bool(ignore_offline),
            })

        return jsonify({'agents': results})

    # ── 373: Agent ingest bulk endpoint ─────────────────────────────────────────

    @bp.route('/api/v1/ingest/bulk', methods=['POST'])
    def agent_ingest_bulk():
        """373: Accept an array of alert payloads in one request.

        Body: {"alerts": [{hostname, token, events:[...]}, ...]}
        Returns per-item status.
        """
        client_ip = get_real_ip()
        if not utils.security.check_rate_limit(client_ip, 'ingest'):
            return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429
        try:
            body = request.get_json(silent=True) or {}
        except Exception:
            body = {}
        alerts_list = body.get("alerts", [])
        if not isinstance(alerts_list, list) or not alerts_list:
            return jsonify({"status": "error", "message": "alerts array required"}), 400
        if len(alerts_list) > 100:
            return jsonify({"status": "error", "message": "max 100 items per bulk call"}), 400

        results = []
        for item in alerts_list:
            if not isinstance(item, dict):
                results.append({"status": "error", "message": "invalid item"})
                continue
            hostname = (item.get("hostname") or "").strip()
            token = (item.get("token") or "").strip()
            if not hostname or not token:
                results.append({"hostname": hostname, "status": "unauthorized"})
                continue
            if not _valid_hostname(hostname):
                results.append({"hostname": hostname, "status": "error", "message": "invalid hostname"})
                continue
            if not state.verify_agent_token(hostname, token):
                results.append({"hostname": hostname, "status": "unauthorized"})
                continue
            # Update heartbeat
            try:
                with state.db_lock:
                    _c = state._get_conn()
                    _c.execute("UPDATE agents SET last_seen=?, status='ONLINE' WHERE hostname=?",
                               (datetime.now(timezone.utc).isoformat(), hostname))
                    _c.commit()
                    _c.close()
            except Exception:
                pass
            # Process events
            events_list = item.get("events", []) or item.get("alerts", [])
            processed = 0
            for alert in events_list:
                if not isinstance(alert, dict):
                    continue
                p_check = alert.get("plugin", alert.get("check_name", "")).lower()
                status_str = alert.get("status", "active")
                msg_text = alert.get("message", "")
                SECURITY_PLUGINS = {"port_security", "vulnerability_scan", "fail2ban"}
                ROOT_PLUGINS = {"root_monitor", "agent_security_root_monitor"}
                if p_check in ROOT_PLUGINS:
                    assigned_channel = 'root'
                elif p_check in SECURITY_PLUGINS:
                    assigned_channel = 'security'
                else:
                    assigned_channel = 'agent'
                issue_key = f"AGENT|{hostname}|{p_check}"
                if status_str.lower() in ("ok", "resolved"):
                    state.resolve_problem(issue_key)
                else:
                    state.save_problem(issue_key, {
                        "status": "active",
                        "channel_type": assigned_channel,
                        "host": hostname,
                        "last_line": msg_text,
                        "plugin_name": p_check,
                        "last_seen": datetime.now(timezone.utc).isoformat(),
                        "missing_count": 0,
                    })
                processed += 1
            results.append({"hostname": hostname, "status": "ok", "processed": processed})
        return jsonify({"status": "ok", "results": results, "count": len(results)})

    # ── 351: Agent token bulk rotation ──────────────────────────────────────────

    @bp.route('/api/agents/rotate_all_tokens', methods=['POST'])
    @requires_auth
    def api_agents_rotate_all_tokens():
        """351: Rotate tokens for all registered agents at once."""
        if g.user_role != 'superadmin':
            return jsonify({"error": "Superadmin only"}), 403
        try:
            conn = state._get_conn()
            agents = conn.execute("SELECT hostname FROM agents").fetchall()
            conn.close()
            rotated = []
            for (hostname,) in agents:
                new_token = secrets.token_hex(32)
                with state.db_lock:
                    _c = state._get_conn()
                    _c.execute("UPDATE agents SET token=? WHERE hostname=?", (new_token, hostname))
                    _c.commit()
                    _c.close()
                rotated.append({"hostname": hostname, "token": new_token})
            service.log_event("agent_bulk_token_rotate",
                              f"Rotated tokens for {len(rotated)} agents", user=g.username)
            return jsonify({"status": "ok", "rotated": rotated, "count": len(rotated)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 398: Composite health score per host ─────────────────────────────────────

    @bp.route('/api/agents/<hostname>/health_score', methods=['GET'])
    @requires_auth
    def api_agent_health_score(hostname):
        """398: Composite health score for a host (0-100)."""
        if not _valid_hostname(hostname):
            return jsonify({"error": "Invalid hostname"}), 400
        try:
            conn = state._get_conn()
            agent = conn.execute(
                "SELECT status, last_seen, last_data_lag_ms FROM agents WHERE hostname=?",
                (hostname,)
            ).fetchone()
            active_issues = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN channel_type='security' THEN 3 WHEN channel_type='root' THEN 3 ELSE 1 END) FROM problems WHERE host=? AND status='active'",
                (hostname,)
            ).fetchone()
            conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        status, last_seen, lag_ms = agent
        issue_count = active_issues[0] or 0
        issue_weight = active_issues[1] or 0

        score = 100
        # Deduct for offline
        if status != 'ONLINE':
            score -= 50
        # Deduct for data lag
        if lag_ms and lag_ms > 5000:
            score -= min(20, int(lag_ms / 1000))
        # Deduct for active issues (weighted by severity)
        score -= min(40, issue_weight * 5)
        score = max(0, score)

        grade = "A" if score >= 90 else ("B" if score >= 70 else ("C" if score >= 50 else "D"))
        return jsonify({
            "hostname": hostname,
            "score": score,
            "grade": grade,
            "status": status,
            "active_issues": issue_count,
            "lag_ms": lag_ms or 0,
        })

    return bp

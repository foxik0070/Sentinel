import logging
import threading
import os
import re
import json
import sqlite3
import subprocess
import yaml
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g, Response, session
from ..auth import requires_auth, int_param, _REVOKED_SESSIONS, global_active_clients, global_active_clients_lock
from .. import state, config, rag, analytics, utils

logger = logging.getLogger("sentinel.chat")


def create_blueprint(service):
    bp = Blueprint('system', __name__)

    @bp.route('/api/sys_monitor_html')
    @requires_auth
    def sys_monitor_html():
        return jsonify({"html": service.render_sys_monitor_html(g.user_role)})

    @bp.route('/api/metrics', methods=['GET'])
    @requires_auth
    def metrics_endpoint():
        import time
        m = service.metrics
        avg_lat = sum(m["ai_latency_history"]) / len(m["ai_latency_history"]) if m["ai_latency_history"] else 0
        now = time.time()
        with global_active_clients_lock:
            stale_keys = [k for k, cdata in global_active_clients.items() if now - cdata["last_seen"] > 120]
            for k in stale_keys:
                del global_active_clients[k]

            snapshot = list(global_active_clients.values())

        clients_payload = []
        for cdata in snapshot:
            is_tunnel = cdata["ip"] in ('127.0.0.1', 'localhost', '::1')
            display_ip = 'SSH tunel' if is_tunnel else cdata["ip"]
            clients_payload.append({
                "user": cdata["user"],
                "ip": display_ip,
                "device_id": cdata["device_id"],
                "connected_since": datetime.fromtimestamp(cdata["connected_since"]).strftime('%d.%m.%Y %H:%M:%S'),
                "last_seen": datetime.fromtimestamp(cdata["last_seen"]).strftime('%H:%M:%S'),
                "is_mobile": cdata.get("is_mobile", False)
            })

        detailed = service.get_detailed_metrics()

        data = {
            "uptime_seconds": int(time.time() - m["start_timestamp"]),
            "queue_depth": service.chat_queue_depth,
            "rag_status": f"Vector DB ({rag.rag_system.get_status() if hasattr(rag, 'rag_system') else 'Ready'})",
            "ram_usage": detailed.get("ram", "N/A"),
            "cpu_load": detailed.get("cpu", "N/A"),
            "swap": detailed.get("swap", "N/A"),
            "disk": detailed.get("disk", "N/A"),
            "db_size": detailed.get("db_size", "0 B"),
            "ai": {
                "requests_total": m["ai_requests"],
                "errors_total": m["ai_errors"],
                "latency_avg_sec": round(avg_lat, 3),
                "model": config.OLLAMA_MODEL,
                "avg_latency_str": detailed.get("ai_lat", "0s")
            },
            "system": {
                "commands_executed": m["cmd_executed"],
                "threads": threading.active_count(),
                "active_clients": clients_payload
            }
        }
        return jsonify(data)

    @bp.route('/api/status_check')
    @requires_auth
    def status_check():
        service.apply_ignored_issues()
        active = state.get_active_issues()
        pending = state.get_pending_actions()
        is_super = (g.user_role == 'superadmin')

        visible = [i for i in active if i.get("key") not in service.ignored_issues]

        infra_count = 0
        agent_count = 0
        root_count = 0
        security_count = 0

        for i in visible:
            key = i.get('key', '')
            ch = i.get('channel_type', '').lower()

            # FIX: Explicit prioritised classification by actual channels
            if ch == 'security':
                security_count += 1
            elif ch == 'root':
                if is_super: root_count += 1
            elif key.startswith('AGENT|'):
                agent_count += 1
            else:
                infra_count += 1

        rag_ready = False
        if hasattr(rag, 'rag_system'):
            rag_ready = rag.rag_system.is_ready

        return jsonify({
            "issues": infra_count,
            "agent_issues": agent_count,
            "root_issues": root_count,
            "security_issues": security_count,
            "pending": len(pending),
            "rag_ready": rag_ready,
            "queue_depth": service.chat_queue_depth,
            "mqtt_enabled": getattr(config, 'MQTT_ENABLED', False),
            "mqtt_connected": utils.mqtt_manager.connected if hasattr(utils, 'mqtt_manager') else False,
            "teams_enabled": getattr(config, 'TEAMS_ENABLED', False),
            "ha_enabled": getattr(config, 'HA_ENABLED', False)
        })

    @bp.route('/api/connection/status', methods=['GET'])
    @requires_auth
    def api_connection_status():
        """Connection & server overview for the status modal."""
        import socket as _socket
        from .. import utils

        # Uptime
        uptime_str = service.get_uptime()
        uptime_secs = int((datetime.now() - service.start_time).total_seconds())

        # AI metrics
        lat_history = list(service.metrics.get("ai_latency_history", []))
        avg_lat = round(sum(lat_history) / len(lat_history), 1) if lat_history else 0

        # DB size
        db_size = 0
        try:
            db_path = getattr(state, 'DB_FILE', None)
            if db_path and os.path.exists(db_path):
                db_size = round(os.path.getsize(db_path) / 1024, 1)
        except Exception:
            pass

        # Active WebSocket clients
        ws_clients = len(service.metrics.get("active_users", set()))

        # Active issues count
        active_issues = len(state.get_active_issues())

        # MQTT status
        mqtt_host = getattr(config, 'MQTT_HOST', '')
        mqtt_port = getattr(config, 'MQTT_PORT', 1883)
        mqtt_enabled = getattr(config, 'MQTT_ENABLED', False)
        mqtt_connected = utils.mqtt_manager.connected if hasattr(utils, 'mqtt_manager') else False

        # HA status
        ha_url = getattr(config, 'HA_URL', '')
        ha_enabled = getattr(config, 'HA_ENABLED', False)

        # Teams
        teams_enabled = getattr(config, 'TEAMS_ENABLED', False)

        # AI engine
        hailo_enabled = getattr(config, 'HAILO_OLLAMA_ENABLED', False)
        if hailo_enabled:
            ai_url = getattr(config, 'HAILO_OLLAMA_URL', '')
            ai_model = getattr(config, 'HAILO_OLLAMA_MODEL', '')
            ai_backend = 'Hailo-ollama (NPU)'
        else:
            ai_url = getattr(config, 'OLLAMA_URL', '')
            ai_model = getattr(config, 'OLLAMA_MODEL', '')
            ai_backend = 'Ollama (CPU)'

        # Hostname
        try:
            server_hostname = _socket.gethostname()
        except Exception:
            server_hostname = 'unknown'

        return jsonify({
            "server": {
                "hostname": server_hostname,
                "host": getattr(config, 'WEB_HOST', '0.0.0.0'),
                "port": getattr(config, 'WEB_PORT', 5050),
                "uptime": uptime_str,
                "uptime_seconds": uptime_secs,
                "version": getattr(config, 'VERSION', '?'),
                "instance_name": getattr(config, 'INSTANCE_NAME', 'Sentinel'),
            },
            "stats": {
                "active_issues": active_issues,
                "ai_requests": service.metrics.get("ai_requests", 0),
                "ai_errors": service.metrics.get("ai_errors", 0),
                "avg_latency_s": avg_lat,
                "queue_depth": service.chat_queue_depth,
                "ws_clients": ws_clients,
                "db_size_kb": db_size,
            },
            "ai": {
                "backend": ai_backend,
                "url": ai_url,
                "model": ai_model,
                "hailo_enabled": hailo_enabled,
            },
            "integrations": {
                "mqtt": {"enabled": mqtt_enabled, "connected": mqtt_connected,
                         "host": mqtt_host, "port": mqtt_port},
                "homeassistant": {"enabled": ha_enabled, "url": ha_url},
                "teams": {"enabled": teams_enabled,
                          "webhook": bool(getattr(config, 'TEAMS_WEBHOOK_URL', ''))},
            },
        })

    @bp.route('/api/sys_info', methods=['GET'])
    @requires_auth
    def api_sys_info():
        return jsonify({"html": service.render_sys_monitor_html(g.user_role)})

    @bp.route('/api/predictions', methods=['GET'])
    @requires_auth
    def get_predictions():
        report = []
        show_hidden = request.args.get('show_hidden', '0') == '1'
        hidden = json.loads(state.get_setting('predictions.hidden_sensors', '[]'))
        data_age_warning = None
        try:
            with sqlite3.connect(state.DB_FILE) as conn:
                c = conn.cursor()
                # Zkus nejdřív last 1 day, jinak last 7 days (stará data)
                c.execute("SELECT DISTINCT metric, category FROM telemetry WHERE timestamp > datetime('now', '-1 day')")
                metrics = c.fetchall()
                if not metrics:
                    c.execute("SELECT DISTINCT metric, category FROM telemetry WHERE timestamp > datetime('now', '-7 day')")
                    metrics = c.fetchall()
                    if metrics:
                        last_ts = c.execute("SELECT MAX(timestamp) FROM telemetry").fetchone()[0]
                        data_age_warning = f"Poslední telemetrie: {(last_ts or '?')[:16]}. Zkontroluj log soubory a agenty."
            for metric, cat in metrics:
                hist = state.get_metric_history(metric, limit=20)
                if not hist: continue
                current = hist[-1]
                status, msg = analytics.analyze_trend(metric, current, cat)
                is_hidden = metric in hidden
                if is_hidden and not show_hidden:
                    continue
                report.append({"metric": metric, "category": cat, "value": current, "status": status, "message": msg or "Stabilní", "history": hist, "hidden": is_hidden})
        except Exception as e:
            logger.exception(f"Error in predictions: {e}")
        return jsonify({"data": report, "hidden_count": len(hidden), "data_age_warning": data_age_warning})

    @bp.route('/api/predictions/toggle_hidden', methods=['POST'])
    @requires_auth
    def predictions_toggle_hidden():
        if g.user_role not in ['admin', 'superadmin']:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        metric = (request.json or {}).get('metric', '').strip()
        if not metric:
            return jsonify({'status': 'error', 'message': 'metric required'}), 400
        hidden = json.loads(state.get_setting('predictions.hidden_sensors', '[]'))
        if metric in hidden:
            hidden.remove(metric)
            action = 'shown'
        else:
            hidden.append(metric)
            action = 'hidden'
        state.set_setting('predictions.hidden_sensors', json.dumps(hidden))
        return jsonify({'status': 'ok', 'action': action, 'hidden_count': len(hidden)})

    @bp.route('/api/predictions/reset_hidden', methods=['POST'])
    @requires_auth
    def predictions_reset_hidden():
        if g.user_role not in ['admin', 'superadmin']:
            return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        state.set_setting('predictions.hidden_sensors', '[]')
        return jsonify({'status': 'ok'})

    @bp.route('/api/config/view', methods=['GET'])
    @requires_auth
    def api_config_view():
        # 350: Mask sensitive fields — password/token/secret/api_key → "***"
        _MASK = '***'
        def _mask(v):
            return _MASK if v else ''
        return jsonify({
            'instance_name': config.INSTANCE_NAME,
            'version': config.VERSION,
            'subversion': config.SUBVERSION,
            'ollama_url': config.OLLAMA_URL,
            'ollama_model': config.OLLAMA_MODEL,
            'ollama_num_ctx': config.OLLAMA_NUM_CTX,
            'ollama_api_key': _mask(getattr(config, 'OLLAMA_API_KEY', '')),
            'log_dir': config.LOG_DIR,
            'data_dir': config.DATA_DIR,
            'kb_file_path': config.KB_FILE_PATH,
            'worker_threads': config.WORKER_THREADS,
            'web_port': config.WEB_PORT,
            'plugin_dir': config.PLUGIN_DIR,
            'teams_enabled': config.TEAMS_ENABLED,
            # HA
            'ha_enabled': config.HA_ENABLED,
            'ha_url': getattr(config, 'HA_URL', ''),
            'ha_notify_service': getattr(config, 'HA_NOTIFY_SERVICE', ''),
            'ha_token': _mask(getattr(config, 'HA_TOKEN', '')),
            # MQTT
            'mqtt_enabled': config.MQTT_ENABLED,
            'mqtt_host': getattr(config, 'MQTT_HOST', ''),
            'mqtt_port': getattr(config, 'MQTT_PORT', 1883),
            'mqtt_user': getattr(config, 'MQTT_USER', ''),
            'mqtt_pass': _mask(getattr(config, 'MQTT_PASS', '')),
            'mqtt_topic_prefix': getattr(config, 'MQTT_TOPIC_PREFIX', 'sentinel'),
            # Hailo
            'hailo_ollama_enabled': config.HAILO_OLLAMA_ENABLED,
            'hailo_ollama_model': config.HAILO_OLLAMA_MODEL,
            'hailo_ollama_url': getattr(config, 'HAILO_OLLAMA_URL', ''),
            # LDAP
            'ldap_enabled': getattr(config, 'LDAP_ENABLED', False),
            'ldap_host': getattr(config, 'LDAP_HOST', ''),
            'ldap_port': getattr(config, 'LDAP_PORT', 389),
            'ldap_use_ssl': getattr(config, 'LDAP_USE_SSL', False),
            'ldap_base_dn': getattr(config, 'LDAP_BASE_DN', ''),
            'ldap_bind_dn': getattr(config, 'LDAP_BIND_DN', '') or '',
            'ldap_bind_password': _mask(getattr(config, 'LDAP_BIND_PASSWORD', '')),
            # SSH
            'ssh_user': getattr(config, 'SSH_USER', 'root'),
            'ssh_key_path': getattr(config, 'SSH_KEY_PATH', ''),
            'ssh_jump_host': getattr(config, 'SSH_JUMP_HOST', ''),
            # Webhook
            'webhook_enabled': getattr(config, 'WEBHOOK_ENABLED', False),
            'webhook_url': getattr(config, 'WEBHOOK_URL', ''),
            'webhook_secret': _mask(getattr(config, 'WEBHOOK_SECRET', '')),
            # misc
            'watch_patterns': config.WATCH_PATTERNS,
            'ignore_patterns': config.IGNORE_PATTERNS,
            'issue_expiry_days': getattr(config, 'ISSUE_EXPIRY_DAYS', {}),
            'auto_severity_enabled':  getattr(config, 'AUTO_SEVERITY_ENABLED', False),
            'auto_duplicate_enabled': getattr(config, 'AUTO_DUPLICATE_ENABLED', True),
        })

    # ── 219: Internal wiki ──────────────────────────────────────────────────
    @bp.route('/api/wiki', methods=['GET'])
    @requires_auth
    def api_wiki_list():
        conn = state._get_conn()
        rows = conn.execute("SELECT id, slug, title, updated_at, updated_by FROM wiki_pages ORDER BY title").fetchall()
        conn.close()
        return jsonify({"pages": [{"id":r[0],"slug":r[1],"title":r[2],"updated_at":r[3],"updated_by":r[4]} for r in rows]})

    @bp.route('/api/wiki/<slug>', methods=['GET'])
    @requires_auth
    def api_wiki_get(slug):
        conn = state._get_conn()
        row = conn.execute("SELECT id, slug, title, content, updated_at, updated_by FROM wiki_pages WHERE slug=?", (slug,)).fetchone()
        conn.close()
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify({"id":row[0],"slug":row[1],"title":row[2],"content":row[3],"updated_at":row[4],"updated_by":row[5]})

    @bp.route('/api/wiki', methods=['POST'])
    @requires_auth
    def api_wiki_save():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        title = (d.get('title') or '').strip()
        slug  = (d.get('slug')  or '').strip()
        content = d.get('content', '')
        if not title or not slug:
            return jsonify({"error": "title and slug required"}), 400
        import re as _re
        if not _re.match(r'^[a-z0-9_-]+$', slug):
            return jsonify({"error": "slug must be lowercase alphanumeric with - and _"}), 400
        conn = state._get_conn()
        conn.execute("""INSERT INTO wiki_pages (slug, title, content, updated_at, updated_by)
                        VALUES (?,?,?,datetime('now'),?)
                        ON CONFLICT(slug) DO UPDATE SET title=excluded.title, content=excluded.content,
                        updated_at=excluded.updated_at, updated_by=excluded.updated_by""",
                     (slug, title, content, g.username))
        conn.commit(); conn.close()
        return jsonify({"status": "ok", "slug": slug})

    @bp.route('/api/wiki/<slug>', methods=['DELETE'])
    @requires_auth
    def api_wiki_delete(slug):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        conn = state._get_conn()
        conn.execute("DELETE FROM wiki_pages WHERE slug=?", (slug,))
        conn.commit(); conn.close()
        return jsonify({"status": "ok"})

    @bp.route('/api/config/validate', methods=['GET'])
    @requires_auth
    def api_config_validate():
        """214: Return config validation warnings."""
        warns = getattr(config, 'VALIDATION_WARNINGS', [])
        return jsonify({"warnings": warns, "count": len(warns),
                        "has_critical": any(w['level'] == 'critical' for w in warns)})

    @bp.route('/api/config/backup', methods=['GET'])
    @requires_auth
    def api_config_backup():
        """Download current config.yaml."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            with open(config.CONFIG_PATH, 'r') as f:
                content = f.read()
            from flask import Response as _Resp
            return _Resp(content, mimetype='application/x-yaml',
                         headers={'Content-Disposition': 'attachment; filename=sentinel-config.yaml'})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/config/restore', methods=['POST'])
    @requires_auth
    def api_config_restore():
        """Upload a new config.yaml (replaces current, triggers reload)."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        f = request.files.get('file')
        if not f:
            return jsonify({"error": "No file"}), 400
        try:
            content = f.read(512 * 1024)  # max 512 KB
            parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict):
                return jsonify({"error": "Invalid YAML: expected a mapping"}), 400
        except yaml.YAMLError as e:
            return jsonify({"error": f"YAML parse error: {e}"}), 400
        cfg_path = str(config.CONFIG_PATH)
        try:
            with open(cfg_path, 'wb') as out:
                out.write(content)
        except Exception as e:
            return jsonify({"error": f"Write failed: {e}"}), 500
        service.log_event("config_restore", "Config restored from UI upload", user=g.username)
        return jsonify({"status": "ok", "message": "Config uložen. Sentinel načte nový config automaticky."})

    @bp.route('/api/config/update', methods=['POST'])
    @requires_auth
    def api_config_update():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "admin required"}), 403
        data = request.json or {}

        # Flat fields: (yaml_key, config_attr, type, min_val_or_None)
        _FLAT = [
            ('instance_name',           'INSTANCE_NAME',         str,   None),
            ('ollama_model',            'OLLAMA_MODEL',           str,   None),
            ('ollama_url',              'OLLAMA_URL',             str,   None),
            ('ollama_num_ctx',          'OLLAMA_NUM_CTX',         int,   128),
            ('worker_threads',          'WORKER_THREADS',         int,   1),
            ('log_dir',                 'LOG_DIR',                str,   None),
            ('auto_severity_enabled',   'AUTO_SEVERITY_ENABLED',  bool,  None),
            ('auto_duplicate_enabled',  'AUTO_DUPLICATE_ENABLED', bool,  None),
        ]
        # Nested fields: (dot_path, config_attr, type)
        _NESTED = [
            ('hailo_ollama.enabled', 'HAILO_OLLAMA_ENABLED', bool),
            ('hailo_ollama.url',     'HAILO_OLLAMA_URL',     str),
            ('hailo_ollama.model',   'HAILO_OLLAMA_MODEL',   str),
            ('mqtt.enabled',         'MQTT_ENABLED',         bool),
            ('mqtt.host',            'MQTT_HOST',            str),
            ('mqtt.port',            'MQTT_PORT',            int),
            ('mqtt.user',            'MQTT_USER',            str),
            ('mqtt.pass',            'MQTT_PASS',            str),
            ('mqtt.topic_prefix',    'MQTT_TOPIC_PREFIX',    str),
            ('homeassistant.enabled','HA_ENABLED',           bool),
            ('homeassistant.url',    'HA_URL',               str),
            ('homeassistant.token',  'HA_TOKEN',             str),
            ('homeassistant.notify_service', 'HA_NOTIFY_SERVICE', str),
            ('ldap.enabled',         'LDAP_ENABLED',         bool),
            ('ldap.host',            'LDAP_HOST',            str),
            ('ldap.port',            'LDAP_PORT',            int),
            ('ldap.use_ssl',         'LDAP_USE_SSL',         bool),
            ('ldap.base_dn',         'LDAP_BASE_DN',         str),
            ('ldap.bind_dn',         'LDAP_BIND_DN',         str),
            ('ldap.bind_password',   'LDAP_BIND_PASSWORD',   str),
            ('ssh_execution.user',   'SSH_USER',             str),
            ('ssh_execution.jump_host', 'SSH_JUMP_HOST',     str),
            ('ssh_execution.key_path',  'SSH_KEY_PATH',      str),
        ]

        # Parse incoming payload (uses flat key names, nested use dot notation in key)
        updates_flat = {}
        updates_nested = {}

        for yaml_key, attr, typ, minval in _FLAT:
            if yaml_key not in data: continue
            try:
                val = bool(data[yaml_key]) if typ is bool else typ(data[yaml_key])
                if typ is int and minval is not None and val < minval:
                    raise ValueError
                updates_flat[yaml_key] = (attr, val)
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": f"Invalid value for {yaml_key}"}), 400

        for dot_path, attr, typ in _NESTED:
            if dot_path not in data: continue
            try:
                raw_val = data[dot_path]
                if typ is bool:
                    val = bool(raw_val) if not isinstance(raw_val, str) else raw_val.lower() in ('true','1','yes')
                else:
                    val = typ(raw_val)
                updates_nested[dot_path] = (attr, val)
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": f"Invalid value for {dot_path}"}), 400

        # 209: issue_expiry_days — dict field, handled separately
        expiry_update = None
        if 'issue_expiry_days' in data:
            raw_exp = data['issue_expiry_days']
            if isinstance(raw_exp, dict):
                expiry_update = {k.lower(): float(v) for k, v in raw_exp.items() if isinstance(v, (int, float)) and float(v) > 0}

        if not updates_flat and not updates_nested and expiry_update is None:
            return jsonify({"status": "error", "message": "No valid fields to update"}), 400

        # Apply to in-memory config
        for _, (attr, val) in {**updates_flat, **updates_nested}.items():
            setattr(config, attr, val)
        if expiry_update is not None:
            config.ISSUE_EXPIRY_DAYS = expiry_update

        # Persist to YAML file
        cfg_path = str(config.CONFIG_PATH)
        try:
            with open(cfg_path, 'r') as f:
                cfg_yaml = yaml.safe_load(f) or {}

            for yaml_key, (_, val) in updates_flat.items():
                cfg_yaml[yaml_key] = val

            for dot_path, (_, val) in updates_nested.items():
                parts = dot_path.split('.')
                node = cfg_yaml
                for p in parts[:-1]:
                    if p not in node or not isinstance(node[p], dict):
                        node[p] = {}
                    node = node[p]
                node[parts[-1]] = val

            if expiry_update is not None:
                cfg_yaml['issue_expiry_days'] = expiry_update

            with open(cfg_path, 'w') as f:
                yaml.dump(cfg_yaml, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            service.log_event("config_update", f"Persisted in memory only: {e}", user=g.username)
            all_keys = list(updates_flat.keys()) + list(updates_nested.keys())
            return jsonify({"status": "warning", "message": f"Applied in memory; file write failed: {e}", "updated": all_keys})

        all_keys = list(updates_flat.keys()) + list(updates_nested.keys())
        if expiry_update is not None: all_keys.append('issue_expiry_days')
        service.log_event("config_update", f"Config updated: {all_keys}", user=g.username)
        return jsonify({"status": "ok", "updated": all_keys})

    @bp.route('/api/system/restart', methods=['POST'])
    @requires_auth
    def api_system_restart():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "admin required"}), 403
        try:
            service.log_event("system_restart", "Service restart requested via UI", user=g.username)
            subprocess.Popen(['sudo', 'systemctl', 'restart', 'sentinel'])
            return jsonify({"status": "ok", "message": "Restart zahájen"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/config/history', methods=['GET'])
    @requires_auth
    def api_config_history():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        return jsonify({"history": state.get_config_history()})

    @bp.route('/api/config/history/<int:sid>', methods=['GET'])
    @requires_auth
    def api_config_history_get(sid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        content = state.get_config_snapshot(sid)
        if content is None:
            return jsonify({"error": "Snapshot nenalezen"}), 404
        return jsonify({"content": content})

    @bp.route('/api/config/diff', methods=['GET'])
    @requires_auth
    def api_config_diff():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        import difflib as _dl
        example_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'config.yaml.example')
        try:
            with open(str(config.CONFIG_PATH)) as f:
                current = f.readlines()
            with open(example_path) as f:
                example = f.readlines()
            diff = list(_dl.unified_diff(current, example, fromfile='current config', tofile='config.yaml.example', lineterm=''))
            return jsonify({"diff": ''.join(diff), "has_diff": bool(diff)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/health/history', methods=['GET'])
    @requires_auth
    def api_health_history():
        days = min(int(request.args.get('days', 7)), 30)
        return jsonify({"history": state.get_health_history(days)})

    @bp.route('/api/patterns', methods=['GET'])
    @requires_auth
    def api_patterns_get():
        return jsonify({"patterns": state.get_custom_patterns()})

    @bp.route('/api/patterns', methods=['POST'])
    @requires_auth
    def api_patterns_add():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        name = d.get('name', '').strip()
        plugin = d.get('plugin', '').strip()
        pattern = d.get('pattern', '').strip()
        channel = d.get('channel', 'agent').strip()
        if not name or not plugin or not pattern:
            return jsonify({"error": "name, plugin a pattern jsou povinné"}), 400
        ok = state.add_custom_pattern(name, plugin, pattern, channel, g.username)
        return jsonify({"status": "ok" if ok else "error — neplatný regex"})

    @bp.route('/api/patterns/<int:pid>/toggle', methods=['POST'])
    @requires_auth
    def api_patterns_toggle(pid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.toggle_custom_pattern(pid)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/patterns/<int:pid>', methods=['DELETE'])
    @requires_auth
    def api_patterns_delete(pid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_custom_pattern(pid)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/patterns/test', methods=['POST'])
    @requires_auth
    def api_patterns_test():
        d = request.json or {}
        pattern = d.get('pattern', '')
        text = d.get('text', '')
        import re as _re
        try:
            m = _re.search(pattern, text)
            return jsonify({"match": bool(m), "groups": list(m.groups()) if m else []})
        except Exception as e:
            return jsonify({"match": False, "error": str(e)})

    @bp.route('/api/changelog', methods=['GET'])
    @requires_auth
    def api_changelog():
        try:
            import subprocess as _sp
            limit = min(int(request.args.get('limit', 30)), 100)
            repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            result = _sp.run(
                ['git', '-c', 'safe.directory=*', 'log', f'--max-count={limit}',
                 '--format=%H|%h|%s|%an|%ar'],
                cwd=repo, capture_output=True, text=True, timeout=5
            )
            commits = []
            for line in result.stdout.strip().splitlines():
                parts = line.split('|', 4)
                if len(parts) == 5:
                    commits.append({"hash": parts[0], "short": parts[1], "subject": parts[2], "author": parts[3], "when": parts[4]})
            return jsonify({"commits": commits})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/rag/reindex', methods=['POST'])
    @requires_auth
    def api_rag_reindex():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            if not hasattr(rag, 'rag_system'):
                return jsonify({"error": "RAG systém není inicializován"}), 500
            rag.rag_system.is_ready = False
            threading.Thread(
                target=rag.rag_system.ingest_knowledge_base,
                daemon=True, name="RAG-HotReload"
            ).start()
            logger.info(f"[rag_reindex] Spuštěno uživatelem {g.username}")
            return jsonify({"status": "ok", "message": "Re-indexace spuštěna v pozadí"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/rag/status', methods=['GET'])
    @requires_auth
    def api_rag_status():
        if not hasattr(rag, 'rag_system'):
            return jsonify({"ready": False, "status": "Neinicializováno"})
        return jsonify({
            "ready": rag.rag_system.is_ready,
            "status": rag.rag_system.get_status(),
        })

    @bp.route('/api/rag/info', methods=['GET'])
    @requires_auth
    def api_rag_info():
        rs = rag.rag_system
        rm = rs.get_metrics() if hasattr(rs, 'get_metrics') else {}
        using_vector = bool(rs.client and rs.collection) if hasattr(rs, 'client') else False
        status = rs.get_status() if hasattr(rs, 'get_status') else 'unknown'
        return jsonify({
            "status": status,
            "provider": "ChromaDB + nomic-embed-text" if using_vector else "BM25 Text Search",
            "model": rm.get('rag_model', getattr(config, 'OLLAMA_MODEL', 'unknown')),
            "docs": rm.get('rag_db_items', 0),
            "chunks": rm.get('rag_chunks_loaded', 0),
            "kb_file": config.KB_FILE_PATH,
            "chroma_path": config.CHROMADB_PATH,
            "avg_latency": rm.get('rag_avg_time', 'N/A'),
            "total_queries": rm.get('rag_total_vectors', 0),
        })

    @bp.route('/api/comments/templates', methods=['GET'])
    @requires_auth
    def api_comment_templates_get():
        return jsonify({"templates": state.get_comment_templates()})

    @bp.route('/api/comments/templates', methods=['POST'])
    @requires_auth
    def api_comment_templates_add():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        name = d.get('name', '').strip()
        text = d.get('text', '').strip()
        if not name or not text:
            return jsonify({"error": "Název a text jsou povinné"}), 400
        ok = state.add_comment_template(name, text, g.username)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/comments/templates/<int:tid>', methods=['DELETE'])
    @requires_auth
    def api_comment_templates_delete(tid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_comment_template(tid)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/system/errors', methods=['GET'])
    @requires_auth
    def api_system_errors():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        limit = min(int(request.args.get('limit', 50)), 200)
        return jsonify({"errors": state.get_sentinel_errors(limit)})

    @bp.route('/api/alerts/host_heatmap', methods=['GET'])
    @requires_auth
    def api_host_heatmap():
        days = min(int(request.args.get('days', 7)), 30)
        return jsonify({"data": state.get_host_heatmap(days), "days": days})

    @bp.route('/api/alerts/timeline', methods=['GET'])
    @requires_auth
    def api_alerts_timeline():
        days = min(int(request.args.get('days', 7)), 30)
        return jsonify(state.get_alert_timeline(days=days))

    @bp.route('/api/ignored', methods=['GET'])
    @requires_auth
    def api_ignored_get():
        import base64
        items = []
        for k in sorted(service.ignored_issues):
            kb64 = base64.b64encode(k.encode()).decode()
            items.append({"key": k, "key_b64": kb64})
        return jsonify({"ignored": items})

    @bp.route('/api/ignored/<key_b64>', methods=['DELETE'])
    @requires_auth
    def api_ignored_delete(key_b64):
        import base64
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            k = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        if k in service.ignored_issues:
            service.ignored_issues.remove(k)
            service.save_ignored_issues()
        return jsonify({"status": "ok"})

    @bp.route('/api/queue/details', methods=['GET'])
    @requires_auth
    def api_queue_details():
        workers = getattr(config, 'WORKER_THREADS', 2)
        m = service.get_detailed_metrics()
        return jsonify({
            "pending": service.chat_queue_depth,      # LLM semaphore queue (badge)
            "db_pending": state.get_queue_depth(),    # DB task_queue (AI actions)
            "workers": workers,
            "ai_latency": m.get('ai_lat', 'N/A'),
            "ai_requests_total": service.metrics.get('ai_requests', 0),
            "ai_errors_total": service.metrics.get('ai_errors', 0),
            "requests": state.get_queue_items(),
        })

    @bp.route('/api/plugins/toggle', methods=['POST'])
    @requires_auth
    def api_plugins_toggle():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        data = request.json or {}
        plugin_name = data.get('plugin', '').strip()
        enabled = bool(data.get('enabled', False))
        if not plugin_name:
            return jsonify({"status": "error", "message": "Missing plugin name"}), 400

        # Update in-memory config
        matched = False
        for det in config.DETECTORS:
            if det.get('plugin') == plugin_name:
                det['enabled'] = enabled
                matched = True
                break
        if not matched:
            return jsonify({"status": "error", "message": "Plugin not found"}), 404

        # Persist to YAML — hot-reload watcher will call load_config + load_plugins
        try:
            with open(config.CONFIG_PATH, 'r') as f:
                cfg_data = yaml.safe_load(f) or {}
            for det in cfg_data.get('detectors', []):
                if det.get('plugin') == plugin_name:
                    det['enabled'] = enabled
                    break
            with open(config.CONFIG_PATH, 'w') as f:
                yaml.dump(cfg_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        return jsonify({"status": "ok", "plugin": plugin_name, "enabled": enabled})

    @bp.route('/api/plugins/stats', methods=['GET'])
    @requires_auth
    def api_plugins_stats():
        stats = state.get_plugin_stats()
        det_map = {d.get('plugin'): d for d in config.DETECTORS}
        for s in stats:
            det = det_map.get(s['plugin'], {})
            s['enabled'] = det.get('enabled', True)
            s['notify'] = det.get('notify', True)
        return jsonify({"stats": stats})

    @bp.route('/api/plugins/toggle_notify', methods=['POST'])
    @requires_auth
    def api_plugins_toggle_notify():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        data = request.json or {}
        plugin_name = data.get('plugin', '').strip()
        notify = bool(data.get('notify', True))
        if not plugin_name:
            return jsonify({"status": "error", "message": "Missing plugin name"}), 400

        matched = False
        for det in config.DETECTORS:
            if det.get('plugin') == plugin_name:
                det['notify'] = notify
                matched = True
                break
        if not matched:
            return jsonify({"status": "error", "message": "Plugin not found"}), 404

        try:
            with open(config.CONFIG_PATH, 'r') as f:
                cfg_data = yaml.safe_load(f) or {}
            for det in cfg_data.get('detectors', []):
                if det.get('plugin') == plugin_name:
                    det['notify'] = notify
                    break
            with open(config.CONFIG_PATH, 'w') as f:
                yaml.dump(cfg_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

        service.log_event("plugin_notify", f"Plugin {plugin_name} notify={notify}", user=g.username)
        return jsonify({"status": "ok", "plugin": plugin_name, "notify": notify})

    @bp.route('/api/plugins/graph', methods=['GET'])
    @requires_auth
    def api_plugins_graph():
        from sentinel import plugin_manager as _pm
        nodes, edges = [], []
        for rx, pl in _pm.active_plugins:
            nodes.append({"id": pl.name, "type": "plugin"})
            # Pattern z detectors config
            det = next((d for d in config.DETECTORS if d.get('plugin') == pl.name), {})
            pattern = det.get('match_pattern', rx.pattern)
            log_id = f"log:{pattern}"
            if not any(n['id'] == log_id for n in nodes):
                nodes.append({"id": log_id, "type": "log", "label": pattern})
            edges.append({"from": log_id, "to": pl.name})
        # Channel mappings ze state
        ch_map = {}
        try:
            conn = state._get_conn()
            rows = conn.execute("SELECT DISTINCT plugin_name, channel_type FROM problems WHERE plugin_name IS NOT NULL AND channel_type IS NOT NULL").fetchall()
            conn.close()
            for pn, ch in rows:
                ch_map.setdefault(pn, set()).add(ch.lower())
        except Exception: pass
        for pn, channels in ch_map.items():
            for ch in channels:
                ch_id = f"channel:{ch}"
                if not any(n['id'] == ch_id for n in nodes):
                    nodes.append({"id": ch_id, "type": "channel", "label": ch.upper()})
                if not any(e['from'] == pn and e['to'] == ch_id for e in edges):
                    edges.append({"from": pn, "to": ch_id})
        return jsonify({"nodes": nodes, "edges": edges})

    @bp.route('/api/plugins/reload', methods=['POST'])
    @requires_auth
    def api_plugins_reload():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            from sentinel import plugin_manager as _pm
            _pm.load_plugins()
            loaded = [{"name": pl.name, "pattern": rx.pattern} for rx, pl in _pm.active_plugins]
            logger.info(f"[plugin_reload] {g.username} reloaded {len(loaded)} plugins")
            return jsonify({"status": "ok", "loaded": loaded, "count": len(loaded)})
        except Exception as e:
            logger.error(f"plugin_reload error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── Session Management ──────────────────────────────────────────────────

    @bp.route('/api/sessions', methods=['GET'])
    @requires_auth
    def api_sessions_list():
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        sessions = state.list_sessions()
        # Označit vlastní session
        my_uuid = session.get('_suuid', '')
        for s in sessions:
            s['is_current'] = (s.get('session_uuid') == my_uuid)
            del s['session_uuid']  # Nesdílet UUID klientovi
        return jsonify({"sessions": sessions})

    @bp.route('/api/sessions/<int:sid>', methods=['DELETE'])
    @requires_auth
    def api_sessions_revoke(sid):
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        revoked_uuid = state.revoke_session(sid)
        if revoked_uuid:
            _REVOKED_SESSIONS.add(revoked_uuid)
            logger.info(f"[session_revoke] {g.username} revokoval session #{sid}")
            return jsonify({"status": "ok"})
        return jsonify({"status": "error", "message": "Session nenalezena"}), 404

    # ── Users & Roles ──────────────────────────────────────────────────────

    @bp.route('/api/users/roles', methods=['GET'])
    @requires_auth
    def api_users_roles_get():
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        users = []
        users.append({"username": config.WEB_USER, "role": "admin", "source": "config"})
        users.append({"username": config.WEB_VIEWER_USER, "role": "viewer", "source": "config"})
        if config.LDAP_ENABLED:
            for u in config.LDAP_SUPERADMINS:
                users.append({"username": u, "role": "superadmin", "source": "ldap"})
            for u in config.LDAP_ADMINS:
                users.append({"username": u, "role": "admin", "source": "ldap"})
            for u in getattr(config, 'LDAP_OPERATORS', []):
                users.append({"username": u, "role": "operator", "source": "ldap"})
            for u in config.LDAP_VIEWERS:
                users.append({"username": u, "role": "viewer", "source": "ldap"})
        db_roles = state.get_all_user_roles()
        users.extend(db_roles)
        return jsonify({"users": users})

    @bp.route('/api/users/roles', methods=['POST'])
    @requires_auth
    def api_users_roles_set():
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        username = d.get('username', '').strip()
        role = d.get('role', '').strip()
        if not username or role not in ('viewer', 'operator', 'admin', 'superadmin'):
            return jsonify({"error": "Invalid params"}), 400
        state.set_user_role(username, role)
        service.log_event("role_change", f"User {username} set to role {role}", user=g.username)
        return jsonify({"status": "ok"})

    @bp.route('/api/users/roles/<username>', methods=['DELETE'])
    @requires_auth
    def api_users_roles_delete(username):
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        state.delete_user_role(username)
        return jsonify({"status": "ok"})

    @bp.route('/api/users/list', methods=['GET'])
    @requires_auth
    def api_users_list():
        """Vrátí seznam uživatelů pro assignee picker."""
        try:
            conn = state._get_conn()
            rows = conn.execute("SELECT username, role FROM user_roles ORDER BY username ASC").fetchall()
            conn.close()
            users = [{"username": r[0], "role": r[1]} for r in rows]
            # Přidat lokální admin/viewer pokud nejsou v DB
            local_users = [
                {"username": getattr(config, 'WEB_USER', 'admin'), "role": "admin"},
                {"username": getattr(config, 'WEB_VIEWER_USER', 'viewer'), "role": "viewer"},
            ]
            existing = {u['username'] for u in users}
            for lu in local_users:
                if lu['username'] not in existing:
                    users.append(lu)
            return jsonify({"users": users})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── API Keys ──────────────────────────────────────────────────────────

    @bp.route('/api/apikeys', methods=['GET'])
    @requires_auth
    def api_keys_list():
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        return jsonify({"keys": state.list_api_keys()})

    @bp.route('/api/apikeys', methods=['POST'])
    @requires_auth
    def api_keys_create():
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        name = d.get('name', '').strip()
        scope = d.get('scope', 'read').strip()
        expires_at = d.get('expires_at') or None
        if not name:
            return jsonify({"error": "Název nesmí být prázdný"}), 400
        if scope not in ('read', 'write', 'admin'):
            return jsonify({"error": "Neplatný scope"}), 400
        raw = state.create_api_key(name, scope, expires_at, g.username)
        if not raw:
            return jsonify({"error": "Chyba vytváření klíče"}), 500
        return jsonify({"status": "ok", "token": raw, "note": "Zkopírujte token — zobrazí se jen jednou!"})

    @bp.route('/api/apikeys/<int:key_id>', methods=['DELETE'])
    @requires_auth
    def api_keys_delete(key_id):
        if g.user_role != 'superadmin':
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_api_key(key_id)
        return jsonify({"status": "ok" if ok else "error"})

    # ── KB Management ──────────────────────────────────────────────────────

    @bp.route('/api/kb/reindex', methods=['POST'])
    @requires_auth
    def api_kb_reindex():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "admin required"}), 403
        import threading as _th
        build_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'build_kb.py')
        def _run():
            try:
                r = subprocess.run(
                    ['python3', build_script],
                    capture_output=True, text=True, timeout=120
                )
                logger.info(f"KB reindex: rc={r.returncode} {r.stdout[-200:] if r.stdout else ''}")
            except Exception as e:
                logger.error(f"KB reindex failed: {e}")
        _th.Thread(target=_run, daemon=True, name="KB-Reindex").start()
        service.log_event("kb_reindex", "KB reindex triggered", user=g.username)
        return jsonify({"status": "ok", "message": "Reindex started in background"})

    @bp.route('/api/kb/files', methods=['GET'])
    @requires_auth
    def api_kb_files():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        source_dirs = [
            ('docs', os.path.join(base, 'docs')),
            ('admindocs', os.path.join(base, 'admindocs')),
            ('uploads', os.path.join(base, 'learning_knowledge_base')),
        ]
        SUPPORTED_EXT = {'.md', '.txt', '.pdf', '.docx', '.csv', '.json'}
        files = []
        for dir_label, dir_path in source_dirs:
            if not os.path.isdir(dir_path):
                continue
            for fname in sorted(os.listdir(dir_path)):
                fpath = os.path.join(dir_path, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXT:
                    continue
                size = os.path.getsize(fpath)
                files.append({'name': fname, 'dir': dir_label, 'size': size,
                              'size_str': f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.2f} MB"})
        return jsonify({"files": files})

    @bp.route('/api/kb/search', methods=['GET'])
    @requires_auth
    def api_kb_search():
        """217: Fulltext search through KB files (plain grep, no RAG)."""
        q = request.args.get('q', '').strip()
        if not q or len(q) < 2:
            return jsonify({"results": [], "error": "Dotaz příliš krátký"})
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        source_dirs = [
            os.path.join(base, 'docs'),
            os.path.join(base, 'admindocs'),
            os.path.join(base, 'learning_knowledge_base'),
        ]
        kb_file = config.KB_FILE_PATH
        TEXT_EXT = {'.md', '.txt', '.csv', '.json'}
        results = []
        q_lower = q.lower()

        def _search_file(fpath, fname):
            try:
                with open(fpath, 'r', errors='ignore') as f:
                    lines = f.readlines()
                hits = []
                for ln, line in enumerate(lines, 1):
                    if q_lower in line.lower():
                        ctx = line.strip()[:200]
                        hits.append({'line': ln, 'text': ctx})
                        if len(hits) >= 5:
                            break
                if hits:
                    results.append({'file': fname, 'hits': hits})
            except Exception:
                pass

        if os.path.isfile(kb_file):
            _search_file(kb_file, os.path.basename(kb_file))

        for d in source_dirs:
            if not os.path.isdir(d): continue
            for fname in sorted(os.listdir(d)):
                if os.path.splitext(fname)[1].lower() not in TEXT_EXT: continue
                _search_file(os.path.join(d, fname), fname)
                if len(results) >= 15:
                    break

        return jsonify({"results": results[:15], "query": q})

    @bp.route('/api/kb/upload', methods=['POST'])
    @requires_auth
    def api_kb_upload():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "admin required"}), 403
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No file"}), 400
        f = request.files['file']
        fname = f.filename or ''
        ext = os.path.splitext(fname)[1].lower()
        ALLOWED = {'.md', '.txt', '.pdf', '.docx', '.csv', '.json'}
        if ext not in ALLOWED:
            return jsonify({"status": "error", "message": f"Nepodporovaný formát ({ext}). Povoleno: {', '.join(ALLOWED)}"}), 400
        safe_name = re.sub(r'[^\w.\-]', '_', os.path.basename(fname))
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'learning_knowledge_base')
        os.makedirs(upload_dir, exist_ok=True)
        dest = os.path.join(upload_dir, safe_name)
        f.save(dest)
        service.log_event("kb_upload", f"Uploaded KB file: {safe_name}", user=g.username)
        return jsonify({"status": "ok", "filename": safe_name})

    @bp.route('/api/kb/delete', methods=['POST'])
    @requires_auth
    def api_kb_delete():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "admin required"}), 403
        fname = (request.json or {}).get('filename', '').strip()
        if not fname or '/' in fname or '..' in fname:
            return jsonify({"status": "error", "message": "Invalid filename"}), 400
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'learning_knowledge_base')
        fpath = os.path.join(upload_dir, fname)
        if not os.path.isfile(fpath):
            return jsonify({"status": "error", "message": "File not found"}), 404
        os.remove(fpath)
        service.log_event("kb_delete", f"Deleted KB file: {fname}", user=g.username)
        return jsonify({"status": "ok"})

    # ── Prometheus Metrics ──────────────────────────────────────────────────

    @bp.route('/metrics', methods=['GET'])
    def prometheus_metrics():
        """Prometheus scrape endpoint. Auth: session nebo ?token=SCRAPE_TOKEN."""
        token = request.args.get('token', '')
        scrape_token = getattr(config, 'PROMETHEUS_SCRAPE_TOKEN', '')
        authed = False
        if scrape_token and token == scrape_token:
            authed = True
        elif not authed:
            # fallback: session auth
            sess = service.get_session_data()
            if sess.get('authenticated'):
                authed = True
        if not authed:
            return Response("Unauthorized", status=401,
                            headers={"WWW-Authenticate": 'Bearer realm="Sentinel metrics"'})

        import re as _re
        def _sanitize(name):
            return _re.sub(r'[^a-zA-Z0-9_]', '_', name).strip('_')

        lines = [
            '# HELP sentinel_info Sentinel Commander instance info',
            '# TYPE sentinel_info gauge',
            f'sentinel_info{{instance="{_sanitize(getattr(config, "INSTANCE_NAME", "sentinel"))}"}} 1',
            '',
        ]

        # Active issues per channel
        issues = state.get_active_issues()
        ch_counts = {}
        for i in issues:
            ch = (i.get('channel_type') or 'unknown').lower()
            ch_counts[ch] = ch_counts.get(ch, 0) + 1
        lines += ['# HELP sentinel_active_issues_total Active issues per channel',
                  '# TYPE sentinel_active_issues_total gauge']
        for ch, cnt in ch_counts.items():
            lines.append(f'sentinel_active_issues_total{{channel="{ch}"}} {cnt}')
        lines.append('')

        # Agent status
        try:
            agents = state.get_all_agents()
            lines += ['# HELP sentinel_agent_online Agent online status (1=online, 0=offline)',
                      '# TYPE sentinel_agent_online gauge']
            for ag in agents:
                host = _sanitize(ag.get('hostname', 'unknown'))
                val = 1 if ag.get('status') == 'ONLINE' else 0
                lines.append(f'sentinel_agent_online{{host="{host}"}} {val}')
            lines.append('')
        except Exception:
            pass

        # Telemetry metrics — latest value per metric
        try:
            with sqlite3.connect(state.DB_FILE) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT t.metric, t.category, t.value
                    FROM telemetry t
                    INNER JOIN (
                        SELECT metric, MAX(rowid) as max_rid FROM telemetry
                        WHERE timestamp > datetime('now', '-2 hours')
                        GROUP BY metric
                    ) latest ON t.metric = latest.metric AND t.rowid = latest.max_rid
                """)
                rows = c.fetchall()

            by_cat = {}
            for metric, category, value in rows:
                by_cat.setdefault(category, []).append((metric, value))

            for category, items in by_cat.items():
                cat_s = _sanitize(category.lower())
                prom_name = f'sentinel_telemetry_{cat_s}'
                lines += [f'# HELP {prom_name} Telemetry metrics — {category}',
                          f'# TYPE {prom_name} gauge']
                for metric, value in items:
                    try:
                        fval = float(value)
                    except (TypeError, ValueError):
                        continue
                    parts = metric.split('.', 1)
                    m_type = _sanitize(parts[0])
                    m_host = _sanitize(parts[1]) if len(parts) > 1 else 'unknown'
                    lines.append(f'{prom_name}{{type="{m_type}",host="{m_host}"}} {fval}')
                lines.append('')
        except Exception as e:
            logger.error(f"Prometheus telemetry error: {e}")

        return Response('\n'.join(lines) + '\n',
                        content_type='text/plain; version=0.0.4; charset=utf-8')

    @bp.route('/api/openapi.json')
    @requires_auth
    def api_openapi_spec():
        from flask import send_from_directory as _sfd
        return _sfd(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'), 'openapi.json', mimetype='application/json')

    @bp.route('/api/docs')
    @requires_auth
    def api_docs():
        return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Sentinel API Docs</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({
  url: '/api/openapi.json',
  dom_id: '#swagger-ui',
  deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
  layout: 'BaseLayout'
});
</script>
</body>
</html>""", 200, {'Content-Type': 'text/html'}

    @bp.route('/api/dashboard', methods=['GET'])
    @requires_auth
    def api_dashboard():
        is_super = (g.user_role == 'superadmin')
        active = state.get_active_issues(include_snoozed=True)
        visible = [i for i in active if i.get("key") not in service.ignored_issues]

        infra_c = security_c = agent_c = root_c = 0
        for i in visible:
            ch = i.get('channel_type', '').lower()
            key = i.get('key', '')
            if ch == 'security': security_c += 1
            elif ch == 'root': root_c += 1 if is_super else 0
            elif key.startswith('AGENT|'): agent_c += 1
            else: infra_c += 1

        agents = [a for a in state.get_all_agents()
                  if not a['hostname'].startswith('sentinel-hw-')
                  and not a['hostname'].startswith('sentinel-alert')]
        agents_online = sum(1 for a in agents if a.get('status') == 'ONLINE')

        m = service.get_detailed_metrics()
        ai_lat = m.get('ai_lat', 'N/A')
        ai_req = service.metrics.get('ai_requests', 0)

        sparklines = []
        try:
            with sqlite3.connect(state.DB_FILE) as _sc:
                _c = _sc.cursor()
                _c.execute("""
                    SELECT metric, value FROM telemetry t
                    INNER JOIN (
                        SELECT metric as m, MAX(rowid) as mr FROM telemetry
                        WHERE metric LIKE 'temp.%' AND timestamp > datetime('now','-2 hours')
                        GROUP BY metric ORDER BY value DESC LIMIT 6
                    ) top ON t.metric = top.m AND t.rowid = top.mr
                """)
                top_metrics = [r[0] for r in _c.fetchall()]
                for metric in top_metrics:
                    hist = state.get_metric_history(metric, limit=20)
                    if hist:
                        host = metric.split('.', 1)[1] if '.' in metric else metric
                        sparklines.append({"host": host, "history": hist,
                                           "latest": hist[-1], "metric": metric})
        except Exception:
            pass

        return jsonify({
            "issues": {
                "total": len(visible),
                "infra": infra_c,
                "agent": agent_c,
                "security": security_c,
                "root": root_c,
                "snoozed": state.get_snoozed_count(),
            },
            "agents": {
                "online": agents_online,
                "offline": len(agents) - agents_online,
                "total": len(agents),
            },
            "pending_actions": len(state.get_pending_actions()),
            "ai_queue": state.get_queue_depth(),
            "ai_latency": ai_lat,
            "ai_requests": ai_req,
            "top_plugins": state.get_plugin_stats()[:5],
            "recent_issues": state.get_recent_issues(8),
            "uptime": service.get_uptime(),
            "cpu_pct": m.get('cpu_pct', 0),
            "ram_pct": m.get('ram_pct', 0),
            "disk_pct": m.get('disk_root', {}).get('pct', 0),
            "version": config.VERSION,
            "sparklines": sparklines,
        })

    @bp.route('/api/reports/monthly_trend', methods=['GET'])
    @requires_auth
    def api_monthly_trend():
        """111: Počty issues za každý měsíc posledních 12 měsíců."""
        try:
            conn = state._get_conn()
            rows = conn.execute("""
                SELECT strftime('%Y-%m', last_seen) AS month,
                       channel_type,
                       COUNT(*) AS cnt
                FROM (
                    SELECT last_seen, channel_type FROM problems
                    UNION ALL
                    SELECT last_seen, channel_type FROM issue_history
                )
                WHERE last_seen >= datetime('now', '-12 months')
                GROUP BY month, channel_type
                ORDER BY month ASC
            """).fetchall()
            conn.close()
            # Sestavit strukturu {month: {channel: count}}
            data: dict = {}
            for month, ch, cnt in rows:
                data.setdefault(month, {})[ch or 'unknown'] = cnt
            months = sorted(data.keys())
            return jsonify({"months": months, "data": data})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/reports/sla_compliance', methods=['GET'])
    @requires_auth
    def api_sla_compliance():
        """112: % issues vyřešených v SLA za posledních N dní."""
        days = min(int(request.args.get('days', 30)), 365)
        sla_rules = getattr(config, 'SLA_RULES', {})
        if not sla_rules:
            return jsonify({"error": "Žádná SLA pravidla v config.yaml"}), 400
        try:
            conn = state._get_conn()
            result = []
            for channel, sla_hours in sla_rules.items():
                # Vyřešené issues: čas řešení = resolved_at - first_seen
                resolved = conn.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN (julianday(resolved_at) - julianday(first_seen)) * 24 <= ? THEN 1 ELSE 0 END) as within_sla
                    FROM issue_history
                    WHERE LOWER(channel_type) = ?
                      AND resolved_at >= datetime('now', ?)
                      AND first_seen IS NOT NULL AND resolved_at IS NOT NULL
                """, (sla_hours, channel.lower(), f'-{days} days')).fetchone()
                total = resolved[0] or 0
                within = resolved[1] or 0
                pct = round(within / total * 100, 1) if total > 0 else None
                # Aktivní porušení SLA
                breaches = conn.execute("""
                    SELECT COUNT(*) FROM problems
                    WHERE LOWER(channel_type) = ?
                      AND status = 'active'
                      AND first_seen IS NOT NULL
                      AND (julianday('now') - julianday(first_seen)) * 24 > ?
                """, (channel.lower(), sla_hours)).fetchone()[0]
                result.append({
                    "channel": channel,
                    "sla_hours": sla_hours,
                    "resolved_total": total,
                    "resolved_within_sla": within,
                    "compliance_pct": pct,
                    "active_breaches": breaches,
                })
            conn.close()
            return jsonify({"days": days, "sla_compliance": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/reports/plugin_efficiency', methods=['GET'])
    @requires_auth
    def api_plugin_efficiency():
        """113: Počty true/false positives per plugin (acknowledged = TP, ignored = FP)."""
        days = min(int(request.args.get('days', 30)), 365)
        try:
            conn = state._get_conn()
            # Aktivní issues per plugin s acknowledged příznakem (TP proxy)
            active = conn.execute("""
                SELECT plugin_name,
                       COUNT(*) as total,
                       SUM(CASE WHEN acknowledged_by IS NOT NULL THEN 1 ELSE 0 END) as acknowledged,
                       SUM(CASE WHEN severity IN ('high','critical') THEN 1 ELSE 0 END) as high_sev
                FROM problems
                WHERE last_seen >= datetime('now', ?)
                  AND plugin_name IS NOT NULL
                GROUP BY plugin_name
                ORDER BY total DESC
            """, (f'-{days} days',)).fetchall()
            # Vyřešené issues za stejné období
            resolved = conn.execute("""
                SELECT plugin_name, COUNT(*) as resolved_cnt
                FROM issue_history
                WHERE last_seen >= datetime('now', ?)
                  AND plugin_name IS NOT NULL
                GROUP BY plugin_name
            """, (f'-{days} days',)).fetchall()
            conn.close()
            res_map = {r[0]: r[1] for r in resolved}
            data = []
            for plugin, total, acked, high_sev in active:
                data.append({
                    "plugin": plugin,
                    "active": total,
                    "acknowledged": acked,
                    "high_severity": high_sev,
                    "resolved": res_map.get(plugin, 0),
                    "ack_rate_pct": round(acked / total * 100, 1) if total > 0 else 0,
                })
            return jsonify({"days": days, "plugins": data})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/patterns/suggest', methods=['POST'])
    @requires_auth
    def api_patterns_suggest():
        """055: AI navrhne nový custom pattern z historických issues."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            conn = state._get_conn()
            # Vezmi nejčastější issues bez existujícího custom patternu
            rows = conn.execute("""
                SELECT plugin_name, last_line, COUNT(*) as cnt
                FROM problems
                WHERE last_seen >= datetime('now', '-30 days')
                  AND plugin_name NOT IN (SELECT plugin FROM custom_patterns WHERE enabled=1)
                GROUP BY plugin_name, last_line
                ORDER BY cnt DESC
                LIMIT 20
            """).fetchall()
            conn.close()
            if not rows:
                return jsonify({"suggestions": [], "message": "Žádné historické issues k analýze."})
            samples = "\n".join(f"[{r[0]}] {r[1]} (×{r[2]})" for r in rows)
            prompt = (
                "Jsi expert na log monitoring. Analyzuj tyto opakující se log zprávy "
                "a navrhni 3 konkrétní regex patterny pro detekci podobných incidentů.\n\n"
                f"LOG ZPRÁVY:\n{samples}\n\n"
                "Pro každý pattern odpověz POUZE ve formátu JSON pole:\n"
                '[{"name":"...", "plugin":"...", "pattern":"...", "channel":"agent", "reason":"..."}]\n'
                "Pattern musí být validní Python regex. Žádný jiný text."
            )
            raw = service.execute_ollama(prompt, num_ctx=2048, max_tokens=500)
            # Extrahuj JSON z odpovědi
            import re as _re
            m = _re.search(r'\[.*\]', raw, _re.DOTALL)
            if not m:
                return jsonify({"suggestions": [], "message": "AI nevygeneroval JSON výstup.", "raw": raw[:300]})
            suggestions = json.loads(m.group(0))
            return jsonify({"suggestions": suggestions})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/export/prometheus_rules.yaml', methods=['GET'])
    @requires_auth
    def api_export_prometheus_rules():
        """070: Vygeneruje Prometheus alerting rules z SLA a escalation konfigu."""
        sla = getattr(config, 'SLA_RULES', {})
        escalation = getattr(config, 'ESCALATION_RULES', [])
        instance = getattr(config, 'INSTANCE_NAME', 'sentinel')
        lines = [
            f"# Sentinel Commander — Prometheus Alerting Rules",
            f"# Instance: {instance}  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "groups:",
            "  - name: sentinel_sla",
            "    rules:",
        ]
        for channel, hours in sla.items():
            expr = (f'sentinel_active_issues_total{{channel="{channel}"}} > 0 '
                    f'and on() (time() - sentinel_active_issues_first_seen{{channel="{channel}"}}) > {int(hours*3600)}')
            lines += [
                f'    - alert: SentinelSLABreach_{channel.upper()}',
                f'      expr: >',
                f'        sentinel_active_issues_total{{channel="{channel}"}} > 0',
                f'      for: {int(hours)}h',
                f'      labels:',
                f'        severity: warning',
                f'        channel: {channel}',
                f'        instance: {instance}',
                f'      annotations:',
                f'        summary: "SLA breach: {channel} issues open > {hours}h"',
                f'        description: "Channel {channel} has issues exceeding {hours}h SLA threshold"',
                '',
            ]
        if escalation:
            lines += ["  - name: sentinel_escalation", "    rules:"]
            for rule in escalation:
                if not isinstance(rule, dict): continue
                ch = rule.get('channels', '*')
                after_h = rule.get('after_hours', 24)
                sev = rule.get('severity', 'high')
                lines += [
                    f'    - alert: SentinelEscalation_{sev.upper()}_{str(ch).replace("*","ALL").replace(",","_")}',
                    f'      expr: sentinel_active_issues_total > 0',
                    f'      for: {int(after_h)}h',
                    f'      labels:',
                    f'        severity: {sev}',
                    f'        channels: "{ch}"',
                    f'      annotations:',
                    f'        summary: "Sentinel escalation after {after_h}h (channels: {ch})"',
                    '',
                ]
        content = '\n'.join(lines)
        return Response(content, mimetype='text/plain',
                        headers={'Content-Disposition': 'attachment; filename=sentinel_rules.yaml'})

    @bp.route('/api/channel-colors', methods=['GET'])
    @requires_auth
    def api_channel_colors():
        return jsonify({"colors": getattr(config, 'CHANNEL_COLORS', {})})

    @bp.route('/api/user/theme', methods=['GET'])
    @requires_auth
    def api_user_theme_get():
        """001: Vrátí uložené téma pro přihlášeného uživatele."""
        key = f"theme.{g.username}"
        val = state.get_setting(key)
        return jsonify({"theme": val or "dark"})

    @bp.route('/api/user/theme', methods=['POST'])
    @requires_auth
    def api_user_theme_set():
        """001: Uloží téma pro přihlášeného uživatele."""
        theme = (request.get_json(silent=True) or {}).get('theme', 'dark')
        if theme not in ('light', 'dark'):
            return jsonify({"error": "Invalid theme"}), 400
        state.set_setting(f"theme.{g.username}", theme)
        return jsonify({"status": "ok", "theme": theme})

    @bp.route('/api/system/ssh-config', methods=['GET'])
    @requires_auth
    def api_ssh_config_get():
        """Vrátí aktuální SSH konfiguraci a fingerprint klíče."""
        key_path = getattr(config, 'SSH_KEY_PATH', '')
        ssh_user = getattr(config, 'SSH_USER', 'root')
        jump_host = getattr(config, 'SSH_JUMP_HOST', '')
        key_exists = os.path.isfile(key_path) if key_path else False
        fingerprint = None
        pubkey = None
        if key_exists:
            try:
                r = subprocess.run(['ssh-keygen', '-l', '-f', key_path],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    fingerprint = r.stdout.strip()
                # Odvoď veřejný klíč pro authorized_keys
                r2 = subprocess.run(['ssh-keygen', '-y', '-f', key_path],
                                    capture_output=True, text=True, timeout=5)
                if r2.returncode == 0:
                    pubkey = r2.stdout.strip()
            except Exception:
                pass
        return jsonify({
            "key_path": key_path,
            "key_exists": key_exists,
            "fingerprint": fingerprint,
            "pubkey": pubkey,
            "ssh_user": ssh_user,
            "jump_host": jump_host,
        })

    @bp.route('/api/system/ssh-config', methods=['POST'])
    @requires_auth
    def api_ssh_config_update():
        """Aktualizuje SSH konfiguraci v config.yaml."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "admin required"}), 403
        d = request.get_json(silent=True) or {}
        updates = {}
        if 'ssh_user' in d:
            updates['user'] = str(d['ssh_user']).strip()[:64]
        if 'jump_host' in d:
            updates['jump_host'] = str(d['jump_host']).strip()[:256]
        if 'key_path' in d:
            kp = str(d['key_path']).strip()
            if not os.path.isabs(kp):
                return jsonify({"error": "key_path musí být absolutní cesta"}), 400
            updates['key_path'] = kp
        if not updates:
            return jsonify({"error": "Žádné pole k aktualizaci"}), 400
        try:
            with open(str(config.CONFIG_PATH), 'r') as f:
                cfg = yaml.safe_load(f) or {}
            ssh_sect = cfg.setdefault('ssh_execution', {})
            ssh_sect.update(updates)
            with open(str(config.CONFIG_PATH), 'w') as f:
                yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            # Aplikuj ihned do running config
            if 'key_path' in updates:
                config.SSH_KEY_PATH = updates['key_path']
            if 'user' in updates:
                config.SSH_USER = updates['user']
            if 'jump_host' in updates:
                config.SSH_JUMP_HOST = updates['jump_host']
            service.log_event("ssh_config_update", f"SSH config updated: {list(updates.keys())}", user=g.username)
            return jsonify({"status": "ok", "updated": updates})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/system/ssh-key', methods=['POST'])
    @requires_auth
    def api_ssh_key_upload():
        """Nahraje nový SSH privátní klíč. Admin only."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "admin required"}), 403
        key_path = getattr(config, 'SSH_KEY_PATH', '/opt/Sentinel/conf/.id_ed25519')
        # Přijme JSON s PEM obsahem NEBO form data soubor
        if request.is_json:
            pem = (request.get_json(silent=True) or {}).get('pem', '').strip()
        else:
            f = request.files.get('key')
            if not f:
                return jsonify({"error": "Chybí soubor nebo PEM obsah"}), 400
            pem = f.read(32768).decode('utf-8', errors='replace').strip()
        if not pem.startswith('-----BEGIN'):
            return jsonify({"error": "Neplatný formát klíče (musí začínat -----BEGIN)"}), 400
        # Uložení
        try:
            os.makedirs(os.path.dirname(key_path), exist_ok=True)
            # Záloha starého klíče
            if os.path.exists(key_path):
                import shutil
                shutil.copy2(key_path, key_path + '.bak')
            with open(key_path, 'w') as kf:
                kf.write(pem + '\n')
            os.chmod(key_path, 0o600)
            # Ověř že je validní
            r = subprocess.run(['ssh-keygen', '-l', '-f', key_path],
                               capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                # Obnov zálohu
                if os.path.exists(key_path + '.bak'):
                    shutil.copy2(key_path + '.bak', key_path)
                return jsonify({"error": f"Neplatný klíč: {r.stderr.strip()}"}), 400
            fingerprint = r.stdout.strip()
            r2 = subprocess.run(['ssh-keygen', '-y', '-f', key_path],
                                capture_output=True, text=True, timeout=5)
            pubkey = r2.stdout.strip() if r2.returncode == 0 else None
            service.log_event("ssh_key_upload", f"SSH key uploaded, fingerprint: {fingerprint}", user=g.username)
            return jsonify({"status": "ok", "fingerprint": fingerprint, "pubkey": pubkey, "key_path": key_path})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/system/ssh-pubkey', methods=['GET'])
    @requires_auth
    def api_ssh_pubkey():
        """Vrátí veřejný klíč jako text pro zkopírování do authorized_keys."""
        key_path = getattr(config, 'SSH_KEY_PATH', '')
        if not key_path or not os.path.isfile(key_path):
            return jsonify({"error": "Klíč neexistuje"}), 404
        try:
            r = subprocess.run(['ssh-keygen', '-y', '-f', key_path],
                               capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                return jsonify({"error": r.stderr.strip()}), 500
            return jsonify({"pubkey": r.stdout.strip(), "key_path": key_path})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/system/ssh-test', methods=['POST'])
    @requires_auth
    def api_ssh_test():
        """Test SSH připojení vůči zadanému hostu pomocí aktuálního klíče."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.json or {}
        host = data.get('host', '').strip()
        if not host:
            return jsonify({"error": "Chybí host"}), 400
        key_path = getattr(config, 'SSH_KEY_PATH', '')
        ssh_user = getattr(config, 'SSH_USER', 'root')
        jump_host = getattr(config, 'SSH_JUMP_HOST', '')
        if not key_path or not os.path.isfile(key_path):
            return jsonify({"ok": False, "output": "Klíč nenalezen: " + key_path}), 200
        cmd = ['ssh', '-i', key_path, '-o', 'StrictHostKeyChecking=no',
               '-o', 'ConnectTimeout=8', '-o', 'BatchMode=yes']
        if jump_host:
            cmd += ['-J', jump_host]
        cmd += [f'{ssh_user}@{host}', 'hostname']
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            ok = r.returncode == 0
            output = (r.stdout.strip() or r.stderr.strip())[:500]
            return jsonify({"ok": ok, "output": output or ('OK' if ok else 'Selhalo')})
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "output": "Timeout (15s)"}), 200
        except Exception as e:
            return jsonify({"ok": False, "output": str(e)}), 200

    @bp.route('/api/system/logrotate', methods=['POST'])
    @requires_auth
    def api_logrotate_trigger():
        """093: Spustí logrotate pro sentinel logy z UI."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            result = subprocess.run(
                ['logrotate', '-f', '/etc/logrotate.d/sentinel'],
                capture_output=True, text=True, timeout=30
            )
            ok = result.returncode == 0
            service.log_event("logrotate", f"Logrotate triggered (rc={result.returncode})", user=g.username)
            return jsonify({
                "status": "ok" if ok else "error",
                "rc": result.returncode,
                "output": (result.stdout + result.stderr).strip()[:500] or "OK"
            })
        except FileNotFoundError:
            return jsonify({"error": "logrotate není nainstalován"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/system/test-url', methods=['POST'])
    @requires_auth
    def api_test_url():
        """Test HTTP dostupnosti URL (pro registrační modal)."""
        import requests as _req
        import time as _time
        d = request.json or {}
        url = (d.get('url') or '').strip().rstrip('/')
        if not url or not url.startswith('http'):
            return jsonify({"ok": False, "error": "Neplatná URL"}), 400
        try:
            t0 = _time.monotonic()
            r = _req.get(url, timeout=6, allow_redirects=True)
            ms = int((_time.monotonic() - t0) * 1000)
            return jsonify({"ok": r.status_code < 500, "status": r.status_code, "ms": ms})
        except _req.exceptions.ConnectionError:
            return jsonify({"ok": False, "error": "Nedostupné"})
        except _req.exceptions.Timeout:
            return jsonify({"ok": False, "error": "Timeout"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── 203: Public status page ─────────────────────────────────────────────
    @bp.route('/status')
    def public_status_page():
        """Public status page — no auth required. Configurable via status_page_enabled."""
        if not getattr(config, 'STATUS_PAGE_ENABLED', True):
            from flask import abort
            abort(404)
        try:
            agents = state.get_agents_health() if hasattr(state, 'get_agents_health') else []
        except Exception:
            agents = []
        online  = sum(1 for a in agents if a.get('status') == 'ONLINE')
        offline = sum(1 for a in agents if a.get('status') != 'ONLINE')
        active_issues = state.get_active_issues()
        counts = {'infra': 0, 'agent': 0, 'security': 0, 'root': 0}
        for i in active_issues:
            ch = (i.get('channel_type') or '').lower()
            if i.get('key', '').startswith('AGENT|'):
                counts['agent'] += 1
            elif ch == 'security':
                counts['security'] += 1
            elif ch == 'root':
                counts['root'] += 1
            else:
                counts['infra'] += 1
        total_issues = sum(counts.values())
        status_color = '#22c55e' if total_issues == 0 and offline == 0 else ('#ef4444' if total_issues > 0 else '#f59e0b')
        status_text  = 'Vše v pořádku' if total_issues == 0 and offline == 0 else ('Aktivní incidenty' if total_issues > 0 else 'Degradovaný výkon')
        instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')
        version  = getattr(config, 'VERSION', '')
        uptime   = service.get_uptime() if hasattr(service, 'get_uptime') else '?'
        from datetime import datetime as _dt
        now_str = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        rows_agents = ''.join(
            f'<tr><td style="padding:6px 12px;">{_esc(a.get("hostname","?"))}</td>'
            f'<td style="padding:6px 12px;color:{"#22c55e" if a.get("status")=="ONLINE" else "#ef4444"};">'
            f'{"● Online" if a.get("status")=="ONLINE" else "● Offline"}</td>'
            f'<td style="padding:6px 12px;color:#888;font-size:.85em;">{_esc(str(a.get("last_seen","?"))[:16])}</td></tr>'
            for a in agents
        )
        def _esc(s): import html; return html.escape(str(s))
        html_page = f"""<!DOCTYPE html>
<html lang="cs">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(instance)} — Status</title>
<style>
  body{{font-family:system-ui,sans-serif;background:#0f0f0f;color:#e0e0e0;margin:0;padding:0;}}
  .container{{max-width:700px;margin:40px auto;padding:0 16px;}}
  h1{{font-size:1.4em;margin:0 0 4px;}}
  .badge{{display:inline-block;padding:6px 18px;border-radius:20px;font-weight:700;font-size:1em;color:#fff;background:{status_color};margin-bottom:24px;}}
  .card{{background:#1a1a1a;border:1px solid #333;border-radius:8px;padding:16px 20px;margin-bottom:16px;}}
  .card h2{{font-size:.8em;text-transform:uppercase;letter-spacing:.06em;color:#888;margin:0 0 12px;}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
  .stat{{text-align:center;background:#111;border:1px solid #2a2a2a;border-radius:6px;padding:10px;}}
  .stat .n{{font-size:1.8em;font-weight:700;}}
  .stat .l{{font-size:.72em;color:#888;text-transform:uppercase;}}
  table{{width:100%;border-collapse:collapse;font-size:.88em;}}
  tr+tr{{border-top:1px solid #2a2a2a;}}
  footer{{text-align:center;color:#555;font-size:.78em;margin-top:24px;padding-bottom:24px;}}
</style></head>
<body><div class="container">
  <h1>{_esc(instance)} <span style="color:#555;font-size:.7em;">v{_esc(version)}</span></h1>
  <div class="badge">{_esc(status_text)}</div>
  <div class="card">
    <h2>Přehled</h2>
    <div class="grid">
      <div class="stat"><div class="n" style="color:#22c55e;">{online}</div><div class="l">Agenti online</div></div>
      <div class="stat"><div class="n" style="color:{"#ef4444" if offline > 0 else "#888"};">{offline}</div><div class="l">Agenti offline</div></div>
      <div class="stat"><div class="n" style="color:{"#ef4444" if total_issues > 0 else "#22c55e"};">{total_issues}</div><div class="l">Aktivní incidenty</div></div>
      <div class="stat"><div class="n" style="color:#888;">{_esc(uptime)}</div><div class="l">Uptime</div></div>
    </div>
  </div>
  {'<div class="card"><h2>Agenti</h2><table>' + rows_agents + '</table></div>' if agents else ''}
  <footer>Aktualizováno: {now_str} · Sentinel Commander</footer>
</div></body></html>"""
        from flask import Response as _Resp
        return _Resp(html_page, mimetype='text/html')

    @bp.route('/api/reports/capacity_plan', methods=['POST'])
    @requires_auth
    def api_capacity_plan():
        """163: AI interpretuje telemetrii a navrhne upgrade/resize doporučení."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        days = min(int(d.get('days', 7)), 30)
        limit = days * 24 * 12  # 5min samples

        try:
            conn = state._get_conn()
            # Aggregate key metrics per host/category — avg, max, last value
            rows = conn.execute("""
                SELECT category, metric,
                       AVG(value) as avg_val, MAX(value) as max_val,
                       MIN(timestamp) as first_ts, MAX(timestamp) as last_ts,
                       COUNT(*) as samples
                FROM (
                    SELECT category, metric, value, timestamp
                    FROM telemetry
                    WHERE timestamp >= datetime('now', ?)
                    ORDER BY timestamp DESC
                )
                WHERE metric IN ('cpu_pct','ram_pct','disk_pct','cpu','mem','disk',
                                 'swap_pct','load_avg','iops','net_rx','net_tx')
                   OR metric LIKE '%cpu%' OR metric LIKE '%mem%' OR metric LIKE '%disk%'
                   OR metric LIKE '%ram%'
                GROUP BY category, metric
                ORDER BY category, metric
            """, (f'-{days} days',)).fetchall()
            conn.close()
        except Exception as e:
            return jsonify({"error": f"DB chyba: {e}"}), 500

        if not rows:
            return jsonify({"report": None, "message": "Žádná telemetrie za zvolené období."})

        # Build summary per host
        host_data: dict = {}
        for cat, metric, avg_v, max_v, first_ts, last_ts, samples in rows:
            host_data.setdefault(cat, []).append({
                "metric": metric, "avg": round(avg_v, 1),
                "max": round(max_v, 1), "samples": samples
            })

        # Format summary for AI
        lines = []
        for host, metrics in host_data.items():
            lines.append(f"\nHost: {host}")
            for m in metrics:
                lines.append(f"  {m['metric']}: avg={m['avg']} max={m['max']} (n={m['samples']})")

        summary = "\n".join(lines)
        prompt = (
            f"Jsi expert na kapacitní plánování serverů. Analyzuj telemetrii za posledních {days} dní "
            "a navrhni konkrétní doporučení pro upgrade, resize nebo optimalizaci.\n\n"
            f"TELEMETRIE:\n{summary}\n\n"
            "Pro každý host kde vidíš problém nebo riziko napiš doporučení ve formátu:\n"
            "HOST: <hostname>\n"
            "PROBLÉM: <co je špatně nebo rizikové>\n"
            "DOPORUČENÍ: <konkrétní akce — upgrade RAM, přidat disk, optimalizovat CPU atd.>\n"
            "PRIORITA: <high/medium/low>\n\n"
            "Piš česky. Pokud jsou data v normálu, řekni to. Maximálně 10 doporučení."
        )

        try:
            raw = service.execute_ollama(prompt, num_ctx=3000, max_tokens=800)
        except Exception as e:
            return jsonify({"error": f"AI chyba: {e}"}), 500

        # Parse structured blocks from AI response
        import re as _re
        blocks = []
        current = {}
        for line in raw.splitlines():
            line = line.strip()
            for key, field in [("HOST:", "host"), ("PROBLÉM:", "problem"),
                                ("DOPORUČENÍ:", "recommendation"), ("PRIORITA:", "priority")]:
                if line.upper().startswith(key.upper()):
                    current[field] = line[len(key):].strip()
                    break
            if current.get("recommendation") and current.get("host"):
                blocks.append(current)
                current = {}
        if current.get("host"):
            blocks.append(current)

        return jsonify({
            "report": raw,
            "blocks": blocks,
            "hosts_analyzed": len(host_data),
            "days": days,
        })

    # ── 354: SSRF protection helper ─────────────────────────────────────────────

    def _is_private_url(url: str) -> bool:
        """Return True if URL resolves to a private/loopback IP range (SSRF guard)."""
        import ipaddress as _ipa
        import urllib.parse as _up
        import socket as _sock
        try:
            parsed = _up.urlparse(url)
            host = parsed.hostname or ''
            if not host:
                return True
            try:
                addr = _ipa.ip_address(host)
            except ValueError:
                # DNS resolve
                try:
                    addr = _ipa.ip_address(_sock.gethostbyname(host))
                except Exception:
                    return False  # Can't resolve — allow, will fail later
            return (addr.is_private or addr.is_loopback or
                    addr.is_link_local or addr.is_multicast or
                    addr.is_reserved)
        except Exception:
            return False

    @bp.route('/api/admin/validate_url', methods=['POST'])
    @requires_auth
    def api_admin_validate_url():
        """354: Validate a URL is not pointing to a private IP (SSRF check)."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        url = (request.json or {}).get('url', '').strip()
        if not url:
            return jsonify({"error": "url required"}), 400
        is_private = _is_private_url(url)
        return jsonify({"url": url, "safe": not is_private,
                        "warning": "URL resolves to private/loopback address — SSRF risk" if is_private else None})

    # ── 356: Rate limit /api/analyze/* ─────────────────────────────────────────

    _analyze_rate: dict = {}  # ip → [timestamps]
    _ANALYZE_MAX = 10  # 10/min per IP

    def _check_analyze_rate(ip: str) -> bool:
        import time as _t
        now = _t.time()
        window = _analyze_rate.setdefault(ip, [])
        _analyze_rate[ip] = [ts for ts in window if now - ts < 60]
        if len(_analyze_rate[ip]) >= _ANALYZE_MAX:
            return False
        _analyze_rate[ip].append(now)
        return True

    @bp.before_app_request
    def _rate_limit_analyze():
        if request.path.startswith('/api/analyze/'):
            ip = request.remote_addr or '127.0.0.1'
            if ip not in ('127.0.0.1', '::1') and not _check_analyze_rate(ip):
                return jsonify({"error": "Rate limit exceeded (max 10/min)"}), 429

    # ── 359: Security headers check ─────────────────────────────────────────────

    @bp.route('/api/admin/security_check', methods=['GET'])
    @requires_auth
    def api_admin_security_check():
        """359: Verify own CSP, HSTS, X-Frame-Options, and other security headers."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        import urllib.request as _ur
        results = []
        try:
            _base = f"http://127.0.0.1:{getattr(config, 'WEB_PORT', 5050)}"
            _req = _ur.Request(f"{_base}/", headers={"Cookie": request.headers.get("Cookie", "")})
            _resp = _ur.urlopen(_req, timeout=5)
            _headers = dict(_resp.headers)
        except Exception as e:
            # Fall back to checking current response headers
            _headers = {}
        # Merge with current request's response headers via a test approach
        checks = [
            ("Content-Security-Policy", "csp",
             lambda h: bool(h.get("Content-Security-Policy")),
             "Missing CSP header"),
            ("Strict-Transport-Security", "hsts",
             lambda h: bool(h.get("Strict-Transport-Security")),
             "Missing HSTS header (only relevant with HTTPS)"),
            ("X-Frame-Options", "x_frame",
             lambda h: bool(h.get("X-Frame-Options")),
             "Missing X-Frame-Options"),
            ("X-Content-Type-Options", "xcto",
             lambda h: h.get("X-Content-Type-Options", "").lower() == "nosniff",
             "X-Content-Type-Options should be 'nosniff'"),
            ("Referrer-Policy", "referrer",
             lambda h: bool(h.get("Referrer-Policy")),
             "Missing Referrer-Policy"),
        ]
        # Also check app's after_request headers
        from flask import current_app as _app
        _test_headers = {}
        for rule in _app.after_request_funcs.get(None, []):
            try:
                from flask import Response as _R
                _fake = _R()
                _updated = rule(_fake)
                if _updated:
                    for k, v in _updated.headers:
                        _test_headers[k] = v
            except Exception:
                pass
        _all_headers = {**_headers, **_test_headers}
        for header_name, key, check_fn, msg in checks:
            ok = check_fn(_all_headers)
            results.append({
                "header": header_name,
                "key": key,
                "present": bool(_all_headers.get(header_name)),
                "value": _all_headers.get(header_name, ""),
                "ok": ok,
                "warning": None if ok else msg,
            })
        score = sum(1 for r in results if r["ok"])
        return jsonify({
            "results": results,
            "score": score,
            "max_score": len(results),
            "grade": "A" if score == len(results) else ("B" if score >= len(results) - 1 else "C"),
        })

    # ── 339: Timezone display config ─────────────────────────────────────────────

    @bp.route('/api/timezone/convert', methods=['POST'])
    @requires_auth
    def api_timezone_convert():
        """339: Convert a UTC timestamp to the configured DISPLAY_TZ timezone."""
        d = request.json or {}
        ts = d.get('timestamp', '').strip()
        tz_name = d.get('tz', '') or getattr(config, 'DISPLAY_TZ', '') or 'UTC'
        if not ts:
            return jsonify({"error": "timestamp required"}), 400
        try:
            from datetime import datetime as _dt, timezone as _tz
            # Parse ISO timestamp
            if ts.endswith('Z'):
                ts = ts[:-1] + '+00:00'
            dt = _dt.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            try:
                import pytz as _pytz
                local_tz = _pytz.timezone(tz_name)
                local_dt = dt.astimezone(local_tz)
            except ImportError:
                # Fallback: just return UTC
                local_dt = dt
                tz_name = 'UTC'
            return jsonify({
                "original": ts,
                "converted": local_dt.strftime('%Y-%m-%d %H:%M:%S %Z'),
                "iso": local_dt.isoformat(),
                "tz": tz_name,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @bp.route('/api/timezone/info', methods=['GET'])
    @requires_auth
    def api_timezone_info():
        """339: Return current DISPLAY_TZ config."""
        tz = getattr(config, 'DISPLAY_TZ', '') or 'UTC'
        available = []
        try:
            import pytz as _pytz
            available = list(_pytz.all_timezones[:50])  # first 50 for UI picker
        except ImportError:
            pass
        return jsonify({"display_tz": tz, "available_timezones": available})

    # ── 427: Prompt library ─────────────────────────────────────────────────────

    @bp.route('/api/prompts', methods=['GET'])
    @requires_auth
    def api_prompts_get():
        """427: Return current PROMPTS dict from config/DB."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        prompts = dict(getattr(config, 'PROMPTS', {}))
        # Also check DB overrides
        try:
            conn = state._get_conn()
            rows = conn.execute("SELECT name, template FROM prompt_library ORDER BY name ASC").fetchall()
            conn.close()
            for name, template in rows:
                prompts[name] = template
        except Exception:
            pass  # Table may not exist yet
        return jsonify({"prompts": prompts})

    @bp.route('/api/prompts/<name>', methods=['PUT'])
    @requires_auth
    def api_prompts_update(name):
        """427: Update or create a prompt in DB."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        template = (request.json or {}).get('template', '').strip()
        if not template:
            return jsonify({"error": "template required"}), 400
        name = name.strip()[:64]
        try:
            with state.db_lock:
                conn = state._get_conn()
                conn.execute(
                    "INSERT INTO prompt_library (name, template, updated_by) VALUES (?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET template=excluded.template, updated_by=excluded.updated_by",
                    (name, template, g.username)
                )
                conn.commit()
                conn.close()
            # Also update in-memory config
            config.PROMPTS[name] = template
            service.log_event("prompt_update", f"Prompt '{name}' updated", user=g.username)
            return jsonify({"status": "ok", "name": name})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/prompts/<name>', methods=['DELETE'])
    @requires_auth
    def api_prompts_delete(name):
        """427: Delete a prompt override from DB."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            with state.db_lock:
                conn = state._get_conn()
                conn.execute("DELETE FROM prompt_library WHERE name=?", (name.strip(),))
                conn.commit()
                conn.close()
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/search', methods=['GET'])
    @requires_auth
    def api_global_search():
        """376: Fulltext vyhledávání napříč issues, agenty, wiki."""
        q = request.args.get('q', '').strip()
        if not q or len(q) < 2:
            return jsonify({"results": []})
        limit = int_param(request.args.get('limit', 20), 20, 1, 50)
        results = []
        try:
            conn = state._get_conn()
            import sqlite3 as _sq; conn.row_factory = _sq.Row
            like = f"%{q}%"
            for r in conn.execute("SELECT key, host, plugin_name, last_line, channel_type FROM problems WHERE (host LIKE ? OR last_line LIKE ? OR plugin_name LIKE ?) AND status IN ('active','acknowledged') LIMIT ?", (like, like, like, limit)).fetchall():
                results.append({"type": "issue", "icon": "triangle-exclamation", "title": f"{r['host']}: {(r['last_line'] or '')[:60]}", "subtitle": (r['channel_type'] or '').upper(), "key": r['key']})
            for r in conn.execute("SELECT hostname, status FROM agents WHERE hostname LIKE ? LIMIT ?", (like, limit // 2)).fetchall():
                results.append({"type": "agent", "icon": "server", "title": r['hostname'], "subtitle": r['status'], "key": r['hostname']})
            for r in conn.execute("SELECT slug, title FROM wiki_pages WHERE (title LIKE ? OR content LIKE ?) LIMIT ?", (like, like, limit // 4)).fetchall():
                results.append({"type": "wiki", "icon": "book", "title": r['title'], "subtitle": "Wiki", "key": r['slug']})
            conn.close()
        except Exception as e:
            logger.debug(f"global search: {e}")
        return jsonify({"results": results[:limit], "query": q})

    @bp.route('/api/admin/log_level', methods=['GET', 'POST'])
    @requires_auth
    def api_admin_log_level():
        """338: Čte nebo mění log level za běhu."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        root_logger = logging.getLogger()
        if request.method == 'GET':
            return jsonify({"level": logging.getLevelName(root_logger.level),
                            "levels": ["DEBUG", "INFO", "WARNING", "ERROR"]})
        level_str = (request.json or {}).get('level', '').upper()
        if level_str not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            return jsonify({"error": "Neplatný level"}), 400
        root_logger.setLevel(level_str)
        logging.getLogger('sentinel').setLevel(level_str)
        service.log_event("log_level_change", f"Log level → {level_str}", user=g.username)
        return jsonify({"status": "ok", "level": level_str})

    # ── Přidané endpointy (znovu přidané po merge) ────────────────────────────

    @bp.route('/api/admin/db_stats', methods=['GET'])
    @requires_auth
    def api_admin_db_stats():
        """300: DB statistiky — velikost + počty záznamů."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            db_path = getattr(state, 'DB_FILE', None)
            db_size_kb = round(os.path.getsize(db_path) / 1024, 1) if db_path and os.path.exists(db_path) else 0
            conn = state._get_conn()
            counts = {}
            for tbl in ('problems', 'issue_history', 'telemetry', 'sentinel_errors', 'actions'):
                try:
                    counts[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                except Exception:
                    counts[tbl] = 0
            conn.close()
            return jsonify({"db_size_kb": db_size_kb, "counts": counts,
                            "retention_days": getattr(config, 'DB_RETENTION_DAYS', 2)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/config/hash_password', methods=['POST'])
    @requires_auth
    def api_config_hash_password():
        """347: Vrátí bcrypt hash zadaného hesla."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        plain = (request.json or {}).get('password', '').strip()
        if not plain or len(plain) < 8:
            return jsonify({"error": "Heslo musí mít alespoň 8 znaků"}), 400
        try:
            import bcrypt as _bcrypt
            hashed = _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(rounds=12)).decode()
            return jsonify({"hash": hashed})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/admin/audit_trail', methods=['GET'])
    @requires_auth
    def api_admin_audit_trail():
        """311: Unified audit trail."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        limit = int_param(request.args.get('limit', 50), 50, 1, 200)
        events = []
        try:
            conn = state._get_conn()
            import sqlite3 as _sq; conn.row_factory = _sq.Row
            for r in conn.execute("SELECT changed_at as at, username as actor, 'config_change' as type, summary as detail FROM config_audit ORDER BY changed_at DESC LIMIT ?", (limit,)).fetchall():
                events.append(dict(r))
            for r in conn.execute("SELECT executed_at as at, actor, 'ssh_execute' as type, hostname||': '||command as detail FROM ssh_execute_log ORDER BY executed_at DESC LIMIT ?", (limit,)).fetchall():
                events.append(dict(r))
            for r in conn.execute("SELECT aa.at, aa.actor, 'action_'||aa.event as type, a.command||' ('||aa.event||')' as detail FROM action_audit aa JOIN actions a ON a.id=aa.action_id ORDER BY aa.at DESC LIMIT ?", (limit,)).fetchall():
                events.append(dict(r))
            conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        events.sort(key=lambda e: e.get('at') or '', reverse=True)
        return jsonify({"events": events[:limit]})

    @bp.route('/api/admin/prune', methods=['POST'])
    @requires_auth
    def api_admin_prune():
        """313: Manuální prune DB."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            from ..state_issues import prune_telemetry, prune_health_snapshots, prune_sentinel_errors, prune_revoked_sessions, prune_stale_sessions
            days = getattr(config, 'DB_RETENTION_DAYS', 2)
            prune_telemetry(days=days)
            prune_health_snapshots(days=30)
            prune_sentinel_errors(days=7)
            prune_revoked_sessions(days=30)
            prune_stale_sessions(hours=24)
            service.log_event("manual_prune", f"retention_days={days}", user=g.username)
            return jsonify({"status": "ok", "message": f"Prune dokončen (retence {days} dní)"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/admin/aggregate_telemetry', methods=['POST'])
    @requires_auth
    def api_admin_aggregate_telemetry():
        """300: Manuální agregace telemetrie."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            from ..state_issues import aggregate_telemetry
            hours = int_param((request.json or {}).get('after_hours', 24), 24, 1, 720)
            compressed = aggregate_telemetry(raw_after_hours=hours)
            service.log_event("aggregate_telemetry", f"compressed={compressed}", user=g.username)
            return jsonify({"status": "ok", "compressed_buckets": compressed})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp

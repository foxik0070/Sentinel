import secrets as _secrets
import hmac as _hmac
import hashlib as _hashlib
from flask import Blueprint, request, jsonify, g
from ..auth import requires_auth
from .. import state, config, utils
import logging
from datetime import datetime, timezone


_used_nonces: dict = {}  # 243: replay ochrana

def _verify_webhook_auth() -> bool:
    """237+243: Token/HMAC auth + replay ochrana přes timestamp."""
    import time as _t
    expected_token = getattr(config, 'INBOUND_WEBHOOK_TOKEN', '')
    if not expected_token:
        return True

    # 243: Replay ochrana — X-Webhook-Timestamp nesmí být starší než 5 min
    ts_header = request.headers.get('X-Webhook-Timestamp', '')
    if ts_header:
        try:
            ts = int(ts_header)
            if abs(_t.time() - ts) > 300:
                return False
        except ValueError:
            return False
        nonce_key = f"{expected_token[:8]}:{ts_header}"
        now = _t.time()
        if nonce_key in _used_nonces:
            return False
        _used_nonces[nonce_key] = now
        for k in list(_used_nonces):
            if now - _used_nonces[k] > 600:
                del _used_nonces[k]

    # 1. Token v query stringu
    token = request.args.get('token', '')
    if token and _secrets.compare_digest(token, expected_token):
        return True
    # 2. HMAC-SHA256 (GitHub / Alertmanager styl)
    sig_header = request.headers.get('X-Hub-Signature-256', '')
    if sig_header.startswith('sha256='):
        body = request.get_data()
        expected_sig = 'sha256=' + _hmac.new(
            expected_token.encode(), body, _hashlib.sha256
        ).hexdigest()
        if _secrets.compare_digest(sig_header, expected_sig):
            return True
    return False

logger = logging.getLogger("sentinel.chat")


def create_blueprint(service):
    bp = Blueprint('integrations', __name__)

    @bp.route('/api/integrations/<name>/status', methods=['GET'])
    @requires_auth
    def api_integration_status(name):
        allowed = {'teams', 'homeassistant', 'mqtt', 'webhook', 'slack', 'pagerduty',
                   'ntfy', 'gotify', 'smtp', 'matrix'}
        if name not in allowed:
            return jsonify({"error": "Unknown integration"}), 400
        if name == 'mqtt':
            connected = utils.mqtt_manager.connected if hasattr(utils, 'mqtt_manager') else False
            return jsonify({
                "enabled": getattr(config, 'MQTT_ENABLED', False),
                "connected": connected,
                "host": getattr(config, 'MQTT_HOST', ''),
                "port": getattr(config, 'MQTT_PORT', 1883),
                "user": getattr(config, 'MQTT_USER', '') or '',
                "topic_prefix": getattr(config, 'MQTT_TOPIC_PREFIX', 'sentinel'),
            })
        elif name == 'homeassistant':
            return jsonify({
                "enabled": getattr(config, 'HA_ENABLED', False),
                "url": getattr(config, 'HA_URL', ''),
                "notify_service": getattr(config, 'HA_NOTIFY_SERVICE', ''),
                "token_configured": bool(getattr(config, 'HA_TOKEN', '')),
            })
        elif name == 'teams':
            channels = getattr(config, 'TEAMS_CHANNELS', {})
            channel_names = [k for k, v in channels.items() if k not in ('enabled',) and isinstance(v, str) and v]
            general_wh = channels.get('general', '') if isinstance(channels, dict) else ''
            return jsonify({
                "enabled": getattr(config, 'TEAMS_ENABLED', False),
                "channels": channel_names,
                "channels_count": len(channel_names),
                "general_webhook": general_wh,
            })
        elif name == 'webhook':
            url = getattr(config, 'WEBHOOK_URL', '')
            return jsonify({
                "enabled": getattr(config, 'WEBHOOK_ENABLED', False),
                "url": url[:40] + '…' if len(url) > 40 else url,
                "url_full": url,
                "secret_configured": bool(getattr(config, 'WEBHOOK_SECRET', '')),
            })
        elif name == 'slack':
            wh_url = getattr(config, 'SLACK_WEBHOOK_URL', '')
            return jsonify({
                "enabled": getattr(config, 'SLACK_ENABLED', False),
                "webhook_configured": bool(wh_url),
                "webhook_url": wh_url,
                "channel": getattr(config, 'SLACK_CHANNEL', ''),
            })
        elif name == 'pagerduty':
            key = getattr(config, 'PAGERDUTY_ROUTING_KEY', '')
            return jsonify({
                "enabled": getattr(config, 'PAGERDUTY_ENABLED', False),
                "routing_key_configured": bool(key),
            })
        elif name == 'ntfy':
            return jsonify({
                "enabled": getattr(config, 'NTFY_ENABLED', False),
                "url_configured": bool(getattr(config, 'NTFY_URL', '')),
            })
        elif name == 'gotify':
            return jsonify({
                "enabled": getattr(config, 'GOTIFY_ENABLED', False),
                "url_configured": bool(getattr(config, 'GOTIFY_URL', '')),
                "token_configured": bool(getattr(config, 'GOTIFY_TOKEN', '')),
            })
        elif name == 'smtp':
            return jsonify({
                "enabled": getattr(config, 'SMTP_ENABLED', False),
                "host": getattr(config, 'SMTP_HOST', ''),
                "port": getattr(config, 'SMTP_PORT', 587),
                "to_configured": bool(getattr(config, 'SMTP_TO', '')),
            })
        elif name == 'matrix':
            return jsonify({
                "enabled": getattr(config, 'MATRIX_ENABLED', False),
                "url_configured": bool(getattr(config, 'MATRIX_URL', '')),
                "token_configured": bool(getattr(config, 'MATRIX_TOKEN', '')),
            })

    @bp.route('/api/integrations/<name>/toggle', methods=['POST'])
    @requires_auth
    def api_integration_toggle(name):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        var_map = {
            'teams': 'TEAMS_ENABLED',
            'homeassistant': 'HA_ENABLED',
            'mqtt': 'MQTT_ENABLED',
            'webhook': 'WEBHOOK_ENABLED',
            'slack': 'SLACK_ENABLED',
            'pagerduty': 'PAGERDUTY_ENABLED',
            'ntfy': 'NTFY_ENABLED',
            'gotify': 'GOTIFY_ENABLED',
            'smtp': 'SMTP_ENABLED',
            'matrix': 'MATRIX_ENABLED',
        }
        if name not in var_map:
            return jsonify({"error": "Unknown integration"}), 400
        try:
            var = var_map[name]
            current = bool(getattr(config, var, False))
            new_val = not current
            # Apply in-memory — no /etc write needed
            setattr(config, var, new_val)
            # Persist to DB so the toggle survives restarts
            state.set_setting(f"integration.{name}", '1' if new_val else '0')
            service.log_event("integration_toggle", f"Integration {name} set to {new_val}", user=g.username)
            return jsonify({"status": "ok", "enabled": new_val})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/integrations/<name>/save', methods=['POST'])
    @requires_auth
    def api_integration_save(name):
        """Save configuration for an integration directly to memory + YAML."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        allowed = {'teams', 'homeassistant', 'mqtt', 'webhook', 'slack', 'pagerduty',
                   'ntfy', 'gotify', 'smtp', 'matrix'}
        if name not in allowed:
            return jsonify({"error": "Unknown integration"}), 400

        import yaml as _yaml
        data = request.json or {}

        def _s(k): v = data.get(k); return str(v).strip() if v is not None else None
        def _b(k): v = data.get(k); return bool(v) if v is not None else None
        def _i(k):
            try: return int(data[k]) if k in data else None
            except Exception: return None

        # (config_attr, value, yaml_path_list)
        updates = []

        if name == 'mqtt':
            if _b('enabled') is not None: updates.append(('MQTT_ENABLED', _b('enabled'), ['mqtt','enabled']))
            if _s('host'): updates.append(('MQTT_HOST', _s('host'), ['mqtt','host']))
            if _i('port'): updates.append(('MQTT_PORT', _i('port'), ['mqtt','port']))
            if _s('user') is not None: updates.append(('MQTT_USER', _s('user'), ['mqtt','user']))
            if _s('topic_prefix'): updates.append(('MQTT_TOPIC_PREFIX', _s('topic_prefix'), ['mqtt','topic_prefix']))
            if _s('pass'): updates.append(('MQTT_PASS', _s('pass'), ['mqtt','pass']))
        elif name == 'homeassistant':
            if _b('enabled') is not None: updates.append(('HA_ENABLED', _b('enabled'), ['homeassistant','enabled']))
            if _s('url') is not None: updates.append(('HA_URL', _s('url'), ['homeassistant','url']))
            if _s('notify_service') is not None: updates.append(('HA_NOTIFY_SERVICE', _s('notify_service'), ['homeassistant','notify_service']))
            if _s('token'): updates.append(('HA_TOKEN', _s('token'), ['homeassistant','token']))
        elif name == 'teams':
            if _b('enabled') is not None: updates.append(('TEAMS_ENABLED', _b('enabled'), ['teams_channels','enabled']))
            if _s('webhook_url') is not None: updates.append(('_TEAMS_GENERAL', _s('webhook_url'), ['teams_channels','general']))
        elif name == 'webhook':
            if _b('enabled') is not None: updates.append(('WEBHOOK_ENABLED', _b('enabled'), ['webhook','enabled']))
            if _s('url') is not None: updates.append(('WEBHOOK_URL', _s('url'), ['webhook','url']))
            if _s('secret'): updates.append(('WEBHOOK_SECRET', _s('secret'), ['webhook','secret']))
        elif name == 'slack':
            if _b('enabled') is not None: updates.append(('SLACK_ENABLED', _b('enabled'), ['slack','enabled']))
            if _s('webhook_url') is not None: updates.append(('SLACK_WEBHOOK_URL', _s('webhook_url'), ['slack','webhook_url']))
            if _s('channel') is not None: updates.append(('SLACK_CHANNEL', _s('channel'), ['slack','channel']))
        elif name == 'pagerduty':
            if _b('enabled') is not None: updates.append(('PAGERDUTY_ENABLED', _b('enabled'), ['pagerduty','enabled']))
            if _s('routing_key'): updates.append(('PAGERDUTY_ROUTING_KEY', _s('routing_key'), ['pagerduty','routing_key']))
        elif name == 'ntfy':
            if _b('enabled') is not None: updates.append(('NTFY_ENABLED', _b('enabled'), ['ntfy','enabled']))
            if _s('url') is not None: updates.append(('NTFY_URL', _s('url'), ['ntfy','url']))
            if _s('token') is not None: updates.append(('NTFY_TOKEN', _s('token'), ['ntfy','token']))
        elif name == 'gotify':
            if _b('enabled') is not None: updates.append(('GOTIFY_ENABLED', _b('enabled'), ['gotify','enabled']))
            if _s('url') is not None: updates.append(('GOTIFY_URL', _s('url'), ['gotify','url']))
            if _s('token') is not None: updates.append(('GOTIFY_TOKEN', _s('token'), ['gotify','token']))
        elif name == 'smtp':
            if _b('enabled') is not None: updates.append(('SMTP_ENABLED', _b('enabled'), ['smtp','enabled']))
            if _s('host') is not None: updates.append(('SMTP_HOST', _s('host'), ['smtp','host']))
            if _i('port'): updates.append(('SMTP_PORT', _i('port'), ['smtp','port']))
            if _s('user') is not None: updates.append(('SMTP_USER', _s('user'), ['smtp','user']))
            if _s('password') is not None: updates.append(('SMTP_PASS', _s('password'), ['smtp','pass']))
            if _s('from') is not None: updates.append(('SMTP_FROM', _s('from'), ['smtp','from']))
            if _s('to') is not None: updates.append(('SMTP_TO', _s('to'), ['smtp','to']))
        elif name == 'matrix':
            if _b('enabled') is not None: updates.append(('MATRIX_ENABLED', _b('enabled'), ['matrix','enabled']))
            if _s('url') is not None: updates.append(('MATRIX_URL', _s('url'), ['matrix','url']))
            if _s('token') is not None: updates.append(('MATRIX_TOKEN', _s('token'), ['matrix','token']))

        if not updates:
            return jsonify({"status": "error", "message": "Žádné změny k uložení"}), 400

        # Apply in-memory
        for attr, val, _ in updates:
            if attr == '_TEAMS_GENERAL':
                tc = getattr(config, 'TEAMS_CHANNELS', {})
                if isinstance(tc, dict): tc['general'] = val
                config.TEAMS_CHANNELS = tc
            else:
                setattr(config, attr, val)

        # Persist to YAML
        cfg_path = str(config.CONFIG_PATH)
        try:
            with open(cfg_path, 'r') as f:
                cfg_yaml = _yaml.safe_load(f) or {}
            for _, val, path in updates:
                node = cfg_yaml
                for p in path[:-1]:
                    if p not in node or not isinstance(node[p], dict):
                        node[p] = {}
                    node = node[p]
                node[path[-1]] = val
            with open(cfg_path, 'w') as f:
                _yaml.dump(cfg_yaml, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            return jsonify({"status": "warning", "message": f"Uloženo v paměti, soubor selhal: {e}"})

        service.log_event("integration_save", f"Integration {name} config saved", user=g.username)
        return jsonify({"status": "ok"})

    @bp.route('/api/integrations/<name>/test', methods=['POST'])
    @requires_auth
    def api_integration_test(name):
        """Send a real test notification through the given integration (bypasses enabled flag)."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        allowed = {'teams', 'homeassistant', 'mqtt', 'webhook', 'slack', 'pagerduty', 'ntfy', 'gotify', 'smtp', 'matrix'}
        if name not in allowed:
            return jsonify({"error": "Unknown integration"}), 400

        test_msg = f"✅ Sentinel test — integrace {name} funguje. ({config.INSTANCE_NAME})"
        try:
            if name == 'teams':
                channels = getattr(config, 'TEAMS_CHANNELS', {})
                sent_to = []
                for ch, url in channels.items():
                    if ch == 'enabled' or not isinstance(url, str) or not url:
                        continue
                    import requests as _req
                    _req.post(url, json={"poster": "Sentinel", "location": "Channel",
                                         "body": {"messageBody": test_msg}},
                              headers={"Content-Type": "application/json"}, timeout=10)
                    sent_to.append(ch)
                if not sent_to:
                    return jsonify({"status": "error", "reply": "Žádné nakonfigurované kanály."})
                return jsonify({"status": "ok", "reply": f"Odesláno do: {', '.join(sent_to)}"})

            elif name == 'homeassistant':
                import requests as _req
                ha_url = getattr(config, 'HA_URL', '').rstrip('/')
                ha_token = getattr(config, 'HA_TOKEN', '')
                svc = getattr(config, 'HA_NOTIFY_SERVICE', 'notify')
                if not ha_url or not ha_token:
                    return jsonify({"status": "error", "reply": "HA URL nebo token nejsou nakonfigurovány."})
                url = f"{ha_url}/api/services/notify/{svc.lstrip('/')}"
                r = _req.post(url, json={"title": "Sentinel Test", "message": test_msg},
                              headers={"Authorization": f"Bearer {ha_token}",
                                       "Content-Type": "application/json"}, timeout=8)
                if r.status_code < 300:
                    return jsonify({"status": "ok", "reply": f"Odesláno na {svc}"})
                return jsonify({"status": "error", "reply": f"HA vrátil {r.status_code}: {r.text[:120]}"})

            elif name == 'mqtt':
                mgr = getattr(utils, 'mqtt_manager', None)
                if not mgr or not mgr.connected:
                    return jsonify({"status": "error", "reply": "MQTT není připojeno."})
                mgr.publish("test", {"message": test_msg, "source": "sentinel-test"})
                return jsonify({"status": "ok", "reply": f"Zpráva publikována na {config.MQTT_TOPIC_PREFIX}/…/test"})

            elif name == 'webhook':
                wh_url = getattr(config, 'WEBHOOK_URL', '')
                if not wh_url:
                    return jsonify({"status": "error", "reply": "Webhook URL není nastavena."})
                import requests as _req
                import hmac as _hmac
                import hashlib as _hashlib
                import json as _json
                body = _json.dumps({"event": "test", "message": test_msg,
                                   "instance": config.INSTANCE_NAME}).encode()
                headers = {"Content-Type": "application/json"}
                secret = getattr(config, 'WEBHOOK_SECRET', '')
                if secret:
                    sig = _hmac.new(secret.encode(), body, _hashlib.sha256).hexdigest()
                    headers['X-Sentinel-Signature'] = f'sha256={sig}'
                r = _req.post(wh_url, data=body, headers=headers, timeout=8)
                if r.status_code < 300:
                    return jsonify({"status": "ok", "reply": f"HTTP {r.status_code}"})
                return jsonify({"status": "error", "reply": f"Webhook vrátil {r.status_code}"})

            elif name == 'slack':
                import requests as _req
                slack_url = getattr(config, 'SLACK_WEBHOOK_URL', '')
                if not slack_url:
                    return jsonify({"status": "error", "reply": "Slack webhook URL není nastavena."})
                payload = {"text": test_msg}
                slack_ch = getattr(config, 'SLACK_CHANNEL', '')
                if slack_ch:
                    payload["channel"] = slack_ch
                r = _req.post(slack_url, json=payload,
                              headers={"Content-Type": "application/json"}, timeout=8)
                if r.status_code < 300:
                    return jsonify({"status": "ok", "reply": "Zpráva odeslána na Slack"})
                return jsonify({"status": "error", "reply": f"Slack vrátil {r.status_code}: {r.text[:120]}"})

            elif name == 'pagerduty':
                import requests as _req
                pd_key = getattr(config, 'PAGERDUTY_ROUTING_KEY', '')
                if not pd_key:
                    return jsonify({"status": "error", "reply": "PagerDuty routing key není nastaven."})
                body = {
                    "routing_key": pd_key,
                    "event_action": "trigger",
                    "payload": {
                        "summary": f"✅ Sentinel test — PagerDuty integrace funguje ({config.INSTANCE_NAME})",
                        "severity": "info",
                        "source": config.INSTANCE_NAME,
                    },
                    "dedup_key": "sentinel-test-notification",
                }
                r = _req.post("https://events.pagerduty.com/v2/enqueue",
                              json=body, headers={"Content-Type": "application/json"}, timeout=8)
                if r.status_code in (200, 202):
                    return jsonify({"status": "ok", "reply": "Test event odeslán do PagerDuty"})
                return jsonify({"status": "error", "reply": f"PagerDuty vrátil {r.status_code}: {r.text[:120]}"})

            # 273: ntfy.sh test
            elif name == 'ntfy':
                import requests as _req
                ntfy_url = getattr(config, 'NTFY_URL', '').rstrip('/')
                if not ntfy_url:
                    return jsonify({"status": "error", "reply": "NTFY_URL není nastaven"})
                hdrs = {"Title": "Sentinel Test", "Tags": "white_check_mark"}
                tok = getattr(config, 'NTFY_TOKEN', '')
                if tok:
                    hdrs['Authorization'] = f'Bearer {tok}'
                r = _req.post(ntfy_url, data=test_msg.encode(), headers=hdrs, timeout=8)
                return jsonify({"status": "ok" if r.status_code < 300 else "error",
                                "reply": f"ntfy HTTP {r.status_code}"})

            # 274: Gotify test
            elif name == 'gotify':
                import requests as _req
                g_url = getattr(config, 'GOTIFY_URL', '').rstrip('/')
                g_tok = getattr(config, 'GOTIFY_TOKEN', '')
                if not g_url or not g_tok:
                    return jsonify({"status": "error", "reply": "GOTIFY_URL nebo TOKEN není nastaven"})
                r = _req.post(f"{g_url}/message", params={"token": g_tok},
                              json={"title": "Sentinel Test", "message": test_msg, "priority": 5}, timeout=8)
                return jsonify({"status": "ok" if r.status_code < 300 else "error",
                                "reply": f"Gotify HTTP {r.status_code}"})

            # 275: SMTP test
            elif name == 'smtp':
                import smtplib
                import email.mime.text as _emt
                to = getattr(config, 'SMTP_TO', '')
                if not to:
                    return jsonify({"status": "error", "reply": "SMTP_TO není nastaven"})
                m = _emt.MIMEText(test_msg, 'plain', 'utf-8')
                m['Subject'] = "Sentinel Test"
                m['From'] = getattr(config, 'SMTP_FROM', 'sentinel@localhost')
                m['To'] = to
                with smtplib.SMTP(getattr(config, 'SMTP_HOST', 'localhost'),
                                   getattr(config, 'SMTP_PORT', 587)) as srv:
                    srv.ehlo()
                    if getattr(config, 'SMTP_PORT', 587) == 587:
                        srv.starttls()
                    u, p = getattr(config, 'SMTP_USER', ''), getattr(config, 'SMTP_PASS', '')
                    if u and p:
                        srv.login(u, p)
                    srv.sendmail(m['From'], to.split(','), m.as_string())
                return jsonify({"status": "ok", "reply": f"Email odeslán na {to}"})

            # 277: Matrix test
            elif name == 'matrix':
                import requests as _req, time as _t
                m_url = getattr(config, 'MATRIX_URL', '').strip()
                m_tok = getattr(config, 'MATRIX_TOKEN', '').strip()
                if not m_url or not m_tok:
                    return jsonify({"status": "error", "reply": "MATRIX_URL nebo TOKEN není nastaven"})
                txn_id = f"sentinel_test_{int(_t.time() * 1000)}"
                send_url = m_url if m_url.endswith('/send/m.room.message') else f"{m_url.rstrip('/')}/{txn_id}"
                r = _req.put(send_url,
                             json={"msgtype": "m.text", "body": test_msg},
                             headers={"Authorization": f"Bearer {m_tok}",
                                      "Content-Type": "application/json"}, timeout=8)
                return jsonify({"status": "ok" if r.status_code < 300 else "error",
                                "reply": f"Matrix HTTP {r.status_code}"})

        except Exception as e:
            return jsonify({"status": "error", "reply": str(e)})

    @bp.route('/api/channels/notify', methods=['GET'])
    @requires_auth
    def api_channels_notify_status():
        """Returns notify on/off per issue channel + integration enabled states."""
        channels = ['infra', 'agent', 'security', 'root']
        result = {}
        for ch in channels:
            val = state.get_setting(f'notify_channel.{ch}')
            result[ch] = (val != '0')  # default True
        result['_integrations'] = {
            'mqtt':        getattr(config, 'MQTT_ENABLED', False),
            'homeassistant': getattr(config, 'HA_ENABLED', False),
            'teams':       getattr(config, 'TEAMS_ENABLED', False),
            'webhook':     getattr(config, 'WEBHOOK_ENABLED', False),
            'slack':       getattr(config, 'SLACK_ENABLED', False),
            'pagerduty':   getattr(config, 'PAGERDUTY_ENABLED', False),
        }
        return jsonify(result)

    @bp.route('/api/channels/<channel>/notify/toggle', methods=['POST'])
    @requires_auth
    def api_channel_notify_toggle(channel):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        allowed = {'infra', 'agent', 'security', 'root'}
        if channel not in allowed:
            return jsonify({"error": "Unknown channel"}), 400
        current = state.get_setting(f'notify_channel.{channel}')
        new_val = '0' if current != '0' else '1'
        state.set_setting(f'notify_channel.{channel}', new_val)
        service.log_event("channel_notify", f"Channel {channel} notify={'on' if new_val=='1' else 'off'}", user=g.username)
        return jsonify({"status": "ok", "channel": channel, "notify": new_val == '1'})

    @bp.route('/api/inbound/grafana', methods=['POST'])
    def api_inbound_grafana():
        """184: Příjem Grafana alert webhooků (legacy i unified alerting)."""
        if not _verify_webhook_auth():
            return jsonify({"status": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        processed = 0

        # Unified alerting (Grafana v8+) — má "alerts" pole
        alerts = data.get('alerts')
        if isinstance(alerts, list):
            for alert in alerts:
                labels = alert.get('labels', {})
                annotations = alert.get('annotations', {})
                fingerprint = alert.get('fingerprint', '')
                alertname = labels.get('alertname', 'grafana_alert')
                instance = labels.get('instance', labels.get('job', 'grafana'))
                severity = labels.get('severity', 'warning').lower()
                summary = annotations.get('summary', annotations.get('description', alertname))
                status = alert.get('status', 'firing').lower()
                key = f"GRAFANA|{instance}|{alertname}|{fingerprint[:8] or 'x'}"
                channel = 'security' if severity in ('critical', 'error') else 'agent'
                if status == 'resolved':
                    state.mark_resolved(key)
                else:
                    state.save_problem(key, {
                        "status": "active", "channel_type": channel,
                        "host": instance, "plugin_name": f"grafana_{alertname.lower()}",
                        "last_line": f"[Grafana] {summary}"[:300],
                        "severity": severity if severity in ('low','medium','high','critical') else None,
                        "missing_count": 0, "last_seen": datetime.now(timezone.utc).isoformat(),
                    })
                processed += 1
        else:
            # Legacy Grafana webhook
            state_str = data.get('state', 'alerting').lower()
            rule = data.get('ruleName', data.get('title', 'grafana_alert'))
            msg = data.get('message', '') or ', '.join(
                f"{m['metric']}={m['value']}" for m in data.get('evalMatches', [])
            ) or rule
            key = f"GRAFANA|grafana|{rule}"
            if state_str == 'ok':
                state.mark_resolved(key)
            else:
                state.save_problem(key, {
                    "status": "active", "channel_type": "agent",
                    "host": "grafana", "plugin_name": "grafana_alert",
                    "last_line": f"[Grafana] {msg}"[:300],
                    "missing_count": 0, "last_seen": datetime.now(timezone.utc).isoformat(),
                })
            processed = 1

        service.log_event("grafana_inbound", f"alerts={processed}", level=logging.DEBUG)
        return jsonify({"status": "ok", "processed": processed})

    @bp.route('/api/inbound/alertmanager', methods=['POST'])
    def api_inbound_alertmanager():
        """194: Příjem Prometheus AlertManager webhooků."""
        if not _verify_webhook_auth():
            return jsonify({"status": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        alerts = data.get('alerts', [])
        processed = 0
        for alert in alerts:
            labels = alert.get('labels', {})
            annotations = alert.get('annotations', {})
            alertname = labels.get('alertname', 'am_alert')
            instance = labels.get('instance', labels.get('job', 'alertmanager'))
            severity = labels.get('severity', 'warning').lower()
            summary = annotations.get('summary', annotations.get('description', alertname))
            fingerprint = alert.get('fingerprint', '')
            status = alert.get('status', 'firing').lower()
            key = f"AM|{instance}|{alertname}|{fingerprint[:8] or 'x'}"
            channel = 'security' if severity in ('critical', 'error') else 'agent'
            if status == 'resolved':
                state.mark_resolved(key)
            else:
                state.save_problem(key, {
                    "status": "active", "channel_type": channel,
                    "host": instance, "plugin_name": f"am_{alertname.lower()}",
                    "last_line": f"[AlertManager] {summary}"[:300],
                    "severity": severity if severity in ('low','medium','high','critical') else None,
                    "missing_count": 0, "last_seen": datetime.now(timezone.utc).isoformat(),
                })
            processed += 1
        service.log_event("alertmanager_inbound", f"alerts={processed}", level=logging.DEBUG)
        return jsonify({"status": "ok", "processed": processed})

    @bp.route('/api/inbound/webhook', methods=['POST'])
    def api_inbound_webhook():
        if not _verify_webhook_auth():
            return jsonify({"status": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        # Mapování: source, title/message, severity, host, plugin
        host = str(data.get('host') or data.get('labels', {}).get('instance', 'external') or 'external')
        plugin = str(data.get('plugin') or data.get('labels', {}).get('alertname', 'inbound_webhook') or 'inbound_webhook')
        msg = str(data.get('message') or data.get('annotations', {}).get('summary', '') or data.get('title', '') or 'Inbound alert')
        severity = str(data.get('severity') or data.get('labels', {}).get('severity', '') or '').lower()
        channel = 'security' if severity in ('critical', 'error') else 'agent'
        key = f"INBOUND|{host}|{plugin}"
        status = str(data.get('status', 'active')).lower()
        if status in ('resolved', 'ok', 'firing') and status == 'resolved':
            state.mark_resolved(key)
            return jsonify({"status": "ok", "action": "resolved"})
        state.save_problem(key, {
            "status": "active",
            "last_line": msg[:300],
            "channel_type": channel,
            "plugin_name": plugin,
            "host": host,
            "severity": severity if severity in ('low', 'medium', 'high', 'critical') else None,
            "missing_count": 0,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "source": "inbound_webhook",
            "raw_payload": __import__('json').dumps(data)[:500],
        })
        return jsonify({"status": "ok", "key": key})

    @bp.route('/api/inbound/zabbix', methods=['POST'])
    def api_inbound_zabbix():
        """325: Příjem Zabbix alert webhooků (JSON formát Zabbix Media Type Webhook)."""
        if not _verify_webhook_auth():
            return jsonify({"status": "unauthorized"}), 401
        data = request.get_json(silent=True) or {}

        # Zabbix webhook posílá flat JSON s klíči: host, hostname, trigger_name,
        # trigger_status, trigger_severity, trigger_description, event_value (1=PROBLEM, 0=OK)
        host = str(data.get('hostname') or data.get('host') or 'zabbix')
        trigger = str(data.get('trigger_name') or data.get('name') or 'zabbix_alert')
        status = str(data.get('trigger_status') or data.get('event_value') or 'PROBLEM').upper()
        severity = str(data.get('trigger_severity') or data.get('severity') or '').lower()
        desc = str(data.get('trigger_description') or data.get('message') or trigger)
        event_id = str(data.get('event_id') or data.get('eventid') or 'z')
        key = f"ZABBIX|{host}|{trigger[:40]}|{event_id[:8]}"

        sev_map = {'disaster': 'critical', 'high': 'high', 'average': 'medium',
                   'warning': 'low', 'information': 'low', 'not classified': 'low'}
        norm_sev = sev_map.get(severity, None)
        channel = 'security' if norm_sev == 'critical' else 'agent'

        if status in ('OK', '0', 'RESOLVED'):
            state.mark_resolved(key)
            return jsonify({"status": "ok", "action": "resolved"})

        state.save_problem(key, {
            "status": "active", "channel_type": channel,
            "host": host, "plugin_name": f"zabbix_{trigger[:30].lower().replace(' ', '_')}",
            "last_line": f"[Zabbix] {trigger}: {desc}"[:300],
            "severity": norm_sev, "missing_count": 0,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        })
        service.log_event("zabbix_inbound", f"host={host} trigger={trigger}", level=logging.DEBUG)
        return jsonify({"status": "ok", "key": key})

    return bp

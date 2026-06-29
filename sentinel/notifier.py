"""
M2-2: Notifier — veškerá odchozí notifikační logika izolovaná od ChatService.

Použití:
    from sentinel.notifier import send_notification
    send_notification("alert_key", "security", "server01", "Disk full")

Throttling (363): per-severity — CRITICAL 15 min, HIGH 1h, ostatní 4h.
Retry (362): dočasné selhání → exponential backoff, max 3 pokusy, background vlákno.
"""
import json
import logging
import time
import hmac
import hashlib
import threading
from collections import deque

import requests

from . import config

logger = logging.getLogger("sentinel.notifier")

# ── 363: Per-severity throttle ────────────────────────────────────────────────
_THROTTLE_BY_SEV: dict[str, int] = {
    'critical': 900,    # 15 minut
    'security': 900,
    'root':     900,
    'high':     3600,   # 1 hodina
    'medium':   14400,  # 4 hodiny
    'low':      14400,
    'agent':    3600,
    'infra':    3600,
}
_THROTTLE_DEFAULT = 3600
_throttle: dict[str, float] = {}

def _throttle_seconds(channel: str) -> int:
    return _THROTTLE_BY_SEV.get(channel.lower(), _THROTTLE_DEFAULT)


# ── 362: Retry queue ──────────────────────────────────────────────────────────
_retry_queue: deque = deque(maxlen=200)  # [(fn, args, kwargs, attempt, next_run)]
_retry_lock = threading.Lock()
_RETRY_MAX = 3
_RETRY_BACKOFF = [30, 120, 300]  # sekundy mezi pokusy


def _retry_worker():
    """Background vlákno — zpracovává neúspěšné notifikace s backoffem."""
    while True:
        time.sleep(10)
        now = time.time()
        ready = []
        with _retry_lock:
            remaining = deque()
            while _retry_queue:
                item = _retry_queue.popleft()
                fn, args, kwargs, attempt, next_run = item
                if now >= next_run:
                    ready.append(item)
                else:
                    remaining.append(item)
            _retry_queue.extend(remaining)

        for fn, args, kwargs, attempt, _ in ready:
            try:
                fn(*args, **kwargs)
            except Exception as e:
                if attempt < _RETRY_MAX:
                    delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    with _retry_lock:
                        _retry_queue.append((fn, args, kwargs, attempt + 1, time.time() + delay))
                else:
                    logger.warning(f"Notifier: {fn.__name__} selhal po {_RETRY_MAX} pokusech: {e}")


_retry_thread = threading.Thread(target=_retry_worker, daemon=True, name="NotifierRetry")
_retry_thread.start()


def _with_retry(fn, *args, **kwargs):
    """Spustí fn okamžitě; při výjimce zařadí do retry fronty."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Notifier {fn.__name__} první pokus selhal ({e}), plánuji retry")
        with _retry_lock:
            _retry_queue.append((fn, args, kwargs, 1, time.time() + _RETRY_BACKOFF[0]))


def send_notification(key: str, channel: str, host: str, msg: str) -> None:
    """Odešle notifikaci přes všechny nakonfigurované integrace.

    363: Throttle per severity — CRITICAL/security/root 15min, HIGH 1h, ostatní 4h.
    362: Dočasné selhání → retry s exponential backoff (max 3 pokusy).
    """
    throttle_key = f"notify_{key}"
    now_ts = time.time()
    throttle_secs = _throttle_seconds(channel)
    if now_ts - _throttle.get(throttle_key, 0) < throttle_secs:
        return
    _throttle[throttle_key] = now_ts

    instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')
    # 337: Instance name v titulku — důležité pro multi-instance setups
    title = f"🚨 [{instance}] {channel.upper()} alert"
    body = f"[{host}] {msg[:200]}"

    _with_retry(_send_teams, title, body, channel, instance)
    _with_retry(_send_webhook, key, channel, host, msg, title, instance)
    _with_retry(_send_pagerduty, key, channel, title, body, msg, instance)
    _with_retry(_send_slack, title, body, channel)
    _with_retry(_send_ntfy, title, body, channel)
    _with_retry(_send_gotify, title, body, channel)
    _with_retry(_send_smtp, title, body)
    _with_retry(_send_ha, title, body)
    _with_retry(_send_matrix, title, body)
    _with_retry(_send_discord, title, body, channel)
    _with_retry(_send_telegram, title, body)
    _with_retry(_send_opsgenie, key, channel, title, body, instance)
    _with_retry(_send_grafana_annotation, key, channel, host, msg)
    send_ha_action(channel)


# ── Kanály ────────────────────────────────────────────────────────────────────

def _send_teams(title: str, body: str, channel: str, instance: str) -> None:
    if not getattr(config, 'TEAMS_ENABLED', False):
        return
    channels = getattr(config, 'TEAMS_CHANNELS', {})
    ch_url = (channels.get(channel)
              or channels.get('all')
              or next((v for k, v in channels.items()
                       if k != 'enabled' and isinstance(v, str) and v), None))
    if not ch_url:
        return
    try:
        requests.post(ch_url,
                      json={"poster": instance, "location": "Alert",
                            "body": {"messageBody": f"**{title}**\n{body}"}},
                      headers={"Content-Type": "application/json"}, timeout=8)
    except Exception as e:
        logger.warning(f"Teams notify failed: {e}")


def _send_webhook(key: str, channel: str, host: str, msg: str,
                  title: str, instance: str) -> None:
    if not getattr(config, 'WEBHOOK_ENABLED', False):
        return
    wh_url = getattr(config, 'WEBHOOK_URL', '')
    if not wh_url:
        return
    try:
        payload = json.dumps({"event": "new_alert", "key": key,
                              "channel": channel, "host": host,
                              "message": msg[:500], "instance": instance}).encode()
        headers = {"Content-Type": "application/json"}
        secret = getattr(config, 'WEBHOOK_SECRET', '')
        if secret:
            sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
            headers['X-Sentinel-Signature'] = f'sha256={sig}'
        requests.post(wh_url, data=payload, headers=headers, timeout=8)
    except Exception as e:
        logger.warning(f"Webhook notify failed: {e}")


def _send_pagerduty(key: str, channel: str, title: str, body: str,
                    msg: str, instance: str) -> None:
    if not getattr(config, 'PAGERDUTY_ENABLED', False):
        return
    pd_key = getattr(config, 'PAGERDUTY_ROUTING_KEY', '')
    if not pd_key:
        return
    try:
        sev_map = {'security': 'critical', 'root': 'critical',
                   'agent': 'error', 'infra': 'warning'}
        requests.post("https://events.pagerduty.com/v2/enqueue",
                      json={"routing_key": pd_key, "event_action": "trigger",
                            "payload": {"summary": f"{title}: {body[:200]}",
                                        "severity": sev_map.get(channel.lower(), 'warning'),
                                        "source": instance, "component": channel,
                                        "custom_details": {"host": "", "message": msg[:500]}},
                            "dedup_key": f"sentinel-{key[:80]}"},
                      headers={"Content-Type": "application/json"}, timeout=8)
    except Exception as e:
        logger.warning(f"PagerDuty notify failed: {e}")


def _send_slack(title: str, body: str, channel: str) -> None:
    if not getattr(config, 'SLACK_ENABLED', False):
        return
    slack_url = getattr(config, 'SLACK_WEBHOOK_URL', '')
    if not slack_url:
        return
    try:
        payload: dict = {"text": f"*{title}*\n{body}"}
        slack_ch = getattr(config, 'SLACK_CHANNEL', '')
        if slack_ch:
            payload["channel"] = slack_ch
        requests.post(slack_url, json=payload,
                      headers={"Content-Type": "application/json"}, timeout=8)
    except Exception as e:
        logger.warning(f"Slack notify failed: {e}")


def _send_ntfy(title: str, body: str, channel: str) -> None:
    if not getattr(config, 'NTFY_ENABLED', False):
        return
    ntfy_url = getattr(config, 'NTFY_URL', '').rstrip('/')
    if not ntfy_url:
        return
    try:
        hdrs = {"Title": title,
                "Priority": "high" if channel in ('security', 'root') else "default",
                "Tags": channel}
        token = getattr(config, 'NTFY_TOKEN', '')
        if token:
            hdrs['Authorization'] = f'Bearer {token}'
        requests.post(ntfy_url, data=body.encode(), headers=hdrs, timeout=8)
    except Exception as e:
        logger.warning(f"ntfy notify failed: {e}")


def _send_gotify(title: str, body: str, channel: str) -> None:
    if not getattr(config, 'GOTIFY_ENABLED', False):
        return
    url = getattr(config, 'GOTIFY_URL', '').rstrip('/')
    token = getattr(config, 'GOTIFY_TOKEN', '')
    if not url or not token:
        return
    try:
        prio = 9 if channel in ('security', 'root') else 5
        requests.post(f"{url}/message", params={"token": token},
                      json={"title": title, "message": body, "priority": prio},
                      timeout=8)
    except Exception as e:
        logger.warning(f"Gotify notify failed: {e}")


def _send_smtp(title: str, body: str) -> None:
    if not getattr(config, 'SMTP_ENABLED', False):
        return
    smtp_to = getattr(config, 'SMTP_TO', '')
    if not smtp_to:
        return
    try:
        import smtplib
        import email.mime.text as _emt
        msg_obj = _emt.MIMEText(f"{title}\n\n{body}\n\n-- Sentinel Commander", 'plain', 'utf-8')
        msg_obj['Subject'] = title
        msg_obj['From'] = getattr(config, 'SMTP_FROM', 'sentinel@localhost')
        msg_obj['To'] = smtp_to
        host = getattr(config, 'SMTP_HOST', 'localhost')
        port = getattr(config, 'SMTP_PORT', 587)
        u, p = getattr(config, 'SMTP_USER', ''), getattr(config, 'SMTP_PASS', '')
        # 289: port 465 = SSL (SMTP_SSL), port 587 = STARTTLS, ostatní = plain
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as srv:
                srv.ehlo()
                if u and p:
                    srv.login(u, p)
                srv.sendmail(msg_obj['From'], smtp_to.split(','), msg_obj.as_string())
        else:
            with smtplib.SMTP(host, port) as srv:
                srv.ehlo()
                if port == 587:
                    srv.starttls()
                if u and p:
                    srv.login(u, p)
                srv.sendmail(msg_obj['From'], smtp_to.split(','), msg_obj.as_string())
    except Exception as e:
        logger.warning(f"SMTP notify failed: {e}")


def _send_matrix(title: str, body: str) -> None:
    """277: Matrix/Element webhook notifikace."""
    if not getattr(config, 'MATRIX_ENABLED', False):
        return
    url = getattr(config, 'MATRIX_URL', '').strip()
    token = getattr(config, 'MATRIX_TOKEN', '').strip()
    if not url or not token:
        return
    try:
        import time as _t, json as _json
        txn_id = f"sentinel_{int(_t.time() * 1000)}"
        send_url = url if url.endswith('/send/m.room.message') else f"{url.rstrip('/')}/{txn_id}"
        requests.put(send_url,
                     json={"msgtype": "m.text", "body": f"{title}\n{body}"},
                     headers={"Authorization": f"Bearer {token}",
                              "Content-Type": "application/json"}, timeout=8)
    except Exception as e:
        logger.warning(f"Matrix notify failed: {e}")


def send_ha_action(channel: str) -> None:
    """278: Zavolá nakonfigurovanou HA service akci (napr. light/turn_on) při kritickém alertu."""
    if not getattr(config, 'HA_ENABLED', False):
        return
    ha_url = getattr(config, 'HA_URL', '').rstrip('/')
    ha_token = getattr(config, 'HA_TOKEN', '')
    svc = getattr(config, 'HA_ACTION_SERVICE', '').strip('/')
    entity = getattr(config, 'HA_ACTION_ENTITY', '').strip()
    if not ha_url or not ha_token or not svc:
        return
    if channel.lower() not in ('security', 'root', 'critical'):
        return
    try:
        payload = {"entity_id": entity} if entity else {}
        requests.post(f"{ha_url}/api/services/{svc}",
                      json=payload,
                      headers={"Authorization": f"Bearer {ha_token}",
                               "Content-Type": "application/json"}, timeout=5)
    except Exception as e:
        logger.debug(f"HA action failed: {e}")


def _send_grafana_annotation(key: str, channel: str, host: str, msg: str) -> None:
    """326: Odešle annotation do Grafana při critical/security alertu."""
    gf_url = getattr(config, 'GRAFANA_URL', '').rstrip('/')
    gf_key = getattr(config, 'GRAFANA_API_KEY', '').strip()
    if not gf_url or not gf_key:
        return
    if channel.lower() not in ('security', 'root', 'critical'):
        return
    try:
        import time as _t
        requests.post(f"{gf_url}/api/annotations",
                      json={"time": int(_t.time() * 1000), "isRegion": False,
                            "tags": ["sentinel", channel.lower()],
                            "text": f"[{host}] {msg[:200]}"},
                      headers={"Authorization": f"Bearer {gf_key}",
                               "Content-Type": "application/json"}, timeout=5)
    except Exception as e:
        logger.debug(f"Grafana annotation failed: {e}")


def _send_discord(title: str, body: str, channel: str) -> None:
    """321: Discord webhook — Embeds format s barvou dle severity."""
    if not getattr(config, 'DISCORD_ENABLED', False):
        return
    url = getattr(config, 'DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        return
    color_map = {'security': 0xdc3545, 'root': 0xffc107, 'agent': 0x28a745, 'infra': 0x0078d4}
    color = color_map.get(channel.lower(), 0x888888)
    try:
        requests.post(url, json={
            "embeds": [{"title": title, "description": body[:2000], "color": color}]
        }, timeout=8)
    except Exception as e:
        logger.warning(f"Discord notify failed: {e}")


def _send_telegram(title: str, body: str) -> None:
    """322: Telegram bot notifikace."""
    if not getattr(config, 'TELEGRAM_ENABLED', False):
        return
    token = getattr(config, 'TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = getattr(config, 'TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return
    try:
        text = f"*{title}*\n{body[:3000]}"
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                      timeout=8)
    except Exception as e:
        logger.warning(f"Telegram notify failed: {e}")


def _send_opsgenie(key: str, channel: str, title: str, body: str, instance: str) -> None:
    """323: Opsgenie alert."""
    if not getattr(config, 'OPSGENIE_ENABLED', False):
        return
    api_key = getattr(config, 'OPSGENIE_API_KEY', '').strip()
    if not api_key:
        return
    try:
        sev_map = {'security': 'P1', 'root': 'P1', 'agent': 'P2', 'infra': 'P3'}
        requests.post("https://api.opsgenie.com/v2/alerts",
                      json={
                          "message": f"{title}: {body[:130]}",
                          "alias": f"sentinel-{key[:80]}",
                          "description": body[:1000],
                          "priority": sev_map.get(channel.lower(), 'P3'),
                          "source": instance,
                          "tags": [channel, "sentinel"],
                      },
                      headers={"Authorization": f"GenieKey {api_key}",
                               "Content-Type": "application/json"},
                      timeout=8)
    except Exception as e:
        logger.warning(f"Opsgenie notify failed: {e}")


def _send_ha(title: str, body: str) -> None:
    if not getattr(config, 'HA_ENABLED', False):
        return
    ha_url = getattr(config, 'HA_URL', '').rstrip('/')
    ha_token = getattr(config, 'HA_TOKEN', '')
    svc = getattr(config, 'HA_NOTIFY_SERVICE', 'notify')
    if not ha_url or not ha_token:
        return
    try:
        requests.post(f"{ha_url}/api/services/notify/{svc.lstrip('/')}",
                      json={"title": title, "message": body},
                      headers={"Authorization": f"Bearer {ha_token}",
                               "Content-Type": "application/json"}, timeout=8)
    except Exception as e:
        logger.warning(f"HA notify failed: {e}")

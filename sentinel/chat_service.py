import logging
import threading
import os
import html
import collections
import subprocess
import requests
import json
import yaml
import base64
import re
import time
import shutil
import uuid
import platform
import sqlite3
from datetime import datetime, timezone, timedelta
from functools import wraps
import numpy as np
from flask import Flask, request, jsonify, render_template, Response, g, session, redirect, url_for
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

try:
    from flask_ldap3_login import LDAP3LoginManager
except ImportError:
    LDAP3LoginManager = None

from . import state
from . import utils
from . import config
from . import actions
from . import rag 
from . import analytics

# --- STRUCTURED LOGGING SETUP ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        if hasattr(record, 'event_type'):
            log_entry['event_type'] = record.event_type
        if hasattr(record, 'duration_ms'):
            log_entry['duration_ms'] = record.duration_ms
        if hasattr(record, 'user'):
            log_entry['user'] = record.user
            
        return json.dumps(log_entry)

logger = logging.getLogger("sentinel.chat")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]
logger.setLevel(logging.INFO)
ldap_manager = None

# --- AUTH HELPER ---
def _role_for_user(username: str) -> str | None:
    """Check DB role overrides first, then return None to fall through to defaults."""
    try:
        from . import state as _state
        db_roles = {r['username']: r['role'] for r in _state.get_all_user_roles()}
        return db_roles.get(username)
    except Exception:
        return None

def check_auth(username, password):
    if username == config.WEB_USER and password == config.WEB_PASS:
        return _role_for_user(username) or 'admin'
    if username == config.WEB_VIEWER_USER and password == config.WEB_VIEWER_PASS:
        return _role_for_user(username) or 'viewer'

    if config.LDAP_ENABLED and ldap_manager:
        try:
            logger.info(f"LDAP CHECK: Overuji uzivatele '{username}'...")
            response = ldap_manager.authenticate(username, password)

            is_success = False
            if hasattr(response.status, 'value') and response.status.value == 'success':
                is_success = True
            elif str(response.status) == 'success':
                is_success = True
            elif str(response.status) == 'AuthenticationResponseStatus.success':
                is_success = True

            if is_success:
                logger.info(f"LDAP: Prihlaseni USPESNE pro {username}")
                db_role = _role_for_user(username)
                if db_role:
                    return db_role
                if username in config.LDAP_SUPERADMINS:
                    return 'superadmin'
                if username in config.LDAP_ADMINS:
                    return 'admin'
                if username in getattr(config, 'LDAP_OPERATORS', []):
                    return 'operator'
                if username in config.LDAP_VIEWERS:
                    return 'viewer'
                return 'admin'
            else:
                logger.warning(f"LDAP FAIL: Uzivatel '{username}' nebyl overen.")
                logger.warning(f"LDAP STATUS: {response.status}")

        except Exception as e:
            logger.error(f"LDAP Auth Error: {e}")

    return None

def authenticate():
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for('login'))

global_active_clients = {}
global_active_clients_lock = threading.Lock()

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr
        if not client_ip.startswith('192.168.') and not client_ip in ['127.0.0.1', '::1']:
            if utils.security.is_ip_banned(client_ip): return Response("Banned", 403)
        
        tracked_user = "anonymous"
        is_mobile = False
        
        client_user_header = request.headers.get('X-Client-User')
        if client_user_header:
            is_mobile = True

        # 1. KONTROLA PREZENCE X-API-KEY (mobilní aplikace nebo REST API klíče)
        api_key = request.headers.get('X-API-Key')
        secure_token = getattr(config, 'CLIENT_API_KEY', 'sentinel_secret_token_2026')

        if api_key and api_key == secure_token:
            g.user_role = 'superadmin'
            g.username = client_user_header if client_user_header else 'admin'
            tracked_user = f"{g.username} (Mobil)"
        elif api_key:
            # Ověření přes DB api_keys tabulku
            key_rec = state.verify_api_key(api_key)
            if key_rec:
                scope = key_rec.get('scope', 'read')
                g.user_role = 'superadmin' if scope == 'admin' else ('admin' if scope == 'write' else 'viewer')
                g.username = key_rec.get('name', 'api-key')
                tracked_user = f"{g.username} (API Key)"
            else:
                return authenticate()
            
        # 2. KONTROLA WEBOVÉ RELACE (Cookies pro Web UI)
        elif 'user' in session:
            # Zkontrolovat revokaci session
            _suuid = session.get('_suuid')
            if _suuid and _suuid in _REVOKED_SESSIONS:
                session.clear()
                return authenticate()
            g.user_role = session.get('role', 'user')
            g.username = session.get('user', 'anonymous')
            tracked_user = g.username
            # Touch session v DB (throttle — ne každý request)
            if _suuid:
                import time as _t
                _now_t = _t.time()
                if _now_t - _SESSION_TOUCH_TS.get(_suuid, 0) > 60:
                    _SESSION_TOUCH_TS[_suuid] = _now_t
                    state.session_touch(_suuid)
            
        # 3. HTTP BASIC AUTH (Fallback)
        else:
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password):
                if auth: utils.security.register_failed_login(client_ip)
                return authenticate()
            
            g.user_role = check_auth(auth.username, auth.password)
            g.username = auth.username
            tracked_user = f"{g.username} (Mobil)" if is_mobile else g.username
        
        # Aktualizace Connection Trackeru — jen pro lidské klienty (ne agenty/zařízení)
        _agent_paths = ('/api/v1/', '/api/sentinel-hw/', '/api/sentinel-alert')
        _is_agent_request = any(request.path.startswith(p) for p in _agent_paths)
        _is_excluded_device = client_ip in getattr(config, 'EXCLUDED_CLIENT_IPS', [])
        if not _is_agent_request and not _is_excluded_device:
            now = time.time()
            device_id = request.headers.get('X-Device-ID', client_ip)
            with global_active_clients_lock:
                global_active_clients[device_id] = {
                    "user": tracked_user,
                    "ip": client_ip,
                    "device_id": device_id,
                    "connected_since": global_active_clients.get(device_id, {}).get("connected_since", now),
                    "last_seen": now,
                    "is_mobile": is_mobile
                }
            
        return f(*args, **kwargs)
    return decorated

IGNORED_FILE = os.path.join(config.LOG_DIR, "ignored_issues.json")

# Session cache for sentinel-hw device proxying (avoids login on every request)
_hw_sessions: dict = {}
_hw_sessions_lock = threading.Lock()

def _hw_get_session(base_url: str, hostname: str) -> requests.Session:
    """Return an authenticated requests.Session for a sentinel-hw device, re-logging in if needed."""
    session = requests.Session()
    for user, passwd in [(config.WEB_USER, config.WEB_PASS), ('admin', 'sentinel')]:
        try:
            resp = session.post(f"{base_url}/login",
                                data={'username': user, 'password': passwd},
                                allow_redirects=False, timeout=5)
            if resp.status_code == 302:
                return session
        except Exception:
            pass
    return session

_REVOKED_SESSIONS: set = set()   # UUID revokovanych sessions (in-memory blacklist)
_SESSION_TOUCH_TS: dict = {}     # suuid → timestamp posledniho touch (throttle)

class ChatService(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.name = "Sentinel-WebChat"
        self.llm_semaphore = threading.Semaphore(1)
        self.chat_queue_depth = 0
        self.last_cleanup_time = None
        
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
        self.app = Flask(__name__, template_folder=template_dir)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')

        # Gzip komprese statických souborů a API odpovědí
        try:
            from flask_compress import Compress
            self.app.config['COMPRESS_MIMETYPES'] = [
                'text/html', 'text/css', 'text/javascript', 'application/javascript',
                'application/json', 'text/plain',
            ]
            self.app.config['COMPRESS_LEVEL'] = 6
            self.app.config['COMPRESS_MIN_SIZE'] = 2048
            Compress(self.app)
        except ImportError:
            pass

        # Global request size cap: 16 MiB. Werkzeug aborts with 413 before reading body.
        self.app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

        self.app.secret_key = getattr(config, 'SECRET_KEY', 'fallback-key')

        @self.app.after_request
        def _add_security_headers(resp):
            # Bezpečnostní HTTP hlavičky
            resp.headers['X-Frame-Options'] = 'DENY'
            resp.headers['X-Content-Type-Options'] = 'nosniff'
            resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            resp.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
            # CSP: povolujeme CDN pro Chart.js, FontAwesome, Swagger UI; inline scripts pro Jinja2
            resp.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
                "font-src 'self' cdn.jsdelivr.net; "
                "img-src 'self' data: blob:; "
                "connect-src 'self' ws: wss:; "
                "frame-ancestors 'none';"
            )
            # 369: Cache-Control + ETag pro statické soubory — versioning přes ?v= zajišťuje invalidaci
            if request.path.startswith('/static/'):
                ext = request.path.rsplit('.', 1)[-1].lower()
                if ext in ('js', 'css', 'woff', 'woff2', 'ttf', 'svg', 'ico', 'png'):
                    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
                    # ETag from content hash if not already set
                    if not resp.headers.get('ETag') and resp.data:
                        import hashlib as _hl
                        _etag = _hl.md5(resp.data).hexdigest()[:16]
                        resp.headers['ETag'] = f'"{_etag}"'
                        # Conditional GET support
                        if request.headers.get('If-None-Match') == f'"{_etag}"':
                            resp.status_code = 304
                            resp.data = b''
            elif request.path in ('/', '/index'):
                resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return resp
        
        if config.LDAP_ENABLED:
            if LDAP3LoginManager:
                # Fix: nastavit ldap_manager v auth modulu (check_auth ho čte odtud)
                from . import auth as _auth_mod
                ldap_host = config.LDAP_HOST
                if not ldap_host.startswith(('ldap://', 'ldaps://')):
                   ldap_host = f"ldap://{ldap_host}"
                self.app.config['LDAP_HOST'] = ldap_host
                self.app.config['LDAP_PORT'] = config.LDAP_PORT
                self.app.config['LDAP_USE_SSL'] = config.LDAP_USE_SSL
                self.app.config['LDAP_ALWAYS_SEARCH_BIND'] = True
                self.app.config['LDAP_SEARCH_FOR_GROUPS'] = False
                
                self.app.config['LDAP_BASE_DN'] = config.LDAP_BASE_DN
                self.app.config['LDAP_USER_DN'] = config.LDAP_SEARCH_USER_DN
                self.app.config['LDAP_USER_LOGIN_ATTR'] = config.LDAP_USER_LOGIN_ATTR
                
                ldap_obj_filter = getattr(config, 'LDAP_USER_OBJECT_FILTER', None)
                if ldap_obj_filter:
                    self.app.config['LDAP_USER_OBJECT_FILTER'] = ldap_obj_filter
                self.app.config['LDAP_USER_SEARCH_SCOPE'] = 'SUBTREE'
                self.app.config['LDAP_ALWAYS_SEARCH_BIND'] = True
                
                self.app.config['LDAP_BIND_USER_DN'] = getattr(config, 'LDAP_BIND_DN', None)
                self.app.config['LDAP_BIND_USER_PASSWORD'] = getattr(config, 'LDAP_BIND_PASSWORD', None)
 
                try:
                    _auth_mod.ldap_manager = LDAP3LoginManager(self.app)
                except Exception as e:
                    logger.error(f"Failed to initialize LDAP: {e}")
            else:
                logger.warning("LDAP enabled in config but 'flask_ldap3_login' is NOT installed.")

        self.start_time = datetime.now()
        self.conversation_history = []
        # 425: Register issue lifecycle callbacks
        from .state_base import _issue_lifecycle_callbacks
        _service_ref = self
        def _lifecycle_cb(event, issue):
            try:
                threading.Thread(
                    target=_service_ref._dispatch_issue_lifecycle_webhook,
                    args=(event, issue), daemon=True
                ).start()
                if event == 'ISSUE_CREATED':
                    threading.Thread(
                        target=_service_ref._sync_gitea_issue,
                        args=(issue,), daemon=True
                    ).start()
            except Exception:
                pass
        _issue_lifecycle_callbacks.clear()
        _issue_lifecycle_callbacks.append(_lifecycle_cb)
        self.user_sessions = {}
  
        self.metrics = {
            "ai_requests": 0,
            "ai_errors": 0,
            "ai_latency_history": collections.deque(maxlen=50),
            "cmd_executed": 0,
            "active_users": set(),
            "start_timestamp": time.time()
        }

        self.setup_routes()
        self.ignored_issues = self.load_ignored_issues()
        self.active_file = None 
        
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

        self.socketio.start_background_task(self.broadcast_alerts_loop)
        self.socketio.start_background_task(self.daily_cleanup_loop)
        self.socketio.start_background_task(self.action_cleanup_loop)
        self.socketio.start_background_task(self.mqtt_telemetry_loop)
        self.socketio.start_background_task(self.ssh_update_check_loop)

    def log_event(self, event_type, message, user=None, duration_ms=None, level=logging.INFO):
        extra = {'event_type': event_type}
        if user: extra['user'] = user
        if duration_ms is not None: extra['duration_ms'] = round(duration_ms, 2)
        logger.log(level, message, extra=extra)

    def run(self):
        # 374: Startup time profiling
        _startup_t0 = time.time()
        self.log_event("startup", f"Starting ChatService at http://{config.WEB_HOST}:{config.WEB_PORT}")
        # Start memory watchdog (375)
        threading.Thread(target=self._memory_watchdog, daemon=True, name="MemWatchdog").start()
        utils.mqtt_manager.start()
        
        # --- BEZPEČNÝ FIX PRO PYTHON 3.13 & WERKZEUG 3.X WSGI COMPATIBILITY ---
        class WSGISocketIOFix:
            def __init__(self, wsgi_app):
                self.wsgi_app = wsgi_app
            def __call__(self, environ, start_response):
                status_called = []
                def custom_start_response(status, headers, exc_info=None):
                    status_called.append(status)
                    return start_response(status, headers, exc_info)
                
                ret = self.wsgi_app(environ, custom_start_response)
                if not status_called and '/socket.io/' in environ.get('PATH_INFO', ''):
                    try:
                        start_response('200 OK', [('Content-Type', 'text/plain'), ('Content-Length', '0')])
                    except:
                        pass
                return ret

        try:
            # Oprava: Wrapper se musí injektovat do FLASK aplikace, nikoliv do SocketIO
            self.app.wsgi_app = WSGISocketIOFix(self.app.wsgi_app)
            # 374: Log startup duration
            _startup_dur = round(time.time() - _startup_t0, 2)
            self.log_event("startup_ready", f"Init complete in {_startup_dur}s")

            ssl_ctx = None
            if config.HTTPS_ENABLED and config.HTTPS_CERT_FILE and config.HTTPS_KEY_FILE:
                import ssl as _ssl
                ssl_ctx = (_ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
                           if not hasattr(_ssl, 'create_default_context') else _ssl.create_default_context(_ssl.Purpose.CLIENT_AUTH))
                ssl_ctx.load_cert_chain(config.HTTPS_CERT_FILE, config.HTTPS_KEY_FILE)
                utils.log_message(f"HTTPS enabled: cert={config.HTTPS_CERT_FILE}")

            if config.HTTPS_ENABLED and config.HTTPS_USE_HTTP2:
                # HTTP/2 via hypercorn (must be installed separately)
                try:
                    import hypercorn.asyncio
                    import hypercorn.config as hc
                    import asyncio as _aio
                    hcfg = hc.Config()
                    hcfg.bind = [f"{config.WEB_HOST}:{config.WEB_PORT}"]
                    if config.HTTPS_CERT_FILE:
                        hcfg.certfile = config.HTTPS_CERT_FILE
                        hcfg.keyfile = config.HTTPS_KEY_FILE
                    utils.log_message("HTTP/2 mode via hypercorn")
                    _aio.run(hypercorn.asyncio.serve(self.app, hcfg))
                    return
                except ImportError:
                    utils.log_message("hypercorn not installed — falling back to Werkzeug HTTPS")

            self.socketio.run(self.app, host=config.WEB_HOST, port=config.WEB_PORT,
                              debug=False, use_reloader=False, allow_unsafe_werkzeug=True,
                              ssl_context=ssl_ctx)
        except Exception as e:
            self.log_event("startup_error", f"Web Server failed: {e}", level=logging.CRITICAL)

    def broadcast_alerts_loop(self):
        while True:
            try:
                item = state.frontend_queue.get()
                if item: self.socketio.emit('new_alert', item)
            except Exception: time.sleep(1)

    def mqtt_telemetry_loop(self):
        """Odesílá kompletní telemetrii do MQTT každých 15s. Bezpečné float parsování."""
        self.log_event("task_scheduler", "Starting MQTT unified telemetry loop.")
        while True:
            try:
                time.sleep(15)
                if getattr(config, 'MQTT_ENABLED', False) and hasattr(utils, 'mqtt_manager') and utils.mqtt_manager.connected:
                    m = self.get_detailed_metrics()
                    
                    # ---------------------------------------------------------
                    # SČÍTÁNÍ OKRUHŮ PRO MQTT SENZORY (FIX PRO "Neznámý" STAV)
                    # ---------------------------------------------------------
                    all_active = state.get_active_issues()
                    visible = [i for i in all_active if i.get("key") not in self.ignored_issues]
                    
                    infra_count = 0
                    agent_count = 0
                    root_count = 0
                    security_count = 0
                    
                    for i in visible:
                        key = i.get('key', '')
                        ch = i.get('channel_type', '').lower()
                        
                        if ch == 'security':
                            security_count += 1
                        elif ch == 'root':
                            root_count += 1
                        elif key.startswith('AGENT|'):
                            agent_count += 1
                        else:
                            infra_count += 1

                    # Bezpečné parsování swapu
                    swap_str = str(m.get('swap', '0'))
                    try:
                        swap_val = int(float(swap_str.split()[0])) if ' ' in swap_str else int(float(swap_str))
                    except ValueError:
                        swap_val = 0
                    
                    # Vyčištění hodnoty latence pro HA (odstranění jednotky 's')
                    try:
                        latency_val = float(str(m.get('ai_lat', '0s')).replace('s', ''))
                    except ValueError:
                        latency_val = 0.0

                    # Kompletní JSON payload, který přesně odpovídá Auto-Discovery v utils.py
                    payload = {
                        "cpu_load": m.get('cpu_pct', 0),
                        "ram_usage": m.get('ram_pct', 0),
                        "disk_usage": m.get('disk_pct', 0),
                        "swap_usage": swap_val,
                        "db_size": m.get('db_size', '0 B'),
                        "threads": m.get('threads', 0),
                        "ai_requests": m.get('ai_req', 0),
                        "ai_latency": latency_val,
                        "queue_depth": self.chat_queue_depth,
                        "active_issues": infra_count,       # Pouze obecné infra incidenty
                        "agent_issues": agent_count,         # FIX: Reálná data pro HA
                        "root_issues": root_count,           # FIX: Reálná data pro HA
                        "security_issues": security_count,   # FIX: Reálná data pro HA
                        "uptime": m.get('uptime', '0:00:00'),
                        "rag_status": rag.rag_system.get_status() if hasattr(rag, 'rag_system') else "Unknown",
                        "active_clients": len(global_active_clients)
                    }
                    
                    # Odeslání do jednotného telemetrického topicu
                    utils.mqtt_manager.publish("telemetry", payload)
            except Exception as e:
                logger.error(f"MQTT Telemetry error: {e}")

    def get_uptime(self): return str(datetime.now() - self.start_time).split('.')[0]

    def _memory_watchdog(self):
        """375: RSS memory watchdog — warn + telemetry if RSS > 1.5 GB."""
        import time as _t
        _RSS_WARN_MB = 1536  # 1.5 GB
        _CHECK_INTERVAL = 120  # every 2 minutes
        _alerted = False
        while True:
            try:
                _t.sleep(_CHECK_INTERVAL)
                import resource as _res
                rss_kb = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss
                # Linux: kilobytes; macOS: bytes
                import sys as _sys
                if _sys.platform == 'darwin':
                    rss_mb = rss_kb / (1024 * 1024)
                else:
                    rss_mb = rss_kb / 1024
                state.save_telemetry('sentinel.rss_mb', round(rss_mb, 1), 'sentinel')
                if rss_mb > _RSS_WARN_MB:
                    if not _alerted:
                        self.log_event("memory_warn", f"RSS memory usage {rss_mb:.0f} MB > {_RSS_WARN_MB} MB threshold", level=logging.WARNING)
                        try:
                            state.log_sentinel_error("memory_watchdog",
                                f"High RSS: {rss_mb:.0f} MB (threshold {_RSS_WARN_MB} MB)", level="WARNING")
                        except Exception:
                            pass
                        _alerted = True
                else:
                    _alerted = False
            except Exception as _e:
                logger.debug(f"memory_watchdog: {_e}")

    def action_cleanup_loop(self):
        self.log_event("task_scheduler", "Starting Action Cleanup Watchdog")
        while True:
            try:
                time.sleep(60) 
                pending_actions = state.get_pending_actions()
                if not pending_actions: continue
                now = datetime.now(timezone.utc)
                for action in pending_actions:
                    try:
                        created_str = action.get('created_at')
                        if not created_str: continue
                        created_dt = datetime.fromisoformat(created_str)
                        if (now - created_dt).total_seconds() > 900:
                            aid = action['id']
                            self.log_event("cleanup", f"Auto-expiring stuck action #{aid} (>15m)", level=logging.WARNING)
                            state.update_action_status(aid, "expired", "Timeout (15m auto-cleanup)", "System")
                    except Exception as e:
                        logger.error(f"Error parsing action time: {e}")
            except Exception as e:
                logger.error(f"Error in action_cleanup_loop: {e}")
                time.sleep(5)

    def ssh_update_check_loop(self):
        """Optional: periodically SSH each ONLINE agent to check for pending apt upgrades."""
        # Initial delay — let the system settle at startup
        for _ in range(60):
            if state.shutdown_event.is_set():
                return
            time.sleep(1)

        while not state.shutdown_event.is_set():
            if getattr(config, 'SSH_UPDATE_CHECK_ENABLED', False):
                try:
                    agents = [a for a in state.get_all_agents()
                              if a['status'] == 'ONLINE'
                              and not a['hostname'].startswith('sentinel-hw-')
                              and not a['hostname'].startswith('sentinel-alert')]
                    for agent in agents:
                        hostname = agent['hostname']
                        key = f"UPDATES|{hostname}"
                        try:
                            result = subprocess.run(
                                ['ssh', '-o', 'StrictHostKeyChecking=no',
                                 '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes',
                                 hostname,
                                 'apt list --upgradable 2>/dev/null | grep -c "\\[" || echo 0'],
                                capture_output=True, text=True, timeout=15
                            )
                            if result.returncode == 0:
                                lines = result.stdout.strip().splitlines()
                                count = int(lines[-1]) if lines and lines[-1].isdigit() else 0
                                if count > 0:
                                    payload = {
                                        'host': hostname,
                                        'cluster': actions._find_cluster_for_host(hostname) or hostname,
                                        'plugin_name': 'ssh_update_check',
                                        'last_line': f"{count} package(s) available for upgrade on {hostname}",
                                        'channel_type': 'agent',
                                        'status': 'active',
                                        'last_seen': datetime.now(timezone.utc).isoformat(),
                                    }
                                    is_new = state.save_problem(key, payload)
                                    if is_new:
                                        actions.maybe_suggest_remediation(key, payload)
                                else:
                                    state.mark_resolved(key)
                        except Exception:
                            pass  # SSH not available for this host — skip
                except Exception as e:
                    logger.error(f"SSH update check error: {e}")

            interval = getattr(config, 'SSH_UPDATE_CHECK_INTERVAL', 3600)
            for _ in range(interval):
                if state.shutdown_event.is_set():
                    return
                time.sleep(1)

    def _send_daily_report(self):
        """Sestaví denní shrnutí a odešle přes nakonfigurované integrace."""
        try:
            active = state.get_active_issues()
            agents = state.get_all_agents()
            online_agents = [a for a in agents if a.get('status') == 'ONLINE']
            offline_agents = [a for a in agents if a.get('status') != 'ONLINE' and not a.get('ignore_offline')]
            today_str = datetime.now().strftime('%Y-%m-%d')
            instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')

            # Počty per kanál
            ch_counts: dict = {}
            plugin_counts: dict = {}
            top_hosts: dict = {}
            for i in active:
                ch = i.get('channel_type', 'unknown').upper()
                ch_counts[ch] = ch_counts.get(ch, 0) + 1
                pl = i.get('plugin_name', 'unknown')
                plugin_counts[pl] = plugin_counts.get(pl, 0) + 1
                h = i.get('host', 'unknown')
                top_hosts[h] = top_hosts.get(h, 0) + 1

            top_plugins = sorted(plugin_counts.items(), key=lambda x: -x[1])[:5]
            top_h = sorted(top_hosts.items(), key=lambda x: -x[1])[:5]

            # Sestavení zprávy
            lines = [
                f"📊 Sentinel denní report — {today_str}",
                f"Instance: {instance}",
                f"",
                f"🔔 Aktivní alertů: {len(active)} | Agentů: {len(online_agents)} online / {len(offline_agents)} offline",
            ]
            if ch_counts:
                lines.append("Kanály: " + " | ".join(f"{k}: {v}" for k, v in sorted(ch_counts.items())))
            if top_plugins:
                lines.append("Top pluginy: " + ", ".join(f"{p}({c})" for p, c in top_plugins))
            if top_h:
                lines.append("Top hosté: " + ", ".join(f"{h}({c})" for h, c in top_h))
            if offline_agents:
                offline_names = ", ".join(a['hostname'] for a in offline_agents[:8])
                if len(offline_agents) > 8:
                    offline_names += f" (+{len(offline_agents)-8})"
                lines.append(f"⚠️ Offline: {offline_names}")

            msg = "\n".join(lines)
            self._send_notification("daily_report", "report", "sentinel", msg)
            logger.info(f"Daily report sent: {len(active)} active issues, {len(offline_agents)} offline agents")
        except Exception as e:
            logger.error(f"Daily report error: {e}")

    _last_health_snap_hour = -1
    _last_self_monitor_ts = 0
    _last_weekly_report_date = None

    def _check_heartbeat_urls(self):
        """407: Ping HEARTBEAT_URLS; create issue on failure, resolve on success.
        409: Also check SSL certificate expiry for HTTPS URLs.
        """
        hb_urls = getattr(config, 'HEARTBEAT_URLS', [])
        if not hb_urls:
            return
        import urllib.request as _ur
        import ssl as _ssl_mod
        import socket as _sock
        for entry in hb_urls:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name', 'heartbeat')
            url = entry.get('url', '').strip()
            timeout = int(entry.get('timeout_s', 10))
            if not url:
                continue
            issue_key = f"HEARTBEAT|{name}"
            try:
                req = _ur.Request(url, method='GET')
                resp = _ur.urlopen(req, timeout=timeout)
                if resp.status < 400:
                    state.resolve_problem(issue_key)
                else:
                    state.save_problem(issue_key, {
                        "status": "active", "channel_type": "infra", "host": name,
                        "last_line": f"Heartbeat URL '{url}' returned HTTP {resp.status}",
                        "plugin_name": "heartbeat_monitor",
                        "last_seen": datetime.now(timezone.utc).isoformat(), "missing_count": 0,
                    })
            except Exception as e:
                state.save_problem(issue_key, {
                    "status": "active", "channel_type": "infra", "host": name,
                    "last_line": f"Heartbeat URL '{url}' unreachable: {e}",
                    "plugin_name": "heartbeat_monitor",
                    "last_seen": datetime.now(timezone.utc).isoformat(), "missing_count": 0,
                })
            # 409: SSL certificate expiry check for HTTPS URLs
            if url.startswith('https://'):
                ssl_key = f"SSL_EXPIRY|{name}"
                try:
                    import urllib.parse as _up
                    parsed = _up.urlparse(url)
                    host = parsed.hostname or ''
                    port = parsed.port or 443
                    ctx = _ssl_mod.create_default_context()
                    with _sock.create_connection((host, port), timeout=timeout) as raw:
                        with ctx.wrap_socket(raw, server_hostname=host) as s:
                            cert = s.getpeercert()
                            expire_str = cert.get('notAfter', '')
                            from datetime import datetime as _dt
                            expire_dt = _dt.strptime(expire_str, '%b %d %H:%M:%S %Y %Z')
                            days_left = (expire_dt - _dt.utcnow()).days
                            if days_left <= 14:
                                state.save_problem(ssl_key, {
                                    "status": "active", "channel_type": "security", "host": name,
                                    "last_line": f"SSL cert for '{host}' expires in {days_left} days ({expire_str})",
                                    "plugin_name": "ssl_expiry_check",
                                    "last_seen": datetime.now(timezone.utc).isoformat(), "missing_count": 0,
                                })
                            else:
                                state.resolve_problem(ssl_key)
                except Exception as _se:
                    logger.debug(f"ssl_expiry_check {name}: {_se}")

    def _run_self_monitor_webhook(self):
        url = getattr(config, 'SELF_MONITOR_WEBHOOK', '')
        interval = int(getattr(config, 'SELF_MONITOR_INTERVAL', 300))
        if not url:
            return
        now_ts = time.time()
        if now_ts - self.__class__._last_self_monitor_ts < interval:
            return
        self.__class__._last_self_monitor_ts = now_ts
        try:
            m = self.get_detailed_metrics()
            active = state.get_active_issues()
            agents = state.get_all_agents()
            payload = {
                "instance": getattr(config, 'INSTANCE_NAME', 'Sentinel'),
                "version": getattr(config, 'VERSION', '?'),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "health_score": max(0, 100 - len(active)*2 - m['cpu_pct']//5 - m['ram_pct']//5),
                "active_issues": len(active),
                "agents_online": sum(1 for a in agents if a.get('status') == 'ONLINE'),
                "agents_total": len(agents),
                "cpu_pct": m['cpu_pct'],
                "ram_pct": m['ram_pct'],
            }
            import urllib.request as _ur
            req = _ur.Request(url, data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"}, method='POST')
            _ur.urlopen(req, timeout=5)
            logger.debug(f"self_monitor webhook sent to {url}")
        except Exception as e:
            logger.debug(f"self_monitor_webhook error: {e}")

    def _send_weekly_report(self):
        try:
            active = state.get_active_issues()
            agents = state.get_all_agents()
            offline_agents = [a for a in agents if a.get('status') != 'ONLINE' and not a.get('ignore_offline')]
            # Top recurring issues (occurrence_count)
            top_recurring = sorted(active, key=lambda i: -(i.get('occurrence_count') or 1))[:5]
            # SLA breaches
            sla_rules = getattr(config, 'SLA_RULES', {})
            sla_breach = []
            now_utc = datetime.now(timezone.utc)
            for i in active:
                ch = (i.get('channel_type') or '').lower()
                if ch in sla_rules:
                    try:
                        fs = datetime.fromisoformat(i.get('first_seen') or i.get('last_seen', ''))
                        if fs.tzinfo is None: fs = fs.replace(tzinfo=timezone.utc)
                        if (now_utc - fs).total_seconds() / 3600 > sla_rules[ch]:
                            sla_breach.append(i)
                    except Exception: pass
            lines = [
                f"📋 Sentinel týdenní report — {now_utc.strftime('%Y-%m-%d')}",
                f"Instance: {getattr(config, 'INSTANCE_NAME', 'Sentinel')}",
                f"",
                f"📊 Aktivní alertů: {len(active)} | Agentů offline: {len(offline_agents)}",
                f"⏰ SLA violations: {len(sla_breach)}",
            ]
            if top_recurring:
                lines.append("🔁 Nejčastější issues:")
                for i in top_recurring:
                    occ = i.get('occurrence_count', 1)
                    lines.append(f"  ×{occ} [{i.get('plugin_name','?')}] {i.get('host','?')}: {(i.get('last_line',''))[:60]}")
            if offline_agents:
                lines.append("⚠️ Offline agenti: " + ", ".join(a['hostname'] for a in offline_agents[:10]))
            self._send_notification("weekly_report", "report", "sentinel", "\n".join(lines))
            logger.info(f"Weekly report sent: {len(active)} issues, {len(sla_breach)} SLA breaches")
        except Exception as e:
            logger.error(f"_send_weekly_report: {e}")

    def _save_health_snapshot(self):
        now = datetime.now()
        if now.hour == self.__class__._last_health_snap_hour:
            return
        self.__class__._last_health_snap_hour = now.hour
        try:
            m = self.get_detailed_metrics()
            active = state.get_active_issues()
            agents = state.get_all_agents()
            online = sum(1 for a in agents if a.get('status') == 'ONLINE')
            score = max(0, 100 - (len(active) * 2) - (m['cpu_pct'] // 5) - (m['ram_pct'] // 5))
            state.save_health_snapshot(score, len(active), online, len(agents))
        except Exception as e:
            logger.debug(f"_save_health_snapshot: {e}")

    def _generate_hourly_joke(self):
        """Hodinový sarkastický vtip o aktuálním stavu infrastruktury ze šablon."""
        try:
            import random as _r
            from datetime import datetime, timezone

            TEMPLATES_ISSUE = [
                # klep-klep
                "Klep klep.\n— Kdo je?\n— {host}.\n— {host} kdo?\n— {host}, ten co má {plugin} v prdeli už {age}.",
                "Klep klep.\n— Kdo je?\n— {plugin}.\n— {plugin} kdo?\n— {plugin} na {host}. Pořád. Furt. Dokola.",
                "Klep klep.\n— Kdo je?\n— Monitoring.\n— Monitoring kdo?\n— Monitoring, co ti hlásí že {host} má problém s {plugin}. Překvapení.",
                "Klep klep.\n— Kdo je?\n— Alert.\n— Alert kdo?\n— Alert číslo {count} dnes. {host}. {plugin}. Zvykej si.",
                "Klep klep.\n— Kdo je?\n— On-call.\n— On-call kdo?\n— On-call, co kvůli {host} a {plugin} dnes zas nespí.",
                "Klep klep.\n— Kdo je?\n— {host}.\n— {host} kdo?\n— {host}, tvůj oblíbený server. Ten s {plugin}. Zase.",
                # jednořádkový sarkazmus
                "Dnešní předpověď počasí: {host} — zataženo, {plugin} mimo provoz, šance na opravu 20 %.",
                "Motivační citát dne: Nevzdávej se. {host} to taky neudělal, a podívej kde je teď.",
                "{host} má {plugin} rozbité už {age}. Grafana to ví. Ty to víš. Všichni to ví. Nikdo nic nedělá.",
                "Funguje to? Ne. Opraví se to? Možná. Kdy? {host} odpoví jakmile bude mít chuť.",
                "Stav infrastruktury: {count} alertů. Nálada týmu: nekomentujeme.",
                "Dobrá zpráva: monitoring funguje. Špatná zpráva: {host} s {plugin} rozhodně ne.",
                "{host} slaví {age} bez {plugin}. Pošleme dort?",
                # horoskop styl
                "Horoskop pro {host}: Dnes není vhodný den pro {plugin}. Vlastně žádný den není.",
                "Horoskop pro správce: Hvězdy říkají, že {host} tě dnes zklamal. Hvězdy mají pravdu.",
                # podpora / ticket styl
                "TICKET #∞ — {host}: {plugin} nefunguje {age}. Priorita: kritická. Status: neřeší se.",
                "Vážený zákazníku, váš server {host} eviduje problém s {plugin} od {age}. Omlouváme se za komplikace. Váš tým ops.",
                # filozofický
                "Pokud {host} spadne do lesa a nikdo ho nevidí, pád stejně zaloguje. A {plugin} to hlásí {age}.",
                "Co dřív? {host} nebo {plugin}? Dnes ani jedno nefunguje, takže to je jedno.",
            ]
            TEMPLATES_OK = [
                # klep-klep ok
                "Klep klep.\n— Kdo je?\n— Infrastruktura.\n— Infrastruktura kdo?\n— Infrastruktura, co dnes nic nehlásí. Pravděpodobně rozbitý monitoring.",
                "Klep klep.\n— Kdo je?\n— Silence.\n— Silence kdo?\n— Silence v alertech. Buď vše funguje, nebo je monitoring taky offline.",
                "Klep klep.\n— Kdo je?\n— Klid.\n— Klid kdo?\n— Klid před bouří. Všechny servery zelené. Zálohuji teď.",
                # jednořádkový ok
                "Všechny servery jsou zelené. Tato zpráva se automaticky smaže, až to přestane platit.",
                "Žádné aktivní alerty. Buď je vše v pořádku, nebo je monitoring konečně taky rozbité.",
                "Infrastruktura funguje. Zapište si datum — tohle se nestává často.",
                "Dnes žádné problémy. Zítra bude hůř, ale to řešíme zítra.",
                "Nula alertů. Tým ops si dává kafe. Vychutnávejte tento vzácný okamžik.",
            ]

            _SKIP_PLUGINS = {'detector_who', 'detector_icinga', 'agent_security_vulnerability_scan', 'agent_security_root_monitor'}

            active = state.get_active_issues()
            if active:
                candidates = [i for i in active if i.get('plugin_name') not in _SKIP_PLUGINS]
                if not candidates:
                    candidates = active
                pool = candidates[:50]
                _r.shuffle(pool)
                issue = pool[0]
                host = issue.get('host') or 'server'
                plugin = issue.get('plugin_name') or 'monitoring'
                try:
                    fs = issue.get('first_seen') or ''
                    dt = datetime.fromisoformat(fs.replace('Z', '+00:00'))
                    age_sec = int((datetime.now(timezone.utc) - dt).total_seconds())
                except Exception:
                    age_sec = 0
                age = f"{age_sec // 3600}h" if age_sec >= 3600 else f"{max(1, age_sec // 60)}min"
                joke = _r.choice(TEMPLATES_ISSUE).format(host=host, plugin=plugin, age=age, count=len(active))
            else:
                joke = _r.choice(TEMPLATES_OK)

            if not joke:
                return
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute(
                        "INSERT INTO infra_jokes (joke, source) VALUES (?, 'hourly')",
                        (joke,)
                    )
                    conn.execute("DELETE FROM infra_jokes WHERE id NOT IN (SELECT id FROM infra_jokes ORDER BY id DESC LIMIT 50)")
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logger.debug(f"_generate_hourly_joke: {e}")

    def _run_escalation_rules(self):
        """Eskaluje issue které jsou aktivní déle než N hodin dle config.yaml escalation_rules."""
        rules = getattr(config, 'ESCALATION_RULES', [])
        if not rules:
            return
        try:
            active = state.get_active_issues()
            now_utc = datetime.now(timezone.utc)
            for issue in active:
                # Přeskočit acknowledged, snoozované a AUTOFAIL
                if issue.get('acknowledged_by') or issue.get('key', '').startswith('AUTOFAIL|'):
                    continue
                first_seen_str = issue.get('first_seen') or issue.get('last_seen', '')
                if not first_seen_str:
                    continue
                try:
                    fs = datetime.fromisoformat(first_seen_str)
                    if fs.tzinfo is None:
                        fs = fs.replace(tzinfo=timezone.utc)
                    age_hours = (now_utc - fs).total_seconds() / 3600
                except Exception:
                    continue
                ch = (issue.get('channel_type') or '').lower()
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    after_h = float(rule.get('after_hours', 24))
                    rule_channels = [c.strip().lower() for c in str(rule.get('channels', '*')).split(',')]
                    target_sev = rule.get('severity', 'high')
                    if age_hours >= after_h and ('*' in rule_channels or ch in rule_channels):
                        cur_sev = (issue.get('severity') or '').lower()
                        sev_order = {'': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
                        if sev_order.get(cur_sev, 0) < sev_order.get(target_sev, 3):
                            state.set_issue_severity(issue['key'], target_sev)
                            msg = (
                                f"⚠️ Eskalace: [{ch.upper()}] {issue.get('host','?')} — "
                                f"'{(issue.get('last_line',''))[:80]}' "
                                f"aktivní {age_hours:.1f}h → priorita {target_sev.upper()}"
                            )
                            self._send_notification("escalation", ch, issue.get('host', 'sentinel'), msg)
                            logger.info(f"[escalation] {issue['key']} → {target_sev} ({age_hours:.1f}h)")
                            break  # Jen jedno pravidlo na issue za jeden cyklus
        except Exception as e:
            logger.error(f"_run_escalation_rules error: {e}")

    def daily_cleanup_loop(self):
        self.log_event("task_scheduler", "Starting daily cleanup scheduler started.")
        last_cleanup_date = None
        last_report_date = None
        last_snooze_check = 0
        while True:
            try:
                now = datetime.now()
                if now.hour == 3 and now.minute == 0 and last_cleanup_date != now.date():
                    retention = getattr(config, 'DB_RETENTION_DAYS', 2)
                    self.log_event("maintenance", f"Running telemetry cleanup (3:00 AM, retention={retention}d)...")
                    state.prune_telemetry(days=retention)
                    state.prune_sentinel_errors(days=7)
                    state.prune_health_snapshots(days=30)
                    state.prune_stale_sessions(hours=24)
                    # 366: Prune issue_history (retain 90 days)
                    _hist_days = getattr(config, 'ISSUE_HISTORY_RETENTION_DAYS', 90)
                    threading.Thread(target=state.prune_issue_history, args=(_hist_days,),
                                     daemon=True, name="IssueHistoryPrune").start()
                    # Telemetry aggregation (066)
                    _agg_hours = getattr(config, 'TELEMETRY_AGGREGATE_AFTER_HOURS', 24)
                    if _agg_hours > 0:
                        threading.Thread(target=state.aggregate_telemetry, args=(_agg_hours,),
                                         daemon=True, name="TelemetryAgg").start()
                    # DB vacuum — jednou týdně v neděli
                    if now.weekday() == 6:
                        threading.Thread(target=state.run_db_vacuum, daemon=True, name="DBVacuum").start()
                        self.log_event("maintenance", "DB VACUUM spuštěn (neděle 03:00)")
                    self.last_cleanup_time = datetime.now()
                    db_path = os.path.abspath(state.DB_FILE)
                    db_size = self.format_size(os.path.getsize(db_path)) if os.path.exists(db_path) else "N/A"
                    self.log_event("maintenance_done", f"Cleanup finished. Database size: {db_size}")
                    last_cleanup_date = now.date()
                # Daily report at configured hour (default 08:00)
                _report_hour = int(getattr(config, 'ANALYTICS', {}).get('daily_report_hour', 8))
                if now.hour == _report_hour and now.minute == 0 and last_report_date != now.date():
                    last_report_date = now.date()
                    threading.Thread(target=self._send_daily_report, daemon=True, name="DailyReport").start()
                # Apply snooze maintenance windows every 60 seconds
                cur_ts = time.time()
                if cur_ts - last_snooze_check >= 60:
                    state.apply_snooze_rules()
                    state.auto_resolve_old_problems(days=getattr(config, 'DB_RETENTION_DAYS', 30))
                    self._run_escalation_rules()
                    self._save_health_snapshot()
                    self._run_self_monitor_webhook()
                    # 407: Heartbeat URL monitoring
                    self._check_heartbeat_urls()
                    last_snooze_check = cur_ts
                # Weekly digest
                _wr_day = int(getattr(config, 'WEEKLY_REPORT_DAY', 0))
                _wr_hour = int(getattr(config, 'WEEKLY_REPORT_HOUR', 8))
                if (now.weekday() == _wr_day and now.hour == _wr_hour and now.minute == 0
                        and self.__class__._last_weekly_report_date != now.date()):
                    self.__class__._last_weekly_report_date = now.date()
                    threading.Thread(target=self._send_weekly_report, daemon=True, name="WeeklyReport").start()
                time.sleep(30)
            except Exception as e:
                self.log_event("maintenance_error", str(e), level=logging.ERROR)
                time.sleep(60)
 
    def format_size(self, size_bytes):
        if size_bytes == 0: return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        return f"{round(size_bytes / math.pow(1024, i), 2)} {units[i]}"

    _MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

    def _safe_log_path(self, filename: str) -> str | None:
        """Return realpath of filename inside LOG_DIR, or None if it would escape."""
        safe_name = secure_filename(os.path.basename(filename))
        if not safe_name:
            return None
        real_root = os.path.realpath(config.LOG_DIR)
        candidate = os.path.realpath(os.path.join(real_root, safe_name))
        if not candidate.startswith(real_root + os.sep) and candidate != real_root:
            return None
        return candidate

    _hailo_fw_cache: dict = {}
    _hailo_fw_ts: float = 0.0

    def _get_hailo_fw_info(self) -> dict:
        """Run hailortcli fw-control identify + sensor-info (cached 30s) — fw version, arch, temp."""
        now = time.time()
        if now - self._hailo_fw_ts < 30 and self._hailo_fw_cache:
            return self._hailo_fw_cache
        info: dict = {}
        try:
            res = subprocess.run(
                ["hailortcli", "fw-control", "identify"],
                capture_output=True, text=True, timeout=5
            )
            for line in res.stdout.splitlines():
                if ':' in line:
                    k, _, v = line.partition(':')
                    k = k.strip(); v = v.strip()
                    if 'Firmware Version' in k:
                        info['fw_version'] = v
                    elif 'Device Architecture' in k:
                        info['architecture'] = v
        except Exception:
            pass
        try:
            res2 = subprocess.run(
                ["hailortcli", "sensor-info"],
                capture_output=True, text=True, timeout=5
            )
            for line in res2.stdout.splitlines():
                if ':' in line:
                    k, _, v = line.partition(':')
                    k = k.strip().lower(); v = v.strip()
                    if 'temperature' in k or 'temp' in k:
                        # strip units like "°C" or "C"
                        temp_val = re.sub(r'[^\d.]', '', v.split()[0]) if v else ''
                        if temp_val:
                            try:
                                info['npu_temp'] = float(temp_val)
                            except ValueError:
                                pass
                        break
        except Exception:
            pass
        self._hailo_fw_cache = info
        self._hailo_fw_ts = now
        return info
 
    def get_sys_metrics(self):
        mem_info = "N/A"
        try:
            with open('/proc/meminfo', 'r') as f: lines = f.readlines()
            total = int([x for x in lines if 'MemTotal' in x][0].split()[1])
            avail = int([x for x in lines if 'MemAvailable' in x][0].split()[1])
            mem_info = f"{round((total - avail)/1024/1024, 1)} / {round(total/1024/1024, 1)} GB"
        except Exception as e:
            logger.debug(f"Failed to parse meminfo: {e}")

        open_files = "N/A"
        try:
            open_files = len(os.listdir('/proc/self/fd'))
        except Exception as e:
            logger.debug(f"Failed to count open files: {e}")

        avg_ai_latency = 0
        if self.metrics["ai_latency_history"]:
            avg_ai_latency = round(sum(self.metrics["ai_latency_history"]) / len(self.metrics["ai_latency_history"]), 2)

        rag_data = {}
        if hasattr(rag, 'rag_system'):
            rag_data = rag.rag_system.get_metrics()

        metrics = {
            "uptime": self.get_uptime(),
            "cpu_load": os.getloadavg() if hasattr(os, "getloadavg") else "N/A",
            "ram_usage": mem_info,
            "open_files_fd": open_files, 
            "active_threads": threading.active_count(),
            "python_ver": platform.python_version(),
            "ai_model_chat": config.OLLAMA_MODEL,
            "ai_avg_reply": f"{avg_ai_latency}s",
            "ai_requests": self.metrics["ai_requests"],
            "rag_status": rag.rag_system.get_status(),
        }
        metrics.update(rag_data)
        return metrics

    def get_detailed_metrics(self):
        # Cache (5s): desítky souběžných dashboard pollů (víc uživatelů současně)
        # sdílí jedno DB čtení místo O(uživatelů) volání get_all_agents + DB connectů.
        import time as _t
        _c = getattr(self, '_dm_cache', None)
        if _c is not None and (_t.time() - getattr(self, '_dm_cache_ts', 0)) < 5:
            return _c
        _c = self._compute_detailed_metrics()
        self._dm_cache = _c
        self._dm_cache_ts = _t.time()
        return _c

    def _compute_detailed_metrics(self):
        # --- CPU ---
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
        cpu_count = os.cpu_count() or 4
        cpu_pct = int(min(100, (load[0] / cpu_count) * 100))
        cpu_color = "val-ok"
        if load[0] > cpu_count * 0.7: cpu_color = "val-warn"
        if load[0] > cpu_count: cpu_color = "val-crit"

        # CPU temperature
        cpu_temp = None
        for tz in range(5):
            try:
                raw = int(open(f'/sys/class/thermal/thermal_zone{tz}/temp').read().strip())
                cpu_temp = round(raw / 1000, 1)
                break
            except Exception: pass

        # CPU model & frequency
        cpu_model = "Unknown"
        try:
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if line.startswith('Model name') or line.startswith('Hardware') or line.startswith('Model'):
                        cpu_model = line.split(':', 1)[1].strip()
                        break
        except Exception: pass
        if len(cpu_model) > 38: cpu_model = cpu_model[:36] + "…"

        cpu_freq_mhz = None
        try:
            raw = int(open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq').read().strip())
            cpu_freq_mhz = raw // 1000
        except Exception: pass

        # --- Memory ---
        mem = {"total": 0, "available": 0, "swap_total": 0, "swap_free": 0}
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    parts = line.split()
                    k = parts[0].rstrip(':')
                    v = int(parts[1])
                    if k == 'MemTotal': mem['total'] = v
                    elif k == 'MemAvailable': mem['available'] = v
                    elif k == 'SwapTotal': mem['swap_total'] = v
                    elif k == 'SwapFree': mem['swap_free'] = v
        except Exception: pass

        mem_used_gb  = round((mem['total'] - mem['available']) / 1024 / 1024, 2)
        mem_total_gb = round(mem['total'] / 1024 / 1024, 2)
        mem_pct = int(round((1 - mem['available'] / mem['total']) * 100)) if mem['total'] > 0 else 0
        mem_color = "val-crit" if mem_pct > 90 else ("val-warn" if mem_pct > 75 else "val-ok")
        swap_used_mb = round((mem['swap_total'] - mem['swap_free']) / 1024, 0)
        swap_total_mb = round(mem['swap_total'] / 1024, 0)

        # --- Disk ---
        def _disk(path):
            try:
                d = shutil.disk_usage(path)
                pct = int(round(d.used / d.total * 100))
                free_gb = round(d.free / (1024**3), 1)
                total_gb = round(d.total / (1024**3), 1)
                return {"pct": pct, "free": free_gb, "total": total_gb,
                        "color": "val-crit" if pct > 90 else ("val-warn" if pct > 75 else "val-ok")}
            except Exception:
                return {"pct": 0, "free": 0, "total": 0, "color": "val-ok"}

        disk_root = _disk('/')
        disk_log  = _disk(config.LOG_DIR)

        # --- Network ---
        net_ifaces = []
        try:
            result = subprocess.run(['ip', '-j', 'addr'], capture_output=True, text=True, timeout=3)
            ifaces_raw = json.loads(result.stdout)
            # Read traffic from /proc/net/dev
            traffic = {}
            with open('/proc/net/dev') as f:
                for line in f.readlines()[2:]:
                    parts = line.split()
                    name = parts[0].rstrip(':')
                    traffic[name] = {'rx': int(parts[1]), 'tx': int(parts[9])}
            for iface in ifaces_raw:
                name = iface.get('ifname', '')
                if name == 'lo' or iface.get('operstate', '') == 'DOWN':
                    continue
                ips = [a['local'] for a in iface.get('addr_info', []) if a.get('family') == 'inet']
                if not ips: continue
                t = traffic.get(name, {})
                rx_mb = round(t.get('rx', 0) / (1024**2), 1)
                tx_mb = round(t.get('tx', 0) / (1024**2), 1)
                net_ifaces.append({'name': name, 'ip': ips[0], 'rx_mb': rx_mb, 'tx_mb': tx_mb})
        except Exception: pass

        # --- OS / System identity ---
        hostname = platform.node()
        kernel   = platform.release().split('-')[0]   # short version
        os_name  = platform.system()
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME'):
                        os_name = line.split('=', 1)[1].strip().strip('"')
                        break
        except Exception: pass

        hw_model = ""
        try:
            hw_model = open('/proc/device-tree/model').read().rstrip('\x00').strip()
        except Exception: pass

        # --- Agents ---
        agents_total = agents_online = 0
        try:
            agents = [a for a in state.get_all_agents()
                      if not a['hostname'].startswith('sentinel-hw-')
                      and not a['hostname'].startswith('sentinel-alert')]
            agents_total  = len(agents)
            agents_online = sum(1 for a in agents if a.get('status') == 'ONLINE')
        except Exception: pass

        # --- DB & runtime ---
        db_path  = state.DB_FILE
        db_size  = self.format_size(os.path.getsize(db_path)) if os.path.exists(db_path) else "N/A"
        threads  = threading.active_count()

        # --- AI & RAG ---
        rag_data = rag.rag_system.get_metrics() if hasattr(rag, 'rag_system') else {}
        ai_lat   = f"{round(sum(self.metrics['ai_latency_history'])/len(self.metrics['ai_latency_history']),2)}s" if self.metrics['ai_latency_history'] else "N/A"

        # --- AI HAT+ ---
        # Hailo-8/8L vytvoří /dev/hailo0 (hailo_pci modul)
        # Hailo-10H používá hailo1x_pci modul bez /dev/hailo0
        hailo_active = (os.path.exists('/dev/hailo0') or
                        os.path.exists('/sys/module/hailo1x_pci'))

        hailo_fw_info = self._get_hailo_fw_info() if hailo_active else {}

        return {
            "cpu": f"{load[0]:.2f} {load[1]:.2f} {load[2]:.2f}",
            "cpu_pct": cpu_pct, "cpu_color": cpu_color,
            "cpu_count": cpu_count, "cpu_model": cpu_model,
            "cpu_temp": cpu_temp, "cpu_freq_mhz": cpu_freq_mhz,
            "ram": f"{mem_used_gb} / {mem_total_gb} GB",
            "ram_pct": mem_pct, "ram_color": mem_color,
            "swap": f"{int(swap_used_mb)} / {int(swap_total_mb)} MB",
            "disk_root": disk_root, "disk_log": disk_log,
            "net_ifaces": net_ifaces,
            "hostname": hostname, "kernel": kernel,
            "os_name": os_name, "hw_model": hw_model,
            "agents_total": agents_total, "agents_online": agents_online,
            "threads": threads, "uptime": self.get_uptime(), "db_size": db_size,
            "ai_req": self.metrics["ai_requests"], "ai_lat": ai_lat,
            "hailo_active": hailo_active,
            "hailo_fw": hailo_fw_info,
            "rag": rag_data,
        }

    def render_sys_monitor_html(self, role='viewer'):
        m = self.get_detailed_metrics()
        r = m.get('rag', {})
        def g(key, default="N/A"): return r.get(key, default)

        active_issues = state.get_active_issues()
        security_count = sum(1 for i in active_issues if i.get('channel_type') == 'security')
        root_count     = sum(1 for i in active_issues if i.get('channel_type') == 'root')
        agent_count    = sum(1 for i in active_issues if i.get('channel_type') == 'agent')
        total_issues   = len(active_issues)

        plugin_counts = collections.Counter(i.get('plugin_name', 'unknown') for i in active_issues)
        top_plugin = f"{plugin_counts.most_common(1)[0][0]} ({plugin_counts.most_common(1)[0][1]}x)" if plugin_counts else "none"

        health_score = max(0, 100 - (total_issues * 2) - (m['cpu_pct'] // 5) - (m['ram_pct'] // 5))
        score_color  = "var(--success)" if health_score >= 80 else ("var(--warning)" if health_score >= 50 else "var(--error)")

        now = datetime.now()
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now: next_run += timedelta(days=1)

        active_plugins = [d['plugin'] for d in config.DETECTORS if d.get('enabled')]

        def pb(pct, color_class):
            return (f"<div style='background:rgba(255,255,255,0.06);border-radius:4px;height:6px;margin-top:3px;overflow:hidden;'>"
                    f"<div style='height:100%;width:{pct}%;border-radius:4px;transition:width .5s ease;' class='{color_class}'></div></div>")

        def pbc(pct):
            if pct > 90: return "pb-crit"
            if pct > 75: return "pb-warn"
            return "pb-ok"

        def row(label, value_html):
            return f"<div class='sys-row'><span class='sys-label'>{label}</span><span class='sys-val'>{value_html}</span></div>"

        def metric_block(label, value, pct, color):
            return (f"<div style='margin-bottom:9px;'>"
                    f"<div style='display:flex;justify-content:space-between;'>"
                    f"<span class='sys-label'>{label}</span>"
                    f"<span class='sys-val {color}'>{value} &nbsp;<b>{pct}%</b></span></div>"
                    f"{pb(pct, pbc(pct))}</div>")

        # CPU detail string
        temp_str  = f" &nbsp;<i class='fa-solid fa-temperature-half'></i> {m['cpu_temp']}°C" if m.get('cpu_temp') else ""
        freq_str  = f" &nbsp;<i class='fa-solid fa-bolt'></i> {m['cpu_freq_mhz']} MHz" if m.get('cpu_freq_mhz') else ""
        cpu_sub   = f"<span style='font-size:.78em;color:var(--text-muted);'>{m['cpu_model']}{temp_str}{freq_str} &nbsp;({m['cpu_count']} cores)</span>"

        # Disk rows
        dr = m['disk_root']
        dl = m['disk_log']
        disk_root_str = f"{dr['free']} GB free / {dr['total']} GB"
        disk_log_str  = f"{dl['free']} GB free / {dl['total']} GB"

        # Network rows
        net_rows = ""
        for iface in m.get('net_ifaces', []):
            net_rows += (f"<div style='display:flex;justify-content:space-between;align-items:center;"
                         f"padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:.85em;'>"
                         f"<span style='color:var(--accent);font-weight:600;min-width:60px;'>{iface['name']}</span>"
                         f"<span style='color:var(--text-muted);flex:1;padding:0 8px;'>{iface['ip']}</span>"
                         f"<span style='color:var(--text-muted);font-size:.8em;'>"
                         f"<i class='fa-solid fa-arrow-down' style='color:var(--success);'></i> {iface['rx_mb']} MB &nbsp;"
                         f"<i class='fa-solid fa-arrow-up' style='color:var(--warning);'></i> {iface['tx_mb']} MB</span></div>")
        if not net_rows:
            net_rows = "<div style='color:var(--text-muted);font-size:.85em;'>No active interfaces</div>"

        # AI Engine — hailo-ollama nebo CPU ollama
        hailo_html = ""
        dot_ok   = "<span style='animation:blinker 1.5s linear infinite;display:inline-block;color:var(--success);'>●</span>"
        dot_warn = "<span style='color:var(--warning);'>●</span>"

        if config.HAILO_OLLAMA_ENABLED:
            npu_ok = m.get('hailo_active', False)
            npu_dot = dot_ok if npu_ok else dot_warn
            npu_label = "<span class='val-ok'>NPU active</span>" if npu_ok else "<span class='val-warn'>NPU offline</span>"

            # Fetch live model list from hailo-ollama /api/tags
            hailo_models_live = []
            try:
                _base = config.HAILO_OLLAMA_URL.replace('/v1/chat/completions', '').rstrip('/')
                _r = requests.get(f"{_base}/api/tags", timeout=2)
                if _r.ok:
                    hailo_models_live = [_m['name'] for _m in _r.json().get('models', [])]
            except Exception:
                pass
            if not hailo_models_live:
                hailo_models_live = ["qwen3:1.7b", "qwen2.5-coder:1.5b", "qwen2.5:1.5b", "llama3.2:1b", "deepseek_r1:1.5b"]

            opts = "".join(
                f"<option value='{mo}' {'selected' if mo == config.HAILO_OLLAMA_MODEL else ''}>{mo}</option>"
                for mo in hailo_models_live
            )
            switcher = (
                f"<select id='hailo-model-sel' onchange='setHailoModel(this.value)' "
                f"style='background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);"
                f"border-radius:4px;padding:2px 4px;font-size:.82em;cursor:pointer;'>{opts}</select>"
            )
            fw = m.get('hailo_fw', {})
            npu_temp_str = ""
            if fw.get('npu_temp') is not None:
                t = fw['npu_temp']
                tc = "var(--success)" if t < 70 else ("var(--warning)" if t < 85 else "var(--error)")
                npu_temp_str = f" &middot; <i class='fa-solid fa-temperature-half' style='color:{tc};'></i> <span style='color:{tc};'>{t}°C</span>"
            fw_str = (
                f"<span style='font-size:.82em;color:var(--text-muted);'>"
                f"{fw.get('architecture', 'HAILO10H')} &middot; FW {fw.get('fw_version', '?')}"
                f"{npu_temp_str}</span>"
            ) if fw else ""
            hailo_html = (
                row("AI Engine:", f"{npu_dot} hailo-ollama (Hailo-10H) &nbsp;{npu_label}") +
                row("&nbsp;↳ LLM model:", switcher) +
                (row("&nbsp;↳ NPU info:", fw_str) if fw_str else "") +
                row("&nbsp;↳ CPU fallback:", f"<span style='color:var(--text-muted);font-size:.85em;'>{config.OLLAMA_MODEL} (neaktivní)</span>")
            )
        else:
            hailo_html = row("AI Engine:", f"{dot_ok} Ollama (CPU) &nbsp;<span class='val-info'>{config.OLLAMA_MODEL}</span>")

        # Embedding info — vždy CPU ollama (hailo-ollama embedding nepodporuje)
        emb_url = getattr(config, 'EMBEDDING_OLLAMA_URL', '') or ''
        if not emb_url:
            emb_url = config.OLLAMA_URL.replace('/v1/chat/completions', '').replace('/api/generate', '').rstrip('/')
        emb_host = emb_url.replace('http://', '').replace('https://', '')
        hailo_html += row("Embedding:", f"<span class='val-info'>nomic-embed-text</span> &nbsp;<span style='font-size:.8em;color:var(--text-muted);'>@ {emb_host}</span>")

        # AI HAT+ (Hailo-8/8L, embeddingy) — starší karta
        if getattr(config, 'AI_HAT_ENABLED', False):
            if m.get('hailo_active'):
                device = getattr(config, 'AI_HAT_DEVICE', 'hailo')
                tops   = getattr(config, 'AI_HAT_TOPS', 0)
                hailo_html += row("AI HAT+:", f"<span class='val-ok'>{dot_ok} {device} ({tops}T) active</span>")
            else:
                hailo_html += row("AI HAT+:", "<span class='val-warn'>configured / offline</span>")

        # Agents badge
        ag_color = "val-ok" if m['agents_online'] == m['agents_total'] and m['agents_total'] > 0 else ("val-warn" if m['agents_online'] > 0 else "val-crit")
        ag_str   = f"<span class='{ag_color}'>{m['agents_online']}/{m['agents_total']}</span> online"

        cleanup_str = self.last_cleanup_time.strftime('%d.%m. %H:%M') if self.last_cleanup_time else 'Never'

        def _plugin_rows(detectors, p_counts):
            rows_html = ""
            for det in detectors:
                name    = det.get('plugin', '')
                pattern = det.get('match_pattern', '')
                enabled = det.get('enabled', False)
                issues  = p_counts.get(name, 0)
                status_dot   = "<span style='color:var(--success);'>●</span>" if enabled else "<span style='color:rgba(255,255,255,.2);'>●</span>"
                status_label = ("<span style='color:var(--success);font-weight:600;'>Aktivní</span>"
                                if enabled else
                                "<span style='color:var(--text-muted);'>Neaktivní</span>")
                issues_html  = (f"<span style='font-size:.78em;color:var(--warning);margin-left:4px;'>({issues} issues)</span>"
                                if issues > 0 else "")
                btn_label = "Vypnout" if enabled else "Zapnout"
                btn_style = ("background:rgba(255,80,80,.15);color:var(--error);border:1px solid rgba(255,80,80,.3);"
                             if enabled else
                             "background:rgba(80,255,120,.12);color:var(--success);border:1px solid rgba(80,255,120,.3);")
                rows_html += (
                    f"<tr style='border-bottom:1px solid rgba(255,255,255,.04);'>"
                    f"<td style='padding:5px 8px;'>{status_dot} <code style='font-size:.9em;'>{name}</code>{issues_html}</td>"
                    f"<td style='padding:5px 8px;color:var(--text-muted);'>{pattern}</td>"
                    f"<td style='padding:5px 8px;text-align:center;'>{status_label}</td>"
                    f"<td style='padding:5px 8px;text-align:center;'>"
                    f"<button onclick=\"sysTogglePlugin(this,'{name}',{'true' if enabled else 'false'})\" "
                    f"style='padding:2px 10px;border-radius:4px;cursor:pointer;font-size:.8em;{btn_style}'>"
                    f"{btn_label}</button></td>"
                    f"</tr>"
                )
            return rows_html

        return f"""<style>
.pb-ok{{background:var(--success);}}.pb-warn{{background:var(--warning);}}.pb-crit{{background:var(--error);}}
@keyframes blinker{{50%{{opacity:0.3;}}}}
.sys-id-bar{{background:linear-gradient(90deg,rgba(var(--accent-rgb),.12),transparent);border:1px solid rgba(var(--accent-rgb),.25);border-radius:8px;padding:10px 14px;margin-bottom:12px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;}}
.sys-id-chip{{font-size:.8em;color:var(--text-muted);display:flex;align-items:center;gap:5px;}}
.sys-id-chip b{{color:var(--text);}}
.sys-score-circle{{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:bold;border:2px solid {score_color};color:{score_color};font-size:1em;background:rgba(0,0,0,0.25);box-shadow:0 0 10px {score_color}40;margin-left:auto;flex-shrink:0;}}
</style>
<div class='sys-id-bar'>
  <div class='sys-id-chip'><i class='fa-solid fa-server' style='color:var(--accent);'></i> <b>{m['hostname']}</b></div>
  <div class='sys-id-chip'><i class='fa-brands fa-linux'></i> <b>{m['os_name']}</b></div>
  <div class='sys-id-chip'><i class='fa-solid fa-microchip'></i> <b>{m['kernel']}</b></div>
  {"<div class='sys-id-chip'><i class='fa-solid fa-memory'></i> <b>" + m['hw_model'] + "</b></div>" if m.get('hw_model') else ""}
  <div class='sys-id-chip'><i class='fa-solid fa-clock'></i> up <b>{m['uptime']}</b></div>
  <div class='sys-score-circle' title='Health Score: {health_score}/100' onclick="openHealthHistory()" style="cursor:pointer;">{health_score}</div>
</div>

<div class='sys-grid'>
  <div class='sys-section'>
    <div class='sys-section-title'><i class='fa-solid fa-microchip'></i> Hardware</div>
    <div style='margin-bottom:6px;'>{cpu_sub}</div>
    {metric_block(f"CPU load ({m['cpu']})", "", m['cpu_pct'], m['cpu_color'])}
    {metric_block(f"RAM ({m['ram']})", "", m['ram_pct'], m['ram_color'])}
    {metric_block(f"Root disk — {disk_root_str}", "", dr['pct'], dr['color'])}
    {metric_block(f"Log disk — {disk_log_str}", "", dl['pct'], dl['color'])}
    {row("Swap:", m['swap'])}
  </div>

  <div class='sys-section'>
    <div class='sys-section-title'><i class='fa-solid fa-network-wired'></i> Network</div>
    {net_rows}
  </div>

  <div class='sys-section'>
    <div class='sys-section-title'><i class='fa-solid fa-shield-halved'></i> Security &amp; Agents</div>
    {row("Active issues:", f"<span class='{'val-crit' if total_issues > 0 else 'val-ok'}'>{total_issues} total</span>")}
    {row("&nbsp;↳ Security:", f"<span class='{'val-crit' if security_count > 0 else 'val-ok'}'>{security_count}</span>")}
    {row("&nbsp;↳ Root:", f"<span class='{'val-crit' if root_count > 0 else 'val-ok'}'>{root_count}</span>")}
    {row("&nbsp;↳ Agent:", f"<span class='{'val-warn' if agent_count > 0 else 'val-ok'}'>{agent_count}</span>")}
    {row("Top alert source:", f"<span style='font-size:.82em;background:rgba(255,255,255,.05);padding:1px 6px;border-radius:4px;'>{top_plugin}</span>")}
    {row("Remote agents:", ag_str)}
    {row("Active plugins:", f"<span class='val-info'>{len(active_plugins)}</span>")}
    {row("AI queue:", f"{self.chat_queue_depth} jobs")}
  </div>

  <div class='sys-section'>
    <div class='sys-section-title'><i class='fa-solid fa-brain'></i> AI Engine</div>
    {hailo_html}
    {row("Total requests:", str(m['ai_req']))}
    {row("Avg latency:", m['ai_lat'])}
    <div style='margin-top:8px;border-top:1px dashed var(--border);padding-top:8px;'>
      {row("RAG:", rag.rag_system.get_status())}
      {row("Vectors:", f"{g('rag_db_items')} items")}
      {row("Embed latency:", g('rag_last_time'))}
    </div>
  </div>

  <div class='sys-section'>
    <div class='sys-section-title'><i class='fa-solid fa-database'></i> Database &amp; Runtime</div>
    {row("State DB:", m['db_size'])}
    {row("Active threads:", str(m['threads']))}
    {row("Last cleanup:", cleanup_str)}
    {row("Next auto-prune:", f"<span class='val-info'>{next_run.strftime('%H:%M')}</span>")}
    {row("Backup:", "<a href='/api/export/db_backup' style='color:var(--accent);font-size:.85em;'><i class='fa-solid fa-download'></i> Stáhnout SQL dump</a>") if role == 'superadmin' else ""}
  </div>
</div>

<div style='margin-top:12px;'>
  <div class='sys-section' style='margin-bottom:0;'>
    <div class='sys-section-title' style='margin-bottom:10px;'><i class='fa-solid fa-puzzle-piece'></i> Detektory &amp; Pluginy <span style='font-weight:400;font-size:.85em;color:var(--text-muted);'>({len(config.DETECTORS)} celkem, {len(active_plugins)} aktivních)</span></div>
    <div style='overflow-x:auto;'>
      <table style='width:100%;border-collapse:collapse;font-size:.83em;'>
        <thead>
          <tr style='color:var(--text-muted);border-bottom:1px solid var(--border);'>
            <th style='text-align:left;padding:4px 8px;font-weight:500;'>Plugin</th>
            <th style='text-align:left;padding:4px 8px;font-weight:500;'>Soubor</th>
            <th style='text-align:center;padding:4px 8px;font-weight:500;'>Stav</th>
            <th style='text-align:center;padding:4px 8px;font-weight:500;'>Akce</th>
          </tr>
        </thead>
        <tbody>
          {_plugin_rows(config.DETECTORS, plugin_counts)}
        </tbody>
      </table>
    </div>
  </div>
</div>
<script>
function sysTogglePlugin(btn, pluginName, currentEnabled) {{
  btn.disabled = true;
  btn.style.opacity = '0.5';
  fetch('/api/plugins/toggle', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{plugin: pluginName, enabled: !currentEnabled}})
  }}).then(r => r.json()).then(d => {{
    if (d.status === 'ok') {{
      if (window.sendChatMessage) window.sendChatMessage('sys');
      else location.reload();
    }} else {{
      alert('Chyba: ' + (d.message || 'neznámá chyba'));
      btn.disabled = false; btn.style.opacity = '1';
    }}
  }}).catch(() => {{ btn.disabled = false; btn.style.opacity = '1'; }});
}}
</script>
<div style='text-align:right;font-size:.7em;color:var(--text-muted);margin-top:8px;border-top:1px solid var(--border);padding-top:4px;'>
  <i class='fa-solid fa-sync fa-spin' style='font-size:.9em;'></i> {datetime.now().strftime('%H:%M:%S')}
  {f"<a href='javascript:void(0)' onclick=\"openSystemErrorsModal()\" style='color:var(--error);margin-left:10px;font-size:.9em;'><i class='fa-solid fa-triangle-exclamation'></i> Chyby systému</a>" if role in ('admin','superadmin') else ""}
</div>"""

    def get_session_data(self):
        if 'uid' not in session: session['uid'] = str(uuid.uuid4())
        uid = session['uid']
        if uid not in self.user_sessions: self.user_sessions[uid] = {'active_file': None}
        return self.user_sessions[uid]

    def read_file_content(self, path):
        if not os.path.exists(path): return "", 0
        try:
            with open(path, 'rb') as f:
                raw_data = f.read()
                content = raw_data.decode('utf-8', errors='replace')
                lines = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
                return content, lines
        except Exception as e: return f"Error: {e}", 0

    def load_ignored_issues(self):
        if os.path.exists(IGNORED_FILE):
            try:
                with open(IGNORED_FILE, 'r') as f: return set(json.load(f))
            except: return set()
        return set()

    def save_ignored_issues(self):
        try:
            with open(IGNORED_FILE, 'w') as f: json.dump(list(self.ignored_issues), f)
        except: pass

    def apply_ignored_issues(self):
        try:
            current_mtime = os.path.getmtime(IGNORED_FILE)
            last_mtime = getattr(self, '_ignored_mtime', 0)
            if current_mtime != last_mtime:
                self.ignored_issues = self.load_ignored_issues()
                self._ignored_mtime = current_mtime
        except FileNotFoundError:
            pass  # File doesn't exist yet, ignore
        except Exception as e:
            logger.error(f"Error syncing ignored issues: {e}")

    def _send_notification(self, key: str, channel: str, host: str, msg: str):
        """Odešle notifikaci přes nakonfigurované integrace. Throttling: max 1x/hod na klíč."""
        try:
            throttle_key = f"notify_throttle_{key}"
            last_sent = getattr(self, '_notify_throttle', {}).get(throttle_key, 0)
            now_ts = time.time()
            if now_ts - last_sent < 3600:
                return
            if not hasattr(self, '_notify_throttle'):
                self._notify_throttle = {}
            self._notify_throttle[throttle_key] = now_ts

            title = f"🚨 Sentinel: {channel.upper()} alert"
            body = f"[{host}] {msg[:200]}"
            instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')

            # Teams
            if getattr(config, 'TEAMS_ENABLED', False):
                channels = getattr(config, 'TEAMS_CHANNELS', {})
                ch_url = channels.get(channel) or channels.get('all') or next(
                    (v for k, v in channels.items() if k != 'enabled' and isinstance(v, str) and v), None)
                if ch_url:
                    try:
                        requests.post(ch_url, json={"poster": instance, "location": "Alert",
                                                     "body": {"messageBody": f"**{title}**\n{body}"}},
                                      headers={"Content-Type": "application/json"}, timeout=8)
                    except Exception as e:
                        logger.warning(f"Teams notify failed: {e}")

            # Generic webhook
            if getattr(config, 'WEBHOOK_ENABLED', False):
                wh_url = getattr(config, 'WEBHOOK_URL', '')
                if wh_url:
                    try:
                        payload = json.dumps({"event": "new_alert", "key": key, "channel": channel,
                                              "host": host, "message": msg[:500],
                                              "instance": instance}).encode()
                        headers = {"Content-Type": "application/json"}
                        secret = getattr(config, 'WEBHOOK_SECRET', '')
                        if secret:
                            import hmac as _hmac, hashlib as _hashlib
                            sig = _hmac.new(secret.encode(), payload, _hashlib.sha256).hexdigest()
                            headers['X-Sentinel-Signature'] = f'sha256={sig}'
                        requests.post(wh_url, data=payload, headers=headers, timeout=8)
                    except Exception as e:
                        logger.warning(f"Webhook notify failed: {e}")

            # PagerDuty (078) — Events v2 API
            if getattr(config, 'PAGERDUTY_ENABLED', False):
                pd_key = getattr(config, 'PAGERDUTY_ROUTING_KEY', '')
                if pd_key:
                    try:
                        sev_map = {'security': 'critical', 'root': 'critical',
                                   'agent': 'error', 'infra': 'warning'}
                        pd_sev = sev_map.get(channel.lower(), 'warning')
                        pd_payload = {
                            "routing_key": pd_key,
                            "event_action": "trigger",
                            "payload": {
                                "summary": f"{title}: {body[:200]}",
                                "severity": pd_sev,
                                "source": getattr(config, 'INSTANCE_NAME', 'Sentinel'),
                                "component": channel,
                                "custom_details": {"host": host, "message": msg[:500]},
                            },
                            "dedup_key": f"sentinel-{key[:80]}",
                        }
                        requests.post("https://events.pagerduty.com/v2/enqueue",
                                      json=pd_payload,
                                      headers={"Content-Type": "application/json"}, timeout=8)
                    except Exception as e:
                        logger.warning(f"PagerDuty notify failed: {e}")

            # Slack (079)
            if getattr(config, 'SLACK_ENABLED', False):
                slack_url = getattr(config, 'SLACK_WEBHOOK_URL', '')
                if slack_url:
                    try:
                        slack_payload = {"text": f"*{title}*\n{body}"}
                        slack_ch = getattr(config, 'SLACK_CHANNEL', '')
                        if slack_ch:
                            slack_payload["channel"] = slack_ch
                        requests.post(slack_url, json=slack_payload,
                                      headers={"Content-Type": "application/json"}, timeout=8)
                    except Exception as e:
                        logger.warning(f"Slack notify failed: {e}")

            # HomeAssistant
            if getattr(config, 'HA_ENABLED', False):
                ha_url = getattr(config, 'HA_URL', '').rstrip('/')
                ha_token = getattr(config, 'HA_TOKEN', '')
                svc = getattr(config, 'HA_NOTIFY_SERVICE', 'notify')
                if ha_url and ha_token:
                    try:
                        requests.post(f"{ha_url}/api/services/notify/{svc.lstrip('/')}",
                                      json={"title": title, "message": body},
                                      headers={"Authorization": f"Bearer {ha_token}",
                                               "Content-Type": "application/json"}, timeout=8)
                    except Exception as e:
                        logger.warning(f"HA notify failed: {e}")
        except Exception as e:
            logger.error(f"_send_notification error: {e}")

    def _dispatch_issue_lifecycle_webhook(self, event: str, issue: dict):
        """425: Fire webhook on ISSUE_CREATED / ISSUE_ACKNOWLEDGED / ISSUE_RESOLVED events."""
        if not getattr(config, 'WEBHOOK_ENABLED', False):
            return
        wh_url = getattr(config, 'WEBHOOK_URL', '').strip()
        if not wh_url:
            return
        try:
            payload = json.dumps({
                "event": event,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "instance": getattr(config, 'INSTANCE_NAME', 'Sentinel'),
                "issue": {
                    "key": issue.get("key", ""),
                    "host": issue.get("host", ""),
                    "channel_type": issue.get("channel_type", ""),
                    "plugin_name": issue.get("plugin_name", ""),
                    "last_line": issue.get("last_line", "")[:300],
                    "severity": issue.get("severity", ""),
                    "status": issue.get("status", ""),
                },
            }).encode()
            headers = {"Content-Type": "application/json"}
            secret = getattr(config, 'WEBHOOK_SECRET', '')
            if secret:
                import hmac as _hmac, hashlib as _hashlib
                sig = _hmac.new(secret.encode(), payload, _hashlib.sha256).hexdigest()
                headers['X-Sentinel-Signature'] = f'sha256={sig}'
                headers['X-Sentinel-Event'] = event
            requests.post(wh_url, data=payload, headers=headers, timeout=8)
        except Exception as e:
            logger.debug(f"lifecycle_webhook {event}: {e}")

    def _sync_gitea_issue(self, issue: dict):
        """415: Sync critical issue to Gitea as a new issue."""
        gitea_url = getattr(config, 'GITEA_URL', '').rstrip('/')
        gitea_token = getattr(config, 'GITEA_TOKEN', '')
        gitea_repo = getattr(config, 'GITEA_REPO', '')  # "owner/repo"
        if not gitea_url or not gitea_token or not gitea_repo:
            return
        ch = issue.get("channel_type", "").lower()
        if ch not in ("security", "root"):
            return  # Only sync critical channels
        try:
            title = f"[Sentinel][{ch.upper()}] {issue.get('host', 'unknown')}: {issue.get('plugin_name', '')}"
            body = (
                f"**Host:** {issue.get('host', 'N/A')}\n"
                f"**Channel:** {ch.upper()}\n"
                f"**Message:** {issue.get('last_line', '')[:500]}\n"
                f"**Key:** `{issue.get('key', '')}`\n"
                f"**First seen:** {issue.get('first_seen', '')}\n\n"
                f"*Auto-created by Sentinel*"
            )
            url = f"{gitea_url}/api/v1/repos/{gitea_repo}/issues"
            resp = requests.post(url, json={"title": title, "body": body},
                                 headers={"Authorization": f"token {gitea_token}",
                                          "Content-Type": "application/json"}, timeout=10)
            if resp.status_code in (200, 201):
                logger.info(f"Gitea issue created: {resp.json().get('html_url', '')}")
            else:
                logger.warning(f"Gitea issue create failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.debug(f"gitea_sync: {e}")

    def execute_ollama(self, prompt, num_ctx=2048, messages=None, max_tokens=None, temperature=0.1):
        self.chat_queue_depth += 1
        try:
            self.llm_semaphore.acquire()
            self.chat_queue_depth -= 1
            self.metrics["ai_requests"] += 1
            start_ts = time.time()

            if config.HAILO_OLLAMA_ENABLED:
                try:
                    # Use native /api/chat endpoint (more reliable for large inputs than /v1/chat/completions)
                    base = config.HAILO_OLLAMA_URL.split('/v1/')[0].split('/api/')[0].rstrip('/')
                    hailo_chat_url = f"{base}/api/chat"
                    if messages is not None:
                        hailo_msgs = [
                            {"role": m["role"],
                             "content": m["content"].replace('\n', ' ').replace('\r', ' ')}
                            for m in messages
                        ]
                    else:
                        safe_prompt = prompt.replace('\n', ' ').replace('\r', ' ')
                        hailo_msgs = [{"role": "user", "content": safe_prompt}]
                    payload = {
                        "model": config.HAILO_OLLAMA_MODEL,
                        "messages": hailo_msgs,
                        "stream": False,
                        "options": {"temperature": 0.1},
                    }
                    resp = requests.post(hailo_chat_url, json=payload,
                                         headers={"Content-Type": "application/json"}, timeout=90)
                    if resp.status_code != 200:
                        raise Exception(f"hailo-ollama error {resp.status_code}:{resp.text[:120]}")
                    data = resp.json()
                    result = data.get("message", {}).get("content", "")
                    if not result:
                        result = "AI Error (No response field)"
                except Exception as hailo_err:
                    utils.log_message(f"AI: hailo-ollama Error: {hailo_err}, falling back to CPU ollama")
                    # Fallback to CPU ollama
                    try:
                        cpu_prompt = prompt or (messages[-1]["content"] if messages else "")
                        cpu_payload = {"model": config.OLLAMA_MODEL,
                                       "messages": [{"role": "user", "content": cpu_prompt}],
                                       "stream": False, "options": {"temperature": 0.1}}
                        cpu_resp = requests.post(config.OLLAMA_URL, json=cpu_payload,
                                                 headers={}, timeout=90)
                        if cpu_resp.status_code == 200:
                            cpu_data = cpu_resp.json()
                            result = (cpu_data.get("message", {}).get("content")
                                      or cpu_data.get("response", "AI Error (CPU fallback no response)"))
                        else:
                            result = f"Chyba spojení s AI: {hailo_err}"
                    except Exception as cpu_err:
                        result = f"Chyba spojení s AI: {hailo_err}"

            elif config.ARGS.get("EXTERNAL_OLLAMA"):
                ext_messages = messages if messages is not None else [{"role": "user", "content": prompt}]
                payload_v1 = {
                    "model": config.OLLAMA_MODEL,
                    "messages": ext_messages,
                    "stream": False,
                    "temperature": temperature,
                    "max_tokens": num_ctx
                }
                payload_legacy = {
                    "model": config.OLLAMA_MODEL,
                    "prompt": prompt or (messages[-1]["content"] if messages else ""),
                    "stream": False,
                    "options": {"temperature": temperature, "num_ctx": num_ctx}
                }
                is_v1 = "/v1/" in config.OLLAMA_URL
                primary_payload = payload_v1 if is_v1 else payload_legacy
                secondary_payload = payload_legacy if is_v1 else payload_v1

                headers = {"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else {}

                try:
                    resp = requests.post(config.OLLAMA_URL, json=primary_payload, headers=headers, timeout=90)
                    if resp.status_code == 400:
                        utils.log_message(f"AI: Primary format failed (400), trying fallback...")
                        resp = requests.post(config.OLLAMA_URL, json=secondary_payload, headers=headers, timeout=90)

                    if resp.status_code != 200:
                        raise Exception(f"External Ollama Error {resp.status_code}: {resp.text}")

                    data = resp.json()
                    result = data.get("choices", [{}])[0].get("message", {}).get("content") # v1
                    if not result:
                        result = data.get("response", "AI Error (No response field)") # legacy

                except Exception as e:
                    utils.log_message(f"AI: Critical Connection Error: {e}")
                    result = f"Chyba spojení s AI: {str(e)}"

            else:
                res = subprocess.run(
                    [config.OLLAMA_BIN, "run", config.OLLAMA_MODEL],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=90
                )
                if res.returncode != 0:
                    raise RuntimeError(f"Local Ollama Error: {res.stderr}")
                result = res.stdout.strip()
            
            duration = time.time() - start_ts
            self.metrics["ai_latency_history"].append(duration)
            self.log_event("ai_inference", "Ollama execution success", duration_ms=duration*1000)
            return result

        except Exception as e:
            self.metrics["ai_errors"] += 1
            self.log_event("ai_error", str(e), level=logging.ERROR)
            return f"AI Error: {e}"
        finally:
            self.llm_semaphore.release()

    def call_ai_knowledge_base(self, query):
        context = rag.rag_system.search(query)
        status_note = "(KB indexing, text-search only) " if not rag.rag_system.is_ready else ""
        has_context = bool(context and context.strip() not in ("", "KB Empty.", "No text match found."))

        # [-5:-1] — last 4 exchanges, excluding the current message (just appended)
        history_str = "\n".join(self.conversation_history[-5:-1])

        # Active alerts summary — top 5 by severity/recency
        alerts_note = ""
        try:
            active = state.get_active_issues()
            if active:
                top = sorted(active, key=lambda i: i.get('last_seen', ''), reverse=True)[:5]
                alerts_note = "Active infrastructure alerts: " + "; ".join(
                    f"{i.get('host','?')} [{(i.get('channel_type','?')).upper()}]: {(i.get('last_line',''))[:60]}"
                    for i in top
                )
        except Exception:
            pass

        system_content = (
            "You are Sentinel, an AI assistant for Linux server and infrastructure administration. "
            f"{status_note}"
            "Answer in ENGLISH. Be concise and structured (bullet points or short paragraphs). "
            "If the provided context is not relevant to the question, answer from your general "
            "Linux/infrastructure expertise and say so briefly. Never hallucinate commands or facts."
        )

        user_parts = []
        if history_str:
            user_parts.append(f"Conversation history:\n{history_str}")
        if alerts_note:
            user_parts.append(alerts_note)
        if has_context:
            user_parts.append(f"Knowledge base context (use if relevant):\n{context}")
        user_parts.append(f"Question: {query}")
        user_content = "\n\n".join(user_parts)

        if config.HAILO_OLLAMA_ENABLED:
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user",   "content": user_content},
            ]
            return self.execute_ollama(None, messages=messages)

        prompt = f"{system_content}\n\n{user_content}\n\nAnswer:"
        return self.execute_ollama(prompt)

    def _render_issue_card(self, i, role) -> str:
        kb64 = base64.b64encode(i['key'].encode()).decode()
        ts = i.get('last_seen', 'N/A').replace('T', ' ').split('.')[0]
        channel = i.get('channel_type', 'general').upper()
        plugin_origin = i.get('plugin_name', 'unknown').upper()

        _ch_colors = getattr(config, 'CHANNEL_COLORS', {})
        border = _ch_colors.get(channel, _ch_colors.get('INFRA', '#aaa'))
        det_color = border

        extra_badge = ""
        card_class = ""
        _status = i.get('status', 'active')
        if _status == 'validating':
            border = "#0078d4"
            card_class = "validating-card"
            extra_badge = "<span class='validating-badge' style='color:#0078d4; margin-left:5px; font-weight:bold;'><i class='fa-solid fa-circle-notch fa-spin'></i> OVĚŘOVÁNÍ</span>"
        elif _status == 'acknowledged':
            border = "#f0ad4e"
            card_class = "acknowledged-card"
            ack_by = html.escape(i.get('acknowledged_by') or '')
            extra_badge = f"<span style='color:#f0ad4e; margin-left:5px; font-weight:bold;'><i class='fa-solid fa-check'></i> POTVRZENO{(' — ' + ack_by) if ack_by else ''}</span>"

        # Auto-remediation failed — výrazné zvýraznění
        _is_autofail = i.get('plugin_name', '').lower() == 'auto_remediation' or i.get('key','').startswith('AUTOFAIL|')
        if _is_autofail:
            border = "#ff4500"
            card_class = (card_class + " autofail-card").strip()
            extra_badge += "<span style='background:#ff4500; color:#fff; border-radius:4px; font-size:0.75em; padding:1px 6px; margin-left:6px; font-weight:bold;'>⚡ AUTO-OPRAVA SELHALA</span>"

        # Severity badge
        _sev = (i.get('severity') or '').lower()
        _sev_colors = {'critical': ('#ff4500', '🔴'), 'high': ('#fd7e14', '🟠'), 'medium': ('#ffc107', '🟡'), 'low': ('#6c757d', '⚪')}
        severity_badge = ""
        if _sev in _sev_colors:
            sc, si = _sev_colors[_sev]
            severity_badge = f"<span title='Priorita: {_sev}' style='color:{sc}; font-size:0.8em; margin-left:5px; cursor:pointer;' onclick=\"_setSeverity('{kb64}', this)\">{si} {_sev.upper()}</span>"
        elif role in ('admin', 'superadmin'):
            severity_badge = f"<span title='Nastavit prioritu' style='color:var(--text-muted); font-size:0.78em; margin-left:5px; cursor:pointer; opacity:0.5;' onclick=\"_setSeverity('{kb64}', this)\">⚪ —</span>"

        # Snooze state
        snoozed_until = i.get('snoozed_until')
        is_snoozed = False
        snooze_badge = ""
        if snoozed_until:
            from datetime import timezone as _tz
            try:
                su = datetime.fromisoformat(snoozed_until)
                if su.tzinfo is None:
                    su = su.replace(tzinfo=_tz.utc)
                if su > datetime.now(_tz.utc):
                    is_snoozed = True
                    snooze_label = su.strftime('%H:%M')
                    snooze_badge = (
                        f"<span style='color:#6c757d; margin-left:6px; font-size:0.82em;'>"
                        f"⏸ do {snooze_label}</span>"
                    )
                    border = "#444"
            except Exception:
                pass

        safe_host = html.escape(i.get('host', '?'))
        safe_msg = html.escape(i.get('last_line', ''))

        fix_btn = ""
        reanalyze_btn = ""
        ssh_btn = ""
        runbook_btn = ""
        if role in ['admin', 'superadmin', 'viewer']:
            raw_payload = f"{i.get('host','?')}: {i.get('last_line','')}"
            b64_payload = base64.b64encode(raw_payload.encode()).decode()
            fix_btn = f"<i class='fa-solid fa-wand-magic-sparkles' title='Autofix' style='cursor:pointer; color:#a855f7; font-size:1.15em; margin-right:12px; transition:opacity 0.2s;' onmouseover=\"this.style.opacity='0.7'\" onmouseout=\"this.style.opacity='1'\" onclick=\"openAutofixModal('{b64_payload}')\"></i>"
        if role in ['admin', 'superadmin']:
            reanalyze_btn = f"<i class='fa-solid fa-rotate-right' title='Re-analyze AI' style='cursor:pointer; color:var(--text-muted); font-size:1.1em; margin-right:12px; transition:color 0.2s;' onmouseover=\"this.style.color='var(--accent)'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"_reanalyzeIssue('{kb64}')\"></i>"
            _host = html.escape(i.get('host', ''))
            if _host:
                ssh_btn = f"<i class='fa-solid fa-terminal' title='SSH na {_host}' style='cursor:pointer; color:var(--text-muted); font-size:1.1em; margin-right:12px; transition:color 0.2s;' onmouseover=\"this.style.color='var(--accent)'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"openSshModal('{_host}')\"></i>"
            _plugin = html.escape(i.get('plugin_name', ''))
            _channel = html.escape(i.get('channel_type', ''))
            _ll_b64 = base64.b64encode((i.get('last_line', '') or '').encode()).decode()
            runbook_btn = f"<i class='fa-solid fa-book-open' title='Runbook' style='cursor:pointer; color:var(--text-muted); font-size:1.05em; margin-right:12px; transition:color 0.2s;' onmouseover=\"this.style.color='#fd7e14'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"openRunbookModal('{_plugin}','{_channel}','{_ll_b64}')\"></i>"

        share_text = f"[{ts}] [{plugin_origin}] {safe_host}: {safe_msg}".replace("'", "\\'")
        comment_btn = (
            f"<span id='cbadge-{kb64}' onclick=\"openIssueCommentsModal('{kb64}')\" "
            f"title='Komentáře' style='cursor:pointer; color:var(--text-muted); font-size:1.15em; margin-right:12px; "
            f"display:inline-flex; align-items:center; gap:3px; transition:color 0.2s;' "
            f"onmouseover=\"this.style.color='var(--text-main)'\" onmouseout=\"this.style.color='var(--text-muted)'\">"
            f"<i class='fa-regular fa-comment-dots'></i></span>"
        )
        share_btn = f"<i class='fa-solid fa-share-nodes' title='Sdílet' style='cursor:pointer; color:var(--text-muted); font-size:1.15em; margin-right:12px; transition:color 0.2s;' onmouseover=\"this.style.color='var(--text-main)'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"shareIssue('{share_text}', this)\"></i>"
        ignore_html = f"<i class='fa-solid fa-eye-slash' title='Ignorovat' style='cursor:pointer; color:var(--text-muted); font-size:1.15em; margin-right:12px; transition:color 0.2s;' onmouseover=\"this.style.color='var(--text-main)'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"triggerAction('ignore_key {kb64}')\"></i>" if role in ['admin', 'superadmin'] else ""
        delete_html = f"<i class='fa-solid fa-trash' title='Smazat' style='cursor:pointer; color:#c50f1f; font-size:1.15em; transition:opacity 0.2s;' onmouseover=\"this.style.opacity='0.7'\" onmouseout=\"this.style.opacity='1'\" onclick=\"triggerAction('delete_key {kb64}')\"></i>" if role in ['admin', 'superadmin'] else ""

        if role in ['admin', 'superadmin']:
            if is_snoozed:
                snooze_btn = (
                    f"<i class='fa-solid fa-bell' title='Zrušit odložení' style='cursor:pointer; color:#ffc107; "
                    f"font-size:1.15em; margin-right:12px;' onclick=\"unsnoozeIssue('{kb64}')\"></i>"
                )
            else:
                snooze_btn = (
                    f"<i class='fa-solid fa-clock' title='Odložit' style='cursor:pointer; color:var(--text-muted); "
                    f"font-size:1.15em; margin-right:12px; transition:color 0.2s;' "
                    f"onmouseover=\"this.style.color='var(--text-main)'\" onmouseout=\"this.style.color='var(--text-muted)'\" "
                    f"onclick=\"snoozeIssue('{kb64}', this)\"></i>"
                )
            if _status == 'acknowledged':
                ack_btn = (
                    f"<i class='fa-solid fa-rotate-left' title='Zrušit potvrzení' style='cursor:pointer; color:#f0ad4e; "
                    f"font-size:1.15em; margin-right:12px;' onclick=\"_unackIssue('{kb64}')\"></i>"
                )
            else:
                ack_btn = (
                    f"<i class='fa-solid fa-check-double' title='Potvrdit (Acknowledge)' style='cursor:pointer; color:var(--text-muted); "
                    f"font-size:1.15em; margin-right:12px; transition:color 0.2s;' "
                    f"onmouseover=\"this.style.color='#f0ad4e'\" onmouseout=\"this.style.color='var(--text-muted)'\" "
                    f"onclick=\"_ackIssue('{kb64}')\"></i>"
                )
        else:
            snooze_btn = ""
            ack_btn = ""

        card_opacity = "opacity:0.55;" if is_snoozed else ""

        # SLA badge
        _sla_badge = ""
        _sla_rules = getattr(config, 'SLA_RULES', {})
        _ch_lower = channel.lower()
        if _sla_rules and _ch_lower in _sla_rules:
            _sla_hours = _sla_rules[_ch_lower]
            _fs = i.get('first_seen') or i.get('last_seen', '')
            if _fs:
                try:
                    from datetime import timezone as _tz2
                    _fs_dt = datetime.fromisoformat(_fs)
                    if _fs_dt.tzinfo is None:
                        _fs_dt = _fs_dt.replace(tzinfo=_tz2.utc)
                    _age_h = (datetime.now(_tz2.utc) - _fs_dt).total_seconds() / 3600
                    _remaining = _sla_hours - _age_h
                    if _remaining < 0:
                        _sla_badge = f"<span style='background:#dc3545; color:#fff; border-radius:4px; font-size:0.72em; padding:1px 6px; margin-left:5px; font-weight:bold;'>⏰ SLA +{abs(_remaining):.1f}h</span>"
                    elif _remaining < _sla_hours * 0.25:
                        _sla_badge = f"<span style='background:#fd7e14; color:#fff; border-radius:4px; font-size:0.72em; padding:1px 6px; margin-left:5px;'>⏰ {_remaining:.1f}h</span>"
                except Exception:
                    pass

        # Assignee badge
        _assignee = i.get('assigned_to')
        _assignee_badge = ""
        if _assignee:
            _safe_assignee = html.escape(str(_assignee)[:20])
            _assignee_badge = (
                f"<span title='Přiřazeno: {_safe_assignee}' onclick=\"_openAssignPicker('{kb64}')\" "
                f"style='background:rgba(0,120,212,.15);color:#a3cfff;border:1px solid rgba(0,120,212,.3);"
                f"border-radius:10px;font-size:.72em;padding:1px 7px;margin-left:5px;cursor:pointer;'>"
                f"@{_safe_assignee}</span>"
            )
        elif role in ('admin', 'superadmin'):
            _assignee_badge = (
                f"<span onclick=\"_openAssignPicker('{kb64}')\" title='Přiřadit' "
                f"style='color:var(--text-muted);font-size:.72em;margin-left:5px;cursor:pointer;opacity:.4;'>@—</span>"
            )

        occ = i.get('occurrence_count', 1) or 1
        occ_badge = (
            f" <span title='Počet výskytů' style='background:#555; color:#fff; border-radius:10px; "
            f"font-size:0.72em; padding:1px 6px; margin-left:4px; font-weight:bold;'>×{occ}</span>"
        ) if occ > 1 else ""

        first_seen_str = ""
        if occ > 1 and i.get('first_seen'):
            try:
                fs = datetime.fromisoformat(i['first_seen'])
                first_seen_str = f" <span title='První výskyt' style='color:var(--text-muted); font-size:0.75em;'>od {fs.strftime('%d.%m %H:%M')}</span>"
            except Exception:
                pass

        return (f"<div class='{card_class}' data-issue-card='1' data-issue-key='{kb64}' "
                f"style='background:var(--card-bg); border-left:4px solid {border}; padding:8px 12px; margin-bottom:6px; "
                f"display:flex; justify-content:space-between; align-items:center; color:var(--text-main); "
                f"border-right:1px solid var(--card-border); border-top:1px solid var(--card-border); border-bottom:1px solid var(--card-border); {card_opacity}'>"
                f"<div style='flex-grow:1; min-width:0;'>"
                f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;'>"
                f"<small style='color:var(--text-muted); font-size:0.8em;'>🕒 {ts} | <b style='color:{det_color};'>[{plugin_origin}]</b>{occ_badge}{first_seen_str}{extra_badge}{snooze_badge}{severity_badge}{_sla_badge}{_assignee_badge}</small>"
                f"<small style='background:rgba(255,255,255,0.05); padding:1px 5px; border-radius:3px; font-size:0.75em; color:var(--text-muted);'>{channel}</small>"
                f"</div>"
                f"<span style='font-size:0.95em; word-break:break-word;'><b>{safe_host}</b>: {safe_msg}</span>"
                f"</div>"
                f"<div style='display:flex; align-items:center; flex-shrink:0; padding-left:15px;'>{fix_btn}{reanalyze_btn}{runbook_btn}{ssh_btn}{ack_btn}{snooze_btn}{comment_btn}{share_btn}{ignore_html}{delete_html}</div>"
                f"</div>")

    _GROUP_COLLAPSE_AT = 3

    def get_status_html(self, role):
        all_active = state.get_active_issues(include_snoozed=True)
        visible_active = [
            i for i in all_active
            if i.get('key') not in self.ignored_issues
            and (role == 'superadmin' or i.get('channel_type', '').lower() != 'root')
        ]
        snoozed_count = state.get_snoozed_count()
        non_snoozed = [i for i in visible_active if not i.get('snoozed_until')]
        snooze_note = (
            f" <span style='font-size:0.7em; color:#6c757d; font-weight:normal;'>⏸ {snoozed_count} odloženo</span>"
            if snoozed_count else ""
        )
        header_html = (
            f"<div class='status-header' onclick='toggleStatus(this)'>"
            f"<h3 style='color:var(--text-main); margin:0; cursor:pointer;'>"
            f"DETECTED ISSUES ({len(non_snoozed)}){snooze_note}"
            f" <span style='font-size:0.8em; color:var(--text-muted);'>▼</span></h3></div>"
        )
        body_html = "<div class='status-body'>"

        if visible_active:
            # Group by plugin_name, preserving insertion order
            groups: dict[str, list] = {}
            for i in visible_active:
                groups.setdefault(i.get('plugin_name', 'unknown'), []).append(i)

            for plugin_key, issues in groups.items():
                threshold = self._GROUP_COLLAPSE_AT
                visible_issues = issues[:threshold]
                overflow = issues[threshold:]

                for i in visible_issues:
                    body_html += self._render_issue_card(i, role)

                if overflow:
                    gid = base64.b64encode(plugin_key.encode()).decode().replace('=', '')[:12]
                    n = len(overflow)
                    label_show = f"+ {n} more [{plugin_key.upper()}] ▼"
                    label_hide = f"− hide [{plugin_key.upper()}] ▲"
                    toggle_js = (
                        f"var g=document.getElementById('grp-{gid}');"
                        f"if(g.style.display==='none'){{g.style.display='block';this.textContent='{label_hide}';}}"
                        f"else{{g.style.display='none';this.textContent='{label_show}';}}"
                    )
                    body_html += (
                        f"<div data-group-row='1' style='text-align:center; margin:-2px 0 6px 0;'>"
                        f"<span style='font-size:0.78em; color:var(--text-muted); cursor:pointer; "
                        f"text-decoration:underline; user-select:none;' onclick=\"{toggle_js}\">"
                        f"{label_show}</span></div>"
                        f"<div id='grp-{gid}' style='display:none;'>"
                    )
                    for i in overflow:
                        body_html += self._render_issue_card(i, role)
                    body_html += "</div>"

            export_btn = ("<a href='/api/export/incidents.csv' style='color:var(--text-muted); font-size:0.8em; text-decoration:underline; margin-right:12px;'><i class='fa-solid fa-file-csv'></i> incidents</a>"
                          "<a href='/api/export/telemetry.csv' style='color:var(--text-muted); font-size:0.8em; text-decoration:underline; margin-right:12px;'><i class='fa-solid fa-file-csv'></i> telemetry</a>")
            delete_all = ""
            if role in ['admin', 'superadmin']:
                delete_all = f"<span style='color:var(--text-muted); font-size:0.8em; cursor:pointer; text-decoration:underline;' onclick=\"triggerAction('delete_all_issues')\">smazat vše</span>"
            body_html += f"<div style='margin-top:10px; text-align:right;'>{export_btn}{delete_all}</div>"
        else:
            body_html += "<div style='color:#107c10; text-align:center; padding:15px; font-weight:bold;'><i class='fa-solid fa-check-circle'></i> System OK</div>"

        body_html += "</div>"
        return f"<div class='status-wrapper'>{header_html}{body_html}</div>"

    def setup_routes(self):
        from .routes import main as main_routes
        from .routes import issues as issues_routes
        from .routes import agents as agents_routes
        from .routes import actions as actions_routes
        from .routes import system as system_routes
        from .routes import export as export_routes
        from .routes import integrations as integrations_routes
        from .routes import chat as chat_routes

        self.app.register_blueprint(main_routes.create_blueprint(self, self.socketio))
        self.app.register_blueprint(issues_routes.create_blueprint(self))
        self.app.register_blueprint(agents_routes.create_blueprint(self))
        self.app.register_blueprint(actions_routes.create_blueprint(self))
        self.app.register_blueprint(system_routes.create_blueprint(self))
        self.app.register_blueprint(export_routes.create_blueprint(self))
        self.app.register_blueprint(integrations_routes.create_blueprint(self))
        self.app.register_blueprint(chat_routes.create_blueprint(self))

def start_chat_service():
    srv = ChatService(); srv.start(); return srv


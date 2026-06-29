import logging
import threading
import os
import time
import json
import requests
import secrets
from functools import wraps
from flask import request, jsonify, g, redirect, url_for, session, Response
from . import state, config, utils


# --- STRUCTURED LOGGING SETUP ---
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": __import__('datetime').datetime.fromtimestamp(record.created).isoformat(),
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

def _check_password(plain: str, stored: str) -> bool:
    """347: Ověří heslo — podporuje bcrypt hash ($2b$) i plaintext (fallback).

    Produkce: web.password_hash v config.yaml ($2b$... vygenerovaný bcrypt).
    Vývoj/migrace: web.password v config.yaml (plaintext).
    """
    if not plain or not stored:
        return False
    if stored.startswith('$2b$') or stored.startswith('$2a$') or stored.startswith('$2y$'):
        try:
            import bcrypt as _bcrypt
            return _bcrypt.checkpw(plain.encode(), stored.encode())
        except Exception:
            return False
    # Plaintext fallback — zachovává zpětnou kompatibilitu
    return plain == stored


def check_auth(username: str, password: str) -> str | None:
    # 347: bcrypt hash nebo plaintext fallback
    if username == config.WEB_USER and _check_password(password, config.WEB_PASS):
        return _role_for_user(username) or 'admin'
    if username == config.WEB_VIEWER_USER and _check_password(password, config.WEB_VIEWER_PASS):
        return _role_for_user(username) or 'viewer'

    if config.LDAP_ENABLED:
        logger.info(f"LDAP CHECK: Overuji uzivatele '{username}'...")
        is_success = False

        # Primární cesta: flask-ldap3-login manager
        if ldap_manager:
            try:
                response = ldap_manager.authenticate(username, password)
                is_success = str(response.status) in (
                    'success', 'AuthenticationResponseStatus.success'
                ) or (hasattr(response.status, 'value') and response.status.value == 'success')
                if not is_success:
                    logger.warning(f"LDAP FAIL (manager): {response.status}")
            except Exception as e:
                logger.error(f"LDAP Auth Error (manager): {e}")

        # Záložní cesta: přímý ldap3 bind (funguje i když ldap_manager je None)
        if not is_success:
            try:
                import ldap3
                _host = config.LDAP_HOST
                if not _host.startswith(('ldap://', 'ldaps://')):
                    _host = f"ldap://{_host}"
                _server = ldap3.Server(_host, port=config.LDAP_PORT,
                                       use_ssl=config.LDAP_USE_SSL, connect_timeout=5)
                # Nejdřív vyhledat DN uživatele přes bind account
                _svc = ldap3.Connection(_server,
                                        user=getattr(config, 'LDAP_BIND_DN', None),
                                        password=getattr(config, 'LDAP_BIND_PASSWORD', None),
                                        auto_bind=True)
                _attr = config.LDAP_USER_LOGIN_ATTR
                _base = f"{config.LDAP_SEARCH_USER_DN},{config.LDAP_BASE_DN}"
                _svc.search(_base, f"({_attr}={ldap3.utils.conv.escape_filter_chars(username)})",
                            attributes=[_attr])
                if _svc.entries:
                    _user_dn = _svc.entries[0].entry_dn
                    _user_conn = ldap3.Connection(_server, user=_user_dn,
                                                  password=password, auto_bind=True)
                    is_success = _user_conn.bound
                    _user_conn.unbind()
                _svc.unbind()
                if is_success:
                    logger.info(f"LDAP: Prihlaseni USPESNE (fallback) pro {username}")
                else:
                    logger.warning(f"LDAP FAIL (fallback): uzivatel '{username}' nenalezen nebo spatne heslo")
            except ldap3.core.exceptions.LDAPBindError:
                logger.warning(f"LDAP FAIL (fallback): spatne heslo pro '{username}'")
            except Exception as e:
                logger.error(f"LDAP Auth Error (fallback): {e}")

        if is_success:
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

    return None

def authenticate():
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"error": "Unauthorized"}), 401
    return redirect(url_for('main.login'))

global_active_clients = {}
global_active_clients_lock = threading.Lock()

_REVOKED_SESSIONS: set = set()   # UUID revokovanych sessions (in-memory blacklist)
_SESSION_TOUCH_TS: dict = {}     # suuid → timestamp posledniho touch (throttle)

def int_param(value, default: int = 0, min_val: int = 0, max_val: int = 9999) -> int:
    """242: Bezpečná konverze query/body parametru na int s rozsahem."""
    try:
        v = int(value)
        return max(min_val, min(max_val, v))
    except (TypeError, ValueError):
        return default

def get_real_ip() -> str:
    """232: Vrátí skutečnou IP klienta — čte X-Forwarded-For jen z důvěryhodných proxy."""
    import ipaddress as _ipa
    remote = request.remote_addr or '127.0.0.1'
    trusted = getattr(config, 'TRUSTED_PROXIES', ['127.0.0.1', '::1'])
    # Normalize trusted list (strip prefixes)
    trusted_set = set()
    for t in trusted:
        try:
            net = _ipa.ip_network(t, strict=False)
            trusted_set.add(net)
        except ValueError:
            pass
    def _is_trusted(ip: str) -> bool:
        try:
            addr = _ipa.ip_address(ip)
            return any(addr in net for net in trusted_set)
        except ValueError:
            return False
    if not _is_trusted(remote):
        return remote
    # Try X-Real-IP first (nginx sets this to single real IP)
    real_ip = request.headers.get('X-Real-IP', '').strip()
    if real_ip:
        try:
            _ipa.ip_address(real_ip)
            return real_ip
        except ValueError:
            pass
    # X-Forwarded-For: "client, proxy1, proxy2" — first entry is real client
    xff = request.headers.get('X-Forwarded-For', '').strip()
    if xff:
        candidate = xff.split(',')[0].strip()
        try:
            _ipa.ip_address(candidate)
            return candidate
        except ValueError:
            pass
    return remote

def _ensure_csrf_token() -> str:
    """Vrátí CSRF token pro aktuální session, případně ho vytvoří."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def validate_csrf() -> bool:
    """Ověří CSRF token pro state-changing requests přes session cookie."""
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return True
    # API key nebo Basic auth → CSRF se nevyžaduje (machine-to-machine)
    if request.headers.get('X-API-Key'):
        return True
    if request.authorization:
        return True
    # Agent paths → bez CSRF
    _agent_paths = ('/api/v1/', '/api/sentinel-hw/', '/api/sentinel-alert', '/ingest')
    if any(request.path.startswith(p) for p in _agent_paths):
        return True
    token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token') or ''
    expected = session.get('csrf_token', '')
    return bool(expected and secrets.compare_digest(token, expected))

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = get_real_ip()
        if not client_ip.startswith('192.168.') and client_ip not in ['127.0.0.1', '::1']:
            if utils.security.is_ip_banned(client_ip): return Response("Banned", 403)

        tracked_user = "anonymous"
        is_mobile = False

        client_user_header = request.headers.get('X-Client-User')
        if client_user_header:
            is_mobile = True

        # 1. KONTROLA PREZENCE X-API-KEY (mobilní aplikace nebo REST API klíče)
        api_key = request.headers.get('X-API-Key')
        secure_token = getattr(config, 'CLIENT_API_KEY', '')

        if api_key and api_key == secure_token:
            g.user_role = 'superadmin'
            g.username = client_user_header if client_user_header else 'admin'
            tracked_user = f"{g.username} (Mobil)"
        elif api_key:
            # Ověření přes DB api_keys tabulku
            key_rec = state.verify_api_key(api_key)
            if key_rec:
                scope = key_rec.get('scope', 'read')
                # 287: fine-grained scopes — nové granulární scopy + zpětná kompatibilita
                _SCOPE_TO_ROLE = {
                    'admin':         'superadmin',  # zpětná kompatibilita
                    'write':         'admin',
                    'read':          'viewer',
                    'read:issues':   'viewer',
                    'write:actions': 'admin',
                    'admin:users':   'superadmin',
                }
                g.user_role = _SCOPE_TO_ROLE.get(scope, 'viewer')
                g.username = key_rec.get('name', 'api-key')
                tracked_user = f"{g.username} (API Key [{scope}])"
            else:
                # 103: rate-limit failed API key attempts
                if not utils.security.check_api_key_rate_limit(api_key[:8], client_ip):
                    return Response("Too Many Requests", 429)
                return authenticate()

        # 2. KONTROLA WEBOVÉ RELACE (Cookies pro Web UI)
        elif 'user' in session:
            # Zkontrolovat revokaci session
            _suuid = session.get('_suuid')
            if _suuid and _suuid in _REVOKED_SESSIONS:
                session.clear()
                return authenticate()
            # 348: Absolute session timeout
            _max_hours = config.SECURITY.get('session_max_hours', 12)
            _session_born = session.get('_born')
            if _session_born and (time.time() - _session_born) > _max_hours * 3600:
                session.clear()
                return authenticate()
            g.username = session.get('user', 'anonymous')
            tracked_user = g.username
            # 231: CSRF validace pro session-based state-changing requests
            if not validate_csrf():
                return Response('CSRF token invalid or missing', 403,
                                {'Content-Type': 'application/json',
                                 'X-CSRF-Error': '1'})
            # Touch session v DB (throttle — ne každý request)
            if _suuid:
                import time as _t
                _now_t = _t.time()
                if _now_t - _SESSION_TOUCH_TS.get(_suuid, 0) > 60:
                    _SESSION_TOUCH_TS[_suuid] = _now_t
                    state.session_touch(_suuid)
            # 286: Role refresh z DB — zachytí změny provedené adminem za běhu
            # Throttlováno na 1× za 5 minut per session aby nedocházelo k DB hitu na každý request
            _role_refresh_key = f"role_refresh_{_suuid or g.username}"
            _now_t2 = time.time()
            if _now_t2 - _SESSION_TOUCH_TS.get(_role_refresh_key, 0) > 300:
                _SESSION_TOUCH_TS[_role_refresh_key] = _now_t2
                _db_role = _role_for_user(g.username)
                if _db_role and _db_role != session.get('role'):
                    session['role'] = _db_role
            g.user_role = session.get('role', 'user')

        # 3. HTTP BASIC AUTH (Fallback)
        else:
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password):
                if auth: utils.security.register_failed_login(client_ip)
                return authenticate()

            g.user_role = check_auth(auth.username, auth.password)
            g.username = auth.username
            tracked_user = f"{g.username} (Mobil)" if is_mobile else g.username

        # 102: IP whitelist per-role
        _role_whitelist = getattr(config, 'IP_WHITELIST', {})
        if _role_whitelist and hasattr(g, 'user_role'):
            _allowed = _role_whitelist.get(g.user_role, _role_whitelist.get('*', []))
            if _allowed:
                import ipaddress as _ip
                _client = client_ip
                _ok = False
                for cidr in _allowed:
                    try:
                        if _ip.ip_address(_client) in _ip.ip_network(cidr, strict=False):
                            _ok = True; break
                    except Exception:
                        if cidr == _client:
                            _ok = True; break
                if not _ok:
                    return Response(f"Access denied for role {g.user_role} from {_client}", 403)

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
    _session = requests.Session()
    for user, passwd in [(config.WEB_USER, config.WEB_PASS), ('admin', 'sentinel')]:
        try:
            resp = _session.post(f"{base_url}/login",
                                data={'username': user, 'password': passwd},
                                allow_redirects=False, timeout=5)
            if resp.status_code == 302:
                return _session
        except Exception:
            pass
    return _session

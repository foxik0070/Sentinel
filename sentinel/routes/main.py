import time
import logging
import secrets
from flask import Blueprint, request, jsonify, render_template, g, session, redirect, url_for
from ..auth import requires_auth, check_auth, get_real_ip, _REVOKED_SESSIONS, global_active_clients, global_active_clients_lock, _ensure_csrf_token
from .. import state, config, utils

# 346: 2FA pending — session klíč pro stav "přihlášen lokálně, čeká na TOTP"
_TOTP_PENDING_KEY = '_totp_pending_user'

logger = logging.getLogger("sentinel.chat")


def create_blueprint(service, socketio):
    bp = Blueprint('main', __name__)

    @bp.route('/')
    @requires_auth
    def index():
        if g.username: service.metrics["active_users"].add(g.username)
        _ensure_csrf_token()
        return render_template(
            'index.html',
            log_groups=config.LOG_GROUPS,
            version=config.VERSION,
            subversion=config.SUBVERSION,
            instance_name=config.INSTANCE_NAME,
            teams_enabled=config.TEAMS_ENABLED,
            ha_enabled=config.HA_ENABLED,
            role=g.user_role,
            username=g.username,
            client_ip=get_real_ip(),
            default_creds_warning=getattr(service, '_default_creds_warning', False),
        )

    @bp.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            # 281: Brute-force ochrana
            client_ip = get_real_ip()
            if utils.security.is_ip_banned(client_ip):
                service.log_event("auth_banned", f"Banned IP {client_ip} attempted login", level=logging.WARNING)
                return render_template('login.html', error="Příliš mnoho pokusů. Zkuste to později."), 429
            u, p = request.form.get('username'), request.form.get('password')
            role = check_auth(u, p)
            if role:
                # 346: Zkontrolovat 2FA
                if state.totp_get(u) and state.totp_get(u).get('enabled'):
                    session[_TOTP_PENDING_KEY] = {'user': u, 'role': role}
                    return render_template('login.html', totp_required=True)
                _complete_login(u, role, service)
                return redirect(url_for('main.index'))
            utils.security.register_failed_login(client_ip)
            service.log_event("auth_fail", f"Failed login attempt for {u} from {client_ip}", level=logging.WARNING)
            return render_template('login.html', error="Neplatné údaje")
        return render_template('login.html')

    @bp.route('/login/totp', methods=['POST'])
    def login_totp():
        """346: Druhý krok přihlášení — ověření TOTP kódu."""
        pending = session.get(_TOTP_PENDING_KEY)
        if not pending:
            return redirect(url_for('main.login'))
        code = (request.form.get('totp_code') or '').strip()
        u, role = pending['user'], pending['role']
        if state.totp_verify(u, code):
            session.pop(_TOTP_PENDING_KEY, None)
            _complete_login(u, role, service)
            return redirect(url_for('main.index'))
        # Špatný kód — zůstat na TOTP formuláři
        return render_template('login.html', totp_required=True, error="Neplatný kód. Zkuste znovu.")

    def _complete_login(u, role, svc):
        """Finalizuje přihlášení — zapíše session do DB."""
        session['user'], session['role'] = u, role
        session['_born'] = time.time()  # 348: absolute timeout marker
        _suuid = secrets.token_hex(16)
        session['_suuid'] = _suuid
        state.session_register(_suuid, u, role,
                               get_real_ip(),
                               request.headers.get('User-Agent', ''))
        svc.log_event("auth_login", f"User {u} logged in as {role}")

    @bp.route('/logout')
    def logout():
        u = session.get('user', 'unknown')
        _suuid = session.get('_suuid')
        if _suuid:
            state.session_remove(_suuid)
        service.log_event("auth_logout", f"User {u} logged out")
        session.clear()
        return redirect(url_for('main.login'))

    # ── 346: 2FA / TOTP management ───────────────────────────────────────────────

    @bp.route('/api/2fa/status', methods=['GET'])
    @requires_auth
    def api_2fa_status():
        """Vrátí stav 2FA pro přihlášeného uživatele."""
        record = state.totp_get(g.username)
        return jsonify({"enabled": bool(record and record.get('enabled'))})

    @bp.route('/api/2fa/setup', methods=['POST'])
    @requires_auth
    def api_2fa_setup():
        """Vygeneruje nový TOTP secret, vrátí provisioning URI + QR kód (base64 PNG)."""
        import pyotp, qrcode, io, base64
        secret = state.totp_setup(g.username)
        instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=g.username, issuer_name=f"Sentinel {instance}")
        # QR kód jako base64 PNG
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
        return jsonify({"secret": secret, "uri": uri, "qr_png_b64": qr_b64})

    @bp.route('/api/2fa/enable', methods=['POST'])
    @requires_auth
    def api_2fa_enable():
        """Aktivuje 2FA po ověření prvního TOTP kódu."""
        code = (request.json or {}).get('code', '').strip()
        if not code:
            return jsonify({"error": "Kód je povinný"}), 400
        if state.totp_enable(g.username, code):
            service.log_event("2fa_enabled", f"2FA aktivováno pro {g.username}", user=g.username)
            return jsonify({"status": "ok"})
        return jsonify({"error": "Neplatný kód"}), 400

    @bp.route('/api/2fa/disable', methods=['POST'])
    @requires_auth
    def api_2fa_disable():
        """Deaktivuje 2FA (vyžaduje aktuální TOTP kód nebo admin právo)."""
        is_admin = g.user_role in ('admin', 'superadmin')
        target = (request.json or {}).get('username', g.username)
        # Vlastní deaktivace: vyžaduje platný kód
        if target == g.username and not is_admin:
            code = (request.json or {}).get('code', '').strip()
            if not state.totp_verify(g.username, code):
                return jsonify({"error": "Neplatný TOTP kód"}), 403
        elif target != g.username and not is_admin:
            return jsonify({"error": "Forbidden"}), 403
        state.totp_disable(target)
        service.log_event("2fa_disabled", f"2FA deaktivováno pro {target}", user=g.username)
        return jsonify({"status": "ok"})

    @bp.route('/api/get_status_html')
    @requires_auth
    def get_status_html_api():
        return jsonify({"html": service.get_status_html(g.user_role)})

    @bp.route('/api/root_audit', methods=['GET'])
    @requires_auth
    def get_root_audit():
        with state.db_lock:
            conn = state._get_conn()
            try:
                c = conn.execute("SELECT server, ip, connected_at, is_active, disconnected_at FROM root_audit ORDER BY is_active DESC, connected_at DESC LIMIT 100")
                rows = [{"server": r[0], "ip": r[1], "connected_at": r[2], "is_active": bool(r[3]), "disconnected_at": r[4]} for r in c.fetchall()]
            finally:
                conn.close()
        return jsonify(rows)

    @socketio.on('join_private')
    def handle_join_private(data):
        from flask_socketio import join_room
        room_id = data.get('room_id', '').strip()
        if room_id:
            join_room(room_id)

    @socketio.on('ping_presence')
    def handle_ping_presence(data):
        room_id = data.get('room_id', '').strip()
        user = data.get('user', 'admin').strip()

        if room_id:
            client_ip = get_real_ip()
            now = time.time()
            # Zapíšeme mobilní spojení z pozadí do aktivních klientů
            with global_active_clients_lock:
                global_active_clients[room_id] = {
                    "user": f"{user} (Mobil)",
                    "ip": client_ip,
                    "device_id": room_id,
                    "connected_since": global_active_clients.get(room_id, {}).get("connected_since", now),
                    "last_seen": now,
                    "is_mobile": True
                }

    @socketio.on('send_private_msg')
    def handle_send_private_msg(data):
        target_ip = data.get('target', '').strip()
        if target_ip and data.get('message'):
            socketio.emit('receive_private_msg', data, room=target_ip)

    return bp

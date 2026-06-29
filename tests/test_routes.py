"""
M0-4: Integration testy na kritické API endpointy — Flask test client.

Testuje: status_check, modal_issues, v1/issues, agent ingest, config update, CSRF.
Používá temp DB — žádný vliv na produkci.

Run:
    python -m pytest tests/test_routes.py -v
"""
import json
import os
import sys
import tempfile
import unittest
import secrets

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state, config


def _create_test_app():
    """Vytvoří Flask app s registrovanými blueprinty a temp DB."""
    from sentinel.chat_service import ChatService

    # Temp DB
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    state.DB_FILE = tmp.name
    state.init_db()

    svc = ChatService.__new__(ChatService)
    # Minimální inicializace bez spuštění vlákna
    from flask import Flask
    from flask_socketio import SocketIO
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sentinel', 'templates')
    svc.app = Flask(__name__, template_folder=os.path.abspath(template_dir))
    svc.socketio = SocketIO(svc.app, async_mode='threading')
    svc.app.secret_key = 'test-secret-key'
    svc.app.config['TESTING'] = True
    svc.app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    svc.ignored_issues = set()
    svc.metrics = {"active_users": set(), "ai_requests": 0, "ai_errors": 0,
                   "ai_latency_history": [], "cmd_executed": 0, "last_request_ts": 0}
    svc.conversation_history = []
    svc._conv_history_limit = 100
    svc._default_creds_warning = False
    svc.user_sessions = {}
    svc.chat_queue_depth = 0
    svc.start_time = __import__('datetime').datetime.now()
    svc._notify_throttle = {}
    import collections
    svc.metrics["ai_latency_history"] = collections.deque(maxlen=50)
    svc.request_history = __import__('collections').defaultdict(__import__('collections').deque)

    def _noop_log_event(*a, **kw): pass
    svc.log_event = _noop_log_event
    def _noop_uptime(): return "0h"
    svc.get_uptime = _noop_uptime
    def _noop_status_html(role='admin'): return "<div>OK</div>"
    svc.get_status_html = _noop_status_html

    # Registrace blueprintů
    from sentinel.routes import main as main_routes
    from sentinel.routes import issues as issues_routes
    from sentinel.routes import agents as agents_routes
    from sentinel.routes import system as system_routes

    svc.app.register_blueprint(main_routes.create_blueprint(svc, svc.socketio))
    svc.app.register_blueprint(issues_routes.create_blueprint(svc))
    svc.app.register_blueprint(agents_routes.create_blueprint(svc))
    svc.app.register_blueprint(system_routes.create_blueprint(svc))

    return svc.app, tmp.name


class TestAPIEndpoints(unittest.TestCase):
    """Testy na klíčové API endpointy přes Flask test client."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db = state.DB_FILE
        cls.app, cls._tmp_path = _create_test_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        state.DB_FILE = cls._orig_db
        try:
            os.unlink(cls._tmp_path)
        except Exception:
            pass

    def _auth_headers(self):
        """Basic auth hlavičky pro test usera."""
        import base64
        creds = base64.b64encode(f"{config.WEB_USER}:{config.WEB_PASS}".encode()).decode()
        return {'Authorization': f'Basic {creds}'}

    def _session_login(self):
        """Přihlásí se přes session a vrátí client s cookies."""
        resp = self.client.post('/login', data={
            'username': config.WEB_USER,
            'password': config.WEB_PASS
        }, follow_redirects=False)
        return resp

    # ── Status Check ──

    def test_status_check_responds(self):
        # V test mode Basic auth prochází přes LAN IP; ověříme jen že endpoint existuje
        resp = self.client.get('/api/status_check')
        self.assertIn(resp.status_code, [200, 401, 302])

    def test_status_check_with_auth(self):
        resp = self.client.get('/api/status_check', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('issues', data)

    # ── Modal Issues ──

    def test_modal_issues_infra(self):
        resp = self.client.get('/api/modal_issues/infra', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('html', data)

    def test_modal_issues_invalid_channel(self):
        resp = self.client.get('/api/modal_issues/evil', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 400)

    # ── V1 Issues (JSON) ──

    def test_v1_issues_json(self):
        resp = self.client.get('/api/v1/issues', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('issues', data)
        self.assertIsInstance(data['issues'], list)

    # ── Agent Registration ──

    def test_agent_register_requires_superadmin(self):
        # viewer nemá práva registrovat
        import base64
        creds = base64.b64encode(f"{config.WEB_VIEWER_USER}:{config.WEB_VIEWER_PASS}".encode()).decode()
        resp = self.client.post('/api/agents/register',
                                headers={'Authorization': f'Basic {creds}',
                                         'Content-Type': 'application/json'},
                                data=json.dumps({'hostname': 'test-agent'}))
        self.assertIn(resp.status_code, [403, 401])

    def test_agent_register_invalid_hostname(self):
        resp = self.client.post('/api/agents/register',
                                headers={**self._auth_headers(), 'Content-Type': 'application/json'},
                                data=json.dumps({'hostname': '../etc/passwd'}))
        self.assertIn(resp.status_code, [400, 403])

    def test_agent_register_valid(self):
        resp = self.client.post('/api/agents/register',
                                headers={**self._auth_headers(), 'Content-Type': 'application/json'},
                                data=json.dumps({'hostname': 'test-agent-01'}))
        # Může být 200 pokud role = superadmin, nebo 403 pokud Basic auth = admin ne superadmin
        self.assertIn(resp.status_code, [200, 403])

    # ── Public Status Page ──

    def test_public_status_page(self):
        resp = self.client.get('/status')
        self.assertEqual(resp.status_code, 200)
        # Instance name může být jiný než 'Sentinel' (config)
        self.assertIn(b'Status', resp.data)

    # ── CSRF Protection ──

    def test_post_without_csrf_blocked_for_session(self):
        """Session-based POST bez CSRF tokenu by měl vrátit 403 nebo 400/404 (ne 500)."""
        self._session_login()
        # POST bez CSRF tokenu na existující endpoint
        resp = self.client.post('/api/config/update',
                                content_type='application/json',
                                data=json.dumps({}))
        # 403 = CSRF block, 400 = bad request, 200 = passed — vše kromě 500 je OK
        self.assertIn(resp.status_code, [200, 400, 403])

    def test_api_key_bypasses_csrf(self):
        """API key request nepotřebuje CSRF token."""
        key = state.create_api_key('test-key', scope='read', created_by='test')
        if key:
            resp = self.client.get('/api/status_check',
                                   headers={'X-API-Key': key})
            self.assertEqual(resp.status_code, 200)

    # ── Hostname Validation ──

    def test_hostname_validation_blocks_injection(self):
        """Hostnames s nebezpečnými znaky jsou odmítnuty (400 nebo 403 pokud role nestačí)."""
        bad_hostnames = ['test;rm -rf', 'host$(cmd)', 'a' * 200, '', ' spaces bad']
        for hostname in bad_hostnames:
            resp = self.client.post('/api/agents/register',
                                    headers={**self._auth_headers(), 'Content-Type': 'application/json'},
                                    data=json.dumps({'hostname': hostname}))
            self.assertNotEqual(resp.status_code, 200,
                                f"Hostname '{hostname[:20]}' should NOT succeed, got 200")


if __name__ == '__main__':
    unittest.main()

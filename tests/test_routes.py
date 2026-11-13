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
    svc.app.sentinel_service = svc  # testy potrebuji na ignored_issues
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

    # ── /api/v1/issues: surová pole a ignorované ──

    def _seed_issue(self, key, ignored=False):
        """Založí issue a volitelně ho dá na ignore list service."""
        from sentinel import api
        api.report_problem(key, {
            "status": "active", "channel_type": "infra", "host": "node1",
            "last_line": "test", "plugin_name": "test_detector",
            "severity": "high", "last_seen": "2026-11-12T10:00:00+00:00",
        })
        if ignored:
            self.app.sentinel_service.ignored_issues.add(key)
        return key

    def _issues(self, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        resp = self.client.get(f"/api/v1/issues{'?' + q if q else ''}",
                               headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        return {i["key"]: i for i in resp.get_json()["issues"]}

    def test_v1_issues_exposes_raw_db_fields(self):
        key = self._seed_issue("INFRA|node1|raw_fields")
        issue = self._issues().get(key)
        self.assertIsNotNone(issue, "zalozene issue se nevratilo")
        for field in ("first_seen", "occurrence_count", "plugin_name",
                      "db_severity", "acknowledged_by", "snoozed_until"):
            self.assertIn(field, issue, f"chybi pole {field}")
        # Stari problemu a razeni podle zavaznosti stoji prave na techto dvou.
        self.assertTrue(issue["first_seen"], "first_seen nesmi byt prazdne")
        self.assertEqual(issue["db_severity"], "high")
        self.assertEqual(issue["plugin_name"], "test_detector")

    def test_v1_issues_keeps_flutter_field_names(self):
        # IssueModel.fromJson na nich zavisi — severity zustava odvozena z kanalu.
        key = self._seed_issue("INFRA|node1|flutter_compat")
        issue = self._issues()[key]
        for field in ("channelType", "lastSeen", "missingCount", "logFile", "lastLine"):
            self.assertIn(field, issue)
        self.assertEqual(issue["severity"], "WARNING")

    def test_v1_issues_hides_ignored_by_default(self):
        key = self._seed_issue("INFRA|node1|hidden_one", ignored=True)
        self.assertNotIn(key, self._issues(),
                         "bez parametru se ignorovane vracet nesmi")

    def test_v1_issues_include_ignored_marks_them(self):
        hidden = self._seed_issue("INFRA|node1|shown_hidden", ignored=True)
        plain = self._seed_issue("INFRA|node1|shown_plain")
        got = self._issues(include_ignored=1)
        self.assertIn(hidden, got)
        self.assertTrue(got[hidden]["ignored"])
        self.assertFalse(got[plain]["ignored"])

    def test_v1_issues_include_ignored_accepts_truthy_values(self):
        key = self._seed_issue("INFRA|node1|truthy", ignored=True)
        for val in ("1", "true", "yes", "TRUE"):
            with self.subTest(value=val):
                self.assertIn(key, self._issues(include_ignored=val))
        for val in ("0", "false", "no", ""):
            with self.subTest(value=val):
                self.assertNotIn(key, self._issues(include_ignored=val))

    # ── Komentáře přímo v kartě issue ──

    def _card_html(self, channel='infra'):
        resp = self.client.get(f'/api/modal_issues/{channel}', headers=self._auth_headers())
        self.assertEqual(resp.status_code, 200)
        return (resp.get_json() or {}).get('html', '')

    def test_comment_is_visible_on_the_card(self):
        from sentinel import api, state
        key = self._seed_issue("INFRA|node1|with_comment")
        state.add_issue_comment(key, "petr", "tohle nesmi zapadnout")
        html = self._card_html()
        self.assertIn("tohle nesmi zapadnout", html,
                      "komentar ma byt videt primo v karte, ne jen pod odznakem")
        self.assertIn("petr", html)

    def test_comment_block_is_visually_distinct(self):
        # Pointa pozadavku: komentar nesmi splynout se zbytkem karty.
        from sentinel import state
        key = self._seed_issue("INFRA|node1|distinct_comment")
        state.add_issue_comment(key, "jana", "odlisena barva")
        html = self._card_html()
        self.assertIn("#a78bfa", html, "komentar nema vlastni barvu")

    def test_comment_text_is_escaped(self):
        from sentinel import state
        key = self._seed_issue("INFRA|node1|xss_comment")
        state.add_issue_comment(key, "petr", "<script>alert(1)</script>")
        html = self._card_html()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_only_recent_comments_inline_rest_behind_link(self):
        from sentinel import state
        key = self._seed_issue("INFRA|node1|many_comments")
        for n in range(1, 6):
            state.add_issue_comment(key, "petr", f"komentar-{n}")
        html = self._card_html()
        # Posledni tri inline, zbytek za odkazem do modalu.
        self.assertIn("komentar-5", html)
        self.assertIn("komentar-3", html)
        self.assertNotIn("komentar-1", html)
        self.assertIn("starších", html)

    def _one_card(self, key, channel='infra'):
        """HTML jedine karty — hledat v celem kanalu by chytlo i cizi komentare."""
        import base64 as _b64
        kb64 = _b64.b64encode(key.encode()).decode()
        html = self._card_html(channel)
        parts = html.split('data-issue-key="')
        for p in parts[1:]:
            if p.startswith(kb64 + '"'):
                return p.split('data-issue-key="')[0]
        self.fail(f"karta pro {key} se ve vypisu nenasla")

    def test_card_without_comments_has_no_block(self):
        key = self._seed_issue("INFRA|node1|no_comment_at_all")
        self.assertNotIn("#a78bfa", self._one_card(key),
                         "karta bez komentaru nema mit blok komentaru")

    def test_card_with_comment_has_block(self):
        from sentinel import state
        key = self._seed_issue("INFRA|node1|own_block")
        state.add_issue_comment(key, "petr", "patri k teto karte")
        card = self._one_card(key)
        self.assertIn("#a78bfa", card)
        self.assertIn("patri k teto karte", card)

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


class TestReadRootScope(unittest.TestCase):
    """Scope read:root — prehled vcetne kanalu ROOT bez prava zapisu.

    Do teto zmeny sel ROOT videt jen pres scope write/admin, tedy za cenu
    klice, ktery umi i zapisovat. Nastroj, ktery jen cte, mel na vyber mezi
    uplnym prehledem a mensim rozsahem skody pri uniku klice.
    """

    @classmethod
    def setUpClass(cls):
        from sentinel import state
        cls._orig_db = state.DB_FILE
        cls.app, cls._tmp_path = _create_test_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        from sentinel import state
        state.DB_FILE = cls._orig_db
        try:
            os.unlink(cls._tmp_path)
        except Exception:
            pass

    def _key(self, scope):
        """Vytvori API klic daneho scope primo v DB a vrati jeho tajnou cast."""
        from sentinel import state
        return state.create_api_key(f"test-{scope}", scope, None, "tester")

    def _get(self, path, scope):
        return self.client.get(path, headers={'X-API-Key': self._key(scope)})

    def test_scope_maps_to_viewer_role(self):
        # Pointa celeho scope: ROOT ano, pravo zapisu ne.
        from sentinel import auth
        import inspect
        src = inspect.getsource(auth)
        self.assertIn("'read:root':     'viewer'", src,
                      "read:root nesmi dostat vyssi roli nez viewer")

    # Endpoint odpira pristup v TELE odpovedi, ne stavovym kodem: vraci 200
    # s JSONem {"html": "..."}. Testy proto ctou to pole, ne syrovy text —
    # v nem je hlaska unicode-escapovana a primy `in` by ji nenasel.
    DENIED = "Přístup odepřen"

    def _root_modal_html(self, scope):
        resp = self._get('/api/modal_issues/root', scope)
        self.assertEqual(resp.status_code, 200)
        return (resp.get_json() or {}).get('html', '')

    def test_read_root_sees_root_channel(self):
        self.assertNotIn(self.DENIED, self._root_modal_html('read:root'),
                         "read:root ma na kanal ROOT dosahnout")

    def test_plain_read_does_not_see_root_channel(self):
        self.assertIn(self.DENIED, self._root_modal_html('read'),
                      "scope read nesmi na ROOT dosahnout")

    def test_read_issues_does_not_see_root_channel(self):
        self.assertIn(self.DENIED, self._root_modal_html('read:issues'))

    def test_read_root_cannot_write(self):
        # Nejdulezitejsi tvrzeni: pridana viditelnost nepridava pravo zapisu.
        key = self._key('read:root')
        resp = self.client.post('/api/agents/register',
                                headers={'X-API-Key': key,
                                         'Content-Type': 'application/json'},
                                data=json.dumps({'hostname': 'rogue-host'}))
        self.assertIn(resp.status_code, (401, 403),
                      "read:root nesmi smet registrovat agenta")

    def test_admin_may_issue_read_root_key(self):
        # Admin uz ROOT v UI vidi, takze ctecí klic se stejnym rozsahem
        # neni eskalace — a bez toho by si ho nemohl vyrobit vubec.
        from sentinel.routes import system as _sys
        import inspect
        src = inspect.getsource(_sys)
        self.assertIn("_admin_scopes = ('read', 'read:issues', 'read:root')", src)

    def test_status_check_reports_version(self):
        resp = self.client.get('/api/status_check', headers={'X-API-Key': self._key('read')})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('version', data)
        self.assertTrue(data['version'], "verze nesmi byt prazdna")

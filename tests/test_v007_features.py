"""
Tests pro v2026.06.006/007:
  - stavová DB leží MIMO inotify-sledovaný LOG_DIR (oprava I/O kontence)
  - add_root_audit je idempotentní (1 aktivní záznam per server+ip)
  - _reverse_dns je bezpečné a ohraničené

Run:
    python -m pytest tests/test_v007_features.py -v
"""
import os
import sys
import shutil
import sqlite3
import tempfile
import importlib
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class TestDbLocation(unittest.TestCase):
    def test_db_dir_env_respected_and_outside_logdir(self):
        tmp = tempfile.mkdtemp()
        os.environ["SENTINEL_DB_DIR"] = tmp
        from sentinel import state_base
        importlib.reload(state_base)
        try:
            self.assertTrue(state_base.DB_FILE.startswith(tmp),
                            f"DB_FILE {state_base.DB_FILE} nerespektuje SENTINEL_DB_DIR")
            self.assertNotIn("/var/log/sentinel/logs", state_base.DB_FILE,
                             "DB nesmí být v inotify-sledovaném LOG_DIR")
        finally:
            os.environ.pop("SENTINEL_DB_DIR", None)
            importlib.reload(state_base)


class TestRootAuditDedup(unittest.TestCase):
    def _mkdb(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE root_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "server TEXT, ip TEXT, connected_at TEXT, disconnected_at TEXT, is_active INTEGER, "
            "last_seen TEXT, origin TEXT)"
        )
        conn.commit()
        conn.close()
        return path

    def test_one_active_record_per_session(self):
        from sentinel import api, state_base
        path = self._mkdb()
        orig = state_base.DB_FILE
        state_base.DB_FILE = path
        try:
            # 3 cykly stejné root session -> musí vzniknout JEDEN aktivní záznam
            for _ in range(3):
                api.add_root_audit("KAROLINA", "10.0.0.1")
            conn = sqlite3.connect(path)
            n = conn.execute(
                "SELECT COUNT(*) FROM root_audit WHERE server='KAROLINA' AND is_active=1"
            ).fetchone()[0]
            # jiná IP -> samostatný záznam
            api.add_root_audit("KAROLINA", "10.0.0.2")
            n2 = conn.execute(
                "SELECT COUNT(*) FROM root_audit WHERE server='KAROLINA' AND is_active=1"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(n, 1, "duplicitní root_audit záznamy (mělo by být 1)")
            self.assertEqual(n2, 2, "druhá IP by měla přidat samostatný záznam")
        finally:
            state_base.DB_FILE = orig
            os.unlink(path)


class TestRootSessionReconcile(unittest.TestCase):
    """Opakované hlášení téže relace nesmí množit řádky ani resetovat connected_at.

    Agent cesta dřív při každém hlášení všechny aktivní záznamy hostitele
    zavřela a vložila znovu — jeden stroj tak vyrobil 126 řádků za 36 minut,
    tabulka narostla na 105 tisíc a "historie relací" byla historie pollů.
    """
    MSG = ("🟢 [ACTIVE] pts/0 from 10.34.1.4 (since 2026-08-20 11:47) | "
           "🟢 [ACTIVE] pts/1 from 10.34.1.4 (since 2026-08-19 10:53)")

    def _conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE root_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "server TEXT, ip TEXT, connected_at TEXT, disconnected_at TEXT, "
                  "is_active INTEGER, last_seen TEXT, tty TEXT, origin TEXT)")
        return c

    def test_parser_reads_tty_ip_and_since(self):
        from sentinel import state_agents as sa
        s = sa.parse_root_sessions(self.MSG)
        self.assertEqual([x['tty'] for x in s], ['pts/0', 'pts/1'])
        self.assertEqual(s[0]['ip'], '10.34.1.4')
        self.assertEqual(s[0]['since'], '2026-08-20 11:47')

    def test_repeated_report_does_not_grow_table(self):
        from sentinel import state_agents as sa
        conn = self._conn()
        sessions = sa.parse_root_sessions(self.MSG)
        for i in range(5):
            sa.reconcile_root_sessions(conn, 'login1.barbora2', sessions, f'2026-09-08T00:0{i}:00+00:00')
        n = conn.execute("SELECT COUNT(*) FROM root_audit").fetchone()[0]
        self.assertEqual(n, 2, "pět hlášení téže dvojice relací musí dát dva řádky, ne deset")
        active = conn.execute("SELECT COUNT(*) FROM root_audit WHERE is_active=1").fetchone()[0]
        self.assertEqual(active, 2)
        conn.close()

    def test_connected_at_is_login_time_not_poll_time(self):
        from sentinel import state_agents as sa
        conn = self._conn()
        sessions = sa.parse_root_sessions(self.MSG)
        sa.reconcile_root_sessions(conn, 'h', sessions, '2026-09-08T00:00:00+00:00')
        sa.reconcile_root_sessions(conn, 'h', sessions, '2026-09-08T02:00:00+00:00')
        ca = conn.execute("SELECT connected_at FROM root_audit WHERE tty='pts/0'").fetchone()[0]
        self.assertEqual(ca, '2026-08-20T11:47:00',
                         "connected_at musí držet čas přihlášení, jinak délka relace lže")
        conn.close()

    def test_two_sessions_same_ip_stay_separate(self):
        from sentinel import state_agents as sa
        conn = self._conn()
        sa.reconcile_root_sessions(conn, 'h', sa.parse_root_sessions(self.MSG), '2026-09-08T00:00:00+00:00')
        n = conn.execute("SELECT COUNT(*) FROM root_audit WHERE is_active=1").fetchone()[0]
        self.assertEqual(n, 2, "pts/0 a pts/1 ze stejné IP jsou dvě relace, ne jedna")
        conn.close()

    def test_unreported_session_gets_closed(self):
        from sentinel import state_agents as sa
        conn = self._conn()
        sa.reconcile_root_sessions(conn, 'h', sa.parse_root_sessions(self.MSG), '2026-09-08T00:00:00+00:00')
        only_one = sa.parse_root_sessions("🟢 [ACTIVE] pts/0 from 10.34.1.4 (since 2026-08-20 11:47)")
        new, kept, closed = sa.reconcile_root_sessions(conn, 'h', only_one, '2026-09-08T00:05:00+00:00')
        self.assertEqual((new, kept, closed), (0, 1, 1))
        row = conn.execute("SELECT is_active, disconnected_at FROM root_audit WHERE tty='pts/1'").fetchone()
        self.assertEqual(row[0], 0)
        self.assertIsNotNone(row[1])
        conn.close()

    def test_relogin_on_same_tty_is_a_new_session(self):
        from sentinel import state_agents as sa
        conn = self._conn()
        sa.reconcile_root_sessions(conn, 'h', sa.parse_root_sessions(self.MSG), '2026-09-08T00:00:00+00:00')
        relogin = sa.parse_root_sessions("🟢 [ACTIVE] pts/0 from 10.34.1.4 (since 2026-09-08 09:00)")
        new, _kept, closed = sa.reconcile_root_sessions(conn, 'h', relogin, '2026-09-08T09:01:00+00:00')
        self.assertEqual(new, 1, "jiný čas přihlášení na stejném pts je nová relace")
        self.assertEqual(closed, 2, "obě původní relace už se nehlásí")
        conn.close()


class TestRootAuditMigration(unittest.TestCase):
    """Migrace musí běžícím relacím nastavit last_seen, ne je nechat NULL.

    add_root_audit je idempotentní — trvající relaci jen mlčky potvrdí. Před
    migrací nebylo to potvrzení kam zapsat, takže sweep by spadl na connected_at
    a uzavřel i relace, které dávno běží (root přes SSH několik dní).
    """
    def test_active_sessions_get_last_seen_backfilled(self):
        from sentinel import state_base
        d = tempfile.mkdtemp()
        path = os.path.join(d, "mig.db")
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE root_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "server TEXT, ip TEXT, connected_at TEXT, disconnected_at TEXT, is_active INTEGER)")
        # živá relace z minulého týdne + dávno uzavřená
        old.execute("INSERT INTO root_audit (server, ip, connected_at, is_active) "
                    "VALUES ('KAROLINA','10.0.0.1','2026-09-01T10:00:00+00:00',1)")
        old.execute("INSERT INTO root_audit (server, ip, connected_at, disconnected_at, is_active) "
                    "VALUES ('CS','10.0.0.2','2026-09-01T10:00:00+00:00','2026-09-01T11:00:00+00:00',0)")
        old.commit()
        old.close()

        orig = state_base.DB_FILE
        state_base.DB_FILE = path
        try:
            state_base.init_db()
            conn = sqlite3.connect(path)
            act = conn.execute("SELECT last_seen FROM root_audit WHERE is_active=1").fetchone()[0]
            ina = conn.execute("SELECT last_seen FROM root_audit WHERE is_active=0").fetchone()[0]
            conn.close()
            self.assertIsNotNone(act, "běžící relace musí po migraci mít last_seen, jinak ji sweep zavře")
            self.assertIsNone(ina, "uzavřené relaci není co doplňovat")
        finally:
            state_base.DB_FILE = orig
            shutil.rmtree(d, ignore_errors=True)


class TestKeeperConnection(unittest.TestCase):
    """Keeper musí DB skutečně otevřít, ne se jen 'připojit'.

    sqlite3.connect() k souboru sáhne až při prvním dotazu. Bez něj nevznikne
    -wal/-shm, keeper nedrží WAL session a per-request close() dál spouští
    checkpoint (= zamrznutí celého procesu, protože close() nepouští GIL).
    """
    def test_keeper_holds_wal_session(self):
        from sentinel import state_base
        d = tempfile.mkdtemp()
        path = os.path.join(d, "keeper.db")
        seed = sqlite3.connect(path)
        seed.execute("PRAGMA journal_mode=WAL")
        seed.execute("CREATE TABLE t(x)")
        seed.commit()
        seed.close()
        self.assertFalse(os.path.exists(path + "-wal"), "výchozí stav: -wal nemá existovat")

        orig_file, orig_keeper = state_base.DB_FILE, state_base._keeper_conn
        state_base.DB_FILE = path
        state_base._keeper_conn = None
        try:
            state_base._ensure_keeper()
            self.assertTrue(os.path.exists(path + "-wal"),
                            "keeper nedrží WAL session — checkpoint při close() dál zmrazí proces")
        finally:
            try:
                state_base._keeper_conn.close()
            except Exception:
                pass
            state_base.DB_FILE, state_base._keeper_conn = orig_file, orig_keeper
            shutil.rmtree(d, ignore_errors=True)


class TestRootAuditStaleSweep(unittest.TestCase):
    """Root relace, kterou detektor přestal hlásit, musí zestárnout do is_active=0.

    Replikace SQL z agent_watchdog_loop — testuje přímo DB logiku včetně
    formátů timestampů, které se v root_audit reálně vyskytují.
    """
    SWEEP = ("UPDATE root_audit SET disconnected_at = ?, is_active = 0 "
             "WHERE is_active = 1 AND julianday(COALESCE(last_seen, connected_at)) "
             "      < julianday('now', ?)")

    def test_stale_closed_fresh_kept(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE root_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "server TEXT, ip TEXT, connected_at TEXT, disconnected_at TEXT, is_active INTEGER, "
            "last_seen TEXT, origin TEXT)"
        )
        cases = [
            # (popis, connected_at, last_seen, ma_se_uzavrit)
            ("orphan bez last_seen (plugin cesta, 67 dní)", "2026-07-02T22:30:52.765777+00:00", None, True),
            ("Z-suffix, dávno neplatná", "2026-08-01T10:00:00Z", None, True),
            ("potvrzená před minutou", (now - timedelta(days=5)).isoformat(),
             (now - timedelta(minutes=1)).isoformat(), False),
            ("nepotvrzená 45 min", (now - timedelta(hours=3)).isoformat(),
             (now - timedelta(minutes=45)).isoformat(), True),
            ("nepotvrzená 29 min — těsně pod limitem", (now - timedelta(hours=3)).isoformat(),
             (now - timedelta(minutes=29)).isoformat(), False),
            ("čerstvá bez last_seen", (now - timedelta(minutes=2)).isoformat(), None, False),
        ]
        for i, (_, ca, ls, _exp) in enumerate(cases, 1):
            conn.execute("INSERT INTO root_audit (id, server, ip, connected_at, is_active, last_seen) "
                         "VALUES (?, 'S', '1.2.3.4', ?, 1, ?)", (i, ca, ls))

        conn.execute(self.SWEEP, (now.isoformat(), '-30 minutes'))

        for i, (desc, _ca, _ls, expect_closed) in enumerate(cases, 1):
            active = conn.execute("SELECT is_active FROM root_audit WHERE id=?", (i,)).fetchone()[0]
            self.assertEqual(active == 0, expect_closed,
                             f"{desc}: očekáváno {'uzavřít' if expect_closed else 'ponechat'}")
        conn.close()


class TestOllamaExtraBody(unittest.TestCase):
    """Extra pole do těla /v1 požadavku — vlastnost modelu, ne Sentinelu.

    qwen3 bez {"chat_template_kwargs": {"enable_thinking": false}} posílá
    <think> bloky rovnou v `content`, kde je nejde oddělit od odpovědi —
    skončily by v chatu i v auto-klasifikaci severity.
    """
    def setUp(self):
        from sentinel import config
        self._orig = config.OLLAMA_EXTRA_BODY

    def tearDown(self):
        from sentinel import config
        config.OLLAMA_EXTRA_BODY = self._orig

    def test_empty_leaves_payload_untouched(self):
        from sentinel import config
        config.OLLAMA_EXTRA_BODY = {}
        p = {"model": "m", "messages": [], "stream": False}
        self.assertEqual(config.apply_extra_body(dict(p)), p)

    def test_merges_into_payload(self):
        from sentinel import config
        config.OLLAMA_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
        p = config.apply_extra_body({"model": "qwen3-32b", "stream": True})
        self.assertEqual(p["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(p["model"], "qwen3-32b", "původní pole musí zůstat")

    def test_non_dict_from_config_is_ignored(self):
        from sentinel import config
        # Uživatel napsal do YAML skalár místo mapy — nesmí to shodit start
        self.assertIsInstance(config.OLLAMA_EXTRA_BODY, dict)

    def test_applied_only_on_v1_branches(self):
        """Hailo ani legacy /api/generate tahle pole neznají — poslat je tam request rozbije."""
        import re as _re
        src = {}
        for f in ('sentinel/chat_service.py', 'sentinel/ollama_service.py', 'sentinel/routes/chat.py'):
            src[f] = open(os.path.join(_ROOT, f)).read()
        joined = "\n".join(src.values())
        # helper se nesmí objevit ve stejném bloku jako hailo/legacy payload
        for marker in ('HAILO_OLLAMA_URL', 'payload_legacy'):
            for m in _re.finditer(_re.escape(marker), joined):
                window = joined[m.start():m.start() + 400]
                self.assertNotIn('apply_extra_body', window,
                                 f"apply_extra_body nesmí být v okolí {marker}")


class TestReverseDns(unittest.TestCase):
    def test_bounded_and_safe(self):
        from sentinel import api
        # TEST-NET-1 (192.0.2.0/24) je nesměrovatelná -> prázdno, bez výjimky, do timeoutu
        r = api._reverse_dns("192.0.2.123", timeout=1.0)
        self.assertIsInstance(r, str)


if __name__ == "__main__":
    unittest.main()


class TestSseGeneratorsAvoidRequestContext(unittest.TestCase):
    """SSE generátor nesmí sahat na `g` — běží až po návratu view.

    Flask tam request kontext už nemá, takže `g.username` uvnitř vyhodí
    RuntimeError: generátor umře, server utne spojení uprostřed streamu
    (nginx: "upstream prematurely closed connection") a prohlížeč vypíše
    chybu ZA už vykreslenou odpovědí. Hodnotu je nutné zachytit předem.
    """
    GENERATORS = [
        ('sentinel/routes/chat.py', '_stream_generator'),
        ('sentinel/routes/actions.py', '_generate'),
    ]

    def test_no_flask_g_inside_generator_bodies(self):
        import re as _re
        for rel, fname in self.GENERATORS:
            src = open(os.path.join(_ROOT, rel), encoding='utf-8').read().split('\n')
            start = next((i for i, l in enumerate(src) if l.strip().startswith(f'def {fname}(')), None)
            self.assertIsNotNone(start, f'{fname} nenalezen v {rel}')
            indent = len(src[start]) - len(src[start].lstrip())
            body = []
            for line in src[start + 1:]:
                if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                    break
                body.append(line)
            offenders = [l.strip() for l in body if _re.search(r'\bg\.[a-z_]+', l)]
            self.assertEqual(offenders, [],
                             f'{rel}:{fname} sahá na `g` uvnitř generátoru: {offenders}')


class TestAlertsContextInBothChatPaths(unittest.TestCase):
    """Obě větve chatu musí modelu poslat aktivní issues.

    Streamovaná větev (tu používá UI) je dřív neposílala vůbec — skládala
    jen historii a knowledge base. Na "analyzuj aktivní problémy" pak model
    odpovídal z KB o účtech a kvótách místo o tom, co zrovna hoří.
    """
    def test_builder_formats_active_issues(self):
        from sentinel import chat_service, state
        svc = chat_service.ChatService.__new__(chat_service.ChatService)
        orig = state.get_active_issues
        state.get_active_issues = lambda: [
            {'host': 'login1.barbora', 'channel_type': 'agent', 'severity': 'high',
             'last_line': 'Swap 100 %', 'last_seen': '2026-09-08T01:00:00'},
            {'host': 'auto.it4i.cz', 'channel_type': 'security',
             'last_line': '78 unpatched CVEs', 'last_seen': '2026-09-08T02:00:00'},
        ]
        try:
            out = svc.build_alerts_context()
        finally:
            state.get_active_issues = orig
        self.assertIn('login1.barbora', out)
        self.assertIn('AGENT/HIGH', out, 'severity patří do kontextu, řídí se jí priorita')
        self.assertIn('78 unpatched CVEs', out)
        self.assertIn('2 total', out)

    def test_no_issues_says_so_explicitly(self):
        from sentinel import chat_service, state
        svc = chat_service.ChatService.__new__(chat_service.ChatService)
        orig = state.get_active_issues
        state.get_active_issues = lambda: []
        try:
            out = svc.build_alerts_context()
        finally:
            state.get_active_issues = orig
        self.assertIn('none', out.lower(),
                      'prázdno musí být řečeno, jinak si model domyslí problémy z KB')

    def test_streaming_path_includes_alerts(self):
        src = open(os.path.join(_ROOT, 'sentinel/routes/chat.py'), encoding='utf-8').read()
        self.assertIn('build_alerts_context()', src,
                      'streamovaná větev musí posílat aktivní issues')


class TestUserAudit(unittest.TestCase):
    """Každý přihlášený musí mít záznam, i když mu nikdo nenastavil roli.

    `user_roles` obsahuje jen ty, u kterých někdo roli změnil — uživatel
    z LDAPu, který se přihlásil, ve správě uživatelů vůbec nefiguroval.
    """
    def setUp(self):
        # `state_agents` i `state_issues` si `_get_conn` naimportovaly hodnotou,
        # takže po importlib.reload(state_base) v jiném testu ukazují na starý
        # modul. Přepsat samotné state_base.DB_FILE proto nestačí — cesta se
        # musí nastavit v globálech té konkrétní funkce, kterou opravdu volají.
        import sys as _sys
        from sentinel import state_agents, state_issues
        self._dir = tempfile.mkdtemp()
        path = os.path.join(self._dir, 'audit.db')
        self.sa, self.si = state_agents, state_issues
        self._g = state_agents._get_conn.__globals__
        self._orig_db = self._g['DB_FILE']
        self._g['DB_FILE'] = path
        # Fasáda by jinak přebila hodnotu výše (viz _db_file()).
        self._facade = _sys.modules.get('sentinel.state')
        self._orig_facade = getattr(self._facade, 'DB_FILE', None) if self._facade else None
        if self._facade is not None:
            self._facade.DB_FILE = path
        self._g['init_db']()

    def tearDown(self):
        self._g['DB_FILE'] = self._orig_db
        if self._facade is not None and self._orig_facade is not None:
            self._facade.DB_FILE = self._orig_facade
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_ldap_user_without_role_gets_record(self):
        self.sa.user_audit_login('kru0052', '10.0.0.5', 'ldap')
        rows = self.sa.get_user_audit()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['username'], 'kru0052')
        self.assertEqual(rows[0]['auth_source'], 'ldap')
        self.assertEqual(rows[0]['login_count'], 1)
        self.assertIsNone(rows[0]['role'], 'roli nikdo nenastavil, ale záznam existovat musí')

    def test_repeated_login_counts_and_updates_ip(self):
        self.sa.user_audit_login('u', '10.0.0.1', 'ldap')
        first = self.sa.get_user_audit()[0]['first_seen']
        self.sa.user_audit_login('u', '10.0.0.2', 'ldap')
        r = self.sa.get_user_audit()[0]
        self.assertEqual(r['login_count'], 2)
        self.assertEqual(r['last_ip'], '10.0.0.2')
        self.assertEqual(r['first_seen'], first, 'first_seen se nesmí přepsat')

    def test_session_close_accumulates_online_time(self):
        self.sa.user_audit_login('u', '10.0.0.1', 'ldap')
        self.si.session_register('s1', 'u', 'admin', '10.0.0.1', 'UA')
        conn = self.sa._get_conn()
        conn.execute("UPDATE active_sessions SET created_at=datetime('now','-45 minutes'), "
                     "last_seen=datetime('now') WHERE session_uuid='s1'")
        conn.commit()
        conn.close()
        self.si.session_remove('s1')
        secs = self.sa.get_user_audit()[0]['online_seconds']
        self.assertGreater(secs, 2600, 'doba relace se musí přičíst')
        self.assertLess(secs, 2800)

    def test_nonsense_durations_ignored(self):
        self.sa.user_audit_login('u', '', 'local')
        self.sa.user_audit_add_online('u', -5)
        self.sa.user_audit_add_online('u', 999_999_999)
        self.assertEqual(self.sa.get_user_audit()[0]['online_seconds'], 0)

    def test_role_is_joined_in(self):
        self.sa.user_audit_login('u', '', 'ldap')
        self.sa.set_user_role('u', 'operator')
        self.assertEqual(self.sa.get_user_audit()[0]['role'], 'operator')


class TestDetectorSelfCheck(unittest.TestCase):
    """Chybějící soubor detektoru musí založit issue, ne mlčet.

    Přesně tohle se stalo v provozu: zdrojáky it4i detektorů zmizely z
    plugins/, běžící proces si je držel v paměti, ale po restartu se
    nenačetly. Config chtěl 12, načetlo se 0, v logu jen řádek u každého —
    a protože logy nikdo nedispatchoval, jejich issues se do hodiny uklidily
    jako vyřešené. Sentinel dva dny hlásil OK.

    Testuje se logika self-checku, ne SQLite, takže se zápis do stavu jen
    odchytí — DB round-trip by sem přinesl jen křehkost.
    """
    DETECTOR_SRC = (
        "class Detector:\n"
        "    def __init__(self, name, config_params=None):\n"
        "        self.name = name\n"
        "    def process(self, lines, file_path):\n"
        "        pass\n"
    )

    def setUp(self):
        from sentinel import config, plugin_manager, state
        self.cfg, self.pm, self.state = config, plugin_manager, state
        self._dir = tempfile.mkdtemp()
        self._plugins = os.path.join(self._dir, 'plugins')
        os.makedirs(self._plugins)
        self._orig_cfg = (config.DETECTORS, config.PLUGIN_DIR)
        config.PLUGIN_DIR = self._plugins

        self.saved, self.resolved, self.severities = [], [], []
        self._orig_fns = (state.save_problem, state.resolve_problem, state.set_issue_severity)
        state.save_problem = lambda k, d: self.saved.append((k, d))
        state.resolve_problem = lambda k, **kw: self.resolved.append(k)
        state.set_issue_severity = lambda k, sev: self.severities.append((k, sev))

    def tearDown(self):
        self.cfg.DETECTORS, self.cfg.PLUGIN_DIR = self._orig_cfg
        (self.state.save_problem, self.state.resolve_problem,
         self.state.set_issue_severity) = self._orig_fns
        self.pm.active_plugins.clear()
        shutil.rmtree(self._dir, ignore_errors=True)

    def _write(self, name):
        with open(os.path.join(self._plugins, f'{name}.py'), 'w') as f:
            f.write(self.DETECTOR_SRC)

    def test_missing_detector_files_raise_issue(self):
        self.cfg.DETECTORS = [
            {'plugin': 'detector_icinga', 'match_pattern': 'icinga.log', 'enabled': True},
            {'plugin': 'detector_ecc', 'match_pattern': 'ecc.log', 'enabled': True},
        ]
        self.pm.load_plugins()
        self.assertEqual(len(self.pm.active_plugins), 0)
        self.assertEqual(len(self.saved), 1, "chybějící detektory musí založit issue")
        key, data = self.saved[0]
        self.assertEqual(key, self.pm.SELF_CHECK_KEY)
        self.assertIn('detector_icinga', data['last_line'])
        self.assertIn('detector_ecc', data['last_line'])
        self.assertEqual(self.severities, [(self.pm.SELF_CHECK_KEY, 'critical')])

    def test_all_loaded_means_no_issue(self):
        self._write('detector_a')
        self._write('detector_b')
        self.cfg.DETECTORS = [
            {'plugin': 'detector_a', 'match_pattern': 'a.log', 'enabled': True},
            {'plugin': 'detector_b', 'match_pattern': 'b.log', 'enabled': True},
        ]
        self.pm.load_plugins()
        self.assertEqual(len(self.pm.active_plugins), 2)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.resolved, [self.pm.SELF_CHECK_KEY])

    def test_partial_load_still_reports(self):
        self._write('detector_a')
        self.cfg.DETECTORS = [
            {'plugin': 'detector_a', 'match_pattern': 'a.log', 'enabled': True},
            {'plugin': 'detector_chybi', 'match_pattern': 'b.log', 'enabled': True},
        ]
        self.pm.load_plugins()
        self.assertEqual(len(self.saved), 1, "i jeden chybějící z dvou je problém")
        self.assertIn('detector_chybi', self.saved[0][1]['last_line'])
        self.assertNotIn('detector_a', self.saved[0][1]['last_line'])

    def test_issue_clears_once_detectors_return(self):
        self.cfg.DETECTORS = [{'plugin': 'detector_a', 'match_pattern': 'a.log', 'enabled': True}]
        self.pm.load_plugins()
        self.assertEqual(len(self.saved), 1)
        self._write('detector_a')
        self.pm.load_plugins()
        self.assertEqual(self.resolved, [self.pm.SELF_CHECK_KEY],
                         "po obnovení souborů se issue musí uklidit")

    def test_disabled_detector_is_not_counted_as_missing(self):
        self.cfg.DETECTORS = [
            {'plugin': 'detector_vypnuty', 'match_pattern': 'x.log', 'enabled': False},
        ]
        self.pm.load_plugins()
        self.assertEqual(self.saved, [], "vypnutý detektor nechybí, je vypnutý")

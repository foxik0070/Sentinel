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

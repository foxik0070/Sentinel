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
            "last_seen TEXT)"
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
            "last_seen TEXT)"
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


class TestReverseDns(unittest.TestCase):
    def test_bounded_and_safe(self):
        from sentinel import api
        # TEST-NET-1 (192.0.2.0/24) je nesměrovatelná -> prázdno, bez výjimky, do timeoutu
        r = api._reverse_dns("192.0.2.123", timeout=1.0)
        self.assertIsInstance(r, str)


if __name__ == "__main__":
    unittest.main()

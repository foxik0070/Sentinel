"""Zachycená AI sezení: identita, uzavírání a retence.

Hlavní riziko není ztráta dat, ale jejich nafouknutí — `root_audit` kdysi
narostl na 101 tisíc řádků právě tím, že každý poll zakládal nový záznam.
Testy proto drží hlavně to, že opakovaný poll NEpřidává řádky.
"""
import os
import sys
import sqlite3
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state_issues as si


def _session(pid=101, started="2026-10-23T08:00:00+00:00", user="foxik",
             tool="Claude Code", category="cli", **kw):
    s = {"pid": pid, "started_at": started, "user": user, "tool": tool,
         "category": category, "model": "", "cwd": "/root/git", "cmdline": "claude"}
    s.update(kw)
    return s


class AiSessionsBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.execute('''CREATE TABLE ai_sessions
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         host TEXT NOT NULL, username TEXT DEFAULT '',
                         tool TEXT DEFAULT '', category TEXT DEFAULT '',
                         model TEXT DEFAULT '', pid INTEGER, cwd TEXT DEFAULT '',
                         cmdline TEXT DEFAULT '', remote TEXT DEFAULT '',
                         started_at TEXT, first_seen TEXT, last_seen TEXT,
                         ended_at TEXT, is_active INTEGER DEFAULT 1)''')
        conn.execute('CREATE UNIQUE INDEX idx_ai_sessions_ident '
                     'ON ai_sessions(host, pid, started_at)')
        conn.commit()
        conn.close()
        self._orig = si._get_conn
        si._get_conn = lambda: sqlite3.connect(self.db_path)

    def tearDown(self):
        si._get_conn = self._orig
        os.unlink(self.db_path)

    def rows(self, where=""):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT host, username, tool, pid, started_at, is_active, ended_at, last_seen "
                "FROM ai_sessions " + where).fetchall()
        finally:
            conn.close()


class TestIdentity(AiSessionsBase):
    def test_repeated_poll_does_not_add_rows(self):
        for _ in range(20):
            si.save_ai_sessions("rpi5", [_session()])
        self.assertEqual(len(self.rows()), 1, "kazdy poll zalozil novy radek")

    def test_repeated_poll_refreshes_last_seen(self):
        si.save_ai_sessions("rpi5", [_session()])
        first = self.rows()[0][7]
        si.save_ai_sessions("rpi5", [_session(cmdline="claude --resume")])
        row = self.rows()[0]
        self.assertGreaterEqual(row[7], first)
        self.assertEqual(row[5], 1)

    def test_same_pid_different_start_is_a_new_session(self):
        # Po restartu stroje se pid recykluje — jiny cas startu = jine sezeni.
        si.save_ai_sessions("rpi5", [_session(pid=101, started="2026-10-23T08:00:00+00:00")])
        si.save_ai_sessions("rpi5", [_session(pid=101, started="2026-10-23T09:00:00+00:00")])
        self.assertEqual(len(self.rows()), 2)

    def test_missing_start_time_still_dedupes(self):
        # started_at=None se uklada jako '' — dva NULL se v UNIQUE indexu
        # nerovnaji a kazdy poll by jinak pridal radek.
        for _ in range(5):
            si.save_ai_sessions("rpi5", [_session(started=None)])
        self.assertEqual(len(self.rows()), 1)

    def test_hosts_do_not_collide(self):
        si.save_ai_sessions("rpi5", [_session()])
        si.save_ai_sessions("auto.it4i.cz", [_session()])
        self.assertEqual(len(self.rows()), 2)


class TestLifecycle(AiSessionsBase):
    def test_session_that_stops_being_reported_is_closed(self):
        si.save_ai_sessions("rpi5", [_session(pid=101), _session(pid=102)])
        si.save_ai_sessions("rpi5", [_session(pid=101)])
        closed = self.rows("WHERE is_active = 0")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0][3], 102)
        self.assertIsNotNone(closed[0][6], "ended_at musi byt vyplnene")

    def test_empty_list_closes_everything_on_that_host(self):
        si.save_ai_sessions("rpi5", [_session(pid=101), _session(pid=102)])
        si.save_ai_sessions("rpi5", [])
        self.assertEqual(len(self.rows("WHERE is_active = 1")), 0)

    def test_empty_list_does_not_touch_other_hosts(self):
        si.save_ai_sessions("rpi5", [_session()])
        si.save_ai_sessions("auto.it4i.cz", [])
        self.assertEqual(len(self.rows("WHERE is_active = 1")), 1)

    def test_returning_session_reopens_instead_of_duplicating(self):
        # Vypadek jednoho cyklu nesmi zalozit druhy zaznam tehoz sezeni.
        si.save_ai_sessions("rpi5", [_session()])
        si.save_ai_sessions("rpi5", [])
        si.save_ai_sessions("rpi5", [_session()])
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][5], 1)
        self.assertIsNone(rows[0][6], "ended_at se musi vymazat")

    def test_session_without_pid_is_skipped(self):
        si.save_ai_sessions("rpi5", [{"user": "x", "tool": "y"}])
        self.assertEqual(len(self.rows()), 0)


class TestRetention(AiSessionsBase):
    def test_finished_sessions_are_capped_per_host(self):
        from sentinel import config
        orig = getattr(config, 'AI_SESSIONS_HISTORY_PER_HOST', 30)
        config.AI_SESSIONS_HISTORY_PER_HOST = 5
        try:
            for pid in range(100, 140):
                si.save_ai_sessions("rpi5", [_session(pid=pid, started=f"2026-10-23T08:{pid-100:02d}:00+00:00")])
            si.save_ai_sessions("rpi5", [])
            self.assertLessEqual(len(self.rows("WHERE is_active = 0")), 5)
        finally:
            config.AI_SESSIONS_HISTORY_PER_HOST = orig

    def test_active_sessions_survive_the_cap(self):
        from sentinel import config
        orig = getattr(config, 'AI_SESSIONS_HISTORY_PER_HOST', 30)
        config.AI_SESSIONS_HISTORY_PER_HOST = 2
        try:
            batch = [_session(pid=p, started=f"2026-10-23T08:{p-100:02d}:00+00:00")
                     for p in range(100, 110)]
            si.save_ai_sessions("rpi5", batch)
            self.assertEqual(len(self.rows("WHERE is_active = 1")), 10)
        finally:
            config.AI_SESSIONS_HISTORY_PER_HOST = orig

    def test_broken_payload_does_not_raise(self):
        si.save_ai_sessions("rpi5", [{"pid": "neni cislo", "started_at": "x"}])


if __name__ == '__main__':
    unittest.main()

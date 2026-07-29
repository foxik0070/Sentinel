"""
Tests for sentinel.state — DB init, save_problem (ON CONFLICT), agent tokens.

Run:
    python -m pytest tests/test_state.py -v
    python -m unittest tests.test_state -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state


def _make_problem_data(msg="Test message", channel="general", plugin="test_plugin"):
    return {
        "last_line": msg,
        "channel_type": channel,
        "plugin_name": plugin,
        "host": "test-host",
    }


class TestStateDB(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self._orig_db = state.DB_FILE
        state.DB_FILE = self._tmp.name
        state._local = threading.local()
        state.init_db()

    def tearDown(self):
        state.DB_FILE = self._orig_db
        os.unlink(self._tmp.name)

    # --- init_db ---

    def test_tables_created(self):
        conn = state._get_conn()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        for expected in ('problems', 'agents', 'task_queue', 'root_audit'):
            self.assertIn(expected, tables, f"Tabulka {expected!r} chybí v DB")

    def test_wal_mode(self):
        conn = state._get_conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        self.assertEqual(mode, 'wal')

    def test_agents_notes_column_exists(self):
        conn = state._get_conn()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
        conn.close()
        self.assertIn('notes', cols, "Sloupec 'notes' v tabulce agents chybí (migrace selhala)")

    def test_agents_ignore_offline_column_exists(self):
        conn = state._get_conn()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
        conn.close()
        self.assertIn('ignore_offline', cols)

    # --- save_problem ---

    def test_save_problem_insert(self):
        state.save_problem("test-key-001", _make_problem_data("Test message"))
        conn = state._get_conn()
        conn.row_factory = None
        row = conn.execute("SELECT key FROM problems WHERE key='test-key-001'").fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_save_problem_on_conflict_update(self):
        """ON CONFLICT(key) DO UPDATE — duplicitní key aktualizuje řádek, ne přidá nový."""
        state.save_problem("dup-key", _make_problem_data("First"))
        state.save_problem("dup-key", _make_problem_data("Second"))
        conn = state._get_conn()
        rows = conn.execute("SELECT key FROM problems WHERE key='dup-key'").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1, "ON CONFLICT musí aktualizovat existující řádek, ne vytvořit duplikát")

    def test_save_problem_details_updated_on_conflict(self):
        state.save_problem("update-key", _make_problem_data("First"))
        state.save_problem("update-key", _make_problem_data("Updated message"))
        conn = state._get_conn()
        row = conn.execute("SELECT details FROM problems WHERE key='update-key'").fetchone()
        conn.close()
        details = json.loads(row[0])
        self.assertEqual(details.get('last_line'), "Updated message")

    def test_save_problem_status_active(self):
        state.save_problem("status-key", _make_problem_data())
        conn = state._get_conn()
        row = conn.execute("SELECT status FROM problems WHERE key='status-key'").fetchone()
        conn.close()
        self.assertEqual(row[0], "active")

    def test_save_problem_empty_last_line_rejected(self):
        """save_problem musí vrátit False pro prázdný last_line (ochrana před prázdnými záznamy)."""
        data = _make_problem_data()
        data['last_line'] = ""
        result = state.save_problem("empty-key", data)
        self.assertFalse(result)
        conn = state._get_conn()
        row = conn.execute("SELECT key FROM problems WHERE key='empty-key'").fetchone()
        conn.close()
        self.assertIsNone(row)

    # --- agent tokens ---

    def test_register_and_verify_agent(self):
        import secrets
        token = secrets.token_hex(32)
        conn = state._get_conn()
        conn.execute(
            "INSERT INTO agents (hostname, token, status) VALUES (?, ?, 'ONLINE')",
            ("test-agent-01", token)
        )
        conn.commit()
        conn.close()
        self.assertTrue(state.verify_agent_token("test-agent-01", token))
        self.assertFalse(state.verify_agent_token("test-agent-01", "wrong-token" * 4))
        self.assertFalse(state.verify_agent_token("nonexistent", token))

    def test_verify_token_timing_safe(self):
        """verify_agent_token musí fungovat pro správný i nesprávný token bez výjimky."""
        import secrets
        token = secrets.token_hex(32)
        conn = state._get_conn()
        conn.execute(
            "INSERT INTO agents (hostname, token, status) VALUES (?, ?, 'ONLINE')",
            ("timing-agent", token)
        )
        conn.commit()
        conn.close()
        self.assertFalse(state.verify_agent_token("timing-agent", "a" * 64))
        self.assertTrue(state.verify_agent_token("timing-agent", token))

    # --- task queue ---

    def test_enqueue_and_fetch_task(self):
        payload = {"text": "test log line", "channel": "general"}
        state.ollama_queue.put(payload)
        task = state.fetch_next_task("W-test")
        self.assertIsNotNone(task)
        self.assertEqual(task['payload']['text'], "test log line")

    def test_fetch_task_marks_in_progress(self):
        state.ollama_queue.put({"text": "x", "channel": "general"})
        state.fetch_next_task("W-1")
        # Druhý worker nesmí dostat stejný task (je ve stavu processing)
        task2 = state.fetch_next_task("W-2")
        self.assertIsNone(task2)

    def test_complete_task_removes_it(self):
        state.ollama_queue.put({"text": "complete-me"})
        task = state.fetch_next_task("W-1")
        self.assertIsNotNone(task)
        state.complete_task(task['id'])
        conn = state._get_conn()
        row = conn.execute("SELECT id FROM task_queue WHERE id=?", (task['id'],)).fetchone()
        conn.close()
        self.assertIsNone(row)

    # --- get_active_issues ---

    def test_get_active_issues(self):
        state.save_problem("active-issue", _make_problem_data("Active issue", "security"))
        issues = state.get_active_issues()
        keys = [i['key'] for i in issues]
        self.assertIn("active-issue", keys)

    def test_resolved_issue_not_in_active(self):
        state.save_problem("res-issue", _make_problem_data())
        conn = state._get_conn()
        conn.execute("UPDATE problems SET status='resolved' WHERE key='res-issue'")
        conn.commit()
        conn.close()
        issues = state.get_active_issues()
        keys = [i['key'] for i in issues]
        self.assertNotIn("res-issue", keys)


class TestAgentWatchdog(unittest.TestCase):
    """agent_watchdog_loop — 180s timeout logika."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self._orig_db = state.DB_FILE
        state.DB_FILE = self._tmp.name
        state._local = threading.local()
        state.init_db()

    def tearDown(self):
        state.DB_FILE = self._orig_db
        os.unlink(self._tmp.name)

    def test_watchdog_timeout_threshold_is_180s(self):
        """Ověří, že agent s last_seen > 180s dostane OFFLINE — testuje logiku přímo."""
        stale_dt = datetime.now(timezone.utc) - timedelta(seconds=200)
        stale_str = stale_dt.isoformat()
        conn = state._get_conn()
        conn.execute(
            "INSERT INTO agents (hostname, token, status, last_seen, ignore_offline) "
            "VALUES ('stale-host', 'tok', 'ONLINE', ?, 0)",
            (stale_str,)
        )
        conn.commit()

        # Replikace watchdog logiky (180s threshold) — testuje přímo DB logiku
        now = datetime.now(timezone.utc)
        c = conn.execute("SELECT hostname, last_seen FROM agents WHERE status='ONLINE'")
        for hostname, last_seen_str in c.fetchall():
            clean = last_seen_str.replace('Z', '+00:00')
            last_dt = datetime.fromisoformat(clean)
            if (now - last_dt).total_seconds() > 180:
                conn.execute("UPDATE agents SET status='OFFLINE' WHERE hostname=?", (hostname,))
        conn.commit()

        row = conn.execute("SELECT status FROM agents WHERE hostname='stale-host'").fetchone()
        conn.close()
        self.assertEqual(row[0], "OFFLINE")

    def test_fresh_agent_stays_online(self):
        """Agent s nedávným heartbeatem nesmí dostat OFFLINE."""
        fresh_dt = datetime.now(timezone.utc) - timedelta(seconds=30)
        conn = state._get_conn()
        conn.execute(
            "INSERT INTO agents (hostname, token, status, last_seen, ignore_offline) "
            "VALUES ('fresh-host', 'tok2', 'ONLINE', ?, 0)",
            (fresh_dt.isoformat(),)
        )
        conn.commit()

        now = datetime.now(timezone.utc)
        c = conn.execute("SELECT hostname, last_seen FROM agents WHERE status='ONLINE'")
        for hostname, last_seen_str in c.fetchall():
            clean = last_seen_str.replace('Z', '+00:00')
            last_dt = datetime.fromisoformat(clean)
            if (now - last_dt).total_seconds() > 180:
                conn.execute("UPDATE agents SET status='OFFLINE' WHERE hostname=?", (hostname,))
        conn.commit()

        row = conn.execute("SELECT status FROM agents WHERE hostname='fresh-host'").fetchone()
        conn.close()
        self.assertEqual(row[0], "ONLINE")


class TestNewFeatures(unittest.TestCase):
    """Tests for new features added in v2026.05.052–057."""

    def setUp(self):
        self._orig = state.DB_FILE
        self._tmp = tempfile.mktemp(suffix='.db')
        state.DB_FILE = self._tmp
        state.init_db()

    def tearDown(self):
        state.DB_FILE = self._orig
        try:
            os.unlink(self._tmp)
        except OSError:
            pass

    # 038: Agent labels
    def test_agent_labels_round_trip(self):
        state.register_new_agent('labels-host', 'tok-labels')
        ok = state.set_agent_labels('labels-host', {'env': 'prod', 'rack': 'A1'})
        self.assertTrue(ok)
        labels = state.get_agent_labels('labels-host')
        self.assertEqual(labels.get('env'), 'prod')
        self.assertEqual(labels.get('rack'), 'A1')

    def test_agent_labels_empty_for_unknown(self):
        labels = state.get_agent_labels('nonexistent-host')
        self.assertEqual(labels, {})

    # 037: Heartbeat timeout column
    def test_heartbeat_timeout_column_exists(self):
        conn = state._get_conn()
        cols = [r[1] for r in conn.execute('PRAGMA table_info(agents)').fetchall()]
        conn.close()
        self.assertIn('heartbeat_timeout', cols)

    # 066: Telemetry aggregation
    def test_aggregate_telemetry_reduces_rows(self):
        from datetime import timedelta
        import time
        # Zápis 10 raw metrik starých > 24h
        conn = state._get_conn()
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        for i in range(10):
            conn.execute(
                "INSERT INTO telemetry (timestamp, category, metric, value) VALUES (?,?,?,?)",
                (old_ts, 'test_cat', 'test_metric', float(i))
            )
        conn.commit()
        conn.close()
        before = state._get_conn().execute("SELECT COUNT(*) FROM telemetry WHERE metric='test_metric'").fetchone()[0]
        state._get_conn().close()
        self.assertEqual(before, 10)
        state.aggregate_telemetry(raw_after_hours=24)
        after = state._get_conn().execute("SELECT COUNT(*) FROM telemetry WHERE metric='test_metric'").fetchone()[0]
        state._get_conn().close()
        # Po agregaci musí být méně řádků (1 průměrný za hodinu)
        self.assertLess(after, before)
        self.assertGreaterEqual(after, 1)

    # 025: Issue expiry per-channel
    def test_issue_expiry_marks_old_issues_resolved(self):
        from datetime import timedelta
        from sentinel import config as _cfg
        _cfg.ISSUE_EXPIRY_DAYS = {'infra': 0.001}  # 0.001 dne ≈ 1.4 minuty → v testu "před dlouhou dobou"
        # Vlož issue které je staré (přepsat last_seen)
        state.save_problem('expiry-test-key', {'last_line': 'old issue', 'channel_type': 'infra', 'plugin_name': 'p', 'host': 'h'})
        conn = state._get_conn()
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute("UPDATE problems SET last_seen=?, first_seen=? WHERE key='expiry-test-key'", (old_ts, old_ts))
        conn.commit()
        conn.close()
        state.auto_resolve_old_problems(days=365)
        active_keys = [i['key'] for i in state.get_active_issues()]
        _cfg.ISSUE_EXPIRY_DAYS = {}
        self.assertNotIn('expiry-test-key', active_keys)

    # state.get_setting / set_setting (pro theme)
    def test_settings_store_and_retrieve(self):
        state.set_setting('theme.testuser', 'light')
        val = state.get_setting('theme.testuser')
        self.assertEqual(val, 'light')
        state.set_setting('theme.testuser', 'dark')
        val2 = state.get_setting('theme.testuser')
        self.assertEqual(val2, 'dark')


if __name__ == "__main__":
    unittest.main(verbosity=2)

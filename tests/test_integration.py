"""
tests/test_integration.py — Integration tests (342)
- save_problem → get_active_issues → mark_resolved lifecycle
"""
import unittest
import os
import sys
import tempfile
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestIssueLifecycle(unittest.TestCase):
    """End-to-end lifecycle: create → get_active → mark_resolved → get_history."""

    @classmethod
    def setUpClass(cls):
        """Use an in-memory DB for isolation."""
        import sentinel.state_base as sb
        import sentinel.state as st
        cls._orig_db = st.DB_FILE
        # Create temp DB
        cls._tmpdir = tempfile.mkdtemp()
        cls._tmpdb = os.path.join(cls._tmpdir, "test_lifecycle.db")
        st.DB_FILE = cls._tmpdb
        sb.DB_FILE = cls._tmpdb  # sync both references
        # Re-init DB schema
        sb.init_db()

    @classmethod
    def tearDownClass(cls):
        import sentinel.state as st
        import sentinel.state_base as sb
        st.DB_FILE = cls._orig_db
        sb.DB_FILE = cls._orig_db
        try:
            import shutil
            shutil.rmtree(cls._tmpdir)
        except Exception:
            pass

    def test_01_save_new_problem(self):
        """save_problem should return True for new issues."""
        import sentinel.state as st
        is_new = st.save_problem("TEST|host1|plugin_test", {
            "status": "active",
            "channel_type": "infra",
            "host": "host1",
            "last_line": "Test error message",
            "plugin_name": "plugin_test",
            "last_seen": "2026-06-01T12:00:00+00:00",
            "missing_count": 0,
        })
        self.assertTrue(is_new, "First save should return True (new issue)")

    def test_02_duplicate_problem_not_new(self):
        """Saving the same key again should return False (update, not new)."""
        import sentinel.state as st
        is_new = st.save_problem("TEST|host1|plugin_test", {
            "status": "active",
            "channel_type": "infra",
            "host": "host1",
            "last_line": "Test error message (updated)",
            "plugin_name": "plugin_test",
            "last_seen": "2026-06-01T12:05:00+00:00",
            "missing_count": 0,
        })
        self.assertFalse(is_new, "Second save of same key should return False")

    def test_03_get_active_issues(self):
        """get_active_issues should include our test issue."""
        import sentinel.state as st
        issues = st.get_active_issues()
        keys = [i.get('key') for i in issues]
        self.assertIn("TEST|host1|plugin_test", keys)

    def test_04_mark_resolved(self):
        """Resolving an issue should remove it from active list."""
        import sentinel.state as st
        st.mark_resolved("TEST|host1|plugin_test")
        issues = st.get_active_issues()
        keys = [i.get('key') for i in issues]
        self.assertNotIn("TEST|host1|plugin_test", keys)

    def test_05_resolved_in_history(self):
        """Resolved issue should appear in issue_history."""
        import sentinel.state_base as sb
        conn = sqlite3.connect(sb.DB_FILE)
        row = conn.execute(
            "SELECT key FROM issue_history WHERE key=?", ("TEST|host1|plugin_test",)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row, "Resolved issue should be in issue_history")

    def test_06_occurrence_counter(self):
        """Creating same issue again should increase occurrence_count."""
        import sentinel.state as st
        # Create fresh issue
        st.save_problem("TEST|host2|counter_test", {
            "status": "active",
            "channel_type": "agent",
            "host": "host2",
            "last_line": "Counter test",
            "plugin_name": "counter_test",
            "last_seen": "2026-06-01T13:00:00+00:00",
            "missing_count": 0,
        })
        # Trigger again
        st.save_problem("TEST|host2|counter_test", {
            "status": "active",
            "channel_type": "agent",
            "host": "host2",
            "last_line": "Counter test occurrence 2",
            "plugin_name": "counter_test",
            "last_seen": "2026-06-01T13:05:00+00:00",
            "missing_count": 0,
        })
        import sentinel.state_base as _sb
        conn = sqlite3.connect(_sb.DB_FILE)
        row = conn.execute(
            "SELECT occurrence_count FROM problems WHERE key=?",
            ("TEST|host2|counter_test",)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertGreater(row[0], 1, "Occurrence count should be > 1 after second save")


class TestIssueHistoryPruning(unittest.TestCase):
    """Test 366: prune_issue_history function."""

    def test_prune_returns_int(self):
        """prune_issue_history should return an integer (count deleted)."""
        from sentinel.state_issues import prune_issue_history
        result = prune_issue_history(days=3650)  # Far future — nothing to delete
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)


if __name__ == '__main__':
    unittest.main()

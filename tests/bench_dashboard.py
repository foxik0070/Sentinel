"""
tests/bench_dashboard.py — Performance test for /api/dashboard (343)
Measures response time under repeated calls.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDashboardPerformance(unittest.TestCase):
    """Performance benchmark for dashboard data aggregation."""

    @classmethod
    def setUpClass(cls):
        """Build minimal Flask app context for benchmark."""
        import tempfile
        import sqlite3
        import sentinel.state_base as sb
        import sentinel.state as st

        cls._tmpdir = tempfile.mkdtemp()
        cls._tmpdb = os.path.join(cls._tmpdir, "bench_dashboard.db")
        cls._orig_db = st.DB_FILE
        st.DB_FILE = cls._tmpdb
        sb.DB_FILE = cls._tmpdb
        sb.init_db()

        # Insert sample data — 50 issues + 10 agents
        conn = sqlite3.connect(cls._tmpdb)
        for i in range(50):
            conn.execute(
                "INSERT OR IGNORE INTO problems (key, status, channel_type, host, last_line, plugin_name, last_seen, missing_count) VALUES (?,?,?,?,?,?,?,?)",
                (f"BENCH|host{i%10}|plugin{i}", "active", "infra", f"host{i%10}",
                 f"benchmark test issue {i}", "bench_plugin", "2026-06-01T10:00:00", 0)
            )
        for i in range(10):
            conn.execute(
                "INSERT OR IGNORE INTO agents (hostname, token, status, last_seen) VALUES (?,?,?,?)",
                (f"host{i}", f"tok{i}", "ONLINE", "2026-06-01T10:00:00")
            )
        conn.commit()
        conn.close()

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

    def test_get_active_issues_latency(self):
        """get_active_issues should respond in < 500ms for 50 issues."""
        import sentinel.state as st
        start = time.time()
        for _ in range(10):
            issues = st.get_active_issues()
        elapsed = time.time() - start
        avg_ms = elapsed / 10 * 1000
        print(f"\n  get_active_issues avg: {avg_ms:.1f}ms (10 calls)")
        self.assertLess(avg_ms, 500, f"get_active_issues too slow: {avg_ms:.1f}ms")
        self.assertGreaterEqual(len(issues), 50)

    def test_get_all_agents_latency(self):
        """get_all_agents should respond in < 200ms."""
        import sentinel.state as st
        start = time.time()
        for _ in range(10):
            agents = st.get_all_agents()
        elapsed = time.time() - start
        avg_ms = elapsed / 10 * 1000
        print(f"  get_all_agents avg: {avg_ms:.1f}ms (10 calls)")
        self.assertLess(avg_ms, 200, f"get_all_agents too slow: {avg_ms:.1f}ms")

    def test_plugin_stats_latency(self):
        """get_plugin_stats should respond in < 300ms."""
        import sentinel.state as st
        start = time.time()
        for _ in range(10):
            stats = st.get_plugin_stats()
        elapsed = time.time() - start
        avg_ms = elapsed / 10 * 1000
        print(f"  get_plugin_stats avg: {avg_ms:.1f}ms (10 calls)")
        self.assertLess(avg_ms, 300, f"get_plugin_stats too slow: {avg_ms:.1f}ms")


if __name__ == '__main__':
    # Run with verbose output when executed directly
    import sys
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestDashboardPerformance)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

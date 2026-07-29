"""526/527: Zpětná vazba na AI a paměť odmítnutých návrhů.

Jádro 527: normalizovaný otisk musí poznat, že jde o TÝŽ návrh i když ho
model naformátuje jinak — jinak by se odmítnutý příkaz nabízel pořád dokola.
"""
import os
import sys
import sqlite3
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state_agents as sa


class FeedbackBase(unittest.TestCase):
    """Každý test běží nad vlastní dočasnou DB."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.execute('''CREATE TABLE ai_feedback
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         kind TEXT NOT NULL, rating TEXT NOT NULL,
                         problem_key TEXT DEFAULT '', plugin_name TEXT DEFAULT '',
                         host TEXT DEFAULT '', suggestion TEXT DEFAULT '',
                         suggestion_hash TEXT DEFAULT '', reason TEXT DEFAULT '',
                         username TEXT DEFAULT '',
                         created_at TEXT DEFAULT (datetime('now')))''')
        conn.commit()
        conn.close()
        self._orig = sa._get_conn
        sa._get_conn = lambda: sqlite3.connect(self.db_path)

    def tearDown(self):
        sa._get_conn = self._orig
        os.unlink(self.db_path)


class TestSuggestionHash(unittest.TestCase):
    def test_same_command_same_hash(self):
        self.assertEqual(sa._suggestion_hash("df -h"), sa._suggestion_hash("df -h"))

    def test_formatting_differences_ignored(self):
        """Model rád mění mezery a velikost písmen — nesmí to obejít paměť."""
        base = sa._suggestion_hash("systemctl restart nginx")
        for variant in ("  systemctl restart nginx  ",
                        "systemctl  restart   nginx",
                        "SystemCtl Restart Nginx",
                        "systemctl restart nginx\n"):
            self.assertEqual(sa._suggestion_hash(variant), base, variant)

    def test_different_commands_differ(self):
        self.assertNotEqual(sa._suggestion_hash("rm -rf /a"),
                            sa._suggestion_hash("rm -rf /b"))

    def test_empty_gives_empty(self):
        for empty in ("", "   ", None):
            self.assertEqual(sa._suggestion_hash(empty), '')


class TestRecordFeedback(FeedbackBase):
    def test_record_returns_true(self):
        self.assertTrue(sa.record_ai_feedback('autofix', 'up', 'df -h'))

    def test_record_persists_fields(self):
        sa.record_ai_feedback('autofix', 'down', 'rm -rf /tmp/x',
                              problem_key='k1', plugin_name='storage',
                              host='rpi', reason='smaže cache', username='foxik')
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT kind, rating, problem_key, plugin_name, host, "
                           "suggestion, reason, username FROM ai_feedback").fetchone()
        conn.close()
        self.assertEqual(row, ('autofix', 'down', 'k1', 'storage', 'rpi',
                               'rm -rf /tmp/x', 'smaže cache', 'foxik'))

    def test_long_values_truncated_not_rejected(self):
        self.assertTrue(sa.record_ai_feedback('autofix', 'down', 'x' * 5000,
                                              reason='y' * 5000))
        conn = sqlite3.connect(self.db_path)
        s, r = conn.execute("SELECT suggestion, reason FROM ai_feedback").fetchone()
        conn.close()
        self.assertEqual(len(s), 1000)
        self.assertEqual(len(r), 500)

    def test_db_error_returns_false_not_raise(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error("boom"))
        self.assertFalse(sa.record_ai_feedback('autofix', 'up', 'df -h'))


class TestWasRejected(FeedbackBase):
    def test_unknown_suggestion_is_none(self):
        self.assertIsNone(sa.was_suggestion_rejected('df -h'))

    def test_rejected_suggestion_is_found(self):
        sa.record_ai_feedback('autofix', 'down', 'systemctl restart nginx',
                              reason='shodí produkci', username='foxik')
        prior = sa.was_suggestion_rejected('systemctl restart nginx')
        self.assertIsNotNone(prior)
        self.assertEqual(prior['reason'], 'shodí produkci')
        self.assertEqual(prior['by'], 'foxik')

    def test_reformatted_suggestion_still_found(self):
        """Klíčové pro 527 — jinak stačí jiná mezera a návrh se vrátí."""
        sa.record_ai_feedback('autofix', 'down', 'systemctl restart nginx')
        self.assertIsNotNone(sa.was_suggestion_rejected('SYSTEMCTL  restart nginx'))

    def test_positive_feedback_is_not_a_rejection(self):
        sa.record_ai_feedback('autofix', 'up', 'df -h')
        sa.record_ai_feedback('autofix', 'applied', 'df -h')
        self.assertIsNone(sa.was_suggestion_rejected('df -h'))

    def test_rejection_count_accumulates(self):
        for _ in range(3):
            sa.record_ai_feedback('autofix', 'down', 'reboot now')
        self.assertEqual(sa.was_suggestion_rejected('reboot now')['times'], 3)

    def test_rejected_status_counts_too(self):
        sa.record_ai_feedback('autofix', 'rejected', 'dd if=/dev/zero of=/dev/sda')
        self.assertIsNotNone(sa.was_suggestion_rejected('dd if=/dev/zero of=/dev/sda'))

    def test_plugin_filter_scopes_lookup(self):
        sa.record_ai_feedback('autofix', 'down', 'df -h', plugin_name='storage')
        self.assertIsNotNone(sa.was_suggestion_rejected('df -h', 'storage'))
        self.assertIsNone(sa.was_suggestion_rejected('df -h', 'network'))

    def test_empty_suggestion_is_none(self):
        self.assertIsNone(sa.was_suggestion_rejected(''))

    def test_db_error_returns_none_not_raise(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error("boom"))
        self.assertIsNone(sa.was_suggestion_rejected('df -h'))


class TestFeedbackStats(FeedbackBase):
    def test_empty_db_gives_null_ratio(self):
        stats = sa.get_ai_feedback_stats()
        self.assertIsNone(stats['useful_pct'])
        self.assertEqual(stats['recent'], [])

    def test_useful_pct_computed(self):
        for _ in range(3):
            sa.record_ai_feedback('autofix', 'up', 'a')
        sa.record_ai_feedback('autofix', 'down', 'b')
        self.assertEqual(sa.get_ai_feedback_stats()['useful_pct'], 75.0)

    def test_applied_counts_as_useful(self):
        sa.record_ai_feedback('autofix', 'applied', 'a')
        sa.record_ai_feedback('autofix', 'rejected', 'b')
        self.assertEqual(sa.get_ai_feedback_stats()['useful_pct'], 50.0)

    def test_split_by_kind(self):
        sa.record_ai_feedback('autofix', 'up', 'a')
        sa.record_ai_feedback('diagnose', 'down', 'b')
        by_kind = sa.get_ai_feedback_stats()['by_kind']
        self.assertEqual(by_kind['autofix']['up'], 1)
        self.assertEqual(by_kind['diagnose']['down'], 1)

    def test_recent_is_capped(self):
        for i in range(30):
            sa.record_ai_feedback('autofix', 'up', f'cmd{i}')
        self.assertEqual(len(sa.get_ai_feedback_stats()['recent']), 20)

    def test_db_error_returns_empty_shape(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error("boom"))
        stats = sa.get_ai_feedback_stats()
        self.assertEqual(stats['by_kind'], {})
        self.assertEqual(stats['recent'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

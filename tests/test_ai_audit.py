"""545: Audit stopa AI rozhodnutí.

Smysl: u zásahu, který AI navrhla, musí jít zpětně zjistit, co model dostal
a co vrátil. Zápis proto nesmí selhat tiše a nesmí shodit volající cestu.
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


class AuditBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.execute('''CREATE TABLE ai_audit
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         kind TEXT NOT NULL, model TEXT DEFAULT '',
                         problem_key TEXT DEFAULT '', host TEXT DEFAULT '',
                         prompt TEXT DEFAULT '', response TEXT DEFAULT '',
                         outcome TEXT DEFAULT '', executed INTEGER DEFAULT 0,
                         suspicious INTEGER DEFAULT 0, username TEXT DEFAULT '',
                         created_at TEXT DEFAULT (datetime('now')))''')
        conn.commit()
        conn.close()
        self._orig = sa._get_conn
        sa._get_conn = lambda: sqlite3.connect(self.db_path)

    def tearDown(self):
        sa._get_conn = self._orig
        os.unlink(self.db_path)


class TestRecord(AuditBase):
    def test_returns_id(self):
        self.assertIsInstance(sa.record_ai_decision('autofix', 'p', 'r'), int)

    def test_persists_fields(self):
        sa.record_ai_decision('diagnose', prompt='co je špatně?', response='disk plný',
                              model='qwen', problem_key='k1', host='rpi',
                              outcome='navrženo', executed=True, suspicious=True,
                              username='foxik')
        e = sa.get_ai_audit()[0]
        self.assertEqual(e['kind'], 'diagnose')
        self.assertEqual(e['prompt'], 'co je špatně?')
        self.assertEqual(e['response'], 'disk plný')
        self.assertEqual(e['host'], 'rpi')
        self.assertEqual(e['executed'], 1)
        self.assertEqual(e['suspicious'], 1)

    def test_long_text_truncated_not_rejected(self):
        """Dlouhý prompt se má oříznout, ne způsobit ztrátu celého záznamu."""
        self.assertIsNotNone(sa.record_ai_decision('autofix', 'x' * 99999, 'y' * 99999))
        e = sa.get_ai_audit()[0]
        self.assertEqual(len(e['prompt']), sa._AUDIT_PROMPT_MAX)
        self.assertEqual(len(e['response']), sa._AUDIT_RESPONSE_MAX)

    def test_booleans_stored_as_ints(self):
        sa.record_ai_decision('autofix', executed=False, suspicious=False)
        e = sa.get_ai_audit()[0]
        self.assertEqual((e['executed'], e['suspicious']), (0, 0))

    def test_db_error_returns_none_not_raise(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error('boom'))
        self.assertIsNone(sa.record_ai_decision('autofix', 'p', 'r'))


class TestUpdate(AuditBase):
    def test_outcome_updated(self):
        aid = sa.record_ai_decision('autofix', 'p', 'r', outcome='navrženo')
        self.assertTrue(sa.update_ai_decision(aid, 'vykonáno', executed=True))
        e = sa.get_ai_audit()[0]
        self.assertEqual(e['outcome'], 'vykonáno')
        self.assertEqual(e['executed'], 1)

    def test_outcome_only_leaves_executed(self):
        aid = sa.record_ai_decision('autofix', executed=True)
        sa.update_ai_decision(aid, 'zamítnuto')
        self.assertEqual(sa.get_ai_audit()[0]['executed'], 1)

    def test_db_error_returns_false(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error('boom'))
        self.assertFalse(sa.update_ai_decision(1, 'x'))


class TestQuery(AuditBase):
    def test_filter_by_kind(self):
        sa.record_ai_decision('autofix')
        sa.record_ai_decision('diagnose')
        self.assertEqual(len(sa.get_ai_audit(kind='autofix')), 1)

    def test_filter_by_problem_key(self):
        sa.record_ai_decision('autofix', problem_key='k1')
        sa.record_ai_decision('autofix', problem_key='k2')
        self.assertEqual(len(sa.get_ai_audit(problem_key='k1')), 1)

    def test_filter_only_executed(self):
        sa.record_ai_decision('autofix', executed=True)
        sa.record_ai_decision('autofix', executed=False)
        self.assertEqual(len(sa.get_ai_audit(only_executed=True)), 1)

    def test_combined_filters(self):
        sa.record_ai_decision('autofix', problem_key='k1', executed=True)
        sa.record_ai_decision('autofix', problem_key='k1', executed=False)
        sa.record_ai_decision('diagnose', problem_key='k1', executed=True)
        self.assertEqual(len(sa.get_ai_audit(kind='autofix', problem_key='k1',
                                             only_executed=True)), 1)

    def test_newest_first(self):
        sa.record_ai_decision('autofix', response='starší')
        sa.record_ai_decision('autofix', response='novější')
        self.assertEqual(sa.get_ai_audit()[0]['response'], 'novější')

    def test_limit_respected(self):
        for i in range(10):
            sa.record_ai_decision('autofix', response=str(i))
        self.assertEqual(len(sa.get_ai_audit(limit=3)), 3)

    def test_db_error_returns_empty(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error('boom'))
        self.assertEqual(sa.get_ai_audit(), [])


class TestPrune(AuditBase):
    def test_old_entries_removed(self):
        sa.record_ai_decision('autofix')
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE ai_audit SET created_at = datetime('now','-200 days')")
        conn.commit()
        conn.close()
        self.assertEqual(sa.prune_ai_audit(90), 1)
        self.assertEqual(sa.get_ai_audit(), [])

    def test_recent_entries_kept(self):
        sa.record_ai_decision('autofix')
        self.assertEqual(sa.prune_ai_audit(90), 0)
        self.assertEqual(len(sa.get_ai_audit()), 1)

    def test_db_error_returns_zero(self):
        sa._get_conn = lambda: (_ for _ in ()).throw(sqlite3.Error('boom'))
        self.assertEqual(sa.prune_ai_audit(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

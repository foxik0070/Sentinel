"""450/447: Korelace se změnami a kauzální řetěz.

Zásada: časová souvislost NENÍ důkaz příčiny. Modul nikde netvrdí
„tohle to způsobilo" — a testy to hlídají i ve formulacích promptu.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import correlate as co

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
ISSUE = {'key': 'K1', 'host': 'rpi', 'plugin_name': 'storage',
         'last_line': 'disk 97%', 'first_seen': NOW.isoformat()}


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat()


class FakeState:
    def __init__(self, cfg=None, actions=None, fixes=None, issues=None):
        self._cfg, self._act = cfg or [], actions or []
        self._fix, self._iss = fixes or [], issues or []

    def get_config_history(self, limit=50):
        return self._cfg

    def list_actions(self, limit=200):
        return self._act

    def get_fix_attempts(self, limit=200):
        return self._fix

    def get_active_issues(self):
        return self._iss


class TestCollectChanges(unittest.TestCase):
    def test_config_change_in_window(self):
        st = FakeState(cfg=[{'timestamp': ago(30), 'content_hash': 'abc123def456'}])
        c = co.collect_changes(st, ISSUE)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]['kind'], 'config_change')
        self.assertEqual(c[0]['minutes_before'], 30.0)

    def test_change_outside_window_ignored(self):
        st = FakeState(cfg=[{'timestamp': ago(999), 'content_hash': 'x'}])
        self.assertEqual(co.collect_changes(st, ISSUE), [])

    def test_change_after_issue_ignored(self):
        """Co se stalo POTOM, nemohlo problém způsobit."""
        later = (NOW + timedelta(minutes=10)).isoformat()
        st = FakeState(cfg=[{'timestamp': later, 'content_hash': 'x'}])
        self.assertEqual(co.collect_changes(st, ISSUE), [])

    def test_action_on_other_host_ignored(self):
        st = FakeState(actions=[{'executed_at': ago(10), 'node': 'jiny', 'command': 'x'}])
        self.assertEqual(co.collect_changes(st, ISSUE), [])

    def test_action_on_same_host_included(self):
        st = FakeState(actions=[{'executed_at': ago(10), 'node': 'rpi',
                                 'command': 'systemctl restart nginx'}])
        c = co.collect_changes(st, ISSUE)
        self.assertEqual(c[0]['kind'], 'action')
        self.assertIn('nginx', c[0]['detail'])

    def test_fix_attempt_included(self):
        st = FakeState(fixes=[{'applied_at': ago(5), 'host': 'rpi', 'command': 'reload'}])
        self.assertEqual(co.collect_changes(st, ISSUE)[0]['kind'], 'fix_attempt')

    def test_prior_issue_included(self):
        st = FakeState(issues=[{'key': 'K2', 'host': 'rpi', 'plugin_name': 'net',
                                'first_seen': ago(15), 'last_line': 'sit mimo'}])
        self.assertEqual(co.collect_changes(st, ISSUE)[0]['kind'], 'prior_issue')

    def test_own_issue_not_listed(self):
        st = FakeState(issues=[dict(ISSUE, first_seen=ago(5))])
        self.assertEqual(co.collect_changes(st, ISSUE), [])

    def test_sorted_by_proximity(self):
        st = FakeState(cfg=[{'timestamp': ago(90), 'content_hash': 'stara'}],
                       fixes=[{'applied_at': ago(3), 'host': 'rpi', 'command': 'nova'}])
        c = co.collect_changes(st, ISSUE)
        self.assertEqual(c[0]['minutes_before'], 3.0)

    def test_broken_source_does_not_hide_others(self):
        st = FakeState(fixes=[{'applied_at': ago(5), 'host': 'rpi', 'command': 'x'}])
        st.get_config_history = lambda limit=50: (_ for _ in ()).throw(RuntimeError('db'))
        self.assertEqual(len(co.collect_changes(st, ISSUE)), 1)

    def test_issue_without_timestamp(self):
        self.assertEqual(co.collect_changes(FakeState(), {'host': 'rpi'}), [])

    def test_window_configurable(self):
        st = FakeState(cfg=[{'timestamp': ago(300), 'content_hash': 'x'}])
        self.assertEqual(co.collect_changes(st, ISSUE), [])
        self.assertEqual(len(co.collect_changes(st, ISSUE, window_min=400)), 1)


class TestChangesNote(unittest.TestCase):
    def test_empty(self):
        self.assertIn('žádné', co.changes_note([]))

    def test_does_not_claim_causation(self):
        """Formulace nesmí modelu podsunout, že jde o příčinu."""
        note = co.changes_note([{'what': 'X', 'detail': 'Y', 'minutes_before': 5}])
        self.assertIn('ne důkaz', note)
        for forbidden in ('způsobil', 'příčinou je', 'kvůli'):
            self.assertNotIn(forbidden, note.lower())

    def test_limited(self):
        items = [{'what': f'x{i}', 'detail': 'd', 'minutes_before': i} for i in range(20)]
        self.assertLessEqual(co.changes_note(items, limit=3).count('\n'), 5)


class TestChainPrompt(unittest.TestCase):
    def test_demands_json_structure(self):
        p = co.chain_prompt(ISSUE)
        self.assertIn('POUZE JSON', p)
        self.assertIn('root_cause', p)
        self.assertIn('chain', p)

    def test_includes_issue(self):
        self.assertIn('disk 97%', co.chain_prompt(ISSUE))

    def test_includes_changes(self):
        p = co.chain_prompt(ISSUE, [{'what': 'restart nginx', 'detail': 'd',
                                     'minutes_before': 5}])
        self.assertIn('restart nginx', p)


class TestNormalizeChain(unittest.TestCase):
    def test_list_chain(self):
        r = co.normalize_chain({'root_cause': 'disk plný', 'chain': ['logy rostou', 'zápis selhal'],
                                'observed': 'služba spadla', 'confidence': 80})
        self.assertEqual(r['chain'], ['logy rostou', 'zápis selhal'])
        self.assertEqual(r['confidence'], 80)

    def test_nodes_include_endpoints(self):
        r = co.normalize_chain({'root_cause': 'A', 'chain': ['B'], 'observed': 'C'})
        self.assertEqual(r['nodes'], ['A', 'B', 'C'])

    def test_arrow_string_chain_split(self):
        """Model rád vrátí řetěz jako jeden slepený řetězec."""
        r = co.normalize_chain({'root_cause': 'A', 'chain': 'B -> C -> D'})
        self.assertEqual(r['chain'], ['B', 'C', 'D'])

    def test_unicode_arrow_split(self):
        r = co.normalize_chain({'root_cause': 'A', 'chain': 'B → C'})
        self.assertEqual(r['chain'], ['B', 'C'])

    def test_semicolon_split(self):
        r = co.normalize_chain({'root_cause': 'A', 'chain': 'B; C'})
        self.assertEqual(r['chain'], ['B', 'C'])

    def test_dict_items_unwrapped(self):
        r = co.normalize_chain({'root_cause': 'A',
                                'chain': [{'effect': 'B'}, {'step': 'C'}, {'text': 'D'}]})
        self.assertEqual(r['chain'], ['B', 'C', 'D'])

    def test_missing_root_cause_rejected(self):
        """Rozbitý strom je horší než žádný."""
        for bad in ({'chain': ['x']}, {'root_cause': ''}, {}, None, 'text', 123):
            self.assertIsNone(co.normalize_chain(bad), repr(bad))

    def test_depth_capped(self):
        r = co.normalize_chain({'root_cause': 'A', 'chain': [f's{i}' for i in range(50)]})
        self.assertLessEqual(len(r['chain']), co.MAX_CHAIN_DEPTH)

    def test_long_text_truncated(self):
        r = co.normalize_chain({'root_cause': 'x' * 999, 'chain': ['y' * 999]})
        self.assertLessEqual(len(r['root_cause']), 300)
        self.assertLessEqual(len(r['chain'][0]), 300)

    def test_bad_confidence_becomes_none(self):
        for bad in ('mnoho', None, [], {}):
            self.assertIsNone(co.normalize_chain({'root_cause': 'A', 'confidence': bad})['confidence'])

    def test_confidence_clamped(self):
        self.assertEqual(co.normalize_chain({'root_cause': 'A', 'confidence': 500})['confidence'], 100)

    def test_missing_chain_ok(self):
        r = co.normalize_chain({'root_cause': 'A'})
        self.assertEqual(r['chain'], [])
        self.assertEqual(r['nodes'], ['A'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

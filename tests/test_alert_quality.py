"""480: Rozpoznání falešných poplachů.

Riziko není v tom, že se něco nenajde — ale že se k utišení navrhne alert,
který byl skutečný. Většina testů proto hlídá vylučovací podmínky.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import alert_quality as aq

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def row(minutes=1.0, resolved_by='', reason='detector_ok', key='K1',
        plugin='svc_monitor', host='docs', line='service X down'):
    start = NOW - timedelta(minutes=minutes)
    return {'key': key, 'plugin_name': plugin, 'host': host, 'last_line': line,
            'first_seen': start.isoformat(), 'resolved_at': NOW.isoformat(),
            'resolve_reason': reason, 'resolved_by': resolved_by,
            'channel_type': 'general', 'last_seen': NOW.isoformat()}


def rows(n, **kw):
    kw.setdefault('key', None)          # None = odvodit z indexu
    base_key = kw.pop('key')
    return [row(key=base_key or f'K{i}', **kw) for i in range(n)]


class TestNormalizeMessage(unittest.TestCase):
    def test_numbers_collapsed(self):
        """Bez toho by každý výskyt s jiným číslem vypadal jedinečně."""
        a = aq.normalize_message('disk usage 97% on /dev/sda1')
        b = aq.normalize_message('disk usage 42% on /dev/sda2')
        self.assertEqual(a, b)

    def test_timestamps_collapsed(self):
        a = aq.normalize_message('Jul 31 08:15:02 error occurred')
        b = aq.normalize_message('Jul 30 22:01:59 error occurred')
        self.assertEqual(a, b)

    def test_hex_collapsed(self):
        self.assertEqual(aq.normalize_message('trace deadbeef1234 failed'),
                         aq.normalize_message('trace 0badc0de9999 failed'))

    def test_different_messages_stay_different(self):
        self.assertNotEqual(aq.normalize_message('disk full'),
                            aq.normalize_message('service down'))

    def test_empty(self):
        for v in ('', None):
            self.assertEqual(aq.normalize_message(v), '')

    def test_truncated(self):
        self.assertLessEqual(len(aq.normalize_message('x' * 999)), 200)


class TestExclusions(unittest.TestCase):
    """Co se NIKDY nesmí navrhnout k utišení."""

    def test_human_resolved_excluded(self):
        """Jediný lidský zásah znamená, že to poplach nebyl."""
        data = rows(30) + [row(resolved_by='foxik')]
        self.assertEqual(aq.analyze(data), [])

    def test_human_reason_excluded(self):
        data = rows(30) + [row(reason='recheck_forced')]
        self.assertEqual(aq.analyze(data), [])

    def test_touched_by_fix_attempt_excluded(self):
        data = rows(30, key='SAME')
        self.assertEqual(aq.analyze(data, touched_keys={'SAME'}), [])

    def test_below_min_occurrences_excluded(self):
        self.assertEqual(aq.analyze(rows(aq.MIN_OCCURRENCES - 1)), [])

    def test_missing_timestamps_excluded(self):
        bad = [dict(row(), first_seen=None) for _ in range(30)]
        self.assertEqual(aq.analyze(bad), [])


class TestDetection(unittest.TestCase):
    def test_recurring_self_resolved_detected(self):
        c = aq.analyze(rows(30))
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]['occurrences'], 30)
        self.assertEqual(c[0]['self_resolved_pct'], 100.0)

    def test_transient_flagged(self):
        c = aq.analyze(rows(30, minutes=1.0))
        self.assertTrue(c[0]['transient'])
        self.assertEqual(c[0]['suggestion']['kind'], 'delay')

    def test_long_running_not_transient(self):
        c = aq.analyze(rows(30, minutes=600.0))
        self.assertFalse(c[0]['transient'])
        self.assertEqual(c[0]['suggestion']['kind'], 'review_threshold')

    def test_delay_exceeds_median(self):
        """Zdržení musí mít rezervu, jinak utiší i o něco delší výskyty."""
        c = aq.analyze(rows(30, minutes=3.0))
        self.assertGreater(c[0]['suggestion']['delay_min'], 3)

    def test_oneshot_gets_warning_note(self):
        """U jednorázové události zdržení nepomůže — musí to říct."""
        c = aq.analyze(rows(30, minutes=1.0))
        self.assertIn('note', c[0]['suggestion'])
        self.assertIn('jednorázov', c[0]['suggestion']['note'])

    def test_longer_transient_has_no_oneshot_note(self):
        c = aq.analyze(rows(30, minutes=6.0))
        self.assertNotIn('note', c[0]['suggestion'])

    def test_grouping_by_plugin_and_host(self):
        data = rows(15, host='a') + rows(15, host='b')
        self.assertEqual(len(aq.analyze(data)), 2)

    def test_variable_numbers_group_together(self):
        data = [row(key=f'K{i}', line=f'disk usage {i}% full') for i in range(30)]
        c = aq.analyze(data)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]['occurrences'], 30)

    def test_sorted_by_occurrences(self):
        data = rows(15, host='malo') + rows(40, host='hodne')
        self.assertEqual(aq.analyze(data)[0]['host'], 'hodne')

    def test_min_occurrences_param(self):
        self.assertTrue(aq.analyze(rows(5), min_occurrences=3))


class TestRobustness(unittest.TestCase):
    def test_malformed_rows_ignored(self):
        for bad in (None, [], [None], ['text'], [{}], [123]):
            self.assertIsInstance(aq.analyze(bad), list)

    def test_negative_duration_ignored(self):
        """Rozbitá data (konec před začátkem) nesmí zkreslit medián."""
        bad = dict(row(), first_seen=NOW.isoformat(),
                   resolved_at=(NOW - timedelta(minutes=10)).isoformat())
        c = aq.analyze(rows(30) + [bad])
        self.assertTrue(c)
        self.assertGreaterEqual(c[0]['median_duration_min'], 0)

    def test_naive_timestamps_handled(self):
        naive = [dict(row(key=f'K{i}'),
                      first_seen='2026-07-31 11:59:00',
                      resolved_at='2026-07-31 12:00:00') for i in range(30)]
        c = aq.analyze(naive)
        self.assertTrue(c)
        self.assertAlmostEqual(c[0]['median_duration_min'], 1.0, places=1)


class TestSummarize(unittest.TestCase):
    def test_empty(self):
        s = aq.summarize([])
        self.assertEqual(s['candidates'], 0)
        self.assertEqual(s['suppressible_alerts'], 0)

    def test_counts_only_transient_noise(self):
        s = aq.summarize([{'occurrences': 100, 'transient': True},
                          {'occurrences': 50, 'transient': False}])
        self.assertEqual(s['candidates'], 2)
        self.assertEqual(s['transient'], 1)
        self.assertEqual(s['suppressible_alerts'], 100)

    def test_none_input(self):
        self.assertEqual(aq.summarize(None)['candidates'], 0)


class TestMedian(unittest.TestCase):
    def test_odd(self):
        self.assertEqual(aq._median([3, 1, 2]), 2)

    def test_even(self):
        self.assertEqual(aq._median([1, 2, 3, 4]), 2.5)

    def test_empty(self):
        self.assertIsNone(aq._median([]))


if __name__ == '__main__':
    unittest.main(verbosity=2)

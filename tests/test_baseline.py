"""469/470/473/475/476/481: detekce pod prahem.

Práh je binární — buď hodnota přeteče, nebo ne. Realita je jiná: deset
neúspěšných přihlášení za hodinu je normál, deset za minutu z deseti adres
je útok, a žádné z nich prahem neprojde.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import baseline as bl

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def series(values, step_min=5):
    n = len(values)
    return [((NOW - timedelta(minutes=step_min * (n - 1 - i))).isoformat(), v)
            for i, v in enumerate(values)]


class TestHostProfile(unittest.TestCase):
    def test_profile_built(self):
        p = bl.build_host_profile('rpi', {'temp': series([45.0] * 30)})
        self.assertEqual(p['metrics']['temp']['mean'], 45.0)

    def test_short_series_skipped(self):
        p = bl.build_host_profile('rpi', {'temp': series([45.0] * 5)})
        self.assertEqual(p['metrics'], {})

    def test_non_numeric_ignored(self):
        p = bl.build_host_profile('rpi', {'temp': series(['x'] * 30)})
        self.assertEqual(p['metrics'], {})

    def test_deviation_detected(self):
        """Stroj běžně na 45 → 60 je u NĚJ problém, i pod obecným prahem."""
        vals = [45.0 + (i % 3) * 0.5 for i in range(40)]
        p = bl.build_host_profile('rpi', {'temp': series(vals)})
        self.assertTrue(bl.deviations_from_profile(p, {'temp': 60.0}))

    def test_normal_value_no_deviation(self):
        vals = [45.0 + (i % 3) * 0.5 for i in range(40)]
        p = bl.build_host_profile('rpi', {'temp': series(vals)})
        self.assertEqual(bl.deviations_from_profile(p, {'temp': 45.5}), [])

    def test_unknown_metric_ignored(self):
        p = bl.build_host_profile('rpi', {'temp': series([45.0] * 30)})
        self.assertEqual(bl.deviations_from_profile(p, {'jina': 999}), [])

    def test_zero_stdev_does_not_divide(self):
        p = bl.build_host_profile('rpi', {'temp': series([45.0] * 30)})
        self.assertEqual(bl.deviations_from_profile(p, {'temp': 999}), [])

    def test_empty(self):
        self.assertEqual(bl.build_host_profile('h', {})['metrics'], {})
        self.assertEqual(bl.deviations_from_profile({}, {'x': 1}), [])


class TestSeasonality(unittest.TestCase):
    def nightly(self, n=20, hour=3):
        return [{'at': (NOW.replace(hour=hour) - timedelta(days=i)).isoformat()}
                for i in range(n)]

    def test_nightly_peak_found(self):
        r = bl.seasonal_profile(self.nightly())
        self.assertTrue(any(p['dimension'] == 'hodina' and p['value'] == 3
                            for p in r['peaks']))

    def test_scheduled_recognised(self):
        """Záloha každou noc není opakovaná porucha, ale rozvrh."""
        r = bl.is_scheduled_pattern(bl.seasonal_profile(self.nightly())['peaks'])
        self.assertTrue(r['scheduled'])
        self.assertIn('cron', r['note'])

    def test_spread_events_no_peak(self):
        events = [{'at': (NOW - timedelta(hours=i)).isoformat()} for i in range(72)]
        self.assertEqual(bl.seasonal_profile(events)['peaks'], [])

    def test_empty(self):
        self.assertEqual(bl.seasonal_profile([])['total'], 0)
        self.assertFalse(bl.is_scheduled_pattern([])['scheduled'])


class TestAuthAudit(unittest.TestCase):
    def test_distributed_bruteforce(self):
        """Jedna adresa práh nepřekročí; deset adres na jeden účet je útok."""
        lines = [f'Failed password for root from 10.0.0.{i} port 22 ssh2'
                 for i in range(10)]
        f = bl.audit_auth_log(lines)
        self.assertTrue(any(x['kind'] == 'distributed_bruteforce' for x in f))

    def test_user_spray(self):
        lines = [f'Failed password for user{i} from 10.0.0.5 port 22 ssh2'
                 for i in range(8)]
        f = bl.audit_auth_log(lines)
        spray = [x for x in f if x['kind'] == 'user_spray']
        self.assertTrue(spray)
        self.assertEqual(spray[0]['source'], '10.0.0.5')

    def test_success_after_bruteforce_is_critical(self):
        lines = [f'Failed password for root from 10.0.0.{i} port 22' for i in range(15)]
        lines.append('Accepted password for root from 10.0.0.1 port 22 ssh2')
        f = bl.audit_auth_log(lines)
        crit = [x for x in f if x['kind'] == 'success_after_bruteforce']
        self.assertTrue(crit)
        self.assertEqual(crit[0]['severity'], 'critical')

    def test_normal_traffic_clean(self):
        lines = ['Accepted publickey for sentinel from 192.168.2.1 port 22 ssh2',
                 'Failed password for root from 10.0.0.1 port 22 ssh2']
        self.assertEqual(bl.audit_auth_log(lines), [])

    def test_empty(self):
        for v in (None, [], ['']):
            self.assertEqual(bl.audit_auth_log(v), [])


class TestFlappingCause(unittest.TestCase):
    def hist(self, gaps_min):
        t = NOW
        out = []
        for g in gaps_min:
            out.append({'first_seen': t.isoformat()})
            t += timedelta(minutes=g)
        return out

    def test_regular_interval_points_to_timer(self):
        r = bl.flapping_cause(self.hist([10] * 8))
        self.assertEqual(r['pattern'], 'regular')
        self.assertIn('časovač', r['note'])

    def test_irregular_points_elsewhere(self):
        r = bl.flapping_cause(self.hist([2, 40, 5, 90, 3, 60, 7]))
        self.assertEqual(r['pattern'], 'irregular')

    def test_too_few_samples(self):
        self.assertFalse(bl.flapping_cause(self.hist([10]))['known'])

    def test_empty(self):
        self.assertFalse(bl.flapping_cause([])['known'])


class TestRelationAnomalies(unittest.TestCase):
    def test_cpu_up_requests_flat_detected(self):
        """Práci dělá něco jiného než provoz."""
        s = {'host.cpu': series([float(i) for i in range(40)]),
             'host.requests': series([100.0 + (i % 2) for i in range(40)])}
        r = bl.relation_anomalies(s)
        self.assertTrue(r)
        self.assertIn('cpu', r[0]['metric_a'])

    def test_both_growing_together_is_fine(self):
        s = {'host.cpu': series([float(i) for i in range(40)]),
             'host.requests': series([float(i * 10) for i in range(40)])}
        self.assertEqual(bl.relation_anomalies(s), [])

    def test_missing_pair_skipped(self):
        self.assertEqual(bl.relation_anomalies({'host.cpu': series([1.0] * 30)}), [])

    def test_short_series_skipped(self):
        s = {'host.cpu': series([float(i) for i in range(5)]),
             'host.requests': series([100.0] * 5)}
        self.assertEqual(bl.relation_anomalies(s), [])

    def test_empty(self):
        for v in (None, {}):
            self.assertEqual(bl.relation_anomalies(v), [])


class TestMissingMonitoring(unittest.TestCase):
    def test_unmonitored_host_found(self):
        """Nula alertů může znamenat klid — nebo že tam nikdo nekouká."""
        r = bl.missing_monitoring(['a', 'b'], agents=[{'hostname': 'a'}], issues=[])
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]['host'], 'b')

    def test_agent_counts_as_monitored(self):
        r = bl.missing_monitoring(['a'], agents=[{'hostname': 'a'}], issues=[])
        self.assertEqual(r, [])

    def test_telemetry_counts_as_monitored(self):
        r = bl.missing_monitoring(['a'], agents=[], issues=[], telemetry_hosts=['a'])
        self.assertEqual(r, [])

    def test_issue_counts_as_monitored(self):
        r = bl.missing_monitoring(['a'], agents=[], issues=[{'host': 'a'}])
        self.assertEqual(r, [])

    def test_case_insensitive(self):
        r = bl.missing_monitoring(['RPi'], agents=[{'hostname': 'rpi'}], issues=[])
        self.assertEqual(r, [])

    def test_empty(self):
        self.assertEqual(bl.missing_monitoring([], [], []), [])

    def test_short_window_gives_no_phantom_monthly_pattern(self):
        """Ze tri dnu historie nelze usuzovat na den v mesici."""
        events = [{'at': (NOW - timedelta(hours=i)).isoformat()} for i in range(72)]
        peaks = bl.seasonal_profile(events)['peaks']
        self.assertFalse(any(p['dimension'] == 'den_v_mesici' for p in peaks))

    def test_long_window_allows_monthly_dimension(self):
        events = [{'at': (NOW - timedelta(days=i)).isoformat()} for i in range(40)]
        bl.seasonal_profile(events)     # nesmi spadnout


if __name__ == '__main__':
    unittest.main(verbosity=2)

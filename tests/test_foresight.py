"""466/471/474: Nezachycené logy, kapacita s kontextem, týdenní výhled."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import unmatched as um
from sentinel import foresight as fs


class TestUnmatchedCapture(unittest.TestCase):
    def setUp(self):
        um.clear()

    def tearDown(self):
        um.clear()

    def test_error_line_captured(self):
        um.record('/var/log/divny.log', ['ERROR: connection refused'])
        self.assertEqual(len(um.top()), 1)

    def test_benign_line_ignored(self):
        um.record('/var/log/x.log', ['GET /api/status 200', 'Started session'])
        self.assertEqual(um.top(), [])

    def test_czech_signals(self):
        um.record('/var/log/x.log', ['Selhal zápis do databáze'])
        self.assertEqual(len(um.top()), 1)

    def test_identical_lines_grouped(self):
        um.record('/var/log/x.log', ['ERROR: disk 91% full'] * 5)
        self.assertEqual(len(um.top()), 1)
        self.assertEqual(um.top()[0]['count'], 5)

    def test_variable_numbers_grouped(self):
        """Tisíc stejných chyb s jiným číslem má zabrat jedno místo."""
        um.record('/var/log/x.log', [f'ERROR: disk {i}% full' for i in range(20)])
        self.assertEqual(len(um.top()), 1)

    def test_different_files_separate(self):
        um.record('/var/log/a.log', ['ERROR: x'])
        um.record('/var/log/b.log', ['ERROR: x'])
        self.assertEqual(len(um.top()), 2)

    def test_memory_bounded(self):
        """Zaplavený log nesmí sníst paměť."""
        # Text musi byt ruzny i po normalizaci (ta setre cisla)
        um.record('/var/log/x.log',
                  [f'ERROR: selhalo {chr(97+i%26)}{chr(97+(i//26)%26)}{chr(97+(i//676)%26)} modulu'
                   for i in range(um.MAX_SAMPLES + 200)])
        self.assertLessEqual(len(um._samples), um.MAX_SAMPLES)
        self.assertGreater(um.stats()['dropped_full'], 0)

    def test_long_line_truncated(self):
        um.record('/var/log/x.log', ['ERROR: ' + 'x' * 5000])
        self.assertLessEqual(len(um.top()[0]['sample']), um.MAX_LINE_LEN)

    def test_sorted_by_frequency(self):
        um.record('/var/log/x.log', ['ERROR: vzacna chyba'])
        um.record('/var/log/x.log', ['ERROR: casta chyba'] * 10)
        self.assertIn('casta', um.top()[0]['sample'])

    def test_malformed_input_does_not_raise(self):
        for bad in (None, [], [None], [''], ['   ']):
            um.record('/var/log/x.log', bad)

    def test_stats_shape(self):
        um.record('/var/log/x.log', ['ERROR: x', 'benign line'])
        s = um.stats()
        self.assertEqual(s['seen'], 2)
        self.assertEqual(s['captured'], 1)


class TestSuggestionValidation(unittest.TestCase):
    SAMPLES = [{'sample': 'ERROR: connection refused to 10.0.0.1:5432'}]

    def test_valid_specific_pattern_accepted(self):
        r = um.validate_suggestions([{'pattern': r'connection refused to \S+'}], self.SAMPLES)
        self.assertIsNone(r[0]['rejected'])
        self.assertEqual(r[0]['matches_samples'], 1)

    def test_invalid_regex_dropped(self):
        self.assertEqual(um.validate_suggestions([{'pattern': '[unclosed'}]), [])

    def test_catch_all_rejected(self):
        """`.*` by zaplavilo systém vším."""
        for pat in ('.*', '.+', '^.*$'):
            r = um.validate_suggestions([{'pattern': pat}])
            self.assertTrue(r and r[0]['rejected'], pat)

    def test_pattern_matching_benign_traffic_rejected(self):
        """Pattern, co chytá běžný provoz, není detektor."""
        r = um.validate_suggestions([{'pattern': r'[a-z]+\s+\d+'}])
        self.assertTrue(r[0]['rejected'])

    def test_too_short_dropped(self):
        self.assertEqual(um.validate_suggestions([{'pattern': 'ab'}]), [])

    def test_malformed_entries_skipped(self):
        self.assertEqual(um.validate_suggestions([None, 'text', {}, {'pattern': ''}]), [])

    def test_prompt_includes_samples(self):
        p = um.suggest_prompt([{'file': '/var/log/x', 'count': 3, 'sample': 'ERROR: neco'}])
        self.assertIn('ERROR: neco', p)
        self.assertIn('POUZE JSON', p)


class TestForecast(unittest.TestCase):
    def test_days_to_limit(self):
        # 50 %, roste 1 %/h → 50 h ≈ 2,1 dne
        self.assertAlmostEqual(fs.forecast_days_to_limit(50, 1.0, 100), 2.1, places=1)

    def test_no_growth_gives_none(self):
        for slope in (0, -1):
            self.assertIsNone(fs.forecast_days_to_limit(50, slope, 100))

    def test_already_over_limit(self):
        self.assertIsNone(fs.forecast_days_to_limit(150, 1.0, 100))

    def test_too_far_future_ignored(self):
        self.assertIsNone(fs.forecast_days_to_limit(50, 0.00001, 100))

    def test_garbage_input(self):
        for args in ((None, 1), ('x', 1), (50, 'y')):
            self.assertIsNone(fs.forecast_days_to_limit(*args))


class TestCapacityItems(unittest.TestCase):
    def item(self, r2=0.9, last=50, slope=1.0):
        return {'metric': 'disk', 'r2': r2, 'last': last, 'slope_per_hour': slope,
                'growth_pct': 20}

    def test_confident_trend_gets_forecast(self):
        r = fs.build_capacity_items([self.item()])
        self.assertIsNotNone(r[0]['days_to_limit'])
        self.assertIn('pokud', r[0]['note'])

    def test_weak_fit_excluded(self):
        """Nízké r² znamená, že přímka nesedí — předpověď by byla věštění."""
        self.assertEqual(fs.build_capacity_items([self.item(r2=0.2)]), [])

    def test_slow_growth_has_no_deadline(self):
        r = fs.build_capacity_items([self.item(slope=0.000001)])
        self.assertIsNone(r[0]['days_to_limit'])

    def test_sorted_by_urgency(self):
        r = fs.build_capacity_items([self.item(slope=0.1), dict(self.item(slope=10.0), metric='rychly')])
        self.assertEqual(r[0]['metric'], 'rychly')

    def test_malformed_input(self):
        for v in (None, [], [None], ['x'], [{}]):
            self.assertIsInstance(fs.build_capacity_items(v), list)

    def test_prompt_forbids_recomputation(self):
        p = fs.capacity_prompt(fs.build_capacity_items([self.item()]))
        self.assertIn('nepočítej', p.lower())
        self.assertIn('POUZE JSON', p)


class TestHealthSnapshot(unittest.TestCase):
    class FakeState:
        def get_active_issues(self):
            return [{'plugin_name': 'p', 'host': 'h', 'last_line': 'x', 'recurring_count': 3}]

        def get_metric_series(self, hours=168):
            return {}

        def get_fix_attempts(self, limit=500):
            return [{'status': 'failed'}, {'status': 'worked'}]

    class FakeTrend:
        def detect_degradation(self, s):
            return []

        def detect_missing(self, s):
            return []

    def test_snapshot_counts(self):
        snap = fs.build_snapshot(self.FakeState(), self.FakeTrend())
        self.assertEqual(snap['active_issues'], 1)
        self.assertEqual(snap['recurring'], 1)
        self.assertEqual(snap['failed_fixes'], 1)

    def test_broken_source_does_not_hide_rest(self):
        st = self.FakeState()
        st.get_active_issues = lambda: (_ for _ in ()).throw(RuntimeError('db'))
        snap = fs.build_snapshot(st, self.FakeTrend())
        self.assertEqual(snap['active_issues'], 0)
        self.assertEqual(snap['failed_fixes'], 1)

    def test_prompt_restricts_to_given_numbers(self):
        p = fs.health_prompt(fs.build_snapshot(self.FakeState(), self.FakeTrend()))
        self.assertIn('nic si nedomýšlej', p)
        self.assertIn('POUZE JSON', p)

    def test_prompt_with_empty_snapshot(self):
        self.assertIn('POUZE JSON', fs.health_prompt({}))


if __name__ == '__main__':
    unittest.main(verbosity=2)

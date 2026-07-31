"""467/468: Tichá degradace a chybějící signál.

Riziko je v obou směrech: přehlédnutý trend nikoho nevaruje, ale hlášený
šum je horší — po pár planých poplaších si toho nikdo nevšímá.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import trend_detect as td

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def series(values, step_min=60, end=NOW):
    """Body rovnoměrně rozložené dozadu od `end`."""
    n = len(values)
    return [((end - timedelta(minutes=step_min * (n - 1 - i))).isoformat(), v)
            for i, v in enumerate(values)]


class TestLinearTrend(unittest.TestCase):
    def test_perfect_rise(self):
        slope, r2 = td.linear_trend(series([10, 20, 30, 40, 50, 60, 70, 80]))
        self.assertAlmostEqual(slope, 10.0, places=3)
        self.assertAlmostEqual(r2, 1.0, places=3)

    def test_perfect_fall(self):
        slope, _ = td.linear_trend(series([80, 70, 60, 50, 40, 30, 20, 10]))
        self.assertLess(slope, 0)

    def test_flat_has_no_trend(self):
        slope, r2 = td.linear_trend(series([50] * 10))
        self.assertAlmostEqual(slope, 0.0, places=6)

    def test_noise_has_low_r2(self):
        """Kolísání kolem stálé hodnoty není trend."""
        _, r2 = td.linear_trend(series([50, 20, 80, 30, 70, 25, 75, 35, 65, 40]))
        self.assertLess(r2, td.MIN_R2)

    def test_too_few_points(self):
        self.assertIsNone(td.linear_trend(series([1, 2, 3])))

    def test_malformed_points_skipped(self):
        pts = series([10, 20, 30, 40, 50, 60, 70, 80]) + [('nedatum', 5), (NOW.isoformat(), 'text')]
        self.assertIsNotNone(td.linear_trend(pts))

    def test_empty(self):
        for v in (None, [], [(None, None)]):
            self.assertIsNone(td.linear_trend(v))

    def test_all_same_timestamp(self):
        pts = [(NOW.isoformat(), i) for i in range(10)]
        self.assertIsNone(td.linear_trend(pts))


class TestDetectDegradation(unittest.TestCase):
    def test_steady_growth_detected(self):
        r = td.detect_degradation({"disk": series([100, 110, 120, 130, 140, 150, 160, 170])})
        self.assertEqual(len(r), 1)
        self.assertGreater(r[0]['growth_pct'], 15)
        self.assertGreater(r[0]['r2'], td.MIN_R2)

    def test_flat_not_reported(self):
        self.assertEqual(td.detect_degradation({"m": series([100] * 12)}), [])

    def test_decline_not_reported(self):
        """Klesající metrika není degradace."""
        self.assertEqual(td.detect_degradation({"m": series([170, 160, 150, 140, 130, 120, 110, 100])}), [])

    def test_noise_not_reported(self):
        self.assertEqual(
            td.detect_degradation({"m": series([50, 20, 80, 30, 70, 25, 75, 35, 65, 40])}), [])

    def test_tiny_growth_below_threshold(self):
        self.assertEqual(
            td.detect_degradation({"m": series([100, 101, 102, 103, 104, 105, 106, 107])}), [])

    def test_threshold_configurable(self):
        s = {"m": series([100, 101, 102, 103, 104, 105, 106, 107])}
        self.assertTrue(td.detect_degradation(s, min_growth_pct=1.0))

    def test_zero_baseline_skipped(self):
        """Z nuly je růst v procentech nesmysl."""
        self.assertEqual(td.detect_degradation({"m": series([0, 1, 2, 3, 4, 5, 6, 7])}), [])

    def test_sorted_by_growth(self):
        r = td.detect_degradation({
            "pomalu": series([100, 105, 110, 115, 120, 125, 130, 135]),
            "rychle": series([100, 140, 180, 220, 260, 300, 340, 380]),
        })
        self.assertEqual(r[0]['metric'], 'rychle')

    def test_empty_input(self):
        for v in (None, {}):
            self.assertEqual(td.detect_degradation(v), [])


class TestMedianInterval(unittest.TestCase):
    def test_regular_cadence(self):
        ts = [(NOW - timedelta(seconds=60 * i)).isoformat() for i in range(10)]
        self.assertAlmostEqual(td.median_interval_sec(ts), 60.0, places=1)

    def test_one_long_gap_does_not_skew(self):
        """Medián, ne průměr — jedna mezera po restartu by průměr vytáhla."""
        ts = [(NOW - timedelta(seconds=60 * i)).isoformat() for i in range(9)]
        ts.append((NOW - timedelta(hours=10)).isoformat())
        self.assertAlmostEqual(td.median_interval_sec(ts), 60.0, delta=5)

    def test_too_few_samples(self):
        self.assertIsNone(td.median_interval_sec([NOW.isoformat()] * 2))

    def test_garbage(self):
        self.assertIsNone(td.median_interval_sec(['x', 'y', 'z', None, '']))


class TestDetectMissing(unittest.TestCase):
    def _regular(self, count=10, step_sec=60, last_ago_sec=60):
        return [((NOW - timedelta(seconds=last_ago_sec + step_sec * i)).isoformat(), 1.0)
                for i in reversed(range(count))]

    def test_fresh_metric_not_reported(self):
        self.assertEqual(td.detect_missing({"m": self._regular()}, now=NOW), [])

    def test_stopped_metric_reported(self):
        s = {"m": self._regular(last_ago_sec=3600)}     # obvykle po 60 s, ticho hodinu
        r = td.detect_missing(s, now=NOW)
        self.assertEqual(len(r), 1)
        self.assertGreater(r[0]['missed_samples'], 10)

    def test_one_missed_sample_tolerated(self):
        """Jedno vynechané měření není výpadek."""
        self.assertEqual(td.detect_missing({"m": self._regular(last_ago_sec=120)}, now=NOW), [])

    def test_cadence_derived_per_metric(self):
        """Pevný práh by u minutové i hodinové metriky jednu hlásil špatně."""
        s = {
            "rychla": self._regular(step_sec=60, last_ago_sec=600),      # 10 min ticho = výpadek
            "pomala": [((NOW - timedelta(seconds=600 + 3600 * i)).isoformat(), 1.0)
                       for i in reversed(range(10))],                    # 10 min ticho = v pořádku
        }
        names = [x['metric'] for x in td.detect_missing(s, now=NOW)]
        self.assertIn('rychla', names)
        self.assertNotIn('pomala', names)

    def test_sorted_by_silence(self):
        s = {"a": self._regular(last_ago_sec=600), "b": self._regular(last_ago_sec=6000)}
        self.assertEqual(td.detect_missing(s, now=NOW)[0]['metric'], 'b')

    def test_insufficient_history_skipped(self):
        s = {"m": [((NOW - timedelta(hours=5)).isoformat(), 1.0)]}
        self.assertEqual(td.detect_missing(s, now=NOW), [])

    def test_empty_input(self):
        for v in (None, {}):
            self.assertEqual(td.detect_missing(v, now=NOW), [])


class TestDescribe(unittest.TestCase):
    def test_degradation_text(self):
        item = td.detect_degradation({"disk": series([100, 120, 140, 160, 180, 200, 220, 240])})[0]
        text = td.describe_degradation(item)
        self.assertIn('disk', text)
        self.assertIn('%', text)

    def test_missing_text(self):
        s = {"m": [((NOW - timedelta(seconds=3600 + 60 * i)).isoformat(), 1.0)
                   for i in reversed(range(10))]}
        text = td.describe_missing(td.detect_missing(s, now=NOW)[0])
        self.assertIn('m', text)
        self.assertIn('min', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)

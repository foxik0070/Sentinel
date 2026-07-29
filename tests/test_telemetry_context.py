"""449: Korelace issue s telemetrií — AI dřív viděla jen text alertu.

get_telemetry_context() porovná okno kolem incidentu s předchozím obdobím,
takže je vidět SOUBĚH (teplota +12 °C v tu chvíli), ne jen absolutní hodnota.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state_issues


class TestTelemetryContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        conn = sqlite3.connect(self.tmp.name)
        conn.execute("""CREATE TABLE telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME, category TEXT, metric TEXT, value REAL)""")
        self.incident = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
        rows = []
        # baseline (−90 až −30 min): teplota 50, napětí 230
        for i in range(6):
            ts = (self.incident - timedelta(minutes=80 - i * 8)).isoformat()
            rows += [(ts, "Hardware", "temp.rpi5", 50.0),
                     (ts, "HomeAssistant", "sensor.hall_socket_rpi5_voltage", 230.0)]
        # okno incidentu (±30 min): teplota vyskočí na 62, napětí beze změny
        for i in range(6):
            ts = (self.incident - timedelta(minutes=25 - i * 8)).isoformat()
            rows += [(ts, "Hardware", "temp.rpi5", 62.0),
                     (ts, "HomeAssistant", "sensor.hall_socket_rpi5_voltage", 230.0)]
        # metrika jiného hosta — nesmí se objevit
        rows.append((self.incident.isoformat(), "Hardware", "temp.jinyhost", 99.0))
        conn.executemany(
            "INSERT INTO telemetry (timestamp, category, metric, value) VALUES (?,?,?,?)", rows)
        conn.commit()
        conn.close()
        p = patch.object(state_issues, "_get_conn",
                         side_effect=lambda *a, **k: sqlite3.connect(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(lambda: os.unlink(self.tmp.name))

    def _ctx(self, host="rpi5", **kw):
        return state_issues.get_telemetry_context(host, self.incident.isoformat(), **kw)

    def test_finds_metrics_by_hostname_in_metric_name(self):
        metrics = {m["metric"] for m in self._ctx()}
        self.assertIn("temp.rpi5", metrics)
        self.assertIn("sensor.hall_socket_rpi5_voltage", metrics)

    def test_other_hosts_metrics_excluded(self):
        self.assertNotIn("temp.jinyhost", {m["metric"] for m in self._ctx()})

    def test_detects_deviation_against_baseline(self):
        temp = next(m for m in self._ctx() if m["metric"] == "temp.rpi5")
        self.assertEqual(temp["during_avg"], 62.0)
        self.assertEqual(temp["baseline_avg"], 50.0)
        self.assertEqual(temp["delta"], 12.0)
        self.assertEqual(temp["delta_pct"], 24.0)

    def test_stable_metric_has_zero_delta(self):
        volt = next(m for m in self._ctx() if "voltage" in m["metric"])
        self.assertEqual(volt["delta"], 0.0)

    def test_sorted_by_largest_deviation(self):
        """AI má nahoře vidět to, co se skutečně změnilo."""
        self.assertEqual(self._ctx()[0]["metric"], "temp.rpi5")

    def test_min_max_and_sample_count(self):
        temp = next(m for m in self._ctx() if m["metric"] == "temp.rpi5")
        self.assertEqual((temp["min"], temp["max"]), (62.0, 62.0))
        self.assertEqual(temp["samples"], 6)

    def test_max_metrics_limit_respected(self):
        self.assertLessEqual(len(self._ctx(max_metrics=1)), 1)

    def test_unknown_host_returns_empty(self):
        self.assertEqual(self._ctx(host="neexistuje"), [])

    def test_empty_host_returns_empty(self):
        self.assertEqual(state_issues.get_telemetry_context("", self.incident.isoformat()), [])

    def test_invalid_timestamp_does_not_raise(self):
        state_issues.get_telemetry_context("rpi5", "není datum")   # nesmí vyhodit

    def test_naive_timestamp_treated_as_utc(self):
        naive = self.incident.replace(tzinfo=None).isoformat()
        self.assertTrue(state_issues.get_telemetry_context("rpi5", naive))


if __name__ == "__main__":
    unittest.main(verbosity=2)

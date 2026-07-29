"""446: Seskupení issues do incidentů.

Dashboard ukazoval desítky izolovaných alertů, i když šlo často o jeden
incident (výpadek uplinku → 5 hostů → 12 alertů). Na produkčních datech
seskupení srazilo 62 aktivních issues na 13 incidentů.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel.analytics import group_incidents

_T0 = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _issue(offset_sec, host="h1", plugin="p", severity="", key=None):
    ts = (_T0 + timedelta(seconds=offset_sec)).isoformat()
    return {"key": key or f"K|{host}|{offset_sec}", "host": host,
            "plugin_name": plugin, "severity": severity,
            "last_line": "něco se stalo", "first_seen": ts}


class TestGrouping(unittest.TestCase):
    def test_simultaneous_issues_form_one_incident(self):
        inc = group_incidents([_issue(0, "a"), _issue(5, "b"), _issue(10, "c")])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["issue_count"], 3)
        self.assertEqual(inc[0]["hosts"], ["a", "b", "c"])

    def test_distant_issues_are_separate(self):
        inc = group_incidents([_issue(0, "a"), _issue(3600, "b")])
        self.assertEqual(len(inc), 0, "osamocené issues nejsou incident (min_size=2)")

    def test_two_clusters_far_apart(self):
        issues = [_issue(0, "a"), _issue(30, "b"),          # shluk 1
                  _issue(7200, "c"), _issue(7230, "d")]     # shluk 2
        inc = group_incidents(issues)
        self.assertEqual(len(inc), 2)
        self.assertEqual({i["issue_count"] for i in inc}, {2})

    def test_cascade_chains_within_window(self):
        """Kaskáda přichází postupně — pevné okno od prvního by ji rozseklo."""
        issues = [_issue(i * 90, f"h{i}") for i in range(5)]   # à 1,5 min
        inc = group_incidents(issues, window_min=2)
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["issue_count"], 5)

    def test_gap_larger_than_window_breaks_chain(self):
        issues = [_issue(0, "a"), _issue(60, "b"), _issue(400, "c"), _issue(430, "d")]
        inc = group_incidents(issues, window_min=2)
        self.assertEqual(len(inc), 2)

    def test_min_size_filters_small_groups(self):
        issues = [_issue(0, "a"), _issue(10, "b"), _issue(20, "c")]
        self.assertEqual(len(group_incidents(issues, min_size=4)), 0)
        self.assertEqual(len(group_incidents(issues, min_size=3)), 1)

    def test_worst_severity_wins(self):
        inc = group_incidents([_issue(0, "a", severity="low"),
                               _issue(5, "b", severity="critical"),
                               _issue(9, "c", severity="medium")])
        self.assertEqual(inc[0]["severity"], "critical")

    def test_metadata_fields(self):
        inc = group_incidents([_issue(0, "a", "disk"), _issue(60, "b", "net")])[0]
        self.assertEqual(inc["span_min"], 1.0)
        self.assertEqual(inc["plugins"], ["disk", "net"])
        self.assertTrue(inc["id"].startswith("INC-"))
        self.assertEqual(len(inc["issues"]), 2)

    def test_newest_incident_first(self):
        issues = [_issue(0, "a"), _issue(10, "b"),
                  _issue(9000, "c"), _issue(9010, "d")]
        inc = group_incidents(issues)
        self.assertGreater(inc[0]["started_at"], inc[1]["started_at"])

    def test_issues_without_timestamp_are_skipped(self):
        bad = {"key": "x", "host": "h", "plugin_name": "p"}   # bez first_seen
        inc = group_incidents([_issue(0, "a"), _issue(5, "b"), bad])
        self.assertEqual(inc[0]["issue_count"], 2)

    def test_falls_back_to_last_seen(self):
        i = {"key": "x", "host": "h", "plugin_name": "p",
             "last_seen": _T0.isoformat()}
        self.assertEqual(len(group_incidents([i, _issue(5, "b")])), 1)

    def test_naive_timestamp_handled(self):
        naive = {"key": "n", "host": "h", "plugin_name": "p",
                 "first_seen": _T0.replace(tzinfo=None).isoformat()}
        self.assertEqual(len(group_incidents([naive, _issue(5, "b")])), 1)

    def test_empty_and_none_input(self):
        self.assertEqual(group_incidents([]), [])
        self.assertEqual(group_incidents(None), [])

    def test_unsorted_input_is_handled(self):
        """Vstup nemusí přijít seřazený podle času."""
        inc = group_incidents([_issue(60, "c"), _issue(0, "a"), _issue(30, "b")])
        self.assertEqual(len(inc), 1)
        self.assertEqual(inc[0]["issues"][0]["host"], "a")


if __name__ == "__main__":
    unittest.main(verbosity=2)

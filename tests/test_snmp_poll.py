"""327: Aktivní SNMP polling — parser hodnot, delta countery, build argumentů."""
import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import snmp_poll


class TestParseValue(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(snmp_poll._parse_snmp_value("42"), 42.0)
        self.assertEqual(snmp_poll._parse_snmp_value("1.23"), 1.23)
        self.assertEqual(snmp_poll._parse_snmp_value("-5"), -5.0)

    def test_quoted_string(self):
        self.assertEqual(snmp_poll._parse_snmp_value('"1.23"'), 1.23)

    def test_typed_prefixes(self):
        self.assertEqual(snmp_poll._parse_snmp_value("INTEGER: 42"), 42.0)
        self.assertEqual(snmp_poll._parse_snmp_value("Gauge32: 7"), 7.0)
        self.assertEqual(snmp_poll._parse_snmp_value("Counter64: 998877"), 998877.0)
        self.assertEqual(snmp_poll._parse_snmp_value('STRING: "1.5"'), 1.5)

    def test_timeticks_uses_raw_ticks(self):
        # surové ticky v závorce, ne formátovaný čas
        self.assertEqual(
            snmp_poll._parse_snmp_value("Timeticks: (123456) 0:20:34.56"), 123456.0)
        self.assertEqual(snmp_poll._parse_snmp_value("(999) 0:00:09.99"), 999.0)

    def test_value_with_unit(self):
        self.assertEqual(snmp_poll._parse_snmp_value("23.5 C"), 23.5)
        self.assertEqual(snmp_poll._parse_snmp_value("42 %"), 42.0)

    def test_non_numeric_returns_none(self):
        for v in [None, "", "   ", "No Such Object available"]:
            self.assertIsNone(snmp_poll._parse_snmp_value(v), f"{v!r} má být None")


class TestDelta(unittest.TestCase):
    def setUp(self):
        snmp_poll._last_counter.clear()

    def test_first_sample_returns_none(self):
        self.assertIsNone(snmp_poll._apply_delta("h|m", 1000.0, 100.0))

    def test_rate_per_second(self):
        snmp_poll._apply_delta("h|m", 1000.0, 100.0)
        # +500 za 10 s = 50/s
        self.assertEqual(snmp_poll._apply_delta("h|m", 1500.0, 110.0), 50.0)

    def test_counter_wrap_returns_none(self):
        snmp_poll._apply_delta("h|m", 5000.0, 100.0)
        self.assertIsNone(snmp_poll._apply_delta("h|m", 10.0, 110.0))

    def test_keys_are_independent(self):
        snmp_poll._apply_delta("a|m", 100.0, 100.0)
        snmp_poll._apply_delta("b|m", 900.0, 100.0)
        self.assertEqual(snmp_poll._apply_delta("a|m", 200.0, 110.0), 10.0)
        self.assertEqual(snmp_poll._apply_delta("b|m", 1000.0, 110.0), 10.0)


class TestAuthArgs(unittest.TestCase):
    def test_v2c_community(self):
        args = snmp_poll._build_auth_args({"version": "2c", "community": "sekret"})
        self.assertEqual(args, ["-v2c", "-c", "sekret"])

    def test_v1_default_community(self):
        self.assertEqual(snmp_poll._build_auth_args({"version": "1"}),
                         ["-v1", "-c", "public"])

    def test_v3_auth_priv(self):
        args = snmp_poll._build_auth_args({
            "version": "3", "secname": "mon", "auth_protocol": "SHA",
            "auth_pass": "a1", "priv_protocol": "AES", "priv_pass": "p1"})
        self.assertIn("-v3", args)
        self.assertEqual(args[args.index("-l") + 1], "authPriv")
        self.assertEqual(args[args.index("-u") + 1], "mon")
        self.assertEqual(args[args.index("-A") + 1], "a1")
        self.assertEqual(args[args.index("-X") + 1], "p1")

    def test_v3_auth_only(self):
        args = snmp_poll._build_auth_args({
            "version": "3", "secname": "mon", "auth_protocol": "SHA", "auth_pass": "a1"})
        self.assertEqual(args[args.index("-l") + 1], "authNoPriv")


class TestPollTarget(unittest.TestCase):
    def setUp(self):
        snmp_poll._last_counter.clear()

    def test_metrics_are_prefixed_by_name(self):
        target = {"host": "10.0.0.1", "name": "gw",
                  "oids": [{"oid": "1.2.3", "metric": "load1"}]}
        with patch.object(snmp_poll, "_snmpget", return_value="INTEGER: 7"):
            self.assertEqual(snmp_poll.poll_target(target), {"gw.load1": 7.0})

    def test_prefix_falls_back_to_host(self):
        target = {"host": "10.0.0.1", "oids": [{"oid": "1.2.3", "metric": "x"}]}
        with patch.object(snmp_poll, "_snmpget", return_value="5"):
            self.assertEqual(snmp_poll.poll_target(target), {"10.0.0.1.x": 5.0})

    def test_plain_string_oid_entry(self):
        target = {"host": "h", "name": "n", "oids": ["1.3.6.1"]}
        with patch.object(snmp_poll, "_snmpget", return_value="3"):
            self.assertEqual(snmp_poll.poll_target(target), {"n.1_3_6_1": 3.0})

    def test_failed_oid_is_skipped_not_fatal(self):
        target = {"host": "h", "name": "n", "oids": [
            {"oid": "1.1", "metric": "ok"}, {"oid": "9.9", "metric": "bad"}]}
        with patch.object(snmp_poll, "_snmpget", side_effect=["10", None]):
            self.assertEqual(snmp_poll.poll_target(target), {"n.ok": 10.0})

    def test_delta_first_poll_skipped_then_rate(self):
        target = {"host": "h", "name": "n",
                  "oids": [{"oid": "1.1", "metric": "bytes", "delta": True}]}
        with patch.object(snmp_poll, "_snmpget", return_value="1000"):
            with patch.object(snmp_poll.time, "time", return_value=100.0):
                self.assertEqual(snmp_poll.poll_target(target), {})   # 1. vzorek
        with patch.object(snmp_poll, "_snmpget", return_value="1600"):
            with patch.object(snmp_poll.time, "time", return_value=110.0):
                self.assertEqual(snmp_poll.poll_target(target), {"n.bytes": 60.0})


class TestPollOnce(unittest.TestCase):
    def test_saves_to_telemetry_with_category(self):
        cfg = {"targets": [{"host": "h", "name": "n", "category": "SNMP",
                            "oids": [{"oid": "1.1", "metric": "m"}]}]}
        with patch.object(snmp_poll, "_snmpget", return_value="12"):
            with patch.object(snmp_poll.state, "save_telemetry_snapshot") as save:
                n = snmp_poll.poll_once(cfg)
        self.assertEqual(n, 1)
        save.assert_called_once_with("SNMP", {"n.m": 12.0})

    def test_target_without_host_skipped(self):
        with patch.object(snmp_poll.state, "save_telemetry_snapshot") as save:
            self.assertEqual(snmp_poll.poll_once({"targets": [{"name": "x"}]}), 0)
        save.assert_not_called()

    def test_one_broken_target_does_not_kill_cycle(self):
        cfg = {"targets": [
            {"host": "bad", "oids": [{"oid": "1.1", "metric": "m"}]},
            {"host": "good", "name": "g", "oids": [{"oid": "1.1", "metric": "m"}]},
        ]}
        # logger je napojen na DB handler — bez ztlumení by test psal do sentinel_errors
        with patch.object(snmp_poll, "logger"):
            with patch.object(snmp_poll, "_snmpget", return_value="1"):
                with patch.object(snmp_poll.state, "save_telemetry_snapshot",
                                  side_effect=[RuntimeError("db down"), None]) as save:
                    n = snmp_poll.poll_once(cfg)
        self.assertEqual(n, 1)                # druhý cíl prošel
        self.assertEqual(save.call_count, 2)


class TestStartGuards(unittest.TestCase):
    def test_disabled_returns_none(self):
        self.assertIsNone(snmp_poll.start_snmp_poll(
            {"enabled": False, "targets": [{"host": "h"}]}))

    def test_no_targets_returns_none(self):
        self.assertIsNone(snmp_poll.start_snmp_poll({"enabled": True, "targets": []}))

    def test_empty_cfg_returns_none(self):
        self.assertIsNone(snmp_poll.start_snmp_poll({}))


if __name__ == "__main__":
    unittest.main(verbosity=2)

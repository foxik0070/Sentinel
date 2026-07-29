"""Regrese: notifier retry fronta byla mrtvý kód + throttle umlčel ztracené alerty.

Tři chyby, které se skládaly dohromady:
  A) každá _send_* měla vlastní `except → logger.warning`, takže výjimka se
     do _with_retry nikdy nedostala a retry fronta (362) se nespustila;
  B) _throttle[key] se nastavil PŘED odesláním, takže při výpadku Teams/Slack
     se alert ztratil A byl umlčen na 15-60 min;
  C) _throttle dict se nikdy neprořezával (klíč per problem_key).
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import notifier


class TestWithRetry(unittest.TestCase):
    def setUp(self):
        with notifier._retry_lock:
            notifier._retry_queue.clear()

    def test_success_returns_true_and_queues_nothing(self):
        self.assertTrue(notifier._with_retry(lambda: None))
        self.assertEqual(len(notifier._retry_queue), 0)

    def test_failure_returns_false_and_queues_retry(self):
        def boom():
            raise RuntimeError("Slack down")
        self.assertFalse(notifier._with_retry(boom))
        self.assertEqual(len(notifier._retry_queue), 1, "selhání se musí zařadit do retry fronty")

    def test_queued_entry_has_attempt_and_backoff(self):
        def boom():
            raise RuntimeError("x")
        notifier._with_retry(boom)
        fn, args, kwargs, attempt, due = notifier._retry_queue[0]
        self.assertEqual(attempt, 1)
        self.assertGreater(due, time.time(), "retry musí být naplánován do budoucna")


class TestSendersPropagate(unittest.TestCase):
    """Jádro chyby A: _send_* musí výjimku propagovat, ne ji spolknout."""

    def test_slack_failure_propagates(self):
        with patch.object(notifier.config, 'SLACK_ENABLED', True), \
             patch.object(notifier.config, 'SLACK_WEBHOOK_URL', 'http://x', create=True), \
             patch.object(notifier.requests, 'post', side_effect=RuntimeError("net down")), \
             patch.object(notifier, 'logger'):
            with self.assertRaises(Exception):
                notifier._send_slack("t", "b", "infra")

    def test_disabled_channel_does_not_raise(self):
        """Vypnutý kanál není chyba — nesmí plnit retry frontu."""
        with patch.object(notifier.config, 'SLACK_ENABLED', False):
            notifier._send_slack("t", "b", "infra")   # nesmí vyhodit


class TestThrottle(unittest.TestCase):
    def setUp(self):
        notifier._throttle.clear()
        with notifier._retry_lock:
            notifier._retry_queue.clear()

    def _all_channels_fail(self):
        """Všechny kanály selžou → send_notification nesmí alert umlčet."""
        return patch.object(notifier, '_with_retry', return_value=False)

    def _all_channels_ok(self):
        return patch.object(notifier, '_with_retry', return_value=True)

    def test_throttle_released_when_every_channel_fails(self):
        """Jádro chyby B: po totálním selhání musí jít alert poslat znovu."""
        with self._all_channels_fail(), patch.object(notifier, 'send_ha_action'), \
             patch.object(notifier, 'logger'):
            notifier.send_notification("KEY|1", "infra", "host1", "zpráva")
        self.assertNotIn("notify_KEY|1", notifier._throttle,
                         "throttle musí být uvolněn, jinak je alert umlčen na hodiny")

    def test_throttle_held_when_send_succeeds(self):
        with self._all_channels_ok(), patch.object(notifier, 'send_ha_action'):
            notifier.send_notification("KEY|2", "infra", "host1", "zpráva")
        self.assertIn("notify_KEY|2", notifier._throttle)

    def test_second_alert_within_window_is_throttled(self):
        calls = []
        with patch.object(notifier, '_with_retry', side_effect=lambda *a, **k: calls.append(1) or True), \
             patch.object(notifier, 'send_ha_action'):
            notifier.send_notification("KEY|3", "infra", "h", "m")
            first = len(calls)
            notifier.send_notification("KEY|3", "infra", "h", "m")
        self.assertEqual(len(calls), first, "druhý alert v okně se nemá odeslat")

    def test_throttle_dict_is_pruned(self):
        """Chyba C: dict rostl bez limitu s kardinalitou problem_key."""
        old = time.time() - 99999          # dávno mimo nejdelší okno
        for i in range(600):
            notifier._throttle[f"notify_old_{i}"] = old
        with self._all_channels_ok(), patch.object(notifier, 'send_ha_action'):
            notifier.send_notification("KEY|new", "infra", "h", "m")
        self.assertLess(len(notifier._throttle), 600, "staré zámky se musí prořezat")
        self.assertIn("notify_KEY|new", notifier._throttle)


if __name__ == "__main__":
    unittest.main(verbosity=2)

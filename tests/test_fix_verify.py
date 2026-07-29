"""486: Ověření, že oprava fungovala.

Jádro: problém znovu detekovaný PO zásahu znamená, že oprava nezabrala.
Testy hlídají hlavně práci s časem — naivní vs. aware datetime už jednou
způsobily posun o hodiny (viz queue timezone bug).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import fix_verify as fv

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def attempt(applied_min_ago=20, status='pending', verify_min_ago=5, **kw):
    a = {
        'id': 1,
        'problem_key': 'PLUGIN|rpi|disk',
        'command': 'systemctl restart nginx',
        'host': 'rpi',
        'plugin_name': 'storage',
        'status': status,
        'applied_at': (NOW - timedelta(minutes=applied_min_ago)).isoformat(),
        'verify_after': (NOW - timedelta(minutes=verify_min_ago)).isoformat(),
    }
    a.update(kw)
    return a


def problem(last_seen_min_ago=30, **kw):
    p = {'last_seen': (NOW - timedelta(minutes=last_seen_min_ago)).isoformat()}
    p.update(kw)
    return p


class TestParseIso(unittest.TestCase):
    def test_naive_treated_as_utc(self):
        """SQLite datetime('now') vrací naive UTC — nesmí se posunout."""
        got = fv._parse_iso('2026-07-29 12:00:00')
        self.assertEqual(got, NOW)

    def test_offset_preserved(self):
        got = fv._parse_iso('2026-07-29T14:00:00+02:00')
        self.assertEqual(got, NOW)

    def test_zulu_suffix(self):
        self.assertEqual(fv._parse_iso('2026-07-29T12:00:00Z'), NOW)

    def test_datetime_passthrough(self):
        self.assertEqual(fv._parse_iso(NOW), NOW)

    def test_garbage_is_none(self):
        for bad in (None, '', 'nikdy', 123.5, 'not-a-date'):
            self.assertIsNone(fv._parse_iso(bad), repr(bad))


class TestIsDue(unittest.TestCase):
    def test_due_when_time_passed(self):
        self.assertTrue(fv.is_due(attempt(verify_min_ago=5), NOW))

    def test_not_due_before_time(self):
        self.assertFalse(fv.is_due(attempt(verify_min_ago=-30), NOW))

    def test_already_closed_never_due(self):
        for st in ('worked', 'failed', 'uncertain'):
            self.assertFalse(fv.is_due(attempt(status=st), NOW), st)

    def test_missing_data_not_due(self):
        self.assertFalse(fv.is_due({}, NOW))
        self.assertFalse(fv.is_due(None, NOW))
        self.assertFalse(fv.is_due({'status': 'pending'}, NOW))


class TestEvaluate(unittest.TestCase):
    def test_problem_gone_means_worked(self):
        v, d = fv.evaluate(attempt(), None, NOW)
        self.assertEqual(v, fv.VERDICT_WORKED)
        self.assertIn('zmizel', d)

    def test_problem_resolved_means_worked(self):
        v, _ = fv.evaluate(attempt(), problem(resolved=1), NOW)
        self.assertEqual(v, fv.VERDICT_WORKED)

    def test_not_seen_since_fix_means_worked(self):
        """Zásah před 20 min, poslední výskyt před 30 min → klid."""
        v, _ = fv.evaluate(attempt(applied_min_ago=20), problem(last_seen_min_ago=30), NOW)
        self.assertEqual(v, fv.VERDICT_WORKED)

    def test_seen_after_fix_means_failed(self):
        """Zásah před 30 min, problém se ozval před 5 min → nezabralo."""
        v, d = fv.evaluate(attempt(applied_min_ago=30), problem(last_seen_min_ago=5), NOW)
        self.assertEqual(v, fv.VERDICT_FAILED)
        self.assertIn('nezabrala', d)

    def test_boundary_same_timestamp_is_worked(self):
        """Detekce přesně v čase zásahu je ještě ta původní, ne návrat."""
        a = attempt(applied_min_ago=20)
        p = {'last_seen': a['applied_at']}
        self.assertEqual(fv.evaluate(a, p, NOW)[0], fv.VERDICT_WORKED)

    def test_too_old_is_uncertain(self):
        v, d = fv.evaluate(attempt(applied_min_ago=fv.MAX_WAIT_MIN + 1),
                           problem(last_seen_min_ago=999), NOW)
        self.assertEqual(v, fv.VERDICT_UNCERTAIN)
        self.assertIn('dlouho', d)

    def test_missing_applied_at_is_uncertain(self):
        v, _ = fv.evaluate(attempt(applied_at=None), problem(), NOW)
        self.assertEqual(v, fv.VERDICT_UNCERTAIN)

    def test_missing_last_seen_is_uncertain(self):
        v, _ = fv.evaluate(attempt(), {'last_seen': None}, NOW)
        self.assertEqual(v, fv.VERDICT_UNCERTAIN)

    def test_naive_last_seen_not_misread(self):
        """Naive čas z DB nesmí vyjít o hodiny jinak než aware čas zásahu."""
        a = attempt(applied_min_ago=30)
        p = {'last_seen': (NOW - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')}
        self.assertEqual(fv.evaluate(a, p, NOW)[0], fv.VERDICT_FAILED)


class FakeState:
    """Minimální náhrada state vrstvy."""

    def __init__(self, attempts, problems=None):
        self.attempts = attempts
        self.problems = problems or {}
        self.closed = []
        self.feedback = []

    def get_pending_fix_attempts(self):
        return self.attempts

    def get_problem(self, key):
        return self.problems.get(key)

    def close_fix_attempt(self, aid, status, detail=''):
        self.closed.append((aid, status, detail))
        return True

    def record_ai_feedback(self, **kw):
        self.feedback.append(kw)
        return True


class TestRunDueVerifications(unittest.TestCase):
    def test_worked_attempt_closed_and_recorded_applied(self):
        st = FakeState([attempt()], {})           # issue zmizel
        summary = fv.run_due_verifications(st, now=NOW)
        self.assertEqual(summary[fv.VERDICT_WORKED], 1)
        self.assertEqual(st.closed[0][1], fv.VERDICT_WORKED)
        self.assertEqual(st.feedback[0]['rating'], 'applied')

    def test_failed_attempt_recorded_as_negative_feedback(self):
        """486 → 527: co nezabralo, ať se příště nenabízí jako hotovo."""
        st = FakeState([attempt(applied_min_ago=30)],
                       {'PLUGIN|rpi|disk': problem(last_seen_min_ago=5)})
        fv.run_due_verifications(st, now=NOW)
        self.assertEqual(st.feedback[0]['rating'], 'down')
        self.assertEqual(st.feedback[0]['suggestion'], 'systemctl restart nginx')
        self.assertEqual(st.feedback[0]['username'], 'auto-verify')

    def test_uncertain_does_not_pollute_feedback(self):
        st = FakeState([attempt(applied_min_ago=fv.MAX_WAIT_MIN + 10)],
                       {'PLUGIN|rpi|disk': problem()})
        fv.run_due_verifications(st, now=NOW)
        self.assertEqual(st.closed[0][1], fv.VERDICT_UNCERTAIN)
        self.assertEqual(st.feedback, [])

    def test_not_due_is_skipped(self):
        st = FakeState([attempt(verify_min_ago=-60)], {})
        fv.run_due_verifications(st, now=NOW)
        self.assertEqual(st.closed, [])

    def test_notify_called_only_on_failure(self):
        calls = []
        st = FakeState([attempt(applied_min_ago=30)],
                       {'PLUGIN|rpi|disk': problem(last_seen_min_ago=5)})
        fv.run_due_verifications(st, notify=lambda a, d: calls.append(a), now=NOW)
        self.assertEqual(len(calls), 1)

        calls.clear()
        st2 = FakeState([attempt()], {})
        fv.run_due_verifications(st2, notify=lambda a, d: calls.append(a), now=NOW)
        self.assertEqual(calls, [])

    def test_notify_failure_does_not_break_loop(self):
        def boom(a, d):
            raise RuntimeError('teams down')
        st = FakeState([attempt(applied_min_ago=30)],
                       {'PLUGIN|rpi|disk': problem(last_seen_min_ago=5)})
        fv.run_due_verifications(st, notify=boom, now=NOW)
        self.assertEqual(st.closed[0][1], fv.VERDICT_FAILED)   # pokus přesto uzavřen

    def test_get_problem_error_skips_attempt(self):
        st = FakeState([attempt()], {})
        st.get_problem = lambda k: (_ for _ in ()).throw(RuntimeError('db'))
        fv.run_due_verifications(st, now=NOW)
        self.assertEqual(st.closed, [])

    def test_feedback_error_does_not_block_close(self):
        st = FakeState([attempt()], {})
        st.record_ai_feedback = lambda **kw: (_ for _ in ()).throw(RuntimeError('db'))
        fv.run_due_verifications(st, now=NOW)
        self.assertEqual(st.closed[0][1], fv.VERDICT_WORKED)


class TestWaitUntil(unittest.TestCase):
    def test_default_wait(self):
        got = fv._parse_iso(fv.wait_until(now=NOW))
        self.assertEqual(got, NOW + timedelta(minutes=fv.DEFAULT_WAIT_MIN))

    def test_custom_wait(self):
        self.assertEqual(fv._parse_iso(fv.wait_until(60, NOW)), NOW + timedelta(minutes=60))

    def test_clamped_to_bounds(self):
        self.assertEqual(fv._parse_iso(fv.wait_until(0, NOW)), NOW + timedelta(minutes=1))
        self.assertEqual(fv._parse_iso(fv.wait_until(99999, NOW)),
                         NOW + timedelta(minutes=fv.MAX_WAIT_MIN))

    def test_garbage_falls_back_to_default(self):
        for bad in ('abc', None, [], {}):
            self.assertEqual(fv._parse_iso(fv.wait_until(bad, NOW)),
                             NOW + timedelta(minutes=fv.DEFAULT_WAIT_MIN), repr(bad))


class TestSummarize(unittest.TestCase):
    def test_empty(self):
        s = fv.summarize([])
        self.assertIsNone(s['success_pct'])
        self.assertEqual(s['total'], 0)

    def test_success_ratio(self):
        s = fv.summarize([{'status': 'worked'}] * 3 + [{'status': 'failed'}])
        self.assertEqual(s['success_pct'], 75.0)

    def test_pending_excluded_from_ratio(self):
        s = fv.summarize([{'status': 'worked'}, {'status': 'failed'},
                          {'status': 'pending'}, {'status': 'uncertain'}])
        self.assertEqual(s['success_pct'], 50.0)
        self.assertEqual(s['total'], 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""499: Eskalace s kontextem.

Podstata: kdo problém přebírá, musí vidět, co už selhalo. A eskalace se
nesmí ztratit kvůli nedostupné AI nebo rozbitému zdroji dat — proto je
většina testů o odolnosti, ne o formátování.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import escalation as esc

NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)

ISSUE = {
    'key': 'PLUGIN|rpi|disk',
    'host': 'rpi',
    'plugin_name': 'storage',
    'last_line': 'disk usage 97%',
    'last_seen': (NOW - timedelta(minutes=5)).isoformat(),
    'severity': 'medium',
}


class FakeState:
    def __init__(self, attempts=None, issues=None, telemetry=None):
        self._attempts = attempts if attempts is not None else []
        self._issues = issues if issues is not None else []
        self._telemetry = telemetry

    def get_fix_attempts(self, key, limit=10):
        return self._attempts

    def get_active_issues(self):
        return self._issues

    def get_telemetry_context(self, host, at_iso):
        return self._telemetry


def attempt(cmd='systemctl restart nginx', status='failed'):
    return {'command': cmd, 'status': status}


class TestAgeHours(unittest.TestCase):
    def test_naive_treated_as_utc(self):
        self.assertAlmostEqual(
            esc._age_hours('2026-07-29 10:00:00', NOW), 2.0, places=3)

    def test_offset_respected(self):
        self.assertAlmostEqual(
            esc._age_hours('2026-07-29T12:00:00+02:00', NOW), 2.0, places=3)

    def test_garbage_is_none(self):
        for bad in (None, '', 'nikdy', []):
            self.assertIsNone(esc._age_hours(bad, NOW), repr(bad))


class TestCollect(unittest.TestCase):
    def test_gathers_all_sources(self):
        st = FakeState(
            attempts=[attempt()],
            issues=[ISSUE, {'key': 'other', 'host': 'rpi', 'plugin_name': 'net'}],
            telemetry={'metrics': [{'metric': 'temp', 'delta_pct': 30.0}]})
        ctx = esc.collect(st, ISSUE, NOW)
        self.assertEqual(len(ctx['attempts']), 1)
        self.assertEqual(len(ctx['siblings']), 1)
        self.assertEqual(len(ctx['metrics']), 1)

    def test_own_issue_excluded_from_siblings(self):
        st = FakeState(issues=[ISSUE])
        self.assertEqual(esc.collect(st, ISSUE, NOW)['siblings'], [])

    def test_other_host_excluded_from_siblings(self):
        st = FakeState(issues=[{'key': 'x', 'host': 'jiny', 'plugin_name': 'net'}])
        self.assertEqual(esc.collect(st, ISSUE, NOW)['siblings'], [])

    def test_failed_attempts_counted(self):
        st = FakeState(attempts=[attempt(status='failed'), attempt('a', 'worked'),
                                 attempt('b', 'failed')])
        self.assertEqual(esc.collect(st, ISSUE, NOW)['attempts_failed'], 2)

    def test_lists_are_capped(self):
        st = FakeState(
            attempts=[attempt(f'c{i}') for i in range(20)],
            issues=[{'key': f'k{i}', 'host': 'rpi', 'plugin_name': 'p'} for i in range(20)],
            telemetry={'metrics': [{'metric': f'm{i}'} for i in range(20)]})
        ctx = esc.collect(st, ISSUE, NOW)
        self.assertEqual(len(ctx['attempts']), esc.MAX_ATTEMPTS_SHOWN)
        self.assertEqual(len(ctx['siblings']), esc.MAX_SIBLINGS_SHOWN)
        self.assertEqual(len(ctx['metrics']), esc.MAX_METRICS_SHOWN)
        self.assertEqual(ctx['attempts_total'], 20)      # počet se neztratí

    def test_broken_source_does_not_lose_the_rest(self):
        """Jeden rozbitý zdroj nesmí připravit příjemce o zbytek kontextu."""
        st = FakeState(attempts=[attempt()], issues=[])
        st.get_telemetry_context = lambda h, a: (_ for _ in ()).throw(RuntimeError('db'))
        ctx = esc.collect(st, ISSUE, NOW)
        self.assertEqual(len(ctx['attempts']), 1)
        self.assertEqual(ctx['metrics'], [])

    def test_all_sources_broken_still_returns_shape(self):
        st = FakeState()
        for name in ('get_fix_attempts', 'get_active_issues', 'get_telemetry_context'):
            setattr(st, name, lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x')))
        ctx = esc.collect(st, ISSUE, NOW)
        self.assertEqual(ctx['attempts'], [])
        self.assertEqual(ctx['siblings'], [])

    def test_empty_issue_does_not_raise(self):
        self.assertIsInstance(esc.collect(FakeState(), {}, NOW), dict)


class TestFormatMessage(unittest.TestCase):
    def test_failed_attempt_is_shown(self):
        ctx = {'attempts': [attempt('systemctl restart nginx', 'failed')],
               'attempts_total': 1}
        msg = esc.format_message(ISSUE, ctx, 26.0, 'high')
        self.assertIn('systemctl restart nginx', msg)
        self.assertIn('❌', msg)

    def test_says_when_nothing_tried(self):
        msg = esc.format_message(ISSUE, {}, 26.0, 'high')
        self.assertIn('nic nezkusilo', msg)

    def test_core_facts_present(self):
        msg = esc.format_message(ISSUE, {}, 26.5, 'critical')
        self.assertIn('rpi', msg)
        self.assertIn('storage', msg)
        self.assertIn('26.5', msg)
        self.assertIn('CRITICAL', msg)

    def test_html_in_log_line_is_escaped(self):
        """Obsah logu je cizí text — nesmí rozbít ani ovlivnit zprávu."""
        evil = dict(ISSUE, last_line='<script>alert(1)</script>')
        msg = esc.format_message(evil, {}, 1.0, 'high')
        self.assertNotIn('<script>', msg)
        self.assertIn('&lt;script&gt;', msg)

    def test_metrics_rendered_with_sign(self):
        ctx = {'metrics': [{'metric': 'temp', 'delta_pct': 42.0}]}
        self.assertIn('+42%', esc.format_message(ISSUE, ctx, 1.0, 'high'))

    def test_metric_without_delta_still_shown(self):
        ctx = {'metrics': [{'metric': 'temp', 'delta_pct': None}]}
        self.assertIn('temp', esc.format_message(ISSUE, ctx, 1.0, 'high'))

    def test_ai_summary_included_when_present(self):
        msg = esc.format_message(ISSUE, {}, 1.0, 'high', ai_summary='Zkus vyměnit disk.')
        self.assertIn('Zkus vyměnit disk.', msg)

    def test_no_ai_marker_when_absent(self):
        self.assertNotIn('<b>AI:</b>', esc.format_message(ISSUE, {}, 1.0, 'high'))

    def test_recurring_shown(self):
        self.assertIn('7×', esc.format_message(ISSUE, {'recurring': 7}, 1.0, 'high'))


class TestAiPrompt(unittest.TestCase):
    def test_lists_failed_attempts(self):
        ctx = {'attempts': [attempt('restart nginx', 'failed')]}
        p = esc.ai_prompt(ISSUE, ctx, 26.0)
        self.assertIn('restart nginx', p)
        self.assertIn('failed', p)
        self.assertIn('Neopakuj', p)

    def test_handles_no_attempts(self):
        self.assertIn('nic', esc.ai_prompt(ISSUE, {}, 26.0))

    def test_includes_issue_and_age(self):
        p = esc.ai_prompt(ISSUE, {}, 26.0)
        self.assertIn('disk usage 97%', p)
        self.assertIn('26.0', p)


class TestBuild(unittest.TestCase):
    def test_ai_summary_used(self):
        st = FakeState(attempts=[attempt()])
        msg = esc.build(st, ISSUE, 26.0, 'high', ask_ai=lambda p: 'Disk umírá.', now=NOW)
        self.assertIn('Disk umírá.', msg)

    def test_ai_failure_does_not_block_escalation(self):
        """Nedostupný model nesmí eskalaci zahodit — to je horší než chybějící shrnutí."""
        st = FakeState(attempts=[attempt()])
        def boom(p):
            raise RuntimeError('ollama down')
        msg = esc.build(st, ISSUE, 26.0, 'high', ask_ai=boom, now=NOW)
        self.assertIn('rpi', msg)
        self.assertIn('systemctl restart nginx', msg)

    def test_empty_ai_answer_omits_section(self):
        st = FakeState()
        msg = esc.build(st, ISSUE, 26.0, 'high', ask_ai=lambda p: '   ', now=NOW)
        self.assertNotIn('<b>AI:</b>', msg)

    def test_works_without_ai_at_all(self):
        msg = esc.build(FakeState(attempts=[attempt()]), ISSUE, 26.0, 'high', now=NOW)
        self.assertIn('systemctl restart nginx', msg)


if __name__ == '__main__':
    unittest.main(verbosity=2)

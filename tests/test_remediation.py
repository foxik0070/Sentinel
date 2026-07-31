"""488: Postupná remediace — nejmenší zásah první.

Bezpečnostní jádro: žebřík nesmí jít přeskočit. Kdyby šel, AI by u prvního
problému navrhla reboot — což je přesně to, čemu má tenhle mechanismus
zabránit.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import remediation as rem

PARAMS = {"service": "nginx", "host": "rpi"}


def att(cmd, status='failed'):
    return {"command": cmd, "status": status}


class TestCatalogSanity(unittest.TestCase):
    def test_first_step_is_always_readonly(self):
        """Než se do něčeho sáhne, musí se to nejdřív změřit."""
        for name, ladder in rem.LADDERS.items():
            self.assertTrue(ladder['steps'][0].get('readonly'),
                            f"{name} začíná zásahem, ne pozorováním")

    def test_levels_are_ascending(self):
        for name, ladder in rem.LADDERS.items():
            levels = [s['level'] for s in ladder['steps']]
            self.assertEqual(levels, sorted(levels), name)

    def test_destructive_steps_require_human(self):
        """reboot a restart sítě se nesmí spustit bez člověka."""
        for name, ladder in rem.LADDERS.items():
            for s in ladder['steps']:
                if 'reboot' in s['cmd'] or 'restart networking' in s['cmd']:
                    self.assertTrue(s.get('requires_human'),
                                    f"{name}: {s['cmd']} nevyžaduje člověka")

    def test_readonly_steps_never_require_human(self):
        for name, ladder in rem.LADDERS.items():
            for s in ladder['steps']:
                if s.get('readonly'):
                    self.assertFalse(s.get('requires_human'), f"{name}: {s['cmd']}")

    def test_every_step_has_description(self):
        for name, ladder in rem.LADDERS.items():
            for s in ladder['steps']:
                self.assertTrue(s.get('desc'), f"{name}: {s['cmd']}")

    def test_reload_comes_before_restart(self):
        """Nejdřív bezvýpadkové načtení konfigurace, teprve pak restart."""
        steps = [s['cmd'] for s in rem.LADDERS['service_failed']['steps']]
        self.assertLess(steps.index('systemctl reload {service}'),
                        steps.index('systemctl restart {service}'))

    def test_restart_comes_before_reboot(self):
        steps = [s['cmd'] for s in rem.LADDERS['service_failed']['steps']]
        self.assertLess(steps.index('systemctl restart {service}'), steps.index('reboot'))


class TestNextStep(unittest.TestCase):
    def test_starts_at_lowest_level(self):
        s = rem.next_step('service_failed', [], PARAMS)
        self.assertEqual(s['level'], 1)
        self.assertTrue(s['readonly'])

    def test_advances_after_failure(self):
        first = rem.next_step('service_failed', [], PARAMS)
        second = rem.next_step('service_failed', [att(first['command'])], PARAMS)
        self.assertGreater(second['level'], first['level'])

    def test_stops_when_something_worked(self):
        """Když zásah zabral, není proč jít výš."""
        s = rem.next_step('service_failed',
                          [att('systemctl reload nginx', 'worked')], PARAMS)
        self.assertIsNone(s)

    def test_waits_while_verification_pending(self):
        """Eskalovat před ověřením by restartovalo něco, co se možná spravuje."""
        s = rem.next_step('service_failed',
                          [att('systemctl reload nginx', 'pending')], PARAMS)
        self.assertIsNone(s)

    def test_cannot_skip_to_reboot(self):
        """Jádro 488: bez vyčerpání nižších stupňů se reboot nenabídne."""
        s = rem.next_step('service_failed', [], PARAMS)
        self.assertNotIn('reboot', s['command'])

    def test_reboot_only_after_all_lower_failed(self):
        tried = []
        seen = []
        for _ in range(10):
            s = rem.next_step('service_failed', tried, PARAMS)
            if s is None:
                break
            seen.append(s['command'])
            tried.append(att(s['command']))
        self.assertEqual(seen[-1], 'reboot')
        self.assertTrue(all('reboot' not in c for c in seen[:-1]))

    def test_reboot_flagged_for_human(self):
        tried = [att(s['command']) for s in rem.plan('service_failed', PARAMS)[:-1]]
        s = rem.next_step('service_failed', tried, PARAMS)
        self.assertEqual(s['command'], 'reboot')
        self.assertTrue(s['requires_human'])

    def test_ladder_exhausted_returns_none(self):
        tried = [att(s['command']) for s in rem.plan('service_failed', PARAMS)]
        self.assertIsNone(rem.next_step('service_failed', tried, PARAMS))

    def test_unknown_situation(self):
        for bad in ('vymyslena', '', None, 'reboot'):
            self.assertIsNone(rem.next_step(bad, [], PARAMS))

    def test_steps_needing_param_skipped_without_it(self):
        """Bez jména služby se kroky s parametrem přeskočí, ne nasadí naprázdno."""
        s = rem.next_step('service_failed', [], {})
        self.assertIsNone(s)

    def test_param_is_substituted(self):
        s = rem.next_step('service_failed', [], {"service": "sshd"})
        self.assertIn('sshd', s['command'])
        self.assertNotIn('{service}', s['command'])

    def test_param_injection_rejected(self):
        for bad in ('nginx; rm -rf /', 'a && id', '$(whoami)', '`id`', 'a b'):
            self.assertIsNone(rem.next_step('service_failed', [], {"service": bad}),
                              f"propuštěno: {bad}")

    def test_malformed_attempts_do_not_raise(self):
        for bad in (None, [], [None], [{}], [{'command': None}], ['text']):
            try:
                rem.next_step('service_failed', bad, PARAMS)
            except Exception as e:
                self.fail(f"{bad!r} → {type(e).__name__}: {e}")

    def test_disk_full_ladder_has_no_param(self):
        s = rem.next_step('disk_full', [], {})
        self.assertIsNotNone(s)
        self.assertEqual(s['level'], 1)


class TestPlan(unittest.TestCase):
    def test_full_ladder_returned(self):
        p = rem.plan('service_failed', PARAMS)
        self.assertGreaterEqual(len(p), 4)
        self.assertEqual([x['level'] for x in p], sorted(x['level'] for x in p))

    def test_unknown_situation_empty(self):
        self.assertEqual(rem.plan('nesmysl', PARAMS), [])

    def test_no_placeholders_left(self):
        for name in rem.LADDERS:
            for step in rem.plan(name, PARAMS):
                self.assertNotIn('{', step['command'], f"{name}: {step['command']}")


class TestPrompt(unittest.TestCase):
    def test_lists_situations_not_commands(self):
        """Model nesmí vidět příkazy — nemá je vybírat."""
        p = rem.plan_prompt('rpi', 'storage', 'disk plný')
        for sid in rem.LADDERS:
            self.assertIn(sid, p)
        for forbidden in ('reboot', 'systemctl restart', 'vacuum-time'):
            self.assertNotIn(forbidden, p, f"prompt prozrazuje příkaz: {forbidden}")

    def test_includes_problem(self):
        p = rem.plan_prompt('rpi', 'storage', 'disk plný')
        self.assertIn('rpi', p)
        self.assertIn('disk plný', p)



class TestNormalizeSituation(unittest.TestCase):
    """Malé modely opisují formát z promptu (`id="x"`) místo holého ID."""

    def test_plain_id(self):
        self.assertEqual(rem.normalize_situation('disk_full'), 'disk_full')

    def test_id_prefix_stripped(self):
        for v in ('id="host_unreachable"', "id='host_unreachable'",
                  'ID="HOST_UNREACHABLE"', '  id="host_unreachable"  '):
            self.assertEqual(rem.normalize_situation(v), 'host_unreachable', v)

    def test_quotes_stripped(self):
        for v in ('"disk_full"', "'disk_full'", '`disk_full`'):
            self.assertEqual(rem.normalize_situation(v), 'disk_full', v)

    def test_garbage_stays_unknown(self):
        for v in (None, '', 'nesmysl', 'id=""'):
            self.assertIsNone(rem.next_step(v, [], PARAMS), repr(v))

    def test_next_step_accepts_model_format(self):
        """Regrese: přesně to, co vrátila llama3.2 na ostrém issue."""
        s = rem.next_step('id="host_unreachable"', [], {"host": "rpizero2"})
        self.assertIsNotNone(s)
        self.assertEqual(s['level'], 1)
        self.assertIn('rpizero2', s['command'])

if __name__ == '__main__':
    unittest.main(verbosity=2)

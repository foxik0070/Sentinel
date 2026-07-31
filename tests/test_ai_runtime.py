"""517/518/519/521/522/523/525: běhové vlastnosti AI.

Model, který na stejnou otázku odpoví pokaždé jinak, se nedá použít
k rozhodování — proto se konflikt hlásí, ne tiše přepisuje.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import ai_runtime as rt

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


class TestRefusal(unittest.TestCase):
    def test_instruction_permits_not_knowing(self):
        i = rt.refusal_instruction()
        self.assertIn('NEHÁDEJ', i)
        self.assertIn('NEVÍM', i)

    def test_detects_czech_refusal(self):
        for t in ('Nevím, chybí mi log služby', 'Nemám dost údajů',
                  'Nelze určit bez telemetrie'):
            self.assertTrue(rt.is_refusal(t), t)

    def test_detects_english_refusal(self):
        for t in ("I don't know", 'Insufficient data to answer'):
            self.assertTrue(rt.is_refusal(t), t)

    def test_normal_answer_not_refusal(self):
        self.assertFalse(rt.is_refusal('Disk je plný, smaž staré logy.'))

    def test_missing_data_listed(self):
        note = rt.missing_data_note({'telemetrie': None, 'log': 'ok', 'topologie': ''})
        self.assertIn('telemetrie', note)
        self.assertIn('topologie', note)
        self.assertNotIn('log,', note)

    def test_missing_note_warns_against_assuming_ok(self):
        """„Žádné chyby v logu" a „log jsem nedostal" nesmí splynout."""
        self.assertIn('nepředpokládej', rt.missing_data_note({'log': None}))

    def test_no_note_when_all_available(self):
        self.assertEqual(rt.missing_data_note({'a': 1, 'b': 'x'}), '')


class TestLanguage(unittest.TestCase):
    def test_czech_default(self):
        self.assertIn('česky', rt.language_instruction())

    def test_english(self):
        self.assertIn('English', rt.language_instruction('en'))

    def test_unknown_falls_back_to_english(self):
        self.assertIn('English', rt.language_instruction('de'))


class TestFewshot(unittest.TestCase):
    INC = [{'problem': 'disk full on /var', 'solution': 'journalctl --vacuum-time=7d',
            'plugin_name': 'storage'},
           {'problem': 'nginx down', 'solution': 'systemctl restart nginx',
            'plugin_name': 'services'}]

    def test_examples_included(self):
        out = rt.build_fewshot(self.INC)
        self.assertIn('journalctl', out)
        self.assertIn('ověřené', out)

    def test_filtered_by_plugin(self):
        out = rt.build_fewshot(self.INC, plugin='storage')
        self.assertIn('journalctl', out)
        self.assertNotIn('nginx', out)

    def test_capped(self):
        many = [{'problem': f'p{i}', 'solution': f's{i}'} for i in range(20)]
        self.assertLessEqual(rt.build_fewshot(many).count('- Problém:'), rt.MAX_FEWSHOT)

    def test_incomplete_examples_skipped(self):
        """Příklad bez řešení by model nic nenaučil."""
        self.assertEqual(rt.build_fewshot([{'problem': 'x'}, {'solution': 'y'}]), '')

    def test_empty(self):
        for v in (None, [], [{}]):
            self.assertEqual(rt.build_fewshot(v), '')


class TestRouting(unittest.TestCase):
    def test_simple_task_goes_fast(self):
        for t in ('classify', 'severity', 'extract'):
            self.assertEqual(rt.route(t), 'fast', t)

    def test_complex_task_goes_strong(self):
        for t in ('correlate', 'analyze', 'causal_chain', 'diagnose'):
            self.assertEqual(rt.route(t), 'strong', t)

    def test_huge_prompt_upgrades_simple_task(self):
        """Malý model velký kontext neudrží."""
        self.assertEqual(rt.route('classify', prompt_len=50000), 'strong')

    def test_unknown_task_defaults_to_strong(self):
        self.assertEqual(rt.route('nevimco'), 'strong')

    def test_length_alone_does_not_downgrade(self):
        self.assertEqual(rt.route('analyze', prompt_len=10), 'strong')


class TestTokenBudget(unittest.TestCase):
    def setUp(self):
        rt.reset_token_budget()

    def tearDown(self):
        rt.reset_token_budget()

    def test_budget_available_initially(self):
        self.assertTrue(rt.token_budget_ok('classify', now=NOW))

    def test_budget_exhausted(self):
        rt.record_tokens('classify', 999999, now=NOW)
        self.assertFalse(rt.token_budget_ok('classify', now=NOW))

    def test_old_usage_expires(self):
        rt.record_tokens('classify', 999999, now=NOW - timedelta(hours=2))
        self.assertTrue(rt.token_budget_ok('classify', now=NOW))

    def test_budgets_are_per_task(self):
        """Zacyklení v jedné úloze nesmí zastavit ostatní."""
        rt.record_tokens('classify', 999999, now=NOW)
        self.assertTrue(rt.token_budget_ok('analyze', now=NOW))

    def test_left_and_used_reported(self):
        rt.record_tokens('classify', 5000, now=NOW)
        left, used, cap = rt.token_budget_left('classify', now=NOW)
        self.assertEqual(used, 5000)
        self.assertEqual(left, cap - 5000)


class TestCache(unittest.TestCase):
    def setUp(self):
        rt.cache_clear()

    def tearDown(self):
        rt.cache_clear()

    def test_hit_after_put(self):
        rt.cache_put('classify', 'otazka', 'odpoved', now=NOW)
        self.assertEqual(rt.cache_get('classify', 'otazka', now=NOW), 'odpoved')

    def test_miss_when_absent(self):
        self.assertIsNone(rt.cache_get('classify', 'nic', now=NOW))

    def test_expires_after_ttl(self):
        rt.cache_put('classify', 'q', 'a', now=NOW)
        self.assertIsNone(rt.cache_get('classify', 'q', now=NOW + timedelta(hours=2)))

    def test_whitespace_normalised(self):
        rt.cache_put('classify', 'jak  je  to', 'a', now=NOW)
        self.assertEqual(rt.cache_get('classify', 'JAK je to', now=NOW), 'a')

    def test_different_task_separate(self):
        rt.cache_put('classify', 'q', 'a', now=NOW)
        self.assertIsNone(rt.cache_get('analyze', 'q', now=NOW))

    def test_bounded(self):
        for i in range(rt.MAX_CACHE_ENTRIES + 50):
            rt.cache_put('t', f'q{i}', 'a', now=NOW + timedelta(seconds=i))
        self.assertLessEqual(len(rt._cache), rt.MAX_CACHE_ENTRIES)

    def test_stats(self):
        rt.cache_put('t', 'q', 'a', now=NOW)
        rt.cache_get('t', 'q', now=NOW)
        rt.cache_get('t', 'jine', now=NOW)
        s = rt.cache_stats()
        self.assertEqual(s['hits'], 1)
        self.assertEqual(s['misses'], 1)


class TestConsistency(unittest.TestCase):
    """518: model, který si protiřečí, se nedá použít k rozhodování."""

    def setUp(self):
        rt.cache_clear()

    def tearDown(self):
        rt.cache_clear()

    def test_contradiction_reported(self):
        rt.cache_put('t', 'q', 'Disk je plný, smaž logy', now=NOW)
        c = rt.cache_put('t', 'q', 'Síť je přetížená, zkontroluj switch', now=NOW)
        self.assertIsNotNone(c)
        self.assertIn('jinak', c['note'])

    def test_rewording_is_not_contradiction(self):
        rt.cache_put('t', 'q', 'Disk je plný, smaž staré logy', now=NOW)
        c = rt.cache_put('t', 'q', 'Smaž staré logy, disk je plný', now=NOW)
        self.assertIsNone(c)

    def test_identical_not_conflict(self):
        rt.cache_put('t', 'q', 'stejná odpověď', now=NOW)
        self.assertIsNone(rt.cache_put('t', 'q', 'stejná odpověď', now=NOW))

    def test_first_answer_no_conflict(self):
        self.assertIsNone(rt.cache_put('t', 'nova', 'odpoved', now=NOW))

    def test_conflict_counted(self):
        rt.cache_put('t', 'q', 'aaa bbbb cccc', now=NOW)
        rt.cache_put('t', 'q', 'xxxx yyyy zzzz', now=NOW)
        self.assertEqual(rt.cache_stats()['conflicts'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

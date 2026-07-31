"""508/510: Kontextové okno podle úlohy + RAG relevance filtr."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import ai_profiles as ap


class TestProfiles(unittest.TestCase):
    def test_all_profiles_complete(self):
        for name, p in ap.PROFILES.items():
            for key in ('num_ctx', 'max_tokens', 'temperature'):
                self.assertIn(key, p, f"{name} nemá {key}")

    def test_classify_is_smallest(self):
        """Zařazení do kategorie nepotřebuje velké okno."""
        smallest = min(ap.PROFILES.values(), key=lambda p: p['num_ctx'])
        self.assertEqual(ap.PROFILES['classify'], smallest)

    def test_analyze_is_largest(self):
        largest = max(ap.PROFILES.values(), key=lambda p: p['num_ctx'])
        self.assertEqual(ap.PROFILES['analyze'], largest)

    def test_machine_read_profiles_are_cold(self):
        """U strojově zpracovávaných odpovědí nechceme kreativitu."""
        for name in ('classify', 'extract', 'correlate', 'analyze'):
            self.assertLessEqual(ap.PROFILES[name]['temperature'], 0.1, name)

    def test_extract_allows_full_json(self):
        """Krátký limit usekával JSON — viz 462."""
        self.assertGreaterEqual(ap.PROFILES['extract']['max_tokens'], 300)

    def test_for_task_returns_copy(self):
        a = ap.for_task('classify')
        a['num_ctx'] = 999999
        self.assertNotEqual(ap.PROFILES['classify']['num_ctx'], 999999)

    def test_unknown_profile_falls_back(self):
        for bad in ('vymyslene', '', None, 123):
            self.assertEqual(ap.for_task(bad), ap.PROFILES[ap.DEFAULT_PROFILE])

    def test_overrides_applied(self):
        self.assertEqual(ap.for_task('classify', max_tokens=999)['max_tokens'], 999)

    def test_none_overrides_ignored(self):
        self.assertEqual(ap.for_task('classify', max_tokens=None)['max_tokens'],
                         ap.PROFILES['classify']['max_tokens'])

    def test_case_insensitive(self):
        self.assertEqual(ap.for_task('CLASSIFY'), ap.PROFILES['classify'])


class TestFits(unittest.TestCase):
    def test_short_prompt_fits_small(self):
        self.assertTrue(ap.fits('classify', 'ahoj'))

    def test_long_prompt_does_not_fit_small(self):
        self.assertFalse(ap.fits('classify', 'x' * 100000))

    def test_empty_prompt(self):
        for v in ('', None):
            self.assertTrue(ap.fits('classify', v))


class TestPickForPrompt(unittest.TestCase):
    def test_short_prompt_gets_small_profile(self):
        self.assertEqual(ap.pick_for_prompt('krátký dotaz'), 'classify')

    def test_respects_preferred_as_minimum(self):
        self.assertEqual(ap.pick_for_prompt('krátký', preferred='summarize'), 'summarize')

    def test_escalates_when_prompt_too_big(self):
        """Usekaný kontext dá horší odpověď než pomalejší běh."""
        big = 'x' * 6000                      # ~1500 tokenů
        self.assertEqual(ap.pick_for_prompt(big, preferred='classify'), 'summarize')

    def test_huge_prompt_gets_largest(self):
        self.assertEqual(ap.pick_for_prompt('x' * 999999), 'analyze')


class TestRagDistanceFilter(unittest.TestCase):
    """510: nesouvisející chunk zmate model víc, než by prázdno uškodilo."""

    def setUp(self):
        from sentinel.rag import filter_by_distance
        self.f = filter_by_distance

    def test_close_documents_kept(self):
        res = {'documents': [['a', 'b']], 'distances': [[0.1, 0.2]]}
        docs, _ = self.f(res, 0.6)
        self.assertEqual(docs, ['a', 'b'])

    def test_distant_documents_dropped(self):
        res = {'documents': [['blizky', 'daleky']], 'distances': [[0.1, 0.95]]}
        docs, _ = self.f(res, 0.6)
        self.assertEqual(docs, ['blizky'])

    def test_all_distant_gives_empty(self):
        res = {'documents': [['x', 'y']], 'distances': [[0.9, 0.99]]}
        docs, dists = self.f(res, 0.6)
        self.assertEqual(docs, [])
        self.assertIsNotNone(dists)          # volající pozná, že něco bylo

    def test_boundary_is_inclusive(self):
        res = {'documents': [['x']], 'distances': [[0.6]]}
        self.assertEqual(self.f(res, 0.6)[0], ['x'])

    def test_missing_distances_keeps_everything(self):
        """Bez vzdáleností nefiltrujeme — jinak by změna formátu odpovědi
        znamenala, že RAG přestane vracet cokoli."""
        res = {'documents': [['a', 'b']]}
        docs, dists = self.f(res, 0.6)
        self.assertEqual(docs, ['a', 'b'])
        self.assertIsNone(dists)

    def test_length_mismatch_keeps_everything(self):
        res = {'documents': [['a', 'b']], 'distances': [[0.1]]}
        self.assertEqual(self.f(res, 0.6)[0], ['a', 'b'])

    def test_empty_result(self):
        for res in (None, {}, {'documents': [[]]}, {'documents': []}):
            docs, dists = self.f(res, 0.6)
            self.assertEqual(docs, [])
            self.assertIsNone(dists)

    def test_none_distance_entry_dropped(self):
        res = {'documents': [['a', 'b']], 'distances': [[0.1, None]]}
        self.assertEqual(self.f(res, 0.6)[0], ['a'])



class TestRagTextFallbackRelevance(unittest.TestCase):
    """510: filtr musí platit i ve fallbacku — jinak přestane fungovat,
    kdykoli není vektorová DB připravená."""

    def _engine(self, chunks):
        from sentinel.rag import RAGEngine
        e = RAGEngine.__new__(RAGEngine)
        e.kb_chunks = chunks
        e._idf = {}
        return e

    def test_relevant_query_matches(self):
        e = self._engine(["Disk je zaplneny, smaz stare logy v /var/log."])
        self.assertIn("logy", e._text_fallback("zaplneny disk logy"))

    def test_stopword_only_match_rejected(self):
        """Predlozka se trefi skoro do vseho — sama o sobe shoda neni."""
        e = self._engine(["Disk je zaplneny na serveru s logy."])
        self.assertEqual(e._text_fallback("recept na svickovou s knedlikem"),
                         "No text match found.")

    def test_short_query_still_works(self):
        e = self._engine(["Disk je zaplneny."])
        self.assertIn("Disk", e._text_fallback("disk"))

    def test_empty_kb(self):
        self.assertEqual(self._engine([])._text_fallback("cokoli"), "KB Empty.")


if __name__ == '__main__':
    unittest.main(verbosity=2)

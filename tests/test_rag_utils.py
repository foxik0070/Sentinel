"""509/511/512/513/514/515: RAG a komprese kontextu.

Společný důvod: model má omezené okno. Každý zbytečný token (opakovaný
řádek, duplicitní chunk, nesouvisející text) vytlačí něco užitečného.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import rag_utils as ru

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


class TestCompressLines(unittest.TestCase):
    def test_identical_lines_collapsed(self):
        out = ru.compress_lines(['ERROR: timeout'] * 50)
        self.assertIn('50×', out)
        self.assertLess(len(out), 100)

    def test_varying_numbers_still_collapse(self):
        """Řádky lišící se jen číslem nesou tutéž informaci."""
        out = ru.compress_lines([f'conn {i} refused from 10.0.0.{i}' for i in range(30)])
        self.assertIn('30×', out)

    def test_timestamps_ignored(self):
        lines = [f'2026-07-31T12:00:{i:02d} disk error' for i in range(20)]
        self.assertIn('20×', ru.compress_lines(lines))

    def test_first_occurrence_kept_verbatim(self):
        """Konkrétní čísla z prvního výskytu se nesmí ztratit."""
        out = ru.compress_lines(['disk 97% full on /var'] * 10)
        self.assertIn('97%', out)
        self.assertIn('/var', out)

    def test_few_repeats_not_collapsed(self):
        out = ru.compress_lines(['a', 'a'])
        self.assertNotIn('×', out)
        self.assertEqual(out, 'a\na')

    def test_distinct_lines_preserved(self):
        lines = ['disk full', 'network down', 'service failed']
        self.assertEqual(ru.compress_lines(lines), "\n".join(lines))

    def test_order_preserved(self):
        lines = ['start'] + ['spam'] * 10 + ['end']
        out = ru.compress_lines(lines)
        self.assertLess(out.index('start'), out.index('spam'))
        self.assertLess(out.index('spam'), out.index('end'))

    def test_interleaved_runs(self):
        out = ru.compress_lines(['a'] * 5 + ['b'] * 5 + ['a'] * 5)
        self.assertEqual(out.count('×'), 3)

    def test_ratio_measured(self):
        lines = ['ERROR: timeout'] * 50
        self.assertGreater(ru.compression_ratio(lines, ru.compress_lines(lines)), 0.8)

    def test_empty(self):
        for v in (None, [], ['']):
            self.assertIsInstance(ru.compress_lines(v), str)


class TestExactTerms(unittest.TestCase):
    def test_service_name(self):
        self.assertIn('nginx.service', ru.exact_terms('proč spadl nginx.service'))

    def test_path(self):
        self.assertIn('/var/log/syslog', ru.exact_terms('chyba v /var/log/syslog'))

    def test_error_code(self):
        self.assertIn('502', ru.exact_terms('server vrací 502'))

    def test_hostname_with_digit(self):
        self.assertIn('proxmox02', ru.exact_terms('problém na proxmox02'))

    def test_plain_words_not_exact(self):
        self.assertEqual(ru.exact_terms('proč to nefunguje'), [])

    def test_empty(self):
        for v in ('', None):
            self.assertEqual(ru.exact_terms(v), [])


class TestHybridRank(unittest.TestCase):
    def test_keyword_match_promotes(self):
        """„chyba 502" a „chyba 404" jsou vektorově blízké, ale jiný problém."""
        cands = [{'doc': 'obecná chyba serveru', 'distance': 0.30},
                 {'doc': 'HTTP 502 bad gateway na nginx', 'distance': 0.40}]
        self.assertIn('502', ru.hybrid_rank('chyba 502', cands)[0]['doc'])

    def test_keyword_does_not_override_distance(self):
        """Shodné číslo nesmí vyhrát bez souvislosti."""
        cands = [{'doc': 'relevantní text o discích', 'distance': 0.10},
                 {'doc': 'úplně jiné téma 502', 'distance': 0.95}]
        self.assertIn('discích', ru.hybrid_rank('disk 502', cands)[0]['doc'])

    def test_no_exact_terms_keeps_vector_order(self):
        cands = [{'doc': 'a', 'distance': 0.5}, {'doc': 'b', 'distance': 0.2}]
        self.assertEqual(ru.hybrid_rank('obecný dotaz', cands)[0]['doc'], 'b')

    def test_missing_distance_tolerated(self):
        self.assertTrue(ru.hybrid_rank('x', [{'doc': 'text'}]))

    def test_malformed_skipped(self):
        self.assertEqual(ru.hybrid_rank('x', [None, 'str', {}, {'doc': ''}]), [])


class TestRerank(unittest.TestCase):
    def test_word_overlap_helps(self):
        cands = [{'doc': 'nesouvisející povídání', 'distance': 0.30},
                 {'doc': 'disk je plný smaž logy', 'distance': 0.35}]
        self.assertIn('disk', ru.rerank('plný disk logy', cands)[0]['doc'])

    def test_top_n_respected(self):
        cands = [{'doc': f'text {i}', 'distance': 0.1 * i} for i in range(20)]
        self.assertEqual(len(ru.rerank('text', cands, top_n=3)), 3)

    def test_empty(self):
        self.assertEqual(ru.rerank('x', []), [])


class TestCitations(unittest.TestCase):
    def test_built_from_candidates(self):
        c = ru.build_citations([{'doc': 'disk je plný', 'distance': 0.2, 'source': 'kb'}])
        self.assertEqual(c[0]['n'], 1)
        self.assertIn('disk', c[0]['excerpt'])
        self.assertTrue(c[0]['id'])

    def test_stable_id(self):
        a = ru.build_citations([{'doc': 'stejný text'}])
        b = ru.build_citations([{'doc': 'stejný text'}])
        self.assertEqual(a[0]['id'], b[0]['id'])

    def test_note_formatting(self):
        note = ru.citations_note(ru.build_citations([{'doc': 'obsah kb', 'source': 'kb'}]))
        self.assertIn('Zdroje', note)
        self.assertIn('obsah kb', note)

    def test_empty_note(self):
        self.assertEqual(ru.citations_note([]), '')

    def test_malformed_skipped(self):
        self.assertEqual(ru.build_citations([None, {}, {'doc': ''}]), [])


class TestDedupe(unittest.TestCase):
    def test_exact_duplicates_removed(self):
        self.assertEqual(len(ru.dedupe_chunks(['a', 'a', 'a'])), 1)

    def test_whitespace_variants_are_duplicates(self):
        self.assertEqual(len(ru.dedupe_chunks(['disk  plný', 'DISK plný', ' disk plný '])), 1)

    def test_distinct_kept(self):
        self.assertEqual(len(ru.dedupe_chunks(['a', 'b'])), 2)

    def test_order_preserved(self):
        self.assertEqual(ru.dedupe_chunks(['first', 'second', 'first']), ['first', 'second'])

    def test_empty_dropped(self):
        self.assertEqual(ru.dedupe_chunks(['', '   ', None]), [])


class TestExpireLearned(unittest.TestCase):
    def e(self, text, days_ago=0):
        return {'text': text, 'at': (NOW - timedelta(days=days_ago)).isoformat()}

    def test_old_dropped(self):
        kept, dropped = ru.expire_learned([self.e('stary', 999)], now=NOW)
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]['reason'], 'příliš staré')

    def test_recent_kept(self):
        kept, _ = ru.expire_learned([self.e('novy', 1)], now=NOW)
        self.assertEqual(len(kept), 1)

    def test_over_limit_drops_oldest(self):
        entries = [self.e(f'e{i}', days_ago=i) for i in range(10)]
        kept, dropped = ru.expire_learned(entries, max_entries=5, now=NOW)
        self.assertEqual(len(kept), 5)
        self.assertIn('e0', [k['text'] for k in kept])       # nejnovější zůstal
        self.assertNotIn('e9', [k['text'] for k in kept])    # nejstarší pryč

    def test_missing_timestamp_kept(self):
        kept, _ = ru.expire_learned([{'text': 'bez data'}], now=NOW)
        self.assertEqual(len(kept), 1)

    def test_malformed_skipped(self):
        kept, _ = ru.expire_learned([None, 'x', {}, {'text': ''}], now=NOW)
        self.assertEqual(kept, [])


class TestSplitByStructure(unittest.TestCase):
    DOC = """# Disk plný
Když dojde místo, zkontroluj df -h a najdi největší adresáře.
Pak smaž staré logy.

# Služba nenaběhla
Zkontroluj systemctl status a journalctl -u.
Nejčastější příčina je chyba v konfiguraci.
"""

    def test_splits_on_headings(self):
        chunks = ru.split_by_structure(self.DOC)
        self.assertEqual(len(chunks), 2)

    def test_section_stays_together(self):
        """Pevná délka rozsekne postup uprostřed; sekce ho drží pohromadě."""
        chunks = ru.split_by_structure(self.DOC)
        disk = next(c for c in chunks if 'Disk plný' in c)
        self.assertIn('df -h', disk)
        self.assertIn('smaž staré logy', disk)

    def test_uppercase_heading_recognised(self):
        doc = "DISK PROBLEMY:\n" + "text " * 20 + "\nSITE PROBLEMY:\n" + "jiny " * 20
        self.assertGreaterEqual(len(ru.split_by_structure(doc)), 2)

    def test_long_section_is_split(self):
        doc = "# Velka sekce\n" + "\n\n".join(["odstavec " * 60] * 10)
        for c in ru.split_by_structure(doc):
            self.assertLessEqual(len(c), ru.MAX_CHUNK_LEN * 2)

    def test_short_tail_merged(self):
        chunks = ru.split_by_structure(self.DOC + "\n# X\nkratke")
        self.assertNotIn('kratke', [c.strip() for c in chunks])

    def test_empty(self):
        for v in ('', None):
            self.assertEqual(ru.split_by_structure(v), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

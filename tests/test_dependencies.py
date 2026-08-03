"""451/458/504: odvozené závislosti.

CDP/LLDP data v téhle instalaci nejsou, takže se závislosti ODVOZUJÍ.
Odvozená závislost není fakt — testy hlídají hlavně to, že se to nikde
netváří jinak.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import dependencies as dp


def facts(**hosts):
    return hosts


class TestKernelInference(unittest.TestCase):
    def test_shared_kernel_grouped(self):
        f = facts(a={'kernel': '7.0-pve', 'os': 'Ubuntu'},
                  b={'kernel': '7.0-pve', 'os': 'Ubuntu'},
                  c={'kernel': '6.1', 'os': 'Debian'})
        r = dp.infer_from_kernel(f)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]['hosts'], ['a', 'b'])

    def test_hypervisor_identified_by_different_distro(self):
        """Kontejnery bývají stejné, hostitel ne."""
        f = facts(a={'kernel': '7.0-pve', 'os': 'Ubuntu'},
                  b={'kernel': '7.0-pve', 'os': 'Ubuntu'},
                  hv={'kernel': '7.0-pve', 'os': 'Debian 13'})
        r = dp.infer_from_kernel(f)
        self.assertEqual(r[0]['parent'], 'hv')
        self.assertGreater(r[0]['confidence'], 80)

    def test_no_parent_when_ambiguous(self):
        """Když to nejde určit, neurčuje se."""
        f = facts(a={'kernel': 'k', 'os': 'A'}, b={'kernel': 'k', 'os': 'B'},
                  c={'kernel': 'k', 'os': 'A'}, d={'kernel': 'k', 'os': 'B'})
        r = dp.infer_from_kernel(f)
        self.assertIsNone(r[0]['parent'])
        self.assertLess(r[0]['confidence'], 85)

    def test_single_host_not_a_group(self):
        self.assertEqual(dp.infer_from_kernel(facts(a={'kernel': 'x'})), [])

    def test_note_says_probably(self):
        f = facts(a={'kernel': 'k'}, b={'kernel': 'k'})
        self.assertIn('pravděpodobně', dp.infer_from_kernel(f)[0]['note'])

    def test_malformed(self):
        for v in (None, {}, {'a': None}, {'a': 'text'}, {'a': {}}):
            self.assertIsInstance(dp.infer_from_kernel(v), list)


class TestCofailure(unittest.TestCase):
    def hist(self, pairs):
        out = []
        for i, (a, b) in enumerate(pairs):
            ts = f"2026-08-01T10:{i:02d}:00+00:00"
            out.append({'host': a, 'first_seen': ts})
            out.append({'host': b, 'first_seen': ts})
        return out

    def test_repeated_cofailure_detected(self):
        r = dp.infer_from_cofailure(self.hist([('a', 'b')] * 8))
        self.assertTrue(r)
        self.assertEqual(sorted(r[0]['hosts']), ['a', 'b'])

    def test_below_threshold_ignored(self):
        self.assertEqual(dp.infer_from_cofailure(self.hist([('a', 'b')] * 2)), [])

    def test_separate_times_not_cofailure(self):
        h = [{'host': 'a', 'first_seen': '2026-08-01T10:00:00+00:00'},
             {'host': 'b', 'first_seen': '2026-08-01T22:00:00+00:00'}] * 10
        self.assertEqual(dp.infer_from_cofailure(h), [])

    def test_noisy_host_does_not_dominate(self):
        """Hlučný host by jinak vypadal jako závislý na všem."""
        h = self.hist([('a', 'b')] * 6)
        h += [{'host': 'a', 'first_seen': f"2026-08-02T{i:02d}:00:00+00:00"}
              for i in range(24)] * 5
        r = dp.infer_from_cofailure(h)
        self.assertTrue(all(x['confidence'] <= 80 for x in r))

    def test_note_denies_causation(self):
        """Souběh není důkaz, že jeden závisí na druhém."""
        r = dp.infer_from_cofailure(self.hist([('a', 'b')] * 8))
        self.assertIn('sdílejí příčinu', r[0]['note'])

    def test_malformed(self):
        for v in (None, [], [None], ['x'], [{}]):
            self.assertEqual(dp.infer_from_cofailure(v), [])


class TestGraph(unittest.TestCase):
    def test_kernel_links_bidirectional(self):
        g = dp.build_graph(kernel_links=[{'hosts': ['a', 'b'], 'confidence': 70}])
        self.assertIn('b', g['a'])
        self.assertIn('a', g['b'])

    def test_stronger_link_wins(self):
        g = dp.build_graph(
            kernel_links=[{'hosts': ['a', 'b'], 'confidence': 85, 'parent': 'a'}],
            cofailure_links=[{'hosts': ['a', 'b'], 'confidence': 40}])
        self.assertEqual(g['a']['b']['via'], 'shared_kernel')

    def test_empty(self):
        self.assertEqual(dp.build_graph(), {})


class TestBlastRadius(unittest.TestCase):
    def graph(self):
        return dp.build_graph(
            kernel_links=[{'hosts': ['hv', 'c1', 'c2'], 'confidence': 85, 'parent': 'hv'}],
            cofailure_links=[{'hosts': ['c1', 'jiny'], 'confidence': 30}])

    def test_affected_listed(self):
        r = dp.blast_radius('hv', self.graph())
        self.assertEqual(r['count'], 2)

    def test_weak_links_filtered(self):
        """Seznam „možná souvisí se vším" by byl k ničemu."""
        r = dp.blast_radius('c1', self.graph())
        self.assertNotIn('jiny', [a['host'] for a in r['affected']])

    def test_parent_reported(self):
        self.assertIn('hv', dp.blast_radius('c1', self.graph())['runs_on'])

    def test_unknown_host_admits_ignorance(self):
        r = dp.blast_radius('nikdo', self.graph())
        self.assertEqual(r['count'], 0)
        self.assertIn('neznamená', r['note'])


class TestSimulateShutdown(unittest.TestCase):
    def graph(self):
        return dp.build_graph(
            kernel_links=[{'hosts': ['hv', 'c1', 'c2'], 'confidence': 85, 'parent': 'hv'}],
            cofailure_links=[{'hosts': ['c1', 'jiny'], 'confidence': 70}])

    def test_hypervisor_takes_containers_down(self):
        r = dp.simulate_shutdown('hv', self.graph())
        self.assertEqual(sorted(r['will_go_down']), ['c1', 'c2'])
        self.assertEqual(r['severity'], 'high')

    def test_container_does_not_take_hypervisor_down(self):
        """Vypnutí kontejneru hypervizor neshodí."""
        r = dp.simulate_shutdown('c1', self.graph())
        self.assertNotIn('hv', r['will_go_down'])

    def test_uncertain_impact_separated(self):
        r = dp.simulate_shutdown('c1', self.graph())
        self.assertIn('jiny', [x['host'] for x in r['may_be_affected']])
        self.assertIn('jistotu nemáme', r['note'])

    def test_online_subset_reported(self):
        agents = [{'hostname': 'c1', 'status': 'ONLINE'},
                  {'hostname': 'c2', 'status': 'OFFLINE'}]
        r = dp.simulate_shutdown('hv', self.graph(), agents=agents)
        self.assertEqual(r['online_now'], ['c1'])

    def test_isolated_host_low_severity(self):
        r = dp.simulate_shutdown('samotar', self.graph())
        self.assertEqual(r['severity'], 'low')
        self.assertIn('nic dalšího neshodí', r['note'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

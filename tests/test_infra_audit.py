"""472/477/479/482/485: audit infrastruktury.

Společné: tyhle problémy nikdo nehlásí. Drift se projeví až tím, že se
jeden stroj chová jinak; zombie služba podle účtu za elektřinu; certifikát
až výpadkem. Mlčí do poslední chvíle.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import infra_audit as ia

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)


def ago(days=0):
    return (NOW - timedelta(days=days)).isoformat()


class TestCatalogSafety(unittest.TestCase):
    def test_all_commands_readonly(self):
        """Audit nesmí nic měnit."""
        forbidden = ('rm ', 'restart', 'stop ', 'start ', 'kill', 'chmod',
                     'chown', 'apt', 'reboot', 'mkfs', 'dd ')
        for name, cmd in ia.AUDIT_COMMANDS.items():
            for bad in forbidden:
                self.assertNotIn(bad, cmd, f"{name}: {cmd}")

    def test_no_write_redirect(self):
        for name, cmd in ia.AUDIT_COMMANDS.items():
            leftover = cmd.replace('2>/dev/null', '')
            self.assertNotIn('>', leftover, f"{name}: {cmd}")


class TestDrift(unittest.TestCase):
    def facts(self, **hosts):
        return hosts

    def test_outlier_detected(self):
        f = self.facts(a={'kernel': '6.1.0'}, b={'kernel': '6.1.0'},
                       c={'kernel': '6.1.0'}, d={'kernel': '5.10.0'})
        r = ia.detect_drift(f)
        self.assertTrue(r)
        self.assertEqual(r[0]['outliers'][0]['host'], 'd')

    def test_uniform_no_drift(self):
        f = self.facts(a={'kernel': '6.1'}, b={'kernel': '6.1'}, c={'kernel': '6.1'})
        self.assertEqual(ia.detect_drift(f), [])

    def test_fragmented_reported_differently(self):
        """Když se „většina" skládá z poloviny, není to norma, ale rozpad."""
        f = self.facts(a={'kernel': '1'}, b={'kernel': '2'},
                       c={'kernel': '3'}, d={'kernel': '4'})
        r = ia.detect_drift(f)
        self.assertEqual(r[0]['kind'], 'fragmented')

    def test_too_few_hosts(self):
        self.assertEqual(ia.detect_drift({'a': {'kernel': '1'}, 'b': {'kernel': '2'}}), [])

    def test_note_says_verify_not_wrong(self):
        """Většina není totéž co správnost — odchylka může být záměr."""
        f = self.facts(a={'os': 'x'}, b={'os': 'x'}, c={'os': 'x'}, d={'os': 'y'})
        self.assertIn('záměr', ia.detect_drift(f)[0]['note'])

    def test_malformed(self):
        for v in (None, {}, {'a': None}, {'a': 'text'}):
            self.assertIsInstance(ia.detect_drift(v), list)


class TestUnitDiff(unittest.TestCase):
    def hosts(self, **kw):
        return {h: {'enabled_units': "\n".join(u)} for h, u in kw.items()}

    def test_missing_on_one_host_flagged(self):
        """Jednotka všude kromě jednoho stroje je obvykle chyba nasazení."""
        f = self.hosts(a=['ssh.service', 'node.service'],
                       b=['ssh.service', 'node.service'],
                       c=['ssh.service', 'node.service'],
                       d=['ssh.service'])
        r = ia.diff_unit_lists(f)
        self.assertTrue(any(x['unit'] == 'node.service' and 'd' in x['missing_on'] for x in r))

    def test_present_everywhere_not_flagged(self):
        f = self.hosts(a=['ssh.service'], b=['ssh.service'], c=['ssh.service'])
        self.assertEqual(ia.diff_unit_lists(f), [])

    def test_rare_unit_not_flagged(self):
        """Služba jen na jednom stroji je záměr, ne chybějící nasazení."""
        f = self.hosts(a=['ssh.service', 'special.service'],
                       b=['ssh.service'], c=['ssh.service'], d=['ssh.service'])
        self.assertEqual([x['unit'] for x in ia.diff_unit_lists(f)], [])

    def test_too_few_hosts(self):
        self.assertEqual(ia.diff_unit_lists(self.hosts(a=['x'], b=['y'])), [])


class TestZombies(unittest.TestCase):
    def test_idle_service_flagged(self):
        s = [{'host': 'rpi', 'unit': 'old.service',
              'active_since': ago(200), 'last_activity': ago(90), 'connections': 0}]
        r = ia.find_zombies(s, now=NOW)
        self.assertEqual(len(r), 1)
        self.assertGreater(r[0]['idle_days'], 30)

    def test_active_connections_not_zombie(self):
        s = [{'host': 'rpi', 'unit': 'x', 'active_since': ago(200),
              'last_activity': ago(90), 'connections': 3}]
        self.assertEqual(ia.find_zombies(s, now=NOW), [])

    def test_recent_activity_not_zombie(self):
        s = [{'host': 'rpi', 'unit': 'x', 'active_since': ago(200),
              'last_activity': ago(2), 'connections': 0}]
        self.assertEqual(ia.find_zombies(s, now=NOW), [])

    def test_recently_started_not_zombie(self):
        """Běží krátce — na závěr je brzy."""
        s = [{'host': 'rpi', 'unit': 'x', 'active_since': ago(1),
              'last_activity': None, 'connections': 0}]
        self.assertEqual(ia.find_zombies(s, now=NOW), [])

    def test_no_evidence_does_not_guess(self):
        s = [{'host': 'rpi', 'unit': 'x', 'active_since': ago(200)}]
        self.assertEqual(ia.find_zombies(s, now=NOW), [])

    def test_note_mentions_attack_surface(self):
        s = [{'host': 'rpi', 'unit': 'x', 'active_since': ago(200),
              'last_activity': ago(90), 'connections': 0}]
        self.assertIn('útoku', ia.find_zombies(s, now=NOW)[0]['note'])

    def test_malformed(self):
        for v in (None, [], [None], ['x'], [{}]):
            self.assertEqual(ia.find_zombies(v, now=NOW), [])


class TestCertImpact(unittest.TestCase):
    def cert(self, days, host='rpi', port='443'):
        return {'host': host, 'port': port, 'subject': 'CN=test',
                'expires': (NOW + timedelta(days=days)).isoformat()}

    def test_expiring_on_active_port_is_critical(self):
        r = ia.cert_impact([self.cert(3)], listening=[{'host': 'rpi', 'ports': ['443']}], now=NOW)
        self.assertEqual(r[0]['severity'], 'critical')
        self.assertTrue(r[0]['in_use'])

    def test_expiring_on_dead_port_is_low(self):
        """Certifikát tam, kde nikdo neposlouchá, počká."""
        r = ia.cert_impact([self.cert(3)], listening=[{'host': 'rpi', 'ports': ['22']}], now=NOW)
        self.assertEqual(r[0]['severity'], 'low')
        self.assertIn('neshodí', r[0]['note'])

    def test_far_future_ignored(self):
        self.assertEqual(ia.cert_impact([self.cert(365)], now=NOW), [])

    def test_sorted_by_urgency(self):
        r = ia.cert_impact([self.cert(20), self.cert(2, port='8443')], now=NOW)
        self.assertEqual(r[0]['days_left'], 2)

    def test_unknown_usage_admitted(self):
        r = ia.cert_impact([self.cert(5)], listening=None, now=NOW)
        self.assertIn('Nevíme', r[0]['note'])

    def test_missing_data_is_unknown_not_absent(self):
        """Chybějící sběr nesmí vypadat jako důkaz, že certifikát nic nedrží."""
        for listening in (None, [], [{'host': 'jiny', 'ports': ['443']}]):
            r = ia.cert_impact([self.cert(5)], listening=listening, now=NOW)
            self.assertIsNone(r[0]['in_use'], repr(listening))
            self.assertNotEqual(r[0]['severity'], 'low')

    def test_malformed(self):
        for v in (None, [], [None], [{}], [{'expires': 'nedatum'}]):
            self.assertEqual(ia.cert_impact(v, now=NOW), [])


class TestAfterReboot(unittest.TestCase):
    def test_missing_unit_detected(self):
        before = {'enabled_units': 'a.service\nb.service', 'listening': '0.0.0.0:80'}
        after = {'enabled_units': 'a.service', 'listening': '0.0.0.0:80'}
        r = ia.compare_after_reboot(before, after)
        self.assertIn('b.service', r['missing_units'])
        self.assertFalse(r['clean'])

    def test_missing_port_detected(self):
        before = {'enabled_units': 'a.service', 'listening': '0.0.0.0:80\n0.0.0.0:443'}
        after = {'enabled_units': 'a.service', 'listening': '0.0.0.0:80'}
        self.assertIn('0.0.0.0:443', ia.compare_after_reboot(before, after)['missing_ports'])

    def test_clean_reboot(self):
        same = {'enabled_units': 'a.service', 'listening': '0.0.0.0:80'}
        r = ia.compare_after_reboot(same, dict(same))
        self.assertTrue(r['clean'])
        self.assertIn('jako předtím', r['note'])

    def test_new_units_reported_separately(self):
        before = {'enabled_units': 'a.service'}
        after = {'enabled_units': 'a.service\nnovy.service'}
        r = ia.compare_after_reboot(before, after)
        self.assertIn('novy.service', r['new_units'])
        self.assertTrue(r['clean'])          # přibylo, nechybí

    def test_empty(self):
        self.assertFalse(ia.compare_after_reboot({}, {})['comparable'])


class TestDocsVsReality(unittest.TestCase):
    def test_stale_unit_found(self):
        """Zastaralý runbook je nebezpečnější než žádný."""
        doc = "Při potížích restartuj stary-nazev.service na stroji rpi."
        r = ia.check_docs_against_reality(doc, ['rpi'], known_units=['nginx.service'])
        self.assertTrue(any(f['kind'] == 'unit' for f in r))

    def test_current_unit_not_flagged(self):
        doc = "Restartuj nginx.service."
        r = ia.check_docs_against_reality(doc, ['rpi'], known_units=['nginx.service'])
        self.assertEqual([f for f in r if f['kind'] == 'unit'], [])

    def test_stale_host_found(self):
        doc = "Přihlas se na stroj stary-server a zkontroluj disk."
        r = ia.check_docs_against_reality(doc, ['rpi', 'docs'])
        self.assertTrue(any(f['kind'] == 'host' for f in r))

    def test_existing_host_not_flagged(self):
        r = ia.check_docs_against_reality("Na stroji rpi zkontroluj disk.", ['rpi'])
        self.assertEqual([f for f in r if f['kind'] == 'host'], [])

    def test_stale_port_found(self):
        r = ia.check_docs_against_reality("Služba běží na port 9999.", ['rpi'],
                                          known_ports=['80', '443'])
        self.assertTrue(any(f['kind'] == 'port' for f in r))

    def test_duplicates_collapsed(self):
        doc = "stroj neexistuje. Znovu stroj neexistuje."
        r = ia.check_docs_against_reality(doc, ['rpi'])
        self.assertLessEqual(len([f for f in r if f['kind'] == 'host']), 1)

    def test_empty_inputs(self):
        self.assertEqual(ia.check_docs_against_reality('', []), [])
        self.assertEqual(ia.check_docs_against_reality(None, None), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

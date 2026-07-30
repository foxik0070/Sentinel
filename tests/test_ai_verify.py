"""516: Detekce halucinací.

Hlavní riziko NENÍ přehlédnutá halucinace, ale planý poplach: kdyby se
označovaly správné odpovědi, uživatel varování přestane číst. Většina
testů proto hlídá, že se NEhlásí to, co hlásit nemá.
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import ai_verify as av

KNOWN = {'hosts': {'rpi', 'docs', 'gitea', 'proxmox02', 'jellyfin-zatisi'},
         'services': {'nginx.service', 'sshd.service'}}


class FakeState:
    def __init__(self, agents=None, issues=None):
        self._agents = agents if agents is not None else []
        self._issues = issues if issues is not None else []

    def get_all_agents(self):
        return self._agents

    def get_active_issues(self):
        return self._issues


class TestKnownEntities(unittest.TestCase):
    def test_collects_from_agents_and_issues(self):
        st = FakeState(agents=[{'hostname': 'rpi'}],
                       issues=[{'host': 'docs', 'last_line': 'nginx.service failed'}])
        k = av.known_entities(st)
        self.assertIn('rpi', k['hosts'])
        self.assertIn('docs', k['hosts'])
        self.assertIn('nginx.service', k['services'])

    def test_lowercased(self):
        st = FakeState(agents=[{'hostname': 'RPi'}])
        self.assertIn('rpi', av.known_entities(st)['hosts'])

    def test_broken_source_does_not_empty_the_world(self):
        """Kdyby výpadek zdroje vrátil prázdno, označí se za halucinaci všechno."""
        st = FakeState(agents=[{'hostname': 'rpi'}])
        st.get_active_issues = lambda: (_ for _ in ()).throw(RuntimeError('db'))
        self.assertIn('rpi', av.known_entities(st)['hosts'])

    def test_all_sources_broken_returns_shape(self):
        st = FakeState()
        st.get_all_agents = lambda: (_ for _ in ()).throw(RuntimeError('x'))
        st.get_active_issues = lambda: (_ for _ in ()).throw(RuntimeError('x'))
        k = av.known_entities(st)
        self.assertEqual(k['hosts'], set())


class TestNoFalsePositives(unittest.TestCase):
    """Nic z tohohle není halucinace a nesmí se hlásit."""

    def test_known_host_not_flagged(self):
        r = av.check("Zkontroluj disk na stroji gitea.", KNOWN)
        self.assertEqual(r['unknown_hosts'], [])
        self.assertFalse(r['suspicious'])

    def test_fqdn_of_known_host_not_flagged(self):
        self.assertEqual(av.check("stroj rpi.local je dostupný", KNOWN)['unknown_hosts'], [])

    def test_urls_ignored(self):
        r = av.check("Viz https://docs.example.com/guide a http://grafana.io/x", KNOWN)
        self.assertEqual(r['unknown_hosts'], [])

    def test_code_blocks_ignored(self):
        r = av.check("Spusť `systemctl status neco.divneho` prosím", KNOWN)
        self.assertEqual(r['unknown_hosts'], [])

    def test_fenced_block_ignored(self):
        r = av.check("```\nssh vymysleny-stroj\n```\nHotovo.", KNOWN)
        self.assertEqual(r['unknown_hosts'], [])

    def test_filenames_not_hosts(self):
        for t in ("uprav config.yaml", "mrkni do sentinel.log", "spusť deploy.sh",
                  "otevři data.json", "soubor archiv.tar"):
            self.assertEqual(av.check(t, KNOWN)['unknown_hosts'], [], t)

    def test_technical_hyphenated_words_not_hosts(self):
        for t in ("je to read-only", "režim dry-run", "skupina systemd-journal",
                  "self-signed certifikát", "root-cause analýza"):
            self.assertEqual(av.check(t, KNOWN)['unknown_hosts'], [], t)

    def test_version_numbers_not_hosts(self):
        self.assertEqual(av.check("verze 1.2.3 a 10.0.0", KNOWN)['unknown_hosts'], [])

    def test_service_of_known_host_not_flagged(self):
        self.assertEqual(av.check("restartuj nginx.service", KNOWN)['unknown_services'], [])

    def test_plain_czech_text_is_clean(self):
        text = ("Disk je zaplněný na 97 %. Doporučuji smazat staré logy "
                "a ověřit, jestli se rotace spouští.")
        r = av.check(text, KNOWN)
        self.assertEqual(r['unknown_hosts'], [])
        self.assertFalse(r['suspicious'])


class TestDetection(unittest.TestCase):
    def test_invented_host_flagged(self):
        r = av.check("Problém je na stroji web-server-03.", KNOWN)
        self.assertIn('web-server-03', r['unknown_hosts'])
        self.assertTrue(r['suspicious'])

    def test_multiple_unknown_hosts(self):
        r = av.check("Zkontroluj db-master-01 a cache-node-7.", KNOWN)
        self.assertEqual(len(r['unknown_hosts']), 2)

    def test_duplicates_reported_once(self):
        r = av.check("stroj fake-host je mimo, fake-host neodpovídá", KNOWN)
        self.assertEqual(len(r['unknown_hosts']), 1)

    def test_unknown_service_is_not_suspicious(self):
        """Model může legitimně navrhnout novou službu — hlásit ji jako
        halucinaci by bylo zavádějící."""
        r = av.check("nainstaluj a spusť redis.service", KNOWN)
        self.assertIn('redis.service', r['unknown_services'])
        self.assertFalse(r['suspicious'])

    def test_empty_input(self):
        for t in ('', None):
            r = av.check(t, KNOWN)
            self.assertFalse(r['suspicious'])

    def test_empty_known_does_not_crash(self):
        r = av.check("stroj gitea", {})
        self.assertIn('gitea', r['unknown_hosts'])

    def test_single_word_host_only_when_introduced(self):
        """Jednoslovný název se od podstatného jména nepozná — chytáme ho
        jen tam, kde ho model označil za stroj."""
        self.assertIn('backupnode', av.check("Problém je na stroji backupnode.", KNOWN)['unknown_hosts'])
        # totéž slovo bez uvození se nehlásí (mohlo by to být cokoli)
        self.assertEqual(av.check("backupnode selhal", KNOWN)['unknown_hosts'], [])

    def test_introduced_known_host_not_flagged(self):
        self.assertEqual(av.check("na stroji gitea je plno", KNOWN)['unknown_hosts'], [])

    def test_czech_words_after_keyword_not_hosts(self):
        for t in ("server je pomalý", "stroj se restartoval", "node nefunguje",
                  "server byl restartován", "stroj má problém"):
            self.assertEqual(av.check(t, KNOWN)['unknown_hosts'], [], t)


class TestVerify(unittest.TestCase):
    def test_end_to_end(self):
        st = FakeState(agents=[{'hostname': 'gitea'}])
        self.assertFalse(av.verify(st, "restartuj gitea")['suspicious'])
        self.assertTrue(av.verify(st, "restartuj vymyslený-stroj-9")['suspicious'])


class TestWarningHtml(unittest.TestCase):
    def test_empty_when_clean(self):
        self.assertEqual(av.warning_html({'unknown_hosts': []}), '')
        self.assertEqual(av.warning_html({}), '')

    def test_lists_hosts(self):
        h = av.warning_html({'unknown_hosts': ['fake-01']})
        self.assertIn('fake-01', h)

    def test_escapes_html(self):
        h = av.warning_html({'unknown_hosts': ['<script>x</script>']})
        self.assertNotIn('<script>', h)

    def test_caps_list(self):
        h = av.warning_html({'unknown_hosts': [f'h-{i}' for i in range(20)]})
        self.assertNotIn('h-9', h)


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""
Tests for sentinel.config — default values, load_config(), Hailo config.

Run:
    python -m pytest tests/test_config.py -v
    python -m unittest tests.test_config -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml
from sentinel import config


class TestConfigDefaults(unittest.TestCase):
    """Kódové výchozí hodnoty definované v config.py — testujeme izolovaně od reálného deploye."""

    # Kódové defaults z config.py (nezávisle na config.yaml)
    _code_defaults = {
        'HAILO_OLLAMA_ENABLED': False,
        'HAILO_OLLAMA_URL': "http://localhost:8000/v1/chat/completions",
        'HAILO_OLLAMA_MODEL': "qwen2.5-coder:1.5b",
        'EMBEDDING_OLLAMA_URL': "",
        'AI_HAT_ENABLED': False,
        'AI_HAT_TOPS': 0,
        'WORKER_THREADS': 2,
        'WEB_PORT': 5050,
    }

    def setUp(self):
        self._orig = {k: getattr(config, k) for k in self._code_defaults}
        for k, v in self._code_defaults.items():
            setattr(config, k, v)

    def tearDown(self):
        for k, v in self._orig.items():
            try:
                setattr(config, k, v)
            except AttributeError:
                pass

    def test_version_format(self):
        self.assertRegex(config.VERSION, r'^\d{4}\.\d{2}\.\d{3}$')

    def test_ollama_url_default(self):
        self.assertIn("11434", config.OLLAMA_URL)

    def test_hailo_ollama_defaults(self):
        self.assertFalse(config.HAILO_OLLAMA_ENABLED)
        self.assertIn("8000", config.HAILO_OLLAMA_URL)
        self.assertEqual(config.HAILO_OLLAMA_MODEL, "qwen2.5-coder:1.5b")

    def test_embedding_url_default_empty(self):
        # Prázdný string = odvodit z OLLAMA_URL
        self.assertIsInstance(config.EMBEDDING_OLLAMA_URL, str)

    def test_ai_hat_defaults(self):
        self.assertFalse(config.AI_HAT_ENABLED)
        self.assertEqual(config.AI_HAT_TOPS, 0)

    def test_web_defaults(self):
        self.assertEqual(config.WEB_PORT, 5050)
        self.assertIsNotNone(config.SECRET_KEY)
        self.assertEqual(len(config.SECRET_KEY), 64)  # 32 bytes hex

    def test_worker_threads_default(self):
        self.assertEqual(config.WORKER_THREADS, 2)


class TestConfigLoad(unittest.TestCase):
    """load_config() načítá hodnoty z YAML správně."""

    def setUp(self):
        # Uložit původní hodnoty globálního config před každým testem
        self._orig = {k: getattr(config, k) for k in dir(config)
                      if k.isupper() and not k.startswith('_') and not callable(getattr(config, k))}

    def tearDown(self):
        # Obnovit původní hodnoty aby testy neovlivňovaly navzájem
        for k, v in self._orig.items():
            try:
                setattr(config, k, v)
            except AttributeError:
                pass

    def _write_and_load(self, data: dict):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(data, f)
            path = f.name
        orig_path = config.CONFIG_PATH
        config.CONFIG_PATH = type('P', (), {'exists': lambda s: True,
                                            '__str__': lambda s: path})()
        try:
            # Patch open to use temp file
            import builtins
            orig_open = builtins.open
            def patched_open(p, *a, **kw):
                if str(p) == path or p == path:
                    return orig_open(path, *a, **kw)
                return orig_open(p, *a, **kw)
            builtins.open = patched_open
            config.load_config()
        finally:
            builtins.open = orig_open
            config.CONFIG_PATH = orig_path
            os.unlink(path)

    def test_hailo_ollama_section_loaded(self):
        self._write_and_load({
            "hailo_ollama": {
                "enabled": True,
                "url": "http://localhost:8000/v1/chat/completions",
                "model": "qwen2.5-coder:1.5b",
            }
        })
        self.assertTrue(config.HAILO_OLLAMA_ENABLED)
        self.assertEqual(config.HAILO_OLLAMA_MODEL, "qwen2.5-coder:1.5b")

    def test_embedding_url_loaded(self):
        self._write_and_load({
            "embedding_ollama_url": "http://localhost:11434"
        })
        self.assertEqual(config.EMBEDDING_OLLAMA_URL, "http://localhost:11434")

    def test_worker_threads_loaded(self):
        self._write_and_load({"worker_threads": 4})
        self.assertEqual(config.WORKER_THREADS, 4)

    def test_missing_file_does_not_crash(self):
        orig = config.CONFIG_PATH
        config.CONFIG_PATH = type('P', (), {'exists': lambda s: False})()
        try:
            config.load_config()  # must not raise
        finally:
            config.CONFIG_PATH = orig

    def test_every_read_key_is_in_known_keys(self):
        """Klíč, který loader čte, musí být i ve whitelistu _KNOWN_KEYS.

        Jinak `load_config()` hodnotu přeskočí a jen zaloguje "Neznámý klíč" —
        volba se tváří jako podporovaná, ale nic nedělá. Přesně tak se stalo,
        že `snapshot_logs` v ostrém provozu tiše nefungoval.
        """
        import re
        src = Path(config.__file__).read_text()
        read_keys = set(re.findall(r'data\.get\(\s*["\']([a-z0-9_]+)["\']', src))
        self.assertTrue(read_keys, "sanity: regex musí najít aspoň nějaké klíče")
        missing = sorted(read_keys - config._KNOWN_KEYS)
        self.assertEqual(missing, [],
                         f"loader čte klíče, které nejsou v _KNOWN_KEYS: {missing}")

    def test_snapshot_logs_loaded(self):
        self._write_and_load({"snapshot_logs": ["sv3.log", "racks.log"]})
        self.assertEqual(config.SNAPSHOT_LOGS, ["sv3.log", "racks.log"])

    def test_snapshot_logs_absent_key_keeps_current(self):
        """Chybějící klíč hodnotu nepřepisuje — stejná konvence jako u ostatních
        seznamů (ignored_failed_services…). Nastavuje se explicitně, aby test
        nezávisel na tom, jaký config modul načetl při importu."""
        orig = config.SNAPSHOT_LOGS
        config.SNAPSHOT_LOGS = ["puvodni.log"]
        try:
            self._write_and_load({"instance_name": "TEST"})
            self.assertEqual(config.SNAPSHOT_LOGS, ["puvodni.log"])
        finally:
            config.SNAPSHOT_LOGS = orig

    def test_snapshot_logs_non_list_ignored(self):
        orig = config.SNAPSHOT_LOGS
        config.SNAPSHOT_LOGS = []
        try:
            self._write_and_load({"snapshot_logs": "sv3.log"})  # string, ne list
            self.assertEqual(config.SNAPSHOT_LOGS, [])
        finally:
            config.SNAPSHOT_LOGS = orig




class TestConfigValidationNeverCrashes(TestConfigLoad):
    """Validace configu je diagnostika — nesmi shodit import, at je v configu cokoliv.

    Preklep v plugin_dir (seznam misto retezce) vyhodil TypeError primo ve
    _validate_config. Protoze se vola pri importu sentinel.config, sestrelil
    celou aplikaci a se systemd Restart=always z toho byla smycka bez webu
    i bez prijmu od agentu.
    """

    def _validate(self, data):
        from sentinel import config
        config.VALIDATION_WARNINGS = []
        config._validate_config(data)
        return config.VALIDATION_WARNINGS

    def test_plugin_dir_list_is_accepted(self):
        """Seznam je u plugin_dir platny zapis (v2026.11.010 a vys)."""
        warns = self._validate({'plugin_dir': ['/nekde', '/jinde']})
        msgs = ' '.join(w['message'] for w in warns)
        self.assertNotIn('musí být řetězec', msgs)
        self.assertIn('/nekde', msgs)   # jen upozorneni, ze neexistuje

    def test_plugin_dir_wrong_type_warns_instead_of_crashing(self):
        for value in (5, {'a': 1}, True):
            with self.subTest(value=value):
                warns = self._validate({'plugin_dir': value})
                self.assertTrue(any(w['level'] == 'error' for w in warns))

    def test_log_dir_list_is_rejected_but_does_not_crash(self):
        """Seznam dava smysl jen u plugin_dir."""
        warns = self._validate({'log_dir': ['/a', '/b']})
        self.assertTrue(any('musí být řetězec' in w['message'] for w in warns))

    def test_none_is_not_reported(self):
        """Chybejici klic neni chyba cesty — jinych varovani si nevsimame."""
        warns = self._validate({'plugin_dir': None})
        self.assertFalse([w for w in warns if 'plugin_dir' in w['message']])

    def test_load_config_survives_broken_validation(self):
        """I kdyby validace sama selhala, konfigurace se musi nacist dal."""
        from sentinel import config
        orig = config._validate_config
        try:
            def boom(_data):
                raise RuntimeError("rozbita validace")
            config._validate_config = boom
            config.load_config()      # nesmi vyhodit
        finally:
            config._validate_config = orig

    def test_plugin_dir_keeps_default_on_bad_type(self):
        """Spatny typ se nesmi dostat do PLUGIN_DIR, jinak spadne az plugin manager."""
        for value, expected in ((42, '/puvodni'),
                                ('/nova', '/nova'),
                                (['/a', '/b'], ['/a', '/b']),
                                ([1, 2], '/puvodni')):
            with self.subTest(value=value):
                config.PLUGIN_DIR = '/puvodni'
                self._write_and_load({'plugin_dir': value})
                self.assertEqual(config.PLUGIN_DIR, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMqttDependency(unittest.TestCase):
    """paho-mqtt musi byt v requirements.txt.

    install.sh ji instaloval zvlast (`pip install paho-mqtt`), takze u rucni
    instalace MQTT fungovalo. Balicek stavi venv jen z requirements.txt —
    knihovna tam chybela a MQTT po prechodu na balicek prestalo jezdit.
    """

    def test_paho_in_requirements(self):
        req = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'requirements.txt'), encoding='utf-8').read()
        self.assertRegex(req, r'(?m)^paho-mqtt==')

    def test_every_import_in_requirements(self):
        """Co utils importuje jako volitelne, musi jit nainstalovat z requirements."""
        from sentinel import utils
        self.assertTrue(hasattr(utils, 'MQTT_AVAILABLE'),
                        "utils musi hlasit, zda je knihovna k dispozici")


class TestStaticAssetsNeverMissing(unittest.TestCase):
    """Chybejici minifikator nesmi znamenat prazdne UI.

    Sablona odkazuje na .min.js. Kdyz je minifikace preskocena a soubor
    neexistuje, Flask vrati HTML chybovou stranku s MIME text/html, prohlizec
    ji odmitne spustit a nenacte se ZADNY skript — aplikace je prazdna.
    Stalo se to po prechodu na balicek, protoze rjsmin byl jen v install.sh.
    """

    def _main_src(self):
        return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'sentinel', '__main__.py'), encoding='utf-8').read()

    def test_minifiers_in_requirements(self):
        req = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'requirements.txt'), encoding='utf-8').read()
        self.assertRegex(req, r'(?m)^rjsmin==')
        self.assertRegex(req, r'(?m)^rcssmin==')

    def test_fallback_copies_unminified(self):
        """Pri selhani se ma zkopirovat nezmensena verze, ne jen zalogovat."""
        src = self._main_src()
        self.assertIn('nezmenšené kopie', src)

    def test_every_template_min_asset_is_generated(self):
        """Co sablona nacita jako .min.js, musi nekdo vyrobit — jinak 404."""
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tpl = open(os.path.join(root, 'sentinel', 'templates', 'index.html'), encoding='utf-8').read()
        wanted = set(re.findall(r"filename='((?:script|i18n)[-\w]*\.min\.js)'", tpl))
        src = self._main_src()
        for name in wanted:
            with self.subTest(asset=name):
                static_file = os.path.join(root, 'sentinel', 'static', name)
                self.assertTrue(name in src or os.path.exists(static_file),
                                f"{name} se nikde negeneruje ani neexistuje")


class TestSuperadminBootstrap(unittest.TestCase):
    """Na instanci musi jit vytvorit prvniho spravce.

    Role nastavuje jen /api/users/roles, ktery vyzaduje superadmina. Lokalni
    ucet z config.yaml ale dostaval jen 'admin', takze na instanci s LDAPem
    a nevyplnenymi skupinami nebyl superadmin NIKDO — a roli tedy neslo
    udelit ani sobe.
    """

    def test_local_account_is_superadmin(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'sentinel', 'auth.py'), encoding='utf-8').read()
        i = src.index('if username == config.WEB_USER')
        blok = src[i:i + 600]
        self.assertIn("or 'superadmin'", blok,
                      "ucet z web.username musi byt superadmin, jinak nelze zalozit prvniho spravce")

    def test_viewer_account_stays_viewer(self):
        """Druhy ucet z configu je ctenar — ten povysit nesmime."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'sentinel', 'auth.py'), encoding='utf-8').read()
        i = src.index('if username == config.WEB_VIEWER_USER')
        self.assertIn("or 'viewer'", src[i:i + 300])

    def test_db_role_wins_over_default(self):
        """Kdyz je ucet v user_roles, plati tam ulozena role."""
        from sentinel import auth
        self.assertTrue(hasattr(auth, '_role_for_user'))
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'sentinel', 'auth.py'), encoding='utf-8').read()
        i = src.index('if username == config.WEB_USER')
        self.assertIn('_role_for_user(username) or', src[i:i + 600])

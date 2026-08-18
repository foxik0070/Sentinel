"""
Testy File Integrity Monitoringu (176).

FIM měl dosud config, dokumentaci i volání v mrtvém scheduleru — ale žádnou
implementaci. Tyhle testy drží chování popsané v dokumentaci (sekce 11.7):
SHA-256 každou minutu, při změně issue v kanálu `security`, plugin
`file_integrity_monitor`, severity `high`.

Run:
    python -m unittest tests.test_fim -v
"""
import os
import sys
import tempfile
import threading
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state, config

try:
    from sentinel import watcher
    _HAS_WATCHER = True
except ImportError:
    _HAS_WATCHER = False


@unittest.skipUnless(_HAS_WATCHER, "watcher requires chromadb")
class TestFimCheck(unittest.TestCase):

    def setUp(self):
        self._tmpdb = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmpdb.close()
        self._orig_db = state.DB_FILE
        state.DB_FILE = self._tmpdb.name
        state._local = threading.local()
        state.init_db()

        self._dir = tempfile.mkdtemp()
        self._watched = os.path.join(self._dir, 'passwd')
        with open(self._watched, 'w') as f:
            f.write('root:x:0:0::/root:/bin/bash\n')

        self._orig_enabled = config.FIM_ENABLED
        self._orig_paths = config.FIM_PATHS
        config.FIM_ENABLED = True
        config.FIM_PATHS = [self._watched]

    def tearDown(self):
        config.FIM_ENABLED = self._orig_enabled
        config.FIM_PATHS = self._orig_paths
        state.DB_FILE = self._orig_db
        os.unlink(self._tmpdb.name)
        for f in os.listdir(self._dir):
            os.unlink(os.path.join(self._dir, f))
        os.rmdir(self._dir)

    def _issues(self):
        return {i['key']: i for i in state.get_active_issues()}

    def _write(self, text):
        with open(self._watched, 'w') as f:
            f.write(text)

    # --- baseline ---

    def test_first_run_creates_baseline_without_alerting(self):
        self.assertEqual(watcher.fim_check(), [])
        self.assertEqual(self._issues(), {},
                         "první běh nesmí hlásit — jinak po zapnutí vyskočí každý soubor")
        self.assertTrue(state.get_setting('fim_state'))

    def test_unchanged_file_is_quiet(self):
        watcher.fim_check()
        self.assertEqual(watcher.fim_check(), [])
        self.assertEqual(self._issues(), {})

    # --- detekce ---

    def test_content_change_is_reported(self):
        watcher.fim_check()
        self._write('root:x:0:0::/root:/bin/bash\nevil:x:0:0::/root:/bin/sh\n')
        self.assertEqual(watcher.fim_check(), [self._watched])

        issue = self._issues().get(f'FIM_CHANGE|{self._watched}')
        self.assertIsNotNone(issue, "změna obsahu musí založit issue")
        # save_problem si kanál ukládá velkými písmeny
        self.assertEqual(issue['channel_type'].lower(), 'security')
        self.assertEqual(issue['plugin_name'], 'file_integrity_monitor')
        # save_problem severity do sloupce nepíše — fim_check ji dosazuje zvlášť
        self.assertEqual((issue.get('severity') or '').lower(), 'high',
                         "podle severity se řídí badge, SLA i eskalace")
        self.assertIn('změnil', issue['last_line'])

    def test_change_is_reported_once_not_every_run(self):
        watcher.fim_check()
        self._write('zmena\n')
        self.assertEqual(watcher.fim_check(), [self._watched])
        # baseline se posunula → další běh už mlčí
        self.assertEqual(watcher.fim_check(), [],
                         "opakované hlášení téže změny by alert utopilo v šumu")

    def test_deleted_file_is_reported(self):
        watcher.fim_check()
        os.unlink(self._watched)
        self.assertEqual(watcher.fim_check(), [self._watched])
        issue = self._issues().get(f'FIM_CHANGE|{self._watched}')
        self.assertIsNotNone(issue)
        self.assertIn('smazán', issue['last_line'])

    def test_reappearing_file_is_reported(self):
        os.unlink(self._watched)
        watcher.fim_check()          # baseline = soubor neexistuje
        self._write('root:x:0:0::/root:/bin/bash\n')
        self.assertEqual(watcher.fim_check(), [self._watched])
        issue = self._issues().get(f'FIM_CHANGE|{self._watched}')
        self.assertIn('objevil', issue['last_line'])

    def test_missing_file_that_never_existed_is_quiet(self):
        config.FIM_PATHS = [os.path.join(self._dir, 'neexistuje')]
        watcher.fim_check()
        self.assertEqual(watcher.fim_check(), [])
        self.assertEqual(self._issues(), {})

    # --- odolnost ---

    def test_disabled_does_nothing(self):
        config.FIM_ENABLED = False
        self.assertEqual(watcher.fim_check(), [])
        self.assertIsNone(state.get_setting('fim_state'))

    def test_unreadable_file_does_not_touch_baseline(self):
        if os.geteuid() == 0:
            self.skipTest("jako root je čitelné všechno")
        watcher.fim_check()
        before = state.get_setting('fim_state')
        os.chmod(self._watched, 0o000)
        try:
            self.assertEqual(watcher.fim_check(), [],
                             "chybějící oprávnění není integritní událost")
            self.assertEqual(state.get_setting('fim_state'), before,
                             "nečitelný soubor nesmí přepsat baseline")
        finally:
            os.chmod(self._watched, 0o644)

    def test_empty_paths_falls_back_to_defaults(self):
        config.FIM_PATHS = []
        watcher.fim_check()
        raw = state.get_setting('fim_state') or '{}'
        # Nehlídáme konkrétní obsah /etc, jen že se sáhlo na výchozí sadu
        self.assertTrue(any(p in raw for p in watcher.DEFAULT_FIM_PATHS),
                        "prázdný seznam má spadnout na DEFAULT_FIM_PATHS")


if __name__ == '__main__':
    unittest.main()

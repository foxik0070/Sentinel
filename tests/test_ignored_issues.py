"""Ignorovane issue se nesmi vratit.

Drive byla ignorace jen JSON soubor, ktery znal chat_service a ktery se
uplatnil az pri VYPISU. Detektor tentyz klic pri dalsim behu zalozil znovu,
notifikace odesla a v poctech se objevil — "ignorovat" tedy znamenalo
"schovat na jednom miste". Vynucuje se proto uz pri zapisu.
"""
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import state


def _problem(line="disk plny"):
    return {"status": "active", "last_line": line, "channel_type": "infra",
            "host": "testhost", "plugin_name": "test_detector"}


class TestIgnoredIssues(unittest.TestCase):
    KEY = "TEST_IGNORE|testhost|disk"

    def setUp(self):
        state.remove_ignored(self.KEY)
        state.delete_problem(self.KEY)

    def tearDown(self):
        state.remove_ignored(self.KEY)
        state.delete_problem(self.KEY)

    def test_ignored_key_is_not_saved_again(self):
        """Jadro veci: po ignoraci uz detektor issue nezalozi."""
        self.assertTrue(state.save_problem(self.KEY, _problem()) is not False)
        state.delete_problem(self.KEY)
        state.add_ignored(self.KEY, created_by="test")

        self.assertFalse(state.save_problem(self.KEY, _problem()))
        keys = {i.get("key") for i in state.get_active_issues()}
        self.assertNotIn(self.KEY, keys)

    def test_unignore_lets_it_come_back(self):
        state.add_ignored(self.KEY, created_by="test")
        self.assertFalse(state.save_problem(self.KEY, _problem()))
        state.remove_ignored(self.KEY)
        self.assertNotEqual(state.save_problem(self.KEY, _problem()), False)
        self.assertIn(self.KEY, {i.get("key") for i in state.get_active_issues()})

    def test_other_keys_are_unaffected(self):
        other = self.KEY + "|jiny"
        state.add_ignored(self.KEY, created_by="test")
        try:
            self.assertNotEqual(state.save_problem(other, _problem()), False)
        finally:
            state.delete_problem(other)

    def test_is_ignored_and_listing(self):
        state.add_ignored(self.KEY, created_by="tester", reason="hlasi to planě")
        self.assertTrue(state.is_ignored(self.KEY))
        row = next((r for r in state.list_ignored() if r["key"] == self.KEY), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["created_by"], "tester")
        self.assertEqual(row["reason"], "hlasi to planě")

    def test_migration_from_legacy_file(self):
        """Co uzivatel ignoroval drive, nesmi se po upgradu zacit hlasit."""
        legacy = self.KEY + "|stary"
        state.remove_ignored(legacy)
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump([legacy], f)
            path = f.name
        try:
            self.assertEqual(state.migrate_ignored_from_file(path), 1)
            self.assertTrue(state.is_ignored(legacy))
            # Podruhe uz nic nepribude.
            self.assertEqual(state.migrate_ignored_from_file(path), 0)
        finally:
            state.remove_ignored(legacy)
            os.unlink(path)

    def test_missing_legacy_file_is_not_an_error(self):
        self.assertEqual(state.migrate_ignored_from_file("/neexistuje/ignored.json"), 0)


class TestIgnoreRouteIsRegisteredOnce(unittest.TestCase):
    def test_single_post_route(self):
        """Dve definice na teze ceste znamenaly mrtvy kod — werkzeug bere prvni."""
        src = open(os.path.join(_ROOT, 'sentinel', 'routes', 'issues.py'), encoding='utf-8').read()
        self.assertEqual(src.count("'/api/issues/<key_b64>/ignore', methods=['POST']"), 1)


if __name__ == '__main__':
    unittest.main()

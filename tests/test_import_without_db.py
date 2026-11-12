"""Import modulu nesmi vyzadovat zapisovatelny adresar databaze.

`_ensure_keeper()` se vola pri importu `sentinel.state_base`. Drzi jedno
trvale DB spojeni, aby zadny per-request close() nebyl posledni a nespustil
WAL checkpoint, ktery mrazi cely proces (v2026.09.001). Jenze volani nebylo
osetrene, takze kdekoliv adresar DB nesel zapsat, spadl uz IMPORT — v CI pak
kazdy test skoncil chybou pri sberu, protoze `sentinel.state` nesel nacist.
CI bylo z tohoto duvodu cervene od 2026-09-08.
"""
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _import_with_db_dir(db_dir):
    """Naimportuje sentinel.state v cistem procesu s danym SENTINEL_DB_DIR."""
    env = dict(os.environ, SENTINEL_DB_DIR=db_dir, PYTHONPATH=_ROOT)
    return subprocess.run(
        [sys.executable, "-c", "from sentinel import state; print('OK')"],
        capture_output=True, text=True, timeout=120, env=env, cwd=_ROOT)


class TestImportWithoutWritableDb(unittest.TestCase):
    def test_import_survives_unwritable_db_dir(self):
        r = _import_with_db_dir("/proc/nelze-zalozit")
        self.assertIn("OK", r.stdout, f"import spadl:\n{r.stderr[-800:]}")
        self.assertEqual(r.returncode, 0)

    def test_import_works_with_writable_db_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = _import_with_db_dir(tmp)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertTrue(os.path.exists(os.path.join(tmp, "sentinel_state.db")),
                            "se zapisovatelnou cestou ma DB vzniknout")

    def test_import_survives_when_sqlite_cannot_open(self):
        # Presna situace z CI: ani /var/lib/sentinel, ani zalozni LOG_DIR
        # nejsou zapisovatelne. Na vyvojovem stroji zalozni cesta existuje,
        # takze selhani simulujeme na urovni sqlite3.connect.
        code = (
            "import sqlite3\n"
            "def boom(*a, **k): raise sqlite3.OperationalError('unable to open database file')\n"
            "sqlite3.connect = boom\n"
            "from sentinel import state_base as sb\n"
            "print('KEEPER', sb._keeper_conn)\n"
        )
        env = dict(os.environ, PYTHONPATH=_ROOT)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=120, env=env, cwd=_ROOT)
        self.assertEqual(r.returncode, 0,
                         f"import spadl, ackoliv ma selhani keeperu prezit:\n{r.stderr[-800:]}")
        self.assertIn("KEEPER None", r.stdout)

    def test_keeper_is_established_when_possible(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, SENTINEL_DB_DIR=tmp, PYTHONPATH=_ROOT)
            r = subprocess.run(
                [sys.executable, "-c",
                 "from sentinel import state_base as sb; print('KEEPER', sb._keeper_conn is not None)"],
                capture_output=True, text=True, timeout=120, env=env, cwd=_ROOT)
            self.assertIn("KEEPER True", r.stdout, r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()

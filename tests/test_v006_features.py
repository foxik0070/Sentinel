"""
Testy pro funkce přidané ve verzi 2026.06.x:

- save_telemetry_snapshot: data jsou skutečně zapsána do DB (oprava chybějícího INSERT)
- _flush_telemetry_buffer: buffer flush přes background thread
- False Positive Patterns: _is_false_positive() a fnmatch logika
- Issue depends_on: sloupec exists, JSON round-trip
- Socket.IO transport: klient používá polling jako fallback (ne jen websocket)
- Cache-Control: statické soubory mají max-age=31536000

Spuštění:
    python -m pytest tests/test_v006_features.py -v
    python -m unittest tests.test_v006_features -v
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config


# ---------------------------------------------------------------------------
# Telemetrie — save_telemetry_snapshot zapisuje do DB
# ---------------------------------------------------------------------------

class TestTelemetrySave(unittest.TestCase):
    """Ověří, že save_telemetry_snapshot() skutečně vloží řádky do DB."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db_path = self._tmp.name
        # Připravit schéma
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                category TEXT,
                metric TEXT,
                value REAL
            )
        """)
        conn.execute("""
            CREATE TABLE telemetry_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT, metric TEXT, threshold REAL, direction TEXT,
                message TEXT, channel TEXT
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self._db_path)

    def _call_save(self, category, data_dict):
        """Zavolá save_telemetry_snapshot s dočasnou DB."""
        from sentinel import state_issues
        orig_get_conn = state_issues._get_conn
        orig_lock = state_issues.db_lock

        import threading
        fake_lock = threading.Lock()

        def fake_get_conn():
            return sqlite3.connect(self._db_path)

        with patch.object(state_issues, '_get_conn', fake_get_conn), \
             patch.object(state_issues, 'db_lock', fake_lock):
            state_issues.save_telemetry_snapshot(category, data_dict)

    def test_data_written_to_db(self):
        """Základní test — data musí být v tabulce po zavolání."""
        self._call_save("test_cat", {"cpu": 42.5, "mem": 70.0})
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            "SELECT category, metric, value FROM telemetry WHERE category='test_cat'"
        ).fetchall()
        conn.close()
        metrics = {r[1]: r[2] for r in rows}
        self.assertIn("cpu", metrics)
        self.assertIn("mem", metrics)
        self.assertAlmostEqual(metrics["cpu"], 42.5)
        self.assertAlmostEqual(metrics["mem"], 70.0)

    def test_non_numeric_values_skipped(self):
        """Řetězce a None musí být ignorovány bez výjimky."""
        self._call_save("cat", {"ok_val": 1.0, "bad_val": "nope", "none_val": None})
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute("SELECT metric FROM telemetry WHERE category='cat'").fetchall()
        conn.close()
        metrics = [r[0] for r in rows]
        self.assertIn("ok_val", metrics)
        self.assertNotIn("bad_val", metrics)
        self.assertNotIn("none_val", metrics)

    def test_empty_dict_no_crash(self):
        """Prázdný slovník nesmí způsobit výjimku."""
        try:
            self._call_save("empty", {})
        except Exception as e:
            self.fail(f"save_telemetry_snapshot raised {e} for empty dict")

    def test_multiple_calls_accumulate(self):
        """Více volání zapíše více řádků."""
        self._call_save("sensors", {"temp": 55.0})
        self._call_save("sensors", {"temp": 58.0})
        conn = sqlite3.connect(self._db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE category='sensors' AND metric='temp'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)


# ---------------------------------------------------------------------------
# Telemetrie buffer flush
# ---------------------------------------------------------------------------

class TestTelemetryBuffer(unittest.TestCase):
    """Ověří, že _flush_telemetry_buffer() funguje správně."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db_path = self._tmp.name
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, category TEXT, metric TEXT, value REAL
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self._db_path)

    def test_buffer_flush_writes_and_clears(self):
        from sentinel import state_issues
        import threading
        fake_lock = threading.Lock()

        def fake_get_conn():
            return sqlite3.connect(self._db_path)

        with patch.object(state_issues, '_get_conn', fake_get_conn), \
             patch.object(state_issues, 'db_lock', fake_lock), \
             patch.object(state_issues, '_telemetry_buffer',
                          [("2026-06-01T00:00:00Z", "buf_cat", "metric_x", 9.9)]):
            state_issues._flush_telemetry_buffer()

        conn = sqlite3.connect(self._db_path)
        rows = conn.execute("SELECT metric, value FROM telemetry WHERE category='buf_cat'").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "metric_x")
        self.assertAlmostEqual(rows[0][1], 9.9)

    def test_empty_buffer_no_op(self):
        from sentinel import state_issues
        import threading
        fake_lock = threading.Lock()

        def fake_get_conn():
            return sqlite3.connect(self._db_path)

        with patch.object(state_issues, '_get_conn', fake_get_conn), \
             patch.object(state_issues, 'db_lock', fake_lock), \
             patch.object(state_issues, '_telemetry_buffer', []):
            try:
                state_issues._flush_telemetry_buffer()
            except Exception as e:
                self.fail(f"_flush_telemetry_buffer raised {e} on empty buffer")


# ---------------------------------------------------------------------------
# False Positive Patterns — fnmatch logika
# ---------------------------------------------------------------------------

class TestFalsePositiveMatching(unittest.TestCase):
    """Ověří logiku fnmatch párování false positive vzorů."""

    def _check_match(self, host_pat, msg_pat, host, msg):
        import fnmatch
        return fnmatch.fnmatch(host, host_pat) and fnmatch.fnmatch(msg, msg_pat)

    def test_exact_match(self):
        self.assertTrue(self._check_match("node01", "disk error*", "node01", "disk error on /dev/sda"))

    def test_wildcard_host(self):
        self.assertTrue(self._check_match("node*", "*timeout*", "node42", "SSH timeout occurred"))

    def test_no_match_wrong_host(self):
        self.assertFalse(self._check_match("node01", "*", "node02", "anything"))

    def test_no_match_wrong_msg(self):
        self.assertFalse(self._check_match("*", "disk*", "node01", "cpu high"))

    def test_global_plugin_wildcard(self):
        self.assertTrue(self._check_match("*", "*test*", "anyhost", "this is a test message"))

    def test_case_sensitive(self):
        # fnmatch je case-sensitive na Linuxu
        self.assertFalse(self._check_match("Node*", "*", "node01", "msg"))

    def test_is_false_positive_with_db(self):
        """Kompletní test _is_false_positive() s reálnou SQLite DB."""
        from sentinel import api as sentinel_api
        from sentinel.state_base import DB_FILE as _orig_db

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE false_positive_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin_name TEXT, host_pattern TEXT, msg_pattern TEXT,
                hit_count INTEGER DEFAULT 0, created_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO false_positive_patterns (plugin_name, host_pattern, msg_pattern)
            VALUES ('test_plugin', 'node*', '*known issue*')
        """)
        conn.commit()
        conn.close()

        try:
            from sentinel import state_base as _sb
            with patch.object(_sb, 'DB_FILE', db_path):
                result = sentinel_api._is_false_positive({
                    "plugin_name": "test_plugin",
                    "host": "node05",
                    "last_line": "this is a known issue with disk"
                })
            self.assertTrue(result)
        finally:
            os.unlink(db_path)

    def test_is_not_false_positive(self):
        """Zpráva která neodpovídá vzoru není false positive."""
        from sentinel import api as sentinel_api

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE false_positive_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin_name TEXT, host_pattern TEXT, msg_pattern TEXT,
                hit_count INTEGER DEFAULT 0, created_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO false_positive_patterns (plugin_name, host_pattern, msg_pattern)
            VALUES ('storage', 'node01', '*disk error*')
        """)
        conn.commit()
        conn.close()

        try:
            from sentinel import state_base as _sb
            with patch.object(_sb, 'DB_FILE', db_path):
                result = sentinel_api._is_false_positive({
                    "plugin_name": "storage",
                    "host": "node99",   # neodpovídá node01
                    "last_line": "disk error detected"
                })
            self.assertFalse(result)
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Issue depends_on — JSON sloupec
# ---------------------------------------------------------------------------

class TestIssueDependsOn(unittest.TestCase):
    """Ověří, že depends_on sloupec existuje a správně uchovává JSON."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db_path = self._tmp.name
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE problems (
                key TEXT PRIMARY KEY,
                host TEXT,
                depends_on TEXT DEFAULT '[]'
            )
        """)
        conn.execute("INSERT INTO problems (key, host, depends_on) VALUES ('A|test', 'node01', '[]')")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self._db_path)

    def test_depends_on_default_is_empty_json(self):
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("SELECT depends_on FROM problems WHERE key='A|test'").fetchone()
        conn.close()
        deps = json.loads(row[0])
        self.assertIsInstance(deps, list)
        self.assertEqual(len(deps), 0)

    def test_depends_on_json_round_trip(self):
        deps = ["B|dep1", "C|dep2"]
        conn = sqlite3.connect(self._db_path)
        conn.execute("UPDATE problems SET depends_on=? WHERE key='A|test'", (json.dumps(deps),))
        conn.commit()
        row = conn.execute("SELECT depends_on FROM problems WHERE key='A|test'").fetchone()
        conn.close()
        result = json.loads(row[0])
        self.assertEqual(result, deps)

    def test_multiple_deps_stored(self):
        deps = [f"KEY|{i}" for i in range(10)]
        conn = sqlite3.connect(self._db_path)
        conn.execute("UPDATE problems SET depends_on=? WHERE key='A|test'", (json.dumps(deps),))
        conn.commit()
        row = conn.execute("SELECT depends_on FROM problems WHERE key='A|test'").fetchone()
        conn.close()
        self.assertEqual(len(json.loads(row[0])), 10)


# ---------------------------------------------------------------------------
# Socket.IO transport konfigurace
# ---------------------------------------------------------------------------

class TestSocketIOTransport(unittest.TestCase):
    """Ověří, že script-core.js používá polling jako fallback (ne jen websocket)."""

    def _read_script_core(self):
        path = os.path.join(_ROOT, "sentinel", "static", "script-core.js")
        with open(path) as f:
            return f.read()

    def test_polling_transport_present(self):
        src = self._read_script_core()
        self.assertIn("'polling'", src,
                      "Socket.IO musí mít 'polling' jako fallback transport")

    def test_websocket_transport_present(self):
        src = self._read_script_core()
        self.assertIn("'websocket'", src,
                      "Socket.IO musí mít 'websocket' transport")

    def test_polling_before_websocket(self):
        """polling musí být v poli před websocket (fallback-first)."""
        src = self._read_script_core()
        idx_poll = src.find("'polling'")
        idx_ws = src.find("'websocket'")
        self.assertGreater(idx_poll, 0)
        self.assertGreater(idx_ws, 0)
        self.assertLess(idx_poll, idx_ws,
                        "'polling' musí být v poli transports před 'websocket'")

    def test_upgrade_enabled(self):
        src = self._read_script_core()
        self.assertIn("upgrade: true", src,
                      "Socket.IO musí mít upgrade: true pro přechod polling→websocket")


# ---------------------------------------------------------------------------
# Cache-Control hlavičky
# ---------------------------------------------------------------------------

class TestCacheControlHeaders(unittest.TestCase):
    """Ověří, že statické soubory mají dlouhý cache (1 rok)."""

    def _get_cache_header_logic(self):
        from sentinel import chat_service as cs
        import inspect
        src = inspect.getsource(cs.SentinelService._build_app
                                if hasattr(cs.SentinelService, '_build_app')
                                else cs.SentinelService.__init__)
        return src

    def test_max_age_is_one_year(self):
        """Cache-Control pro static musí obsahovat max-age=31536000."""
        path = os.path.join(_ROOT, "sentinel", "chat_service.py")
        with open(path) as f:
            src = f.read()
        self.assertIn("max-age=31536000", src,
                      "Statické soubory musí mít Cache-Control: max-age=31536000")

    def test_immutable_directive(self):
        path = os.path.join(_ROOT, "sentinel", "chat_service.py")
        with open(path) as f:
            src = f.read()
        self.assertIn("immutable", src,
                      "Cache-Control musí obsahovat immutable pro versioned assets")

    def test_no_600_max_age_for_static(self):
        """Stará hodnota max-age=600 nesmí zůstat pro statické soubory."""
        path = os.path.join(_ROOT, "sentinel", "chat_service.py")
        with open(path) as f:
            src = f.read()
        # max-age=600 může být kdekoliv jinde, ale ne u static block
        import re
        static_block = re.search(
            r"if request\.path\.startswith\('/static/'\).*?return resp",
            src, re.DOTALL
        )
        if static_block:
            self.assertNotIn("max-age=600", static_block.group(),
                             "Blok pro static nesmí používat max-age=600")


# ---------------------------------------------------------------------------
# Defer atribut na skriptech
# ---------------------------------------------------------------------------

class TestDeferredScripts(unittest.TestCase):
    """Ověří, že index.html má defer na všech externích skriptech."""

    def _read_template(self):
        path = os.path.join(_ROOT, "sentinel", "templates", "index.html")
        with open(path) as f:
            return f.read()

    def _get_external_scripts(self, src):
        import re
        return re.findall(r'<script[^>]+src=[^>]+>', src)

    def test_all_external_scripts_have_defer(self):
        src = self._read_template()
        scripts = self._get_external_scripts(src)
        self.assertGreater(len(scripts), 0, "Žádné externí scripty nalezeny")
        for tag in scripts:
            self.assertIn("defer", tag,
                          f"Script tag nemá defer: {tag}")

    def test_critical_scripts_deferred(self):
        import re
        src = self._read_template()
        # Najít pouze <script src="..."> tagy (ne preload linky)
        for fname in ("socket.io.js", "script-core.min.js", "script-ui.min.js"):
            pattern = rf'<script[^>]+{re.escape(fname)}[^>]*>'
            match = re.search(pattern, src)
            self.assertIsNotNone(match, f"<script src> pro {fname} nenalezen v template")
            self.assertIn("defer", match.group(), f"{fname} nemá defer atribut")

    def test_preload_hints_present(self):
        src = self._read_template()
        self.assertIn('rel="preload"', src,
                      "Template musí obsahovat preload hints pro kritické soubory")


if __name__ == "__main__":
    unittest.main(verbosity=2)

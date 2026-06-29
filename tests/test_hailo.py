"""
Tests for Hailo AI HAT 2+ integration — config, ollama_service routing, hailo_models.py args,
MODEL_DB structure, TUI helper functions.

Run:
    python -m pytest tests/test_hailo.py -v
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config


class TestHailoOllamaConfig(unittest.TestCase):

    def test_hailo_ollama_url_points_to_port_8000(self):
        self.assertIn("8000", config.HAILO_OLLAMA_URL)

    def test_default_model_is_qwen25_coder(self):
        self.assertEqual(config.HAILO_OLLAMA_MODEL, "qwen2.5-coder:1.5b")

    def test_hailo_and_ollama_urls_distinct(self):
        """Hailo-ollama (port 8000) a CPU ollama (11434) musí mít různé URL."""
        self.assertNotEqual(config.HAILO_OLLAMA_URL, config.OLLAMA_URL)


class TestHailoOllamaRouting(unittest.TestCase):
    """ollama_service.process_single_task() routuje na hailo-ollama když enabled."""

    def _fake_response(self, content="test response"):
        resp = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        resp.raise_for_status = lambda: None
        return resp

    def test_hailo_ollama_path_used_when_enabled(self):
        from sentinel import ollama_service, utils, actions
        orig_enabled = config.HAILO_OLLAMA_ENABLED
        orig_model = config.HAILO_OLLAMA_MODEL
        orig_url = config.HAILO_OLLAMA_URL
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_MODEL = "qwen3:1.7b"
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"

        posted_to = []

        def fake_post(url, **kw):
            posted_to.append(url)
            return self._fake_response()

        with patch("requests.post", side_effect=fake_post), \
             patch.object(utils, "send_to_teams", return_value=None), \
             patch.object(utils, "ollama_logger") as mock_log:
            mock_log.info = lambda *a, **kw: None
            ollama_service.process_single_task({"text": "test", "channel": "general"})

        config.HAILO_OLLAMA_ENABLED = orig_enabled
        config.HAILO_OLLAMA_MODEL = orig_model
        config.HAILO_OLLAMA_URL = orig_url

        self.assertTrue(posted_to, "requests.post musí být zavolán")
        self.assertIn("8000", posted_to[0])

    def test_standard_ollama_path_when_hailo_disabled(self):
        from sentinel import ollama_service, utils
        orig_enabled = config.HAILO_OLLAMA_ENABLED
        orig_args = config.ARGS.copy()
        config.HAILO_OLLAMA_ENABLED = False
        config.ARGS["EXTERNAL_OLLAMA"] = True

        posted_to = []

        def fake_post(url, **kw):
            posted_to.append(url)
            return self._fake_response()

        with patch("requests.post", side_effect=fake_post), \
             patch.object(utils, "send_to_teams", return_value=None), \
             patch.object(utils, "ollama_logger") as mock_log:
            mock_log.info = lambda *a, **kw: None
            ollama_service.process_single_task({"text": "test", "channel": "general"})

        config.HAILO_OLLAMA_ENABLED = orig_enabled
        config.ARGS = orig_args

        self.assertTrue(posted_to)
        self.assertNotIn("8000", posted_to[0])


class TestHailoModelsArgs(unittest.TestCase):
    """hailo_models.py argparse — URL a models-dir konfigurace."""

    def _parse(self, argv=None, env_url=None, env_models=None):
        """Pomocná funkce — simuluje _parse_args() s danými env hodnotami."""
        import argparse
        env_url = env_url or "http://127.0.0.1:8000"
        env_models = env_models or "/mnt/nvme/hailo_system/models"
        p = argparse.ArgumentParser()
        p.add_argument("--url", default=env_url)
        p.add_argument("--models-dir", default=env_models)
        return p.parse_known_args(argv or [])[0]

    def test_default_url_contains_port_8000(self):
        args = self._parse()
        self.assertIn("8000", args.url)

    def test_default_models_dir_on_nvme(self):
        args = self._parse()
        self.assertIn("nvme", args.models_dir)

    def test_env_url_override(self):
        args = self._parse(env_url="http://10.0.0.5:8000")
        self.assertEqual(args.url, "http://10.0.0.5:8000")

    def test_cli_url_override(self):
        args = self._parse(argv=["--url", "http://192.168.1.50:8000"])
        self.assertEqual(args.url, "http://192.168.1.50:8000")

    def test_cli_models_dir_override(self):
        args = self._parse(argv=["--models-dir", "/data/models"])
        self.assertEqual(args.models_dir, "/data/models")


class TestSentinelInitHailoDetect(unittest.TestCase):
    """sentinel_init.detect_hailo() — základní kontrakty."""

    def test_returns_dict_with_expected_keys(self):
        import sentinel_init
        # Mock vše co potřebuje detekce (žádný Hailo HW v testovacím prostředí)
        with patch("subprocess.run") as mock_run, \
             patch("pathlib.Path.glob", return_value=[]), \
             patch("pathlib.Path.exists", return_value=False):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = sentinel_init.detect_hailo()

        self.assertIn('detected', result)
        self.assertIn('is_10h', result)
        self.assertIn('hailo_ollama_bin', result)
        self.assertIn('active', result)

    def test_no_hailo_hw_returns_not_detected(self):
        import sentinel_init
        with patch("subprocess.run") as mock_run, \
             patch("pathlib.Path.glob", return_value=[]), \
             patch("pathlib.Path.exists", return_value=False):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = sentinel_init.detect_hailo()

        self.assertFalse(result['detected'])
        self.assertFalse(result['is_10h'])
        self.assertEqual(result['hailo_ollama_bin'], "")

    def test_hailo_ollama_bin_detection(self):
        import sentinel_init
        from pathlib import Path

        def fake_exists(self):
            return str(self) == "/usr/bin/hailo-ollama"

        with patch("subprocess.run") as mock_run, \
             patch("pathlib.Path.glob", return_value=[Path("/dev/hailo0")]), \
             patch.object(Path, "exists", fake_exists):
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = sentinel_init.detect_hailo()

        self.assertEqual(result['hailo_ollama_bin'], "/usr/bin/hailo-ollama")


class TestHailoModelsDB(unittest.TestCase):
    """MODEL_DB struktura — kontrakty pro nová pole size_gb (float) a tps (float)."""

    def setUp(self):
        import importlib, types
        # hailo_models.py parsuje argv při importu — neutralizujeme
        self._orig_argv = sys.argv[:]
        sys.argv = [sys.argv[0]]
        spec = importlib.util.spec_from_file_location(
            "hailo_models", os.path.join(_ROOT, "hailo_models.py")
        )
        self.hm = importlib.util.module_from_spec(spec)
        with patch("subprocess.check_output", side_effect=Exception("no hw")):
            spec.loader.exec_module(self.hm)

    def tearDown(self):
        sys.argv = self._orig_argv

    def test_all_entries_have_tps_float(self):
        for name, det in self.hm.MODEL_DB.items():
            self.assertIsInstance(det['tps'], (int, float),
                                  f"{name}: tps musí být číslo, ne string")

    def test_all_entries_have_size_gb_float(self):
        for name, det in self.hm.MODEL_DB.items():
            self.assertIsInstance(det['size_gb'], (int, float),
                                  f"{name}: size_gb musí být číslo")
            self.assertGreater(det['size_gb'], 0, f"{name}: size_gb musí být > 0")

    def test_all_entries_have_required_keys(self):
        required = {'type', 'size', 'size_gb', 'tps', 'release', 'ctx', 'focus', 'detail'}
        for name, det in self.hm.MODEL_DB.items():
            missing = required - det.keys()
            self.assertFalse(missing, f"{name}: chybí klíče {missing}")

    def test_type_colors_covers_all_types(self):
        all_types = {det['type'] for det in self.hm.MODEL_DB.values()}
        for t in all_types:
            self.assertIn(t, self.hm.TYPE_COLORS,
                          f"TYPE_COLORS chybí mapování pro typ '{t}'")

    def test_whisper_tiny_fastest(self):
        tps_vals = {n: d['tps'] for n, d in self.hm.MODEL_DB.items()}
        fastest = max(tps_vals, key=tps_vals.get)
        self.assertEqual(fastest, "whisper-tiny")

    def test_bar_helper_full_and_empty(self):
        self.assertEqual(self.hm.bar(100, 10), '█' * 10)
        self.assertEqual(self.hm.bar(0, 10),   '░' * 10)

    def test_bar_helper_half(self):
        result = self.hm.bar(50, 10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.startswith('█'))
        self.assertTrue(result.endswith('░'))

    def test_disk_usage_mb_returns_float(self):
        with patch("os.listdir", return_value=[]), \
             patch("os.path.isfile", return_value=False):
            result = self.hm.disk_usage_mb()
        self.assertIsInstance(result, float)
        self.assertEqual(result, 0.0)

    def test_disk_usage_mb_sums_files(self):
        with patch("os.listdir", return_value=["a.hef", "b.hef"]), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=1024 * 1024):
            result = self.hm.disk_usage_mb()
        self.assertAlmostEqual(result, 2.0)

    def test_get_hailo_service_status_offline_on_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("refused")):
            result = self.hm.get_hailo_service_status()
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

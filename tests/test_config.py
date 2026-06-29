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


if __name__ == "__main__":
    unittest.main(verbosity=2)

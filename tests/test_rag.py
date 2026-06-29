"""
Tests for sentinel.rag — embedding URL selection, 404 fallback to text search.

Run:
    python -m pytest tests/test_rag.py -v
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config


class TestEmbeddingUrlSelection(unittest.TestCase):
    """_get_embedding_ollama() musí použít EMBEDDING_OLLAMA_URL pokud je nastavena."""

    def _make_engine(self):
        from sentinel import rag
        engine = rag.RAGEngine.__new__(rag.RAGEngine)
        engine.client = None
        engine.collection = None
        engine.kb_chunks = []
        engine._idf = {}
        engine.stats = {"model_name": "nomic-embed-text", "total_embeddings": 0,
                        "last_latency": 0.0, "latencies": []}
        engine._hailo = None
        return engine

    def test_uses_embedding_url_when_set(self):
        from sentinel import rag
        engine = self._make_engine()
        captured = {}

        def fake_post(url, **kw):
            captured['url'] = url
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
            resp.raise_for_status = lambda: None
            return resp

        orig_emb_url = config.EMBEDDING_OLLAMA_URL
        config.EMBEDDING_OLLAMA_URL = "http://cpu-ollama:11434"
        try:
            with patch("requests.post", side_effect=fake_post):
                engine._get_embedding_ollama("test text")
        finally:
            config.EMBEDDING_OLLAMA_URL = orig_emb_url

        self.assertIn("cpu-ollama:11434", captured.get('url', ''))

    def test_falls_back_to_ollama_url_when_embedding_url_empty(self):
        from sentinel import rag
        engine = self._make_engine()
        captured = {}

        def fake_post(url, **kw):
            captured['url'] = url
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"embedding": [0.1]}
            resp.raise_for_status = lambda: None
            return resp

        orig_emb = config.EMBEDDING_OLLAMA_URL
        orig_oll = config.OLLAMA_URL
        config.EMBEDDING_OLLAMA_URL = ""
        config.OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
        try:
            with patch("requests.post", side_effect=fake_post):
                engine._get_embedding_ollama("test")
        finally:
            config.EMBEDDING_OLLAMA_URL = orig_emb
            config.OLLAMA_URL = orig_oll

        self.assertIn("11434", captured.get('url', ''))
        # OLLAMA_URL contains /v1/ → code uses OpenAI-compatible /v1/embeddings endpoint
        self.assertIn("/v1/embeddings", captured.get('url', ''))

    def test_404_disables_vector_db(self):
        """Při HTTP 404 musí _get_embedding_ollama vypnout client (fallback na text search)."""
        from sentinel import rag
        engine = self._make_engine()
        engine.client = MagicMock()  # simulace aktivního klienta

        def fake_post(url, **kw):
            resp = MagicMock()
            resp.status_code = 404
            return resp

        config_emb_orig = config.EMBEDDING_OLLAMA_URL
        config.EMBEDDING_OLLAMA_URL = ""
        try:
            with patch("requests.post", side_effect=fake_post):
                result = engine._get_embedding_ollama("text")
        finally:
            config.EMBEDDING_OLLAMA_URL = config_emb_orig

        self.assertIsNone(result)
        self.assertIsNone(engine.client)

    def test_text_fallback_returns_result(self):
        from sentinel import rag
        engine = self._make_engine()
        engine.kb_chunks = [
            "SSH authentication failure detected on server",
            "CPU temperature warning: 85°C",
            "Disk usage at 95% on /var/log",
        ]
        engine._build_idf_index()
        result = engine._text_fallback("SSH authentication", limit=2)
        self.assertIn("SSH", result)

    def test_text_fallback_empty_kb(self):
        from sentinel import rag
        engine = self._make_engine()
        engine.kb_chunks = []
        result = engine._text_fallback("anything")
        self.assertIn("Empty", result)


class TestHailoEmbedderFallback(unittest.TestCase):
    """Hailo embedder selhal → transparentní fallback na Ollama."""

    def test_hailo_failure_falls_back(self):
        from sentinel import rag
        engine = rag.RAGEngine.__new__(rag.RAGEngine)
        engine.client = MagicMock()
        engine.collection = None
        engine.kb_chunks = []
        engine.stats = {"model_name": "hailo", "total_embeddings": 0,
                        "last_latency": 0.0, "latencies": []}

        hailo_mock = MagicMock()
        hailo_mock._ready = True
        hailo_mock.embed.return_value = None  # Hailo selhal
        engine._hailo = hailo_mock

        ollama_called = []

        def fake_ollama(text):
            ollama_called.append(text)
            return [0.1, 0.2]

        engine._get_embedding_ollama = fake_ollama
        result = engine._get_embedding("test text")
        # Fallback na Ollama musí být zavolán
        self.assertTrue(ollama_called)


if __name__ == "__main__":
    unittest.main(verbosity=2)

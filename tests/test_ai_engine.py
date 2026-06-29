"""
Tests for AI engine routing — execute_ollama() v chat_service, monitor URL, NPU detection.

Run:
    python -m pytest tests/test_ai_engine.py -v
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sentinel import config


def _fake_hailo_response(content="test"):
    resp = MagicMock()
    resp.status_code = 200
    # /api/chat format (native Ollama) — used since execute_ollama switched from /v1/chat/completions
    resp.json.return_value = {"message": {"content": content}}
    resp.text = content
    return resp


def _fake_ollama_response(content="test"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    resp.text = content
    return resp


class TestExecuteOllamaRouting(unittest.TestCase):
    """execute_ollama() v chat_service routuje správně dle HAILO_OLLAMA_ENABLED."""

    def _make_service(self):
        """Vytvoří ChatService instanci bez spuštění Flask serveru."""
        from sentinel import chat_service
        svc = chat_service.ChatService.__new__(chat_service.ChatService)
        import threading, collections
        svc.metrics = {
            "ai_requests": 0,
            "ai_errors": 0,
            "ai_latency_history": collections.deque(maxlen=50),
            "active_users": set(),
        }
        svc.chat_queue_depth = 0
        svc.llm_semaphore = threading.Semaphore(1)
        return svc

    def setUp(self):
        self._orig = {k: getattr(config, k) for k in
                      ('HAILO_OLLAMA_ENABLED', 'HAILO_OLLAMA_MODEL', 'HAILO_OLLAMA_URL',
                       'OLLAMA_MODEL', 'OLLAMA_URL', 'OLLAMA_API_KEY', 'ARGS')}
        config.ARGS = config.ARGS.copy()

    def tearDown(self):
        for k, v in self._orig.items():
            try:
                setattr(config, k, v)
            except AttributeError:
                pass

    def test_hailo_route_when_enabled(self):
        """Když HAILO_OLLAMA_ENABLED=True, POST jde na hailo-ollama URL (port 8000)."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_MODEL = "qwen3:1.7b"
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        svc = self._make_service()
        posted_to = []

        def fake_post(url, **kw):
            posted_to.append(url)
            return _fake_hailo_response("answer")

        with patch("requests.post", side_effect=fake_post):
            result = svc.execute_ollama("test prompt")

        self.assertTrue(posted_to, "requests.post musí být zavolán")
        self.assertIn("8000", posted_to[0], "POST musí jít na hailo-ollama port 8000")
        self.assertEqual(result, "answer")

    def test_hailo_model_in_payload(self):
        """Payload poslaný na hailo-ollama musí obsahovat HAILO_OLLAMA_MODEL."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_MODEL = "llama3.2:1b"
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        svc = self._make_service()
        payloads = []

        def fake_post(url, json=None, **kw):
            payloads.append(json or {})
            return _fake_hailo_response("ok")

        with patch("requests.post", side_effect=fake_post):
            svc.execute_ollama("test")

        self.assertTrue(payloads)
        self.assertEqual(payloads[0].get("model"), "llama3.2:1b")

    def test_cpu_ollama_route_when_hailo_disabled(self):
        """Když HAILO_OLLAMA_ENABLED=False, POST jde na OLLAMA_URL."""
        config.HAILO_OLLAMA_ENABLED = False
        config.ARGS["EXTERNAL_OLLAMA"] = True
        config.OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
        config.OLLAMA_MODEL = "nomic-embed-text"
        svc = self._make_service()
        posted_to = []

        def fake_post(url, **kw):
            posted_to.append(url)
            return _fake_ollama_response("cpu answer")

        with patch("requests.post", side_effect=fake_post):
            result = svc.execute_ollama("test prompt")

        self.assertTrue(posted_to)
        self.assertIn("11434", posted_to[0], "POST musí jít na standard ollama port 11434")
        self.assertNotIn("8000", posted_to[0])

    def test_multiline_prompt_sanitized_for_hailo(self):
        """Hailo-ollama bug: LF v content způsobí parse_error.101. Prompt musí být sanitizován."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        svc = self._make_service()
        captured_payloads = []

        def fake_post(url, json=None, **kw):
            captured_payloads.append(json or {})
            return _fake_hailo_response("ok")

        multiline_prompt = "Role: Analyst.\nHistory:\nUser: test\n\nTask: answer."
        with patch("requests.post", side_effect=fake_post):
            svc.execute_ollama(multiline_prompt)

        self.assertTrue(captured_payloads)
        sent_content = captured_payloads[0]["messages"][0]["content"]
        self.assertNotIn("\n", sent_content, "Prompt odeslaný na hailo-ollama nesmí obsahovat LF")
        self.assertNotIn("\r", sent_content)

    def test_hailo_error_returns_error_string(self):
        """Chyba hailo-ollama vrátí chybový string, nehodí výjimku."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        svc = self._make_service()

        def fake_post(url, **kw):
            raise ConnectionError("NPU unavailable")

        with patch("requests.post", side_effect=fake_post):
            result = svc.execute_ollama("test")

        self.assertIn("Chyba", result)

    def test_latency_recorded(self):
        """Po úspěšném volání se latence zaznamená do ai_latency_history."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        svc = self._make_service()

        with patch("requests.post", return_value=_fake_hailo_response("ok")):
            svc.execute_ollama("test")

        self.assertEqual(len(svc.metrics["ai_latency_history"]), 1)
        self.assertGreater(svc.metrics["ai_latency_history"][0], 0)

    def test_request_counter_incremented(self):
        """Po každém volání se zvýší ai_requests."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        svc = self._make_service()

        with patch("requests.post", return_value=_fake_hailo_response("ok")):
            svc.execute_ollama("one")
            svc.execute_ollama("two")

        self.assertEqual(svc.metrics["ai_requests"], 2)


class TestMonitorUrl(unittest.TestCase):
    """ollama_monitor() používá správný endpoint pro hailo-ollama."""

    def setUp(self):
        self._orig = {k: getattr(config, k) for k in
                      ('HAILO_OLLAMA_ENABLED', 'HAILO_OLLAMA_URL', 'OLLAMA_URL', 'ARGS')}
        config.ARGS = config.ARGS.copy()

    def tearDown(self):
        for k, v in self._orig.items():
            try:
                setattr(config, k, v)
            except AttributeError:
                pass

    def test_hailo_monitor_uses_api_tags(self):
        """Když HAILO_OLLAMA_ENABLED=True, monitor volá /api/tags (ne /v1/models)."""
        config.HAILO_OLLAMA_ENABLED = True
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"

        from sentinel import ollama_service, state, utils
        checked_urls = []

        def fake_get(url, **kw):
            checked_urls.append(url)
            r = MagicMock()
            r.status_code = 200
            return r

        # Spustit jeden průchod smyčky monitoringu
        with patch("requests.get", side_effect=fake_get), \
             patch.object(state.shutdown_event, "is_set", side_effect=[False, True]), \
             patch.object(utils, "log_message"):
            try:
                ollama_service.ollama_monitor(interval=1)
            except StopIteration:
                pass

        self.assertTrue(checked_urls, "requests.get musí být zavolán")
        self.assertIn("/api/tags", checked_urls[0])
        self.assertNotIn("/v1/models", checked_urls[0])


class TestNpuDetection(unittest.TestCase):
    """hailo_active detekuje NPU přes hailo1x_pci modul (Hailo-10H) i /dev/hailo0 (Hailo-8/8L)."""

    def test_hailo0_device_detected(self):
        """Když /dev/hailo0 existuje, hailo_active = True."""
        with patch("os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == '/dev/hailo0'
            result = (os.path.exists('/dev/hailo0') or
                      os.path.exists('/sys/module/hailo1x_pci'))
        self.assertTrue(result)

    def test_hailo1x_module_detected(self):
        """Když /sys/module/hailo1x_pci existuje (Hailo-10H), hailo_active = True."""
        with patch("os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == '/sys/module/hailo1x_pci'
            result = (os.path.exists('/dev/hailo0') or
                      os.path.exists('/sys/module/hailo1x_pci'))
        self.assertTrue(result)

    def test_no_hailo_hardware(self):
        """Bez Hailo hardware hailo_active = False."""
        with patch("os.path.exists", return_value=False):
            result = (os.path.exists('/dev/hailo0') or
                      os.path.exists('/sys/module/hailo1x_pci'))
        self.assertFalse(result)


class TestEmbeddingUrl(unittest.TestCase):
    """EMBEDDING_OLLAMA_URL izoluje embedding provoz od LLM provozu."""

    def setUp(self):
        self._orig = {k: getattr(config, k) for k in
                      ('EMBEDDING_OLLAMA_URL', 'OLLAMA_URL')}

    def tearDown(self):
        for k, v in self._orig.items():
            try:
                setattr(config, k, v)
            except AttributeError:
                pass

    def test_embedding_url_used_when_set(self):
        """Když EMBEDDING_OLLAMA_URL je nastaven, RAG ho použije pro embeddings."""
        config.EMBEDDING_OLLAMA_URL = "http://localhost:11434"
        from sentinel import rag
        emb_base = getattr(config, 'EMBEDDING_OLLAMA_URL', '') or ''
        self.assertEqual(emb_base, "http://localhost:11434")

    def test_embedding_url_falls_back_to_ollama_url(self):
        """Když EMBEDDING_OLLAMA_URL je prázdný, odvodí se z OLLAMA_URL."""
        config.EMBEDDING_OLLAMA_URL = ""
        config.OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
        emb_base = getattr(config, 'EMBEDDING_OLLAMA_URL', '') or ''
        if not emb_base:
            emb_base = config.OLLAMA_URL.replace('/v1/chat/completions', '').rstrip('/')
        self.assertEqual(emb_base, "http://localhost:11434")

    def test_embedding_independent_from_hailo_url(self):
        """I když hailo-ollama je enabled, embedding URL ukazuje na CPU ollama (:11434)."""
        config.EMBEDDING_OLLAMA_URL = "http://localhost:11434"
        config.HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
        self.assertNotEqual(config.EMBEDDING_OLLAMA_URL,
                            config.HAILO_OLLAMA_URL.replace('/v1/chat/completions', ''))


@unittest.skipUnless(
    os.environ.get("SENTINEL_LIVE_TESTS") == "1",
    "Live tests disabled — set SENTINEL_LIVE_TESTS=1 to run"
)
class TestHailoOllamaLive(unittest.TestCase):
    """Live integration testy — volají skutečnou hailo-ollama instanci.
    Spustit: SENTINEL_LIVE_TESTS=1 python -m pytest tests/test_ai_engine.py::TestHailoOllamaLive -v
    """

    def test_api_tags_reachable(self):
        """hailo-ollama /api/tags vrací seznam modelů."""
        import requests
        r = requests.get("http://localhost:8000/api/tags", timeout=5)
        self.assertEqual(r.status_code, 200)
        models = [m['name'] for m in r.json().get('models', [])]
        self.assertGreater(len(models), 0, "Musí být aspoň jeden model")

    def test_llama32_inference(self):
        """llama3.2:1b na hailo-ollama vrací smysluplnou odpověď."""
        import requests, time
        start = time.time()
        r = requests.post("http://localhost:8000/v1/chat/completions",
                          json={"model": "llama3.2:1b",
                                "messages": [{"role": "user", "content": "Say OK"}],
                                "stream": False},
                          timeout=60)
        elapsed = round(time.time() - start, 2)
        self.assertEqual(r.status_code, 200)
        content = r.json()["choices"][0]["message"]["content"]
        self.assertGreater(len(content), 0)
        print(f"\n  llama3.2:1b latency: {elapsed}s | response: {content[:80]}")

    def test_embedding_via_cpu_ollama(self):
        """nomic-embed-text na CPU ollama (:11434) vrací embedding vektor."""
        import requests
        r = requests.post("http://localhost:11434/api/embeddings",
                          json={"model": "nomic-embed-text", "prompt": "test"},
                          timeout=15)
        self.assertEqual(r.status_code, 200)
        emb = r.json().get("embedding", [])
        self.assertGreater(len(emb), 0, "Embedding musí mít nenulovou délku")


if __name__ == "__main__":
    unittest.main(verbosity=2)

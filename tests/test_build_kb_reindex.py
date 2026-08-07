"""
Tests pro build_kb.request_reindex() — po přestavbě KB si build_kb vyžádá
re-index sám (POST /api/rag/reindex), nespoléhá na filesystem watcher.

Run:
    python -m pytest tests/test_build_kb_reindex.py -v
    python -m unittest tests.test_build_kb_reindex -v
"""
import io
import os
import sys
import tempfile
import unittest
import urllib.error

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import build_kb


class _FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def read(self):
        return b'{"status": "ok"}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RequestReindexTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_path = os.path.join(self.tmp.name, "client_api_key")
        self.cfg_path = os.path.join(self.tmp.name, "config.yaml")
        with open(self.key_path, "w") as f:
            f.write("a" * 64 + "\n")
        with open(self.cfg_path, "w") as f:
            f.write("web:\n  port: 5099\n")

        self._orig = (build_kb.CLIENT_KEY_PATH, build_kb.SENTINEL_CONFIG,
                      build_kb.urllib.request.urlopen)
        build_kb.CLIENT_KEY_PATH = self.key_path
        build_kb.SENTINEL_CONFIG = self.cfg_path

        self.requests = []

    def tearDown(self):
        (build_kb.CLIENT_KEY_PATH, build_kb.SENTINEL_CONFIG,
         build_kb.urllib.request.urlopen) = self._orig
        self.tmp.cleanup()

    def _install_urlopen(self, result):
        def fake_urlopen(req, timeout=None):
            self.requests.append(req)
            if isinstance(result, Exception):
                raise result
            return result
        build_kb.urllib.request.urlopen = fake_urlopen

    def test_posts_to_local_api_with_key(self):
        self._install_urlopen(_FakeResponse(200))
        self.assertTrue(build_kb.request_reindex())
        self.assertEqual(len(self.requests), 1)
        req = self.requests[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:5099/api/rag/reindex")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("X-api-key"), "a" * 64)

    def test_port_falls_back_to_default(self):
        with open(self.cfg_path, "w") as f:
            f.write("logs_dir: /var/log\n")
        self._install_urlopen(_FakeResponse(200))
        build_kb.request_reindex()
        self.assertEqual(self.requests[0].full_url,
                         "http://127.0.0.1:5050/api/rag/reindex")

    def test_missing_key_is_not_fatal(self):
        os.unlink(self.key_path)
        self._install_urlopen(_FakeResponse(200))
        self.assertFalse(build_kb.request_reindex())
        self.assertEqual(self.requests, [])

    def test_sentinel_down_is_not_fatal(self):
        self._install_urlopen(OSError("Connection refused"))
        self.assertFalse(build_kb.request_reindex())

    def test_http_error_is_not_fatal(self):
        self._install_urlopen(urllib.error.HTTPError(
            "http://127.0.0.1:5099/api/rag/reindex", 403, "Forbidden", {},
            io.BytesIO(b"")))
        self.assertFalse(build_kb.request_reindex())


class BuildTriggersReindexTest(unittest.TestCase):
    """Zápis KB musí reindex vyžádat, dry-run ne."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "docs")
        os.makedirs(self.src)
        with open(os.path.join(self.src, "a.md"), "w") as f:
            f.write("# Test\n\nObsah pro knowledge base.\n")
        self.out = os.path.join(self.tmp.name, "knowledge_base.txt")

        self.called = []
        self._orig = build_kb.request_reindex
        build_kb.request_reindex = lambda: self.called.append(1) or True

    def tearDown(self):
        build_kb.request_reindex = self._orig
        self.tmp.cleanup()

    def test_build_requests_reindex(self):
        build_kb.build_knowledge_base(source_dirs=[self.src],
                                      output_file=self.out,
                                      include_meta=False)
        self.assertTrue(os.path.exists(self.out))
        self.assertEqual(len(self.called), 1)

    def test_dry_run_does_not_request_reindex(self):
        build_kb.build_knowledge_base(source_dirs=[self.src],
                                      output_file=self.out,
                                      include_meta=False, dry_run=True)
        self.assertEqual(self.called, [])


if __name__ == "__main__":
    unittest.main()

"""
Tests pro hot-reload KB — ConfigHandler musí zachytit i atomický zápis
(os.replace → IN_MOVED_TO) a musí sledovat adresář KB, který leží mimo
adresář config.yaml.

Run:
    python -m pytest tests/test_kb_hotreload.py -v
    python -m unittest tests.test_kb_hotreload -v
"""
import os
import sys
import tempfile
import threading
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from watchdog.events import (FileCreatedEvent, FileModifiedEvent,
                             FileMovedEvent)

from sentinel import config, watcher


class _FakeRag:
    """Náhrada za rag.rag_system — zaznamená, že reindex proběhl."""

    def __init__(self):
        self.event = threading.Event()
        self.calls = 0

    def ingest_knowledge_base(self):
        self.calls += 1
        self.event.set()

    def wait(self, timeout=3.0):
        return self.event.wait(timeout)


class _KBFixture(unittest.TestCase):
    """KB leží v jiném adresáři než config.yaml — jako v reálném deployi."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.cfg_dir = os.path.join(base, "etc", "sentinel")
        self.kb_dir = os.path.join(base, "opt", "Sentinel")
        os.makedirs(self.cfg_dir)
        os.makedirs(self.kb_dir)

        self.cfg_path = os.path.join(self.cfg_dir, "config.yaml")
        self.kb_path = os.path.join(self.kb_dir, "knowledge_base.txt")
        with open(self.cfg_path, "w") as f:
            f.write("web:\n  port: 5050\n")
        with open(self.kb_path, "w") as f:
            f.write("<<<SENTINEL_ENTRY>>>\n")

        self._orig = (config.CONFIG_PATH, config.KB_FILE_PATH)
        config.CONFIG_PATH = self.cfg_path
        config.KB_FILE_PATH = self.kb_path

        self.fake_rag = _FakeRag()
        self._orig_rag = getattr(watcher.rag, "rag_system", None)
        watcher.rag.rag_system = self.fake_rag

        # config větev nesmí sahat na reálný config/pluginy
        self.cfg_reloads = []
        self._orig_load = config.load_config
        self._orig_compile = watcher.compile_patterns
        self._orig_plugins = watcher.plugin_manager.load_plugins
        config.load_config = lambda *a, **k: self.cfg_reloads.append(1)
        watcher.compile_patterns = lambda *a, **k: None
        watcher.plugin_manager.load_plugins = lambda *a, **k: None

        self.handler = watcher.ConfigHandler()
        self.handler.debounce_interval = 0.0

    def tearDown(self):
        config.CONFIG_PATH, config.KB_FILE_PATH = self._orig
        watcher.rag.rag_system = self._orig_rag
        config.load_config = self._orig_load
        watcher.compile_patterns = self._orig_compile
        watcher.plugin_manager.load_plugins = self._orig_plugins
        self.tmp.cleanup()


class KBHotReloadTest(_KBFixture):
    """Routing událostí ve ConfigHandler."""

    # ── KB ────────────────────────────────────────────────────────────────
    def test_atomic_replace_triggers_reindex(self):
        """os.replace() generuje IN_MOVED_TO — musí spustit reindex."""
        tmp_src = self.kb_path + ".tmp"
        self.handler.on_moved(FileMovedEvent(tmp_src, self.kb_path))
        self.assertTrue(self.fake_rag.wait(), "reindex po atomickém zápisu nevystřelil")

    def test_plain_write_triggers_reindex(self):
        self.handler.on_modified(FileModifiedEvent(self.kb_path))
        self.assertTrue(self.fake_rag.wait(), "reindex po obyčejném zápisu nevystřelil")

    def test_created_triggers_reindex(self):
        self.handler.on_created(FileCreatedEvent(self.kb_path))
        self.assertTrue(self.fake_rag.wait(), "reindex po vytvoření KB nevystřelil")

    def test_temp_file_ignored(self):
        """Mezisoubor atomického zápisu nesmí spustit reindex."""
        self.handler.on_modified(FileModifiedEvent(self.kb_path + ".tmp"))
        self.assertFalse(self.fake_rag.wait(0.3), "reindex vystřelil na .tmp souboru")

    # ── config ────────────────────────────────────────────────────────────
    def test_config_atomic_replace_triggers_reload(self):
        """ansible/sed -i zapisují configy taky přes rename."""
        self.handler.on_moved(FileMovedEvent(self.cfg_path + ".tmp", self.cfg_path))
        self.assertEqual(len(self.cfg_reloads), 1)

    def test_stray_config_yaml_outside_cfg_dir_ignored(self):
        """config.yaml ležící v adresáři KB (vývojový strom) nesmí reloadovat."""
        stray = os.path.join(self.kb_dir, "config.yaml")
        with open(stray, "w") as f:
            f.write("web:\n")
        self.handler.on_modified(FileModifiedEvent(stray))
        self.assertEqual(self.cfg_reloads, [])

    def test_debounce_is_per_target(self):
        """Uložení configu nesmí umlčet reindex KB (sdílený debounce)."""
        self.handler.debounce_interval = 30.0
        self.handler.on_modified(FileModifiedEvent(self.cfg_path))
        self.handler.on_modified(FileModifiedEvent(self.kb_path))
        self.assertEqual(len(self.cfg_reloads), 1)
        self.assertTrue(self.fake_rag.wait(), "KB event spolkl config debounce")

    def test_debounce_suppresses_event_storm(self):
        """Atomický zápis vyprodukuje created+moved+modified — reindex jen jednou."""
        self.handler.debounce_interval = 30.0
        self.handler.on_created(FileCreatedEvent(self.kb_path))
        self.handler.on_moved(FileMovedEvent(self.kb_path + ".tmp", self.kb_path))
        self.handler.on_modified(FileModifiedEvent(self.kb_path))
        self.assertTrue(self.fake_rag.wait())
        time.sleep(0.3)
        self.assertEqual(self.fake_rag.calls, 1)


class KBObserverIntegrationTest(_KBFixture):
    """End-to-end: reálný inotify Observer nad adresářem KB + os.replace."""

    def test_observer_catches_atomic_replace(self):
        from watchdog.observers import Observer

        observer = Observer()
        # stejné plánování jako v sentinel/__main__.py
        observer.schedule(self.handler, self.cfg_dir, recursive=False)
        observer.schedule(self.handler, self.kb_dir, recursive=False)
        observer.start()
        try:
            time.sleep(0.3)
            tmp_src = self.kb_path + ".tmp"
            with open(tmp_src, "w") as f:
                f.write("<<<SENTINEL_ENTRY>>>\nnovy obsah\n")
            os.replace(tmp_src, self.kb_path)
            self.assertTrue(self.fake_rag.wait(5.0),
                            "observer nezachytil os.replace() nad KB")
        finally:
            observer.stop()
            observer.join(5)


if __name__ == "__main__":
    unittest.main()

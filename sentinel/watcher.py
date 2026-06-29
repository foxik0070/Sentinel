import os
import re
import fnmatch
import time
import threading
from watchdog.events import FileSystemEventHandler

from . import config
from . import utils
from . import plugin_manager
from . import rag

IGNORE_REGEXES = []
WATCH_REGEXES = []

# 314: Lines parsed tracking for telemetry report
_lines_parsed_count = 0
_lines_parsed_lock = threading.Lock()
_lines_parsed_last_flush = time.time()

def _track_lines_parsed(n: int):
    """Accumulate lines parsed; flush to telemetry every 60s."""
    global _lines_parsed_count, _lines_parsed_last_flush
    with _lines_parsed_lock:
        _lines_parsed_count += n
        now = time.time()
        if now - _lines_parsed_last_flush >= 60:
            rate = _lines_parsed_count / max(1, now - _lines_parsed_last_flush)
            try:
                from . import state as _st
                _st.save_telemetry('sentinel.lines_parsed_per_min', round(rate * 60, 1), 'sentinel')
            except Exception:
                pass
            _lines_parsed_count = 0
            _lines_parsed_last_flush = now

def compile_patterns():
    global IGNORE_REGEXES, WATCH_REGEXES
    def to_regex(patterns):
        return [re.compile(fnmatch.translate(p)) for p in patterns]
    
    IGNORE_REGEXES = to_regex(config.IGNORE_PATTERNS)
    WATCH_REGEXES = to_regex(config.WATCH_PATTERNS)
    utils.log_message(f"Watcher: Patterns recompiled.")

compile_patterns()

def should_process_file(path):
    name = os.path.basename(path)
    for regex in IGNORE_REGEXES:
        if regex.match(name): return False
    for regex in WATCH_REGEXES:
        if regex.match(name): return True
    return False

def _reinit_ldap():
    """Po reloadu configu znovu inicializuje LDAP manager pokud je LDAP zapnutý."""
    if not config.LDAP_ENABLED:
        return
    try:
        from . import auth as _auth_mod
        from flask_ldap3_login import LDAP3LoginManager
        from flask import current_app
        app = current_app._get_current_object()
        ldap_host = config.LDAP_HOST
        if not ldap_host.startswith(('ldap://', 'ldaps://')):
            ldap_host = f"ldap://{ldap_host}"
        app.config['LDAP_HOST'] = ldap_host
        app.config['LDAP_PORT'] = config.LDAP_PORT
        app.config['LDAP_USE_SSL'] = config.LDAP_USE_SSL
        app.config['LDAP_BASE_DN'] = config.LDAP_BASE_DN
        app.config['LDAP_USER_DN'] = config.LDAP_SEARCH_USER_DN
        app.config['LDAP_USER_LOGIN_ATTR'] = config.LDAP_USER_LOGIN_ATTR
        app.config['LDAP_USER_SEARCH_SCOPE'] = 'SUBTREE'
        app.config['LDAP_ALWAYS_SEARCH_BIND'] = True
        app.config['LDAP_BIND_USER_DN'] = getattr(config, 'LDAP_BIND_DN', None)
        app.config['LDAP_BIND_USER_PASSWORD'] = getattr(config, 'LDAP_BIND_PASSWORD', None)
        app.config['LDAP_SEARCH_FOR_GROUPS'] = False
        _auth_mod.ldap_manager = LDAP3LoginManager(app)
        utils.log_message("LDAP manager reinitialized after config reload.")
    except Exception as e:
        utils.log_message(f"[!] LDAP reinit failed: {e}")


class ConfigHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.last_reload_time = 0
        self.debounce_interval = 10.0 

    def on_modified(self, event):
        fname = os.path.basename(event.src_path)
        kb_filename = os.path.basename(config.KB_FILE_PATH)

        now = time.time()
        if now - self.last_reload_time < self.debounce_interval:
            return

        if fname in ["config.yaml", "settings.yaml"]:
            self.last_reload_time = now
            utils.log_message(f"CONFIG CHANGE DETECTED: {fname}")
            # Počkat 1s aby se dokončil zápis souboru před čtením
            # (inotify IN_MODIFY firuje při prvním zapsaném bajtu, ne po close)
            time.sleep(1.0)
            try:
                config.load_config()
                compile_patterns()
                plugin_manager.load_plugins()
                utils.log_message("Configuration & Plugins reloaded.")
                # Reinicializovat LDAP manager pokud je LDAP zapnutý
                _reinit_ldap()
                # Uložit snapshot do DB
                try:
                    from sentinel import state as _state
                    with open(config.CONFIG_PATH, 'r') as _f:
                        _state.save_config_snapshot(_f.read())
                except Exception: pass
            except Exception as e:
                utils.log_message(f"[!] Config Reload Failed: {e}")

        elif fname == kb_filename:
            self.last_reload_time = now
            utils.log_message(f"KB CHANGE DETECTED: {fname}")
            
            def run_reindex():
                try:
                    utils.log_message("Starting RAG Re-Indexing (Background) ---")
                    rag.rag_system.ingest_knowledge_base()
                    utils.log_message("RAG Re-Indexing End")
                except Exception as e:
                    utils.log_message(f"[!] KB Reload Failed: {e}")

            import threading
            t = threading.Thread(target=run_reindex, daemon=True, name="RAG-HotReload")
            t.start()

class LogHandler(FileSystemEventHandler):
    def __init__(self):
        self._file_positions = {}

    def on_modified(self, event):
        self._process_event(event.src_path, event.is_directory, is_new_file=False)

    def on_created(self, event):
        self._process_event(event.src_path, event.is_directory, is_new_file=True)

    def on_deleted(self, event):
        if not event.is_directory: 
            self._file_positions.pop(event.src_path, None)

    def on_moved(self, event):
        """Zachytava os.replace() z orchestratoru."""
        if not event.is_directory:
            self._file_positions.pop(event.src_path, None)
            self._file_positions.pop(event.dest_path, None)
            self._process_event(event.dest_path, event.is_directory, is_new_file=True)

    def _process_event(self, path, is_directory, is_new_file=False):
        if is_directory or path.endswith("sms.txt"): 
            return
            
        if not should_process_file(path): 
            return

        try:
            if not os.path.exists(path):
                self._file_positions.pop(path, None)
                return

            current_size = os.path.getsize(path)
            
            # Pokud prepisujeme cely soubor atomicky, last_pos je 0
            last_pos = 0 if is_new_file else self._file_positions.get(path, 0)
            
            # Ochrana proti logrotaci (velikost je mensi nez minuly stav)
            if current_size < last_pos: 
                last_pos = 0 

            # Pokud se velikost nezmenila, neprovadime zadnou IO operaci
            if current_size == last_pos: 
                return

            with open(path, "r", errors="replace") as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                self._file_positions[path] = f.tell() 

            if new_lines:
                # 314: Track lines_parsed for telemetry report
                _track_lines_parsed(len(new_lines))
                plugin_manager.dispatch(path, new_lines)

        except Exception as e:
            utils.log_message(f"[!] Error processing file {path}: {e}")

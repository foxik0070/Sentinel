import sys
from datetime import datetime

# --- CRITICAL FIX FOR CHROMADB ON RHEL/CENTOS ---
sqlite_fix_status = "N/A"
try:
    __import__('pysqlite3')
    import sys
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
    sqlite_fix_status = "SUCCESS (Switched to pysqlite3)"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {sqlite_fix_status}")
except ImportError:
    sqlite_fix_status = "WARNING (pysqlite3 not found, using system sqlite)"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {sqlite_fix_status}")
# -----------------------------------------------

import argparse
import time
import signal
import os
import socket
import requests
import base64
import faulthandler
import traceback
import threading
import concurrent.futures
from watchdog.observers import Observer

from . import config
from . import utils
from . import state
from . import ollama_service
from . import watcher
from . import chat_service
from . import rag 
from . import plugin_manager

faulthandler.register(signal.SIGUSR1)
faulthandler.enable()  # dump all-thread tracebacks on SIGABRT (watchdog kill) -> journal

# --- SYSTEMD NOTIFICATION HELPER ---
def systemd_notify(msg):
    """Sends a notification to systemd watchdog socket."""
    notify_socket = os.getenv('NOTIFY_SOCKET')
    if not notify_socket:
        return False

    try:
        if notify_socket.startswith('@'):
            notify_socket = '\0' + notify_socket[1:]

        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(notify_socket)
            sock.sendall(msg.encode())
            return True
    except Exception:
        return False

def _make_watchdog_socket():
    """Opens and connects a persistent Unix DGRAM socket to NOTIFY_SOCKET. Returns (sock, addr) or (None, None)."""
    addr = os.getenv('NOTIFY_SOCKET')
    if not addr:
        return None, None
    if addr.startswith('@'):
        addr = '\0' + addr[1:]
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)  # non-blocking: sendall nikdy nezablokuje hlavní vlákno
        sock.connect(addr)
        return sock, addr
    except Exception as e:
        try:
            sock.close()
        except Exception:
            pass
        return None, None

# --- DIAGNOSTICS ---
def get_ram_usage():
    """Gets current RAM usage (Linux specific)."""
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return line.strip()
    except:
        return "RAM: N/A"

def dump_stack_traces():
    """Prints stack traces of all running threads."""
    utils.log_message(" --- DIAGNOSTIC THREAD DUMP START ---")
    utils.log_message(f"System State: {get_ram_usage()}")
    
    for thread_id, frame in sys._current_frames().items():
        t_name = "Unknown"
        for t in threading.enumerate():
            if t.ident == thread_id:
                t_name = t.name
                break
        
        utils.log_message(f"\n Thread ID: {thread_id} ({t_name})")
        utils.log_message("".join(traceback.format_stack(frame)))
        
    utils.log_message(" --- DIAGNOSTIC THREAD DUMP END ---")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--external", action="store_true", help="Use external Ollama API")
    parser.add_argument("-d", "--debug", action="store_true", help="Disable Teams sending")
    args = parser.parse_args()
    
    if args.external: config.ARGS["EXTERNAL_OLLAMA"] = True
    if args.debug: config.ARGS["DEBUG_MODE"] = True

    # --- Startup Info ---
    ollama_type = ollama_service.get_ollama_type()
    timestart = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    
    if hasattr(config, 'BANNER'):
        utils.log_message("\n" + config.BANNER)
    
    start_msg = (
        f"Sentinel started/restarted: {timestart}\n"
        f"Instance Name: [{config.INSTANCE_NAME}]\n"
        f"Use AI model: {config.HAILO_OLLAMA_MODEL if config.HAILO_OLLAMA_ENABLED else config.OLLAMA_MODEL}\n"
        f"Using Backend: {ollama_type}\n"
        f"Version: v{config.VERSION}\n"
        f"Subversion: {config.SUBVERSION}\n"
        f"MS Teams: {'Active' if getattr(config, 'TEAMS_ENABLED', False) else 'Disabled'}\n"
        f"Home Assistant: {'Active' if getattr(config, 'HA_ENABLED', False) else 'Disabled'}\n"
        f"Config loaded from: {config.CONFIG_PATH}\n"
        f"SQLite Fix: {sqlite_fix_status}"
    )
    
    utils.log_message(start_msg)
    utils.send_to_teams(f" <b>SENTINEL STARTED</b><br><pre>{start_msg}</pre>", "tests")

    if getattr(config, 'HA_ENABLED', False):
        try:
            ha_start_title = f"Sentinel"
            utils.send_ha_alert(start_msg, ha_start_title)
        except Exception as e:
            utils.log_message(f"[!] Failed to send HA startup alert: {e}")

    # --- LOAD PLUGINS ---
    utils.log_message("Loading Sentinel Plugins...")
    plugin_manager.load_plugins()

    # --- RAG INIT (Background) ---
    utils.log_message("Starting RAG Initialization Background Worker...")
    try:
        rag.rag_system.initialize_background()
        utils.log_message("RAG Background Worker started.")
    except Exception as e:
        utils.log_message(f" CRITICAL RAG FAILURE: {e}")

    # --- Minifikace statických souborů ---
    try:
        import rjsmin, rcssmin
        from pathlib import Path
        _static = Path(__file__).parent / 'static'
        for _f in ['script-core.js', 'script-modals.js', 'script-agents.js', 'script-ui.js', 'i18n.js']:
            _src = (_static / _f).read_text()
            (_static / _f.replace('.js', '.min.js')).write_text(rjsmin.jsmin(_src))
        _css = (_static / 'style.css').read_text()
        (_static / 'style.min2.css').write_text(rcssmin.cssmin(_css))
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Static assets minified OK")
    except Exception as _e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Minification skipped: {_e}")

    # --- Start Services ---
    state.init_db()
    # 092: Ulož snapshot config při startu (poprvé nebo při změně)
    try:
        with open(config.CONFIG_PATH, 'r') as _cf:
            state.save_config_snapshot(_cf.read())
    except Exception:
        pass
    threading.Thread(target=state._telemetry_flush_loop, daemon=True, name="TelemetryFlush").start()
    # 082: Syslog UDP receiver
    from . import syslog_receiver as _syslog
    _syslog.start_syslog_receiver()
    # 081: SNMP Trap receiver
    if config.SNMP_TRAP_ENABLED:
        from . import snmp_trap as _snmp
        from . import api as _api
        _snmp.start(config.SNMP_TRAP_CFG, _api.report_problem)
    # 120: Network topology SNMP poller
    from . import topology as _topology
    _topology.start_snmp_poller(config.TOPOLOGY_CFG)
    # 327: Aktivní SNMP polling OID → telemetrie
    from . import snmp_poll as _snmp_poll
    _snmp_poll.start_snmp_poll(config.SNMP_POLL_CFG)
    ollama_thread, monitor_thread = ollama_service.start_threads()
    chat_svc = chat_service.start_chat_service()

    observer = Observer()

    # 1. Log Watcher
    log_handler = watcher.LogHandler()
    # Pozice z minulého běhu ještě před observer.start() — jinak první událost
    # u dosud neznámého souboru přečte log od nuly a přehraje jeho historii.
    log_handler._file_positions.update(watcher.seed_positions(config.LOG_DIR))
    observer.schedule(log_handler, config.LOG_DIR, recursive=True)

    # Initial scan — zpracuj poslední řádky existujících log souborů při startu
    def _initial_scan():
        import glob, gzip, time as _t
        _t.sleep(2)  # počkat na inicializaci plugin manageru
        from . import plugin_manager as _pm
        # 292: volitelně zpracovat čerstvě zrotované archivy (.log.1 / .log.1.gz)
        # — řádky zapsané mezi rotací a startem služby by jinak zapadly.
        # Issue klíče jsou idempotentní, duplicitní dispatch jen zvýší occurrence.
        if getattr(config, 'PROCESS_ROTATED_LOGS', False):
            _max_age = 24 * 3600
            for rpath in (glob.glob(os.path.join(config.LOG_DIR, "*.log.1"))
                          + glob.glob(os.path.join(config.LOG_DIR, "*.log.1.gz"))):
                try:
                    if _t.time() - os.path.getmtime(rpath) > _max_age:
                        continue
                    opener = gzip.open if rpath.endswith('.gz') else open
                    with opener(rpath, 'rt', errors='replace') as f:
                        rlines = f.readlines()[-500:]
                    if rlines:
                        # dispatch pod jménem původního logu, ať matchují patterny
                        orig = rpath[:-3] if rpath.endswith('.gz') else rpath
                        orig = orig[:-2]  # odřízne ".1"
                        _pm.dispatch(orig, rlines)
                        utils.log_message(f"[292] Zpracován rotovaný log {os.path.basename(rpath)} ({len(rlines)} řádků)")
                except Exception as e:
                    utils.log_message(f"[!] Rotated log {rpath}: {e}")
        # Jen to, co přiteklo od posledního běhu — pozice logů restart přežívají.
        # Dřív se přehrálo posledních 200 řádků každého logu a dávno neplatné
        # issue se po každém restartu vynořilo znovu s čerstvým last_seen.
        for fpath in glob.glob(os.path.join(config.LOG_DIR, "*.log")):
            try:
                pos = log_handler._file_positions.get(fpath)
                lines, new_offset = watcher.read_new_lines(fpath, pos)
                log_handler._file_positions[fpath] = new_offset
                if lines:
                    _pm.dispatch(fpath, lines)
            except Exception:
                pass
        watcher.save_offsets(dict(log_handler._file_positions))
    threading.Thread(target=_initial_scan, daemon=True, name="InitialScan").start()
    
    # 2. Config Watcher (Hot-Reload)
    cfg_handler = watcher.ConfigHandler()
    cfg_dir = None
    if config.CONFIG_PATH and os.path.exists(config.CONFIG_PATH):
        cfg_dir = os.path.abspath(os.path.dirname(config.CONFIG_PATH) or ".")
        observer.schedule(cfg_handler, cfg_dir, recursive=False)
        utils.log_message(f"Starting Hot-Reload: {cfg_dir}")

    # 2b. KB Watcher — KB lezi typicky mimo adresar configu (/opt/Sentinel vs
    #     /etc/sentinel), bez samostatneho schedule by KB vetev nikdy nevystrelila.
    kb_dir = os.path.abspath(os.path.dirname(config.KB_FILE_PATH)) if config.KB_FILE_PATH else ""
    if kb_dir and kb_dir != cfg_dir and os.path.isdir(kb_dir):
        observer.schedule(cfg_handler, kb_dir, recursive=False)
        utils.log_message(f"Starting KB Hot-Reload: {kb_dir}")

    observer.start()

    # --- INTERNAL WATCHDOG CONFIG ---
    web_failures = 0
    loop_counter = 0
    WEB_CHECK_INTERVAL = 30
    STALE_CHECK_INTERVAL = 3600  # resolve stale problems once per hour
    stale_counter = STALE_CHECK_INTERVAL - 60  # první sweep ~minutu po startu
    # 486: ověřování oprav — často, protože pokusy dozrávají po ~15 min
    FIX_VERIFY_INTERVAL = 120
    fix_verify_counter = 0
    # Pozice v logách: po SIGKILL se přehraje maximálně poslední minuta
    OFFSET_SAVE_INTERVAL = 60
    offset_counter = 0
    _scheme = "https" if getattr(config, 'HTTPS_ENABLED', False) else "http"
    WEB_URL = f"{_scheme}://127.0.0.1:{config.WEB_PORT}/api/status_check"

    # --- Main Loop ---
    running = True
    def signal_handler(signum, frame):
        nonlocal running
        utils.log_message(f"[!] Received signal {signum}. Shutting down...")
        utils.send_to_teams(" <b>SENTINEL STOPPING...</b>", "tests")
        state.shutdown_event.set()
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    systemd_notify("READY=1")

    # Watchdog ping v dedikovaném vlákně — nezávislé na hlavní smyčce.
    # Používá persistentní socket (neotvírá nový při každém pingu) a loguje selhání.
    def _watchdog_loop():
        sock, addr = _make_watchdog_socket()
        if sock is None:
            utils.log_message("[WATCHDOG] NOTIFY_SOCKET není nastaven — watchdog ping vypnut")
            return
        utils.log_message(f"[WATCHDOG] Ping spuštěn, socket: {repr(os.getenv('NOTIFY_SOCKET'))}")
        fail_count = 0
        while True:
            try:
                sock.sendall(b"WATCHDOG=1")
                if fail_count > 0:
                    utils.log_message(f"[WATCHDOG] ping obnoven po {fail_count} selháních")
                    fail_count = 0
            except BlockingIOError:
                pass  # socket buffer plný — systemd dostane příští ping, nevyžaduje obnovu
            except Exception as e:
                fail_count += 1
                utils.log_message(f"[WATCHDOG] ping selhal ({fail_count}): {e} — obnova socketu")
                try:
                    sock.close()
                except Exception:
                    pass
                sock, addr = _make_watchdog_socket()
                if sock is None:
                    utils.log_message("[WATCHDOG] KRITICKÉ: nelze obnovit watchdog socket!")
            time.sleep(15)
    threading.Thread(target=_watchdog_loop, daemon=True, name="SystemdWatchdog").start()

    try:
        while running:
            time.sleep(1)
            loop_counter  += 1
            stale_counter += 1
            fix_verify_counter += 1
            offset_counter += 1

            if offset_counter >= OFFSET_SAVE_INTERVAL:
                offset_counter = 0
                watcher.save_offsets(dict(log_handler._file_positions))

            if not ollama_thread.is_alive():
                utils.log_message("CRITICAL: Ollama worker died!")
                utils.send_to_teams("⚠️ <b>CRITICAL:</b> Ollama worker thread died!", "tests")
                running = False
            
            if not chat_svc.is_alive():
                utils.log_message("CRITICAL: Chat Service (Web GUI) thread died!")
                utils.send_to_teams("⚠️ <b>CRITICAL:</b> Chat Service thread died!", "tests")
                running = False

            if not observer.is_alive():
                utils.log_message("CRITICAL: Watcher (Log Monitor) thread died!")
                utils.send_to_teams("⚠️ <b>CRITICAL:</b> Watcher thread died!", "tests")
                running = False

            if stale_counter >= STALE_CHECK_INTERVAL:
                stale_counter = 0
                try:
                    n = state.resolve_stale_problems()
                    if n:
                        utils.log_message(f"Stale cleanup: resolved {n} inactive problems (per-severity TTL)")
                except Exception as _e:
                    utils.log_message(f"[!] Stale cleanup failed: {_e}")

            # 486: dozrálé pokusy o opravu — zabralo to, nebo se problém vrátil?
            if fix_verify_counter >= FIX_VERIFY_INTERVAL:
                fix_verify_counter = 0
                try:
                    from . import fix_verify

                    def _notify_failed(attempt, detail):
                        utils.send_to_teams(
                            f"⚠️ <b>Oprava nezabrala</b><br>"
                            f"{attempt.get('host', '?')} — <code>{attempt.get('command', '?')}</code><br>"
                            f"{detail}", "tests")

                    res = fix_verify.run_due_verifications(state, notify=_notify_failed)
                    if any(res.values()):
                        utils.log_message(
                            f"Fix verify: {res.get('worked', 0)} zabralo, "
                            f"{res.get('failed', 0)} nezabralo, "
                            f"{res.get('uncertain', 0)} nejasných")
                except Exception as _e:
                    utils.log_message(f"[!] Fix verify failed: {_e}")

            if loop_counter >= WEB_CHECK_INTERVAL:
                loop_counter = 0
                try:
                    auth_str = f"{config.WEB_USER}:{config.WEB_PASS}"
                    b64_auth = base64.b64encode(auth_str.encode()).decode()
                    hdrs = {"Authorization": f"Basic {b64_auth}", "Connection": "close"}

                    # HTTP check běží v separátním vlákně s tvrdým wall-clock limitem.
                    # Zabraňuje zablokování main threadu při zavěšeném TCP spojení.
                    def _do_check():
                        # verify=False — self-signed cert na localhost
                        return requests.get(WEB_URL, headers=hdrs, timeout=10, verify=False)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                        _fut = _ex.submit(_do_check)
                        resp = _fut.result(timeout=20)

                    if resp.status_code == 200 or resp.status_code == 401:
                        if web_failures > 0:
                            utils.log_message(f"Watchdog: Web UI recovered after {web_failures} failures.")
                            web_failures = 0
                    else:
                        raise Exception(f"Status Code {resp.status_code}")

                except concurrent.futures.TimeoutError:
                    web_failures += 1
                    utils.log_message(f"Watchdog WARNING: Web UI check TIMED OUT (wall-clock 20s) ({web_failures}/10)")
                    if web_failures == 5:
                        utils.log_message(f"Watchdog Diag (5/10): {get_ram_usage()}")
                    if web_failures == 9:
                        utils.log_message("Watchdog Diag (9/10): Pre-kill thread dump initiated...")
                        try: dump_stack_traces()
                        except: pass
                    if web_failures >= 10:
                        utils.log_message("CRITICAL: Web UI is DEAD (10 strikes). Triggering self-restart.")
                        utils.send_to_teams("⚠️ <b>SELF-HEALING:</b> Web interface froze. Restarting service...", "general")
                        running = False
                except Exception as e:
                    web_failures += 1
                    utils.log_message(f"Watchdog WARNING: Web UI unresponsive ({web_failures}/10). Error: {str(e)[:100]}")
                    if web_failures == 5:
                        utils.log_message(f"Watchdog Diag (5/10): {get_ram_usage()}")
                    if web_failures == 9:
                        utils.log_message("Watchdog Diag (9/10): Pre-kill thread dump initiated...")
                        try: dump_stack_traces()
                        except: pass
                    if web_failures >= 10:
                        utils.log_message("CRITICAL: Web UI is DEAD (10 strikes). Triggering self-restart.")
                        utils.send_to_teams("⚠️ <b>SELF-HEALING:</b> Web interface froze. Restarting service...", "general")
                        running = False

    except Exception as e:
        utils.log_message(f"CRITICAL ERROR: {e}")
        utils.send_to_teams(f" <b>CRITICAL ERROR:</b> {e}", "tests")
        try: dump_stack_traces()
        except: pass

    finally:
        utils.log_message("Stopping Sentinel services...")
        watcher.save_offsets(dict(log_handler._file_positions))
        state.shutdown_event.set()
        
        if observer.is_alive():
            observer.stop()
            observer.join()
        
        if ollama_thread.is_alive():
            ollama_thread.join(timeout=5) 
        
        utils.log_message("Sentinel stopped.")

if __name__ == "__main__":
    main()

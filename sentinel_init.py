#!/usr/bin/env python3
# sentinel_init.py - Sentinel Setup & Interactive Wizard

import os
import sys
import subprocess
import secrets
from pathlib import Path

try:
    import yaml
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml

# --- ANSI TERMINAL COLORS ---
class C:
    CYAN   = '\033[96m'
    GREEN  = '\033[92m'
    YELLOW = '\033[93m'
    RED    = '\033[91m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'

def info(msg):    print(f"{C.CYAN}[*]{C.RESET} {msg}")
def ok(msg):      print(f"{C.GREEN}[+]{C.RESET} {msg}")
def warn(msg):    print(f"{C.YELLOW}[!]{C.RESET} {msg}")
def err(msg):     print(f"{C.RED}[x]{C.RESET} {msg}")
def section(msg): print(f"\n{C.BOLD}{C.CYAN}=== {msg} ==={C.RESET}")
def ask(msg, default=""):
    val = input(f"{C.YELLOW}  > {msg}{C.RESET} [{default}]: ").strip()
    return val if val else default

# --- CORE PATHS ---
CONFIG_PATH  = Path("/etc/sentinel/config.yaml")
PLUGINS_DIR  = Path("/opt/Sentinel/sentinel/plugins")
LOG_DIR      = Path("/var/log/sentinel/logs")
CHROMA_DIR   = Path("/var/log/sentinel/chroma_db")
DB_DIR       = Path("/var/lib/sentinel")   # stavová SQLite DB MIMO inotify-sledovaný LOG_DIR
KB_FILE      = Path("/opt/Sentinel/knowledge_base.txt")

def print_banner():
    print(f"""{C.CYAN}{C.BOLD}
  ██████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗
 ██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║
 ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║
 ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║
 ███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗
 ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
 --- Setup Wizard v2026.06 ---{C.RESET}
""")

def check_root():
    if os.geteuid() != 0:
        err("Critical Error: vyžadována práva root. Spusť přes sudo.")
        sys.exit(1)

# =============================================================================
# DETEKCE HARDWARU
# =============================================================================

def detect_rpi5() -> bool:
    try:
        model = Path("/proc/device-tree/model").read_bytes().decode(errors="replace").rstrip("\x00")
        return "raspberry pi 5" in model.lower()
    except Exception:
        return False

def detect_hailo() -> dict:
    """
    Detekuje Hailo hardware přes PCIe, /dev nebo lsmod.
    Rozlišuje Hailo-10H (AI HAT 2+, LLM) od Hailo-8/8L (AI HAT+, computer vision).
    Vrací dict: {
      'detected': bool, 'chip': str, 'tops': int, 'active': bool,
      'is_10h': bool,           # True = Hailo-10H (AI HAT 2+ — LLM)
      'hailo_ollama_bin': str,  # cesta k hailo-ollama nebo ""
    }
    """
    result = {
        "detected": False, "chip": "unknown", "tops": 0, "active": False,
        "is_10h": False, "hailo_ollama_bin": "",
    }

    HAILO_VENDOR = "1e60"
    HAILO_DEVICES = {
        "0001": ("hailo8",   26, False),  # Hailo-8  — AI HAT+ (26 TOPS, CV)
        "0004": ("hailo8l",  13, False),  # Hailo-8L — AI Kit  (13 TOPS, CV)
        "000b": ("hailo10h", 40, True),   # Hailo-10H — AI HAT 2+ (40 TOPS, LLM)
    }

    # Metoda 1: lspci
    try:
        lspci = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=5)
        for line in lspci.stdout.splitlines():
            if HAILO_VENDOR.lower() in line.lower() or "hailo" in line.lower():
                result["detected"] = True
                for dev_id, (chip, tops, is_10h) in HAILO_DEVICES.items():
                    if f"{HAILO_VENDOR}:{dev_id}" in line.lower():
                        result["chip"] = chip
                        result["tops"] = tops
                        result["is_10h"] = is_10h
                        break
                if result["chip"] == "unknown":
                    result["chip"] = "hailo8l"
                    result["tops"] = 13
                break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Metoda 2: /sys/bus/pci vendor soubory
    if not result["detected"]:
        for vendor_f in Path("/sys/bus/pci/devices").glob("*/vendor"):
            try:
                if vendor_f.read_text().strip() == f"0x{HAILO_VENDOR}":
                    result["detected"] = True
                    dev_id = (vendor_f.parent / "device").read_text().strip().replace("0x", "")
                    if dev_id in HAILO_DEVICES:
                        result["chip"], result["tops"], result["is_10h"] = HAILO_DEVICES[dev_id]
                    else:
                        result["chip"] = "hailo8l"
                        result["tops"] = 13
                    break
            except Exception:
                pass

    # Metoda 3: chardev /dev/hailo*
    if not result["detected"]:
        if list(Path("/dev").glob("hailo*")):
            result["detected"] = True
            result["chip"] = "hailo8l"
            result["tops"] = 13

    # Metoda 4: lsmod
    if not result["detected"]:
        try:
            lsmod = subprocess.run(["lsmod"], capture_output=True, text=True, timeout=5)
            if "hailo_pci" in lsmod.stdout:
                result["detected"] = True
                result["chip"] = "hailo8l"
                result["tops"] = 13
        except Exception:
            pass

    # Ověření aktivního /dev/hailo0
    if result["detected"]:
        result["active"] = Path("/dev/hailo0").exists()
        # Zpřesnění přes hailortcli
        try:
            out = subprocess.run(
                ["hailortcli", "fw-control", "identify"],
                capture_output=True, text=True, timeout=10
            ).stdout.lower()
            if "hailo-10" in out or "hailo10" in out:
                result["chip"] = "hailo10h"
                result["tops"] = 40
                result["is_10h"] = True
            elif "hailo8l" in out or "hailo-8l" in out:
                result["chip"] = "hailo8l"
                result["tops"] = 13
                result["is_10h"] = False
            elif "hailo8" in out or "hailo-8 " in out:
                result["chip"] = "hailo8"
                result["tops"] = 26
                result["is_10h"] = False
        except Exception:
            pass

    # Detekce hailo-ollama binary
    for candidate in ["/usr/bin/hailo-ollama", "/usr/local/bin/hailo-ollama"]:
        if Path(candidate).exists():
            result["hailo_ollama_bin"] = candidate
            # Pokud je hailo-ollama nainstalován a chip nebyl jinak určen, předpokládáme 10H
            if result["detected"] and not result["is_10h"]:
                result["is_10h"] = True
                result["chip"] = "hailo10h"
                result["tops"] = 40
            break

    return result

def install_hailo(chip: str):
    """Nainstaluje Hailo runtime (hailo-all) přes apt."""
    section("Instalace Hailo Runtime")
    # Ověř, zda není již nainstalováno
    r = subprocess.run(["dpkg", "-l", "hailo-all"], capture_output=True, text=True)
    if "ii" in r.stdout:
        ok("hailo-all je již nainstalován.")
        return True

    info("Instaluji hailo-all (driver + HailoRT + Python bindings)...")
    try:
        subprocess.run(["apt-get", "install", "-y", "hailo-all"], check=True)
        ok("hailo-all nainstalován úspěšně.")
        return True
    except subprocess.CalledProcessError:
        warn("hailo-all nenalezen v repozitářích.")
        warn("Ruční instalace: sudo apt install hailo-all")
        warn("Dokumentace: https://github.com/hailo-ai/hailo-rpi5-examples")
        return False

# =============================================================================
# SETUP KROKY
# =============================================================================

def setup_directories():
    section("Vytváření adresářové struktury")
    for d in [CONFIG_PATH.parent, PLUGINS_DIR, LOG_DIR, CHROMA_DIR, DB_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        ok(f"Adresář: {d}")
    if not KB_FILE.exists():
        KB_FILE.touch()
        ok(f"Prázdná knowledge base: {KB_FILE}")

HAILO_OLLAMA_MODELS = [
    "qwen3:1.7b",
    "qwen2.5-coder:1.5b",
    "qwen2.5:1.5b",
    "llama3.2:1b",
    "deepseek_r1:1.5b",
]

def select_ai_backend(hailo: dict, is_rpi5: bool) -> dict:
    """
    Interaktivní výběr AI backendu.
    Vrací dict s konfigurací pro generate_config().
    """
    section("Konfigurace AI backendu")

    print(f"\n  Detekovaný hardware:")
    print(f"    {'Raspberry Pi 5' if is_rpi5 else 'Jiný systém'}")
    if hailo["detected"]:
        status = "aktivní" if hailo["active"] else "detekován (čeká na reboot)"
        chip_label = f"{hailo['chip']} ({hailo['tops']} TOPS)"
        role = "AI HAT 2+ — LLM (hailo-ollama)" if hailo["is_10h"] else "AI HAT+ — Computer Vision / Embeddingy"
        print(f"    Hailo: {chip_label} — {status}")
        print(f"    Role:  {role}")
        if hailo["hailo_ollama_bin"]:
            ok(f"hailo-ollama nalezen: {hailo['hailo_ollama_bin']}")
    else:
        print(f"    Hailo NPU: nedetekován")

    # RAM detekce pro výběr modelu
    try:
        mem_kb = int(Path("/proc/meminfo").read_text().split()[1])
        ram_gb = mem_kb // (1024 * 1024)
    except Exception:
        ram_gb = 4

    default_cpu_model = "llama3.2:1b" if ram_gb < 8 else "llama3.2:3b"
    default_url       = "http://localhost:11434/v1/chat/completions"
    default_workers   = 1 if is_rpi5 else 4

    print(f"\n  Dostupné AI backendy:")
    print(f"    [1] Ollama CPU — LLM na CPU (výchozí, vždy funguje)")
    if hailo["detected"] and hailo["is_10h"]:
        print(f"    [2] Hailo AI HAT 2+ — LLM přes hailo-ollama (NPU akcelerace, port 8000)")
        print(f"        Modely: {', '.join(HAILO_OLLAMA_MODELS)}")
        print(f"    [3] Hailo AI HAT 2+ + Ollama CPU — hailo-ollama primárně, CPU fallback")
        default_choice = "2" if hailo["hailo_ollama_bin"] else "1"
    elif hailo["detected"] and not hailo["is_10h"]:
        print(f"    [2] Ollama CPU + AI HAT+ embeddingy — LLM na CPU, Hailo-8/8L pro RAG vektory")
        default_choice = "2"
    else:
        default_choice = "1"

    choice = ask("Vyber backend", default_choice)

    # --- Ollama CPU only ---
    if choice == "1":
        ollama_url    = ask("Ollama URL", default_url)
        ollama_model  = ask("Ollama model", default_cpu_model)
        worker_threads = int(ask("Worker threads", str(default_workers)))
        return {
            "ollama_url": ollama_url,
            "ollama_model": ollama_model,
            "worker_threads": worker_threads,
            "ai_hat": {"enabled": False},
            "hailo_ollama": {"enabled": False},
        }

    # --- Hailo AI HAT 2+ (hailo-ollama) ---
    elif choice == "2" and hailo["detected"] and hailo["is_10h"]:
        if not hailo["active"]:
            warn("Hailo detekován, ale /dev/hailo0 není dostupný. hailo-ollama může stále fungovat.")
        hailo_url = ask("hailo-ollama URL", "http://localhost:8000/v1/chat/completions")
        print(f"\n  Dostupné modely na Hailo AI HAT 2+:")
        for i, m in enumerate(HAILO_OLLAMA_MODELS, 1):
            print(f"    [{i}] {m}")
        hailo_model = ask("Model (jméno nebo číslo)", "qwen3:1.7b")
        if hailo_model.isdigit():
            idx = int(hailo_model) - 1
            hailo_model = HAILO_OLLAMA_MODELS[idx] if 0 <= idx < len(HAILO_OLLAMA_MODELS) else "qwen3:1.7b"
        return {
            "ollama_url": default_url,
            "ollama_model": default_cpu_model,
            "worker_threads": 1,
            "ai_hat": {"enabled": False},
            "hailo_ollama": {
                "enabled": True,
                "url": hailo_url,
                "model": hailo_model,
            },
        }

    # --- Hailo AI HAT 2+ + CPU fallback ---
    elif choice == "3" and hailo["detected"] and hailo["is_10h"]:
        hailo_url   = ask("hailo-ollama URL", "http://localhost:8000/v1/chat/completions")
        hailo_model = ask("Hailo model (primární)", "qwen3:1.7b")
        ollama_url  = ask("Ollama CPU URL (fallback)", default_url)
        ollama_model = ask("Ollama CPU model (fallback)", default_cpu_model)
        return {
            "ollama_url": ollama_url,
            "ollama_model": ollama_model,
            "worker_threads": 1,
            "ai_hat": {"enabled": False},
            "hailo_ollama": {
                "enabled": True,
                "url": hailo_url,
                "model": hailo_model,
            },
        }

    # --- Ollama CPU + AI HAT+ embeddingy (Hailo-8/8L) ---
    elif choice == "2" and hailo["detected"] and not hailo["is_10h"]:
        chip = hailo["chip"]
        tops = hailo["tops"]
        if not hailo["active"]:
            warn("AI HAT+ detekován, ale /dev/hailo0 není dostupný — pravděpodobně nutný reboot.")
        hef_path  = ask("Cesta k .hef embedding modelu (prázdné = bez NPU embeddingy)", "")
        use_embed = ask("Použít Hailo pro embedding? (ano/ne)", "ne")
        ollama_url    = ask("Ollama URL", default_url)
        ollama_model  = ask("Ollama model", default_cpu_model)
        worker_threads = int(ask("Worker threads", str(default_workers)))
        return {
            "ollama_url": ollama_url,
            "ollama_model": ollama_model,
            "worker_threads": worker_threads,
            "ai_hat": {
                "enabled": True,
                "device": chip,
                "tops": tops,
                "hef_model_path": hef_path,
                "use_for_embeddings": use_embed.lower() in ("ano", "a", "yes", "y"),
            },
            "hailo_ollama": {"enabled": False},
        }

    else:
        warn("Neplatná volba, použit výchozí (Ollama CPU).")
        return {
            "ollama_url": default_url,
            "ollama_model": default_cpu_model,
            "worker_threads": default_workers,
            "ai_hat": {"enabled": False},
            "hailo_ollama": {"enabled": False},
        }

def generate_config(ai_cfg: dict):
    """Generuje config.yaml odpovídající aktuální verzi Sentinelu."""
    section("Generování konfigurace")

    instance = ask("Název instance Sentinelu", "Sentinel-Core")
    web_port  = int(ask("Web port", "5050"))
    web_key   = secrets.token_hex(32)

    # 234: Vynutit změnu výchozích hesel hned při instalaci
    web_user = ask("Admin uživatel", "admin")
    web_pass = ask("Admin heslo (NUTNÉ změnit z výchozího!)", "")
    while not web_pass or web_pass in ("admin", "CHANGE_ME"):
        warn("Heslo nesmí být prázdné ani výchozí 'admin'.")
        web_pass = ask("Admin heslo", "")
    viewer_user = ask("Viewer uživatel", "viewer")
    viewer_pass = ask("Viewer heslo", secrets.token_hex(8))

    # LDAP
    ldap_en = ask("Zapnout LDAP autentizaci? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
    ldap_cfg = {"enabled": ldap_en}
    if ldap_en:
        ldap_cfg.update({
            "host": ask("LDAP host", "localhost"),
            "port": int(ask("LDAP port", "389")),
            "use_ssl": ask("LDAP SSL? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y"),
            "base_dn": ask("LDAP Base DN", "dc=example,dc=com"),
            "user_login_attr": ask("Login atribut", "uid"),
            "search_user_dn": ask("Search User DN", ""),
            "bind_dn": ask("Bind DN (nechej prázdné pro anonymous)", "") or None,
            "bind_password": ask("Bind heslo", "") or None,
            "admin_users": [],
            "superadmin_users": [],
            "viewer_users": [],   # config.py čte 'viewer_users'
        })
    else:
        ldap_cfg.update({
            "admin_users": ["admin"],
            "superadmin_users": ["root"],
        })

    # HTTPS / HTTP2
    https_en = ask("Zapnout HTTPS (SSL/TLS)? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
    https_cfg = {"enabled": https_en}
    if https_en:
        https_cfg["cert_file"] = ask("Cesta k SSL certifikátu (.crt/.pem)", "/etc/sentinel/ssl/cert.pem")
        https_cfg["key_file"]  = ask("Cesta k SSL privátnímu klíči (.key)", "/etc/sentinel/ssl/key.pem")
        use_h2 = ask("HTTP/2 přes hypercorn? Vyžaduje: pip install hypercorn (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
        https_cfg["use_http2"] = use_h2
        print(f"\n  [!] Nezapomeň nahrát certifikát a klíč na zadané cesty.")
        print(f"      Pro self-signed certifikát: openssl req -x509 -newkey rsa:4096 -keyout {https_cfg['key_file']} -out {https_cfg['cert_file']} -days 365 -nodes")

    # MQTT — config.py čte klíč 'pass' (ne 'password')
    mqtt_en = ask("Zapnout MQTT integraci? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
    mqtt_cfg = {"enabled": mqtt_en}
    if mqtt_en:
        mqtt_cfg.update({
            "host":         ask("MQTT broker host", "localhost"),
            "port":         int(ask("MQTT port", "1883")),
            "user":         ask("MQTT uživatel", ""),
            "pass":         ask("MQTT heslo", ""),
            "topic_prefix": ask("MQTT topic prefix", "sentinel"),
        })

    # MS Teams — config.py čte sekci 'teams_channels' (enabled + channel→URL mapa)
    teams_en = ask("Zapnout MS Teams notifikace? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
    teams_cfg = {"enabled": teams_en}
    if teams_en:
        teams_cfg["general"] = ask("Teams Webhook URL (kanál general)", "")

    # Home Assistant — config.py čte sekci 'homeassistant' (bez podtržítka)
    ha_en = ask("Zapnout Home Assistant integraci? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
    ha_cfg = {"enabled": ha_en}
    if ha_en:
        ha_cfg.update({
            "url":   ask("HA URL", "http://homeassistant.local:8123"),
            "token": ask("HA Long-Lived Access Token", ""),
            "notify_service": ask("HA notify service", "notify"),
        })

    # ntfy.sh (volitelné push notifikace)
    ntfy_en = ask("Zapnout ntfy.sh notifikace? (ano/ne)", "ne").lower() in ("ano", "a", "yes", "y")
    ntfy_cfg = {"enabled": ntfy_en}
    if ntfy_en:
        ntfy_cfg["url"]   = ask("ntfy URL (např. https://ntfy.sh/muj-topic)", "")
        ntfy_cfg["token"] = ask("ntfy token (prázdné = bez auth)", "")

    config_data = {
        "instance_name": instance,

        # Cesty
        "log_dir":           str(LOG_DIR),
        "data_dir":          "/opt/Sentinel/data",
        "plugin_dir":        str(PLUGINS_DIR),
        "knowledge_base_file": str(KB_FILE),

        # AI backend
        "ollama_url":       ai_cfg["ollama_url"],
        "ollama_model":     ai_cfg["ollama_model"],
        "worker_threads":   ai_cfg["worker_threads"],

        # Web
        "web": {
            "port":            web_port,
            "secret_key":      web_key,
            "username":        web_user,
            "password":        web_pass,
            "viewer_username": viewer_user,
            "viewer_password": viewer_pass,
        },

        # LDAP
        "ldap": ldap_cfg,

        # HTTPS
        "https": https_cfg,

        # MQTT
        "mqtt": mqtt_cfg,

        # MS Teams (config.py čte 'teams_channels')
        "teams_channels": teams_cfg,

        # Home Assistant (config.py čte 'homeassistant')
        "homeassistant": ha_cfg,

        # ntfy.sh
        "ntfy": ntfy_cfg,

        # Další notifikační kanály — vypnuté stuby k ruční editaci
        "gotify": {"enabled": False, "url": "", "token": ""},
        "smtp":   {"enabled": False, "host": "localhost", "port": 587,
                   "user": "", "pass": "", "from": "sentinel@localhost", "to": ""},
        "matrix": {"enabled": False, "url": "", "token": ""},

        # Infrastruktura
        "infrastructure_mapping": [
            {"name": "CORE-GW", "pattern": "auth.log", "mgmt_node": "localhost"}
        ],

        # Detektory
        "detectors": [
            {
                "plugin": "detector_universal_security",
                "match_pattern": "auth.log*",
                "enabled": True,
                "params": {"threshold": 5}
            }
        ],

        # AI prompty
        "prompts": {
            "default":     "ROLE: Technical AI. TASK: Analyze log entry: {line}. Answer in CZECH.",
            "security":    "ROLE: CyberSec AI. TASK: Check for unauthorized access in: {line}. Format output in HTML.",
            "remediation": "ROLE: Senior SysAdmin. TASK: Propose fix command for Node: {node}, Log: {raw_line}. JSON format ONLY: {{\"command\": \"...\", \"description\": \"...\"}}.",
        },
    }

    # AI HAT+ sekce (Hailo-8/8L embeddingy — pouze pokud je relevantní)
    if ai_cfg.get("ai_hat", {}).get("enabled") or ai_cfg.get("ai_hat", {}).get("device"):
        config_data["ai_hat"] = ai_cfg["ai_hat"]

    # Hailo AI HAT 2+ sekce (Hailo-10H LLM — pouze pokud je aktivní)
    hailo_ollama_cfg = ai_cfg.get("hailo_ollama", {})
    if hailo_ollama_cfg.get("enabled"):
        config_data["hailo_ollama"] = hailo_ollama_cfg

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    ok(f"Konfigurace uložena: {CONFIG_PATH}")

def configure_systemd():
    section("Konfigurace systemd služby")
    svc_path = Path("/etc/systemd/system/sentinel.service")
    svc_content = """[Unit]
Description=Sentinel System Orchestrator & AI Worker Pool
After=network.target syslog.target

[Service]
Type=notify
# Checkpoint + úklid WAL/SHM před startem (DB je v /var/lib/sentinel, mimo watched log-dir)
ExecStartPre=/bin/bash -c 'sqlite3 /var/lib/sentinel/sentinel_state.db "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null; rm -f /var/lib/sentinel/sentinel_state.db-wal /var/lib/sentinel/sentinel_state.db-shm'
ExecStart=/usr/local/bin/sentinel
WatchdogSec=900s
Restart=always
RestartSec=5
User=root
WorkingDirectory=/opt/Sentinel
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
"""
    svc_path.write_text(svc_content)
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "sentinel.service"], check=True)
        ok("systemd služba 'sentinel.service' nainstalována a povolena.")
    except subprocess.CalledProcessError as e:
        err(f"Chyba konfigurace systemd: {e}")

def main():
    check_root()
    print_banner()

    section("Detekce hardwaru")
    is_rpi5 = detect_rpi5()
    hailo   = detect_hailo()

    if is_rpi5:
        ok("Raspberry Pi 5 detekován.")
    else:
        info("Jiný systém než RPi5.")

    if hailo["detected"]:
        status = "aktivní (/dev/hailo0)" if hailo["active"] else "detekován, čeká na reboot"
        label = "AI HAT 2+ (Hailo-10H, LLM)" if hailo["is_10h"] else "AI HAT+ (Hailo-8/8L, CV)"
        ok(f"{label}: {hailo['chip']} ({hailo['tops']} TOPS) — {status}")
        if hailo["hailo_ollama_bin"]:
            ok(f"hailo-ollama: {hailo['hailo_ollama_bin']}")
    else:
        info("AI HAT+ / Hailo NPU nebyl nalezen.")

    setup_directories()
    ai_cfg = select_ai_backend(hailo, is_rpi5)
    generate_config(ai_cfg)
    configure_systemd()

    section("Hotovo")
    print(f"\n{C.GREEN}{C.BOLD}[SUCCESS] Instalace dokončena.{C.RESET}")
    print(f"{C.CYAN}Další kroky:{C.RESET}")
    print(f"  1. Uprav konfiguraci:  nano {CONFIG_PATH}")
    print(f"  2. Přidej pluginy:     {PLUGINS_DIR}")
    print(f"  3. Spusť Sentinel:     systemctl start sentinel")
    if hailo["detected"] and not hailo["active"]:
        print(f"\n{C.YELLOW}  [!] Hailo vyžaduje reboot pro aktivaci PCIe driveru.{C.RESET}")
        print(f"      Po rebootu ověř: hailortcli scan")

if __name__ == "__main__":
    main()

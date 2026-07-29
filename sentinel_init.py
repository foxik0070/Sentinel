#!/usr/bin/env python3
# sentinel_init.py - Sentinel Setup & Interactive Wizard

import os
import sys
import subprocess
import secrets
import shutil
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError

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
    DIM    = '\033[2m'
    RESET  = '\033[0m'

def info(msg):    print(f"{C.CYAN}[*]{C.RESET} {msg}")
def ok(msg):      print(f"{C.GREEN}[+]{C.RESET} {msg}")
def warn(msg):    print(f"{C.YELLOW}[!]{C.RESET} {msg}")
def err(msg):     print(f"{C.RED}[x]{C.RESET} {msg}")
def section(n, total, msg):
    print(f"\n{C.BOLD}{C.CYAN}━━━ Krok {n}/{total}: {msg} ━━━{C.RESET}")
def hint(msg):    print(f"  {C.DIM}{msg}{C.RESET}")
def ask(msg, default=""):
    val = input(f"{C.YELLOW}  > {msg}{C.RESET} [{default}]: ").strip()
    return val if val else default
def ask_yn(msg, default="ne"):
    val = ask(msg + " (ano/ne)", default).lower()
    return val in ("ano", "a", "yes", "y", "1")
def ask_pass(msg, auto_label="auto-generovat"):
    """Zeptá se na heslo — prázdné = auto-generovat."""
    val = input(f"{C.YELLOW}  > {msg}{C.RESET} [Enter = {auto_label}]: ").strip()
    return val

# --- CORE PATHS ---
CONFIG_PATH  = Path("/etc/sentinel/config.yaml")
PLUGINS_DIR  = Path("/opt/Sentinel/sentinel/plugins")
LOG_DIR      = Path("/var/log/sentinel/logs")
CHROMA_DIR   = Path("/var/log/sentinel/chroma_db")
DB_DIR       = Path("/var/lib/sentinel")
KB_FILE      = Path("/opt/Sentinel/knowledge_base.txt")
DATA_DIR     = Path("/opt/Sentinel/data")

GITHUB_PLUGINS_API = "https://api.github.com/repos/foxik0070/sentinel-plugins/contents"
GITHUB_PLUGINS_RAW = "https://raw.githubusercontent.com/foxik0070/sentinel-plugins/main"

TOTAL_STEPS = 12

def print_banner():
    print(f"""{C.CYAN}{C.BOLD}
  ██████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗
 ██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║
 ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║
 ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║
 ███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗
 ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝
 --- Setup Wizard v2026.07 ---{C.RESET}
""")

def check_root():
    if os.geteuid() != 0:
        err("Vyžadována práva root. Spusť přes: sudo python3 sentinel_init.py")
        sys.exit(1)

# =============================================================================
# ZÁLOHA KONFIGURACE
# =============================================================================

def backup_config() -> Path | None:
    """Pokud /etc/sentinel/config.yaml existuje, vytvoří zálohu."""
    if not CONFIG_PATH.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = CONFIG_PATH.with_suffix(f".yaml.backup-{ts}")
    shutil.copy2(CONFIG_PATH, backup)
    ok(f"Záloha existující konfigurace: {backup}")
    return backup

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
    result = {
        "detected": False, "chip": "unknown", "tops": 0, "active": False,
        "is_10h": False, "hailo_ollama_bin": "",
    }
    HAILO_VENDOR = "1e60"
    HAILO_DEVICES = {
        "0001": ("hailo8",   26, False),
        "0004": ("hailo8l",  13, False),
        "000b": ("hailo10h", 40, True),
    }
    try:
        lspci = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=5)
        for line in lspci.stdout.splitlines():
            if HAILO_VENDOR.lower() in line.lower() or "hailo" in line.lower():
                result["detected"] = True
                for dev_id, (chip, tops, is_10h) in HAILO_DEVICES.items():
                    if f"{HAILO_VENDOR}:{dev_id}" in line.lower():
                        result["chip"] = chip; result["tops"] = tops; result["is_10h"] = is_10h
                        break
                if result["chip"] == "unknown":
                    result["chip"] = "hailo8l"; result["tops"] = 13
                break
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    if not result["detected"]:
        for vendor_f in Path("/sys/bus/pci/devices").glob("*/vendor"):
            try:
                if vendor_f.read_text().strip() == f"0x{HAILO_VENDOR}":
                    result["detected"] = True
                    dev_id = (vendor_f.parent / "device").read_text().strip().replace("0x", "")
                    if dev_id in HAILO_DEVICES:
                        result["chip"], result["tops"], result["is_10h"] = HAILO_DEVICES[dev_id]
                    else:
                        result["chip"] = "hailo8l"; result["tops"] = 13
                    break
            except Exception:
                pass
    if not result["detected"] and list(Path("/dev").glob("hailo*")):
        result["detected"] = True; result["chip"] = "hailo8l"; result["tops"] = 13
    if result["detected"]:
        result["active"] = Path("/dev/hailo0").exists()
        try:
            out = subprocess.run(["hailortcli", "fw-control", "identify"],
                                 capture_output=True, text=True, timeout=10).stdout.lower()
            if "hailo-10" in out or "hailo10" in out:
                result["chip"] = "hailo10h"; result["tops"] = 40; result["is_10h"] = True
        except Exception:
            pass
    for candidate in ["/usr/bin/hailo-ollama", "/usr/local/bin/hailo-ollama"]:
        if Path(candidate).exists():
            result["hailo_ollama_bin"] = candidate
            if result["detected"] and not result["is_10h"]:
                result["is_10h"] = True; result["chip"] = "hailo10h"; result["tops"] = 40
            break
    return result

# =============================================================================
# SETUP ADRESÁŘŮ
# =============================================================================

def setup_directories():
    section(1, TOTAL_STEPS, "Adresářová struktura")
    for d in [CONFIG_PATH.parent, PLUGINS_DIR, LOG_DIR, CHROMA_DIR, DB_DIR, DATA_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        ok(f"  {d}")
    if not KB_FILE.exists():
        KB_FILE.touch()
        ok(f"  {KB_FILE} (prázdná knowledge base)")

# =============================================================================
# WEB PŘIHLAŠOVACÍ ÚDAJE
# =============================================================================

def configure_credentials() -> dict:
    section(2, TOTAL_STEPS, "Přihlašovací údaje do webového rozhraní")
    hint("Zanechej pole prázdné = automaticky vygenerovat bezpečné heslo.")
    hint("Admin má plný přístup. Viewer má přístup jen na čtení.")

    admin_user = ask("Admin uživatelské jméno", "admin")
    raw = ask_pass("Admin heslo")
    admin_pass = raw if raw else secrets.token_urlsafe(16)
    auto_admin = not raw

    viewer_user = ask("Viewer uživatelské jméno", "viewer")
    raw = ask_pass("Viewer heslo")
    viewer_pass = raw if raw else secrets.token_hex(16)
    auto_viewer = not raw

    web_port = int(ask("Web port", "5050"))
    secret_key = secrets.token_hex(32)

    if auto_admin:
        ok(f"Admin heslo vygenerováno: {C.BOLD}{admin_pass}{C.RESET}")
    if auto_viewer:
        ok(f"Viewer heslo vygenerováno: {C.BOLD}{viewer_pass}{C.RESET}")

    warn("ZAPIŠ SI TATO HESLA! Nezobrazí se znovu.")
    input(f"  {C.DIM}[Enter pro pokračování]{C.RESET}")

    return {
        "web": {
            "host": "0.0.0.0",
            "port": web_port,
            "secret_key": secret_key,
            "username": admin_user,
            "password": admin_pass,
            "viewer_username": viewer_user,
            "viewer_password": viewer_pass,
        },
        "_credentials_summary": {
            "admin": f"{admin_user} / {admin_pass}",
            "viewer": f"{viewer_user} / {viewer_pass}",
        }
    }

# =============================================================================
# LDAP / lldap
# =============================================================================

def configure_ldap() -> dict:
    section(3, TOTAL_STEPS, "LDAP autentizace (volitelné)")
    hint("lldap = lightweight LDAP server, ideální pro domácí prostředí.")
    hint("Přeskočit = přihlašování jen lokálními účty výše.")

    if not ask_yn("Zapnout LDAP autentizaci?", "ne"):
        return {"ldap": {"enabled": False, "admin_users": ["admin"], "superadmin_users": []}}

    print(f"\n  {C.BOLD}lldap výchozí nastavení:{C.RESET}")
    print(f"    Port: 17170 (LDAP) nebo 3890 (standardní LDAP)")
    print(f"    Base DN: dc=domain,dc=cz")
    print(f"    Bind DN: uid=foxik,ou=people,dc=domain,dc=cz")

    host    = ask("LDAP host / IP", "localhost")
    port    = int(ask("LDAP port", "17170"))
    use_ssl = ask_yn("Použít LDAPS (SSL)?", "ne")
    base_dn = ask("Base DN", "dc=home,dc=local")
    search_dn = ask("Search User OU", "ou=people")
    login_attr = ask("Login atribut (uid pro lldap)", "uid")
    bind_dn = ask("Bind DN (pro čtení adresáře)", f"uid=sentinel,ou=people,{base_dn}")
    bind_pw = ask_pass("Bind heslo", "zadat")
    if not bind_pw:
        bind_pw = secrets.token_urlsafe(16)
        ok(f"Bind heslo vygenerováno: {bind_pw}")

    superadmin = ask("Superadmin uživatelé (odděluj čárkou)", "root").split(",")
    admins     = ask("Admin uživatelé (odděluj čárkou)", "foxik").split(",")
    operators  = ask("Operator uživatelé (volitelné, čárkou)", "")
    viewers    = ask("Viewer uživatelé (volitelné, čárkou)", "")

    return {
        "ldap": {
            "enabled": True,
            "host": host,
            "port": port,
            "use_ssl": use_ssl,
            "base_dn": base_dn,
            "search_user_dn": search_dn,
            "user_login_attr": login_attr,
            "bind_dn": bind_dn,
            "bind_password": bind_pw,
            "superadmin_users": [u.strip() for u in superadmin if u.strip()],
            "admin_users":      [u.strip() for u in admins     if u.strip()],
            "operator_users":   [u.strip() for u in operators.split(",") if u.strip()],
            "viewer_users":     [u.strip() for u in viewers.split(",")   if u.strip()],
        }
    }

# =============================================================================
# AI BACKEND
# =============================================================================

HAILO_OLLAMA_MODELS = [
    "qwen3:1.7b", "qwen2.5-coder:1.5b", "qwen2.5:1.5b",
    "llama3.2:1b", "deepseek_r1:1.5b",
]

def select_ai_backend(hailo: dict, is_rpi5: bool) -> dict:
    section(4, TOTAL_STEPS, "AI backend")
    try:
        mem_kb = int(Path("/proc/meminfo").read_text().split()[1])
        ram_gb = mem_kb // (1024 * 1024)
    except Exception:
        ram_gb = 4

    default_cpu_model  = "llama3.2:1b" if ram_gb < 8 else "llama3.2:3b"
    default_url        = "http://localhost:11434/v1/chat/completions"
    default_workers    = 1 if is_rpi5 else 4

    print(f"\n  Hardware: {'Raspberry Pi 5' if is_rpi5 else 'Jiný systém'} | RAM: ~{ram_gb} GB")
    if hailo["detected"]:
        status = "aktivní" if hailo["active"] else "detekován (nutný reboot)"
        role   = "AI HAT 2+ — LLM" if hailo["is_10h"] else "AI HAT+ — CV/Embeddingy"
        print(f"  Hailo: {hailo['chip']} ({hailo['tops']} TOPS) — {role} — {status}")

    print(f"\n  [1] Ollama CPU          — LLM na CPU (výchozí)")
    if hailo["detected"] and hailo["is_10h"]:
        print(f"  [2] Hailo AI HAT 2+     — hailo-ollama NPU (port 8000)")
        print(f"  [3] Hailo + Ollama CPU  — NPU primárně, CPU fallback")
        default_choice = "2" if hailo["hailo_ollama_bin"] else "1"
    elif hailo["detected"]:
        print(f"  [2] Ollama + AI HAT+    — CPU LLM + Hailo-8 embeddingy")
        default_choice = "2"
    else:
        default_choice = "1"

    choice = ask("Vyber backend", default_choice)

    if choice == "1":
        return {
            "ollama_url": ask("Ollama URL", default_url),
            "ollama_model": ask("Model", default_cpu_model),
            "worker_threads": int(ask("Worker threads", str(default_workers))),
            "ai_hat": {"enabled": False}, "hailo_ollama": {"enabled": False},
        }
    elif choice == "2" and hailo["detected"] and hailo["is_10h"]:
        if not hailo["active"]:
            warn("Hailo NPU není aktivní — nutný reboot po instalaci driveru.")
        hailo_url = ask("hailo-ollama URL", "http://localhost:8000/v1/chat/completions")
        print(f"  Dostupné modely: {', '.join(HAILO_OLLAMA_MODELS)}")
        hailo_model = ask("Model", "qwen2.5-coder:1.5b")
        if hailo_model.isdigit():
            idx = int(hailo_model) - 1
            hailo_model = HAILO_OLLAMA_MODELS[idx] if 0 <= idx < len(HAILO_OLLAMA_MODELS) else "qwen2.5-coder:1.5b"
        return {
            "ollama_url": default_url, "ollama_model": default_cpu_model, "worker_threads": 1,
            "ai_hat": {"enabled": False},
            "hailo_ollama": {"enabled": True, "url": hailo_url, "model": hailo_model},
        }
    elif choice == "3" and hailo["detected"] and hailo["is_10h"]:
        hailo_url   = ask("hailo-ollama URL", "http://localhost:8000/v1/chat/completions")
        hailo_model = ask("Hailo model (primární)", "qwen2.5-coder:1.5b")
        return {
            "ollama_url": ask("Ollama CPU URL (fallback)", default_url),
            "ollama_model": ask("Ollama CPU model (fallback)", default_cpu_model),
            "worker_threads": 1, "ai_hat": {"enabled": False},
            "hailo_ollama": {"enabled": True, "url": hailo_url, "model": hailo_model},
        }
    elif choice == "2" and hailo["detected"] and not hailo["is_10h"]:
        hef_path  = ask("Cesta k .hef embedding modelu (prázdné = bez NPU)", "")
        use_embed = ask_yn("Použít Hailo pro embedding?", "ne")
        return {
            "ollama_url": ask("Ollama URL", default_url),
            "ollama_model": ask("Model", default_cpu_model),
            "worker_threads": int(ask("Worker threads", str(default_workers))),
            "ai_hat": {
                "enabled": True, "device": hailo["chip"], "tops": hailo["tops"],
                "hef_model_path": hef_path, "use_for_embeddings": use_embed,
            },
            "hailo_ollama": {"enabled": False},
        }
    else:
        warn("Neplatná volba, použit výchozí (Ollama CPU).")
        return {
            "ollama_url": default_url, "ollama_model": default_cpu_model,
            "worker_threads": default_workers,
            "ai_hat": {"enabled": False}, "hailo_ollama": {"enabled": False},
        }

# =============================================================================
# DETEKTORY — z GitHub nebo ručně
# =============================================================================

# Fallback mapa plugin → match_pattern pokud nelze extrahovat ze souboru
PLUGIN_MATCH_FALLBACK = {
    "port_detector":         "ports.log",
    "audit_detector":        "audit.log",
    "availability_detector": "availability.log",
    "services_detector":     "services.log",
    "ha_detector":           "homeassistant.log",
    "security_detector":     "secure.log",
    "system_detector":       "system.log",
    "temperature_detector":  "temperature.log",
    "storage_detector":      "storage.log",
    "capacity_detector":     "capacity.log",
    "detector_universal_security": "auth.log*",
}

def _extract_match_pattern(content: str) -> str:
    """Extrahuje MATCH_PATTERN nebo PLUGIN_MATCH_PATTERN z obsahu plugin souboru."""
    for pattern in [
        r'MATCH_PATTERN\s*=\s*["\']([^"\']+)["\']',
        r'PLUGIN_MATCH\s*=\s*["\']([^"\']+)["\']',
        r'match_pattern\s*=\s*["\']([^"\']+)["\']',
        r'LOG_PATTERN\s*=\s*["\']([^"\']+)["\']',
    ]:
        m = re.search(pattern, content)
        if m:
            return m.group(1)
    return ""

def _fetch_github_plugin_list() -> list[dict]:
    """Stáhne seznam pluginů z GitHub API. Vrací list {name, download_url}."""
    try:
        with urlopen(GITHUB_PLUGINS_API, timeout=10) as r:
            items = json.loads(r.read())
        plugins = []
        for item in items:
            name = item.get("name", "")
            if name.endswith(".py") and not name.startswith("_") and name != "__init__.py":
                plugins.append({
                    "name": name,
                    "plugin_id": name[:-3],
                    "download_url": item.get("download_url", ""),
                })
        return plugins
    except Exception as e:
        warn(f"GitHub API nedostupné: {e}")
        return []

def _download_plugin(plugin: dict) -> str | None:
    """Stáhne plugin soubor. Vrací obsah nebo None."""
    try:
        url = plugin["download_url"] or f"{GITHUB_PLUGINS_RAW}/{plugin['name']}"
        with urlopen(url, timeout=15) as r:
            return r.read().decode()
    except Exception as e:
        warn(f"  Nelze stáhnout {plugin['name']}: {e}")
        return None

def setup_detectors() -> list[dict]:
    section(5, TOTAL_STEPS, "Detektory (pluginy)")
    hint("Detektory sledují log soubory a hlásí anomálie.")
    hint(f"Plugin dir: {PLUGINS_DIR}")

    print(f"\n  [1] Stáhnout z GitHub   — {GITHUB_PLUGINS_API.replace('/contents', '')}")
    print(f"  [2] Použít lokální      — pluginy již v {PLUGINS_DIR}")
    print(f"  [3] Přeskočit           — nakonfigurovat detektory později v UI")
    choice = ask("Zdroj detektorů", "1")

    detectors = []

    if choice == "1":
        info("Načítám seznam pluginů z GitHub...")
        github_plugins = _fetch_github_plugin_list()

        if not github_plugins:
            warn("GitHub nedostupný nebo prázdný repo. Přecházím na ruční zadání.")
            choice = "manual"
        else:
            print(f"\n  Nalezeno {len(github_plugins)} pluginů v repozitáři:\n")
            for i, p in enumerate(github_plugins, 1):
                print(f"    [{i:2d}] {p['plugin_id']}")

            print(f"\n  Zadej čísla pluginů k instalaci (oddělená čárkou),")
            print(f"  nebo 'vse' pro všechny, nebo 'preskocit' pro žádný.")
            sel = ask("Výběr", "vse").strip().lower()

            if sel in ("vse", "all", "*"):
                selected = github_plugins
            elif sel in ("preskocit", "skip", ""):
                selected = []
            else:
                indices = [int(x.strip()) - 1 for x in sel.split(",") if x.strip().isdigit()]
                selected = [github_plugins[i] for i in indices if 0 <= i < len(github_plugins)]

            if selected:
                info(f"Stahuji {len(selected)} pluginů...")
                PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
                for p in selected:
                    content = _download_plugin(p)
                    if content:
                        dest = PLUGINS_DIR / p["name"]
                        dest.write_text(content)
                        match_pat = _extract_match_pattern(content) or \
                                    PLUGIN_MATCH_FALLBACK.get(p["plugin_id"], "")
                        if not match_pat:
                            match_pat = ask(
                                f"  match_pattern pro {p['plugin_id']} (např. system.log)",
                                f"{p['plugin_id'].replace('_detector','')}.log"
                            )
                        detectors.append({
                            "plugin": p["plugin_id"],
                            "match_pattern": match_pat,
                            "enabled": True,
                        })
                        ok(f"  {p['plugin_id']} → {match_pat}")
                    else:
                        warn(f"  {p['plugin_id']} přeskočen (chyba stahování)")

    if choice == "2" or (choice == "1" and not detectors):
        local_plugins = sorted(PLUGINS_DIR.glob("*.py"))
        local_plugins = [p for p in local_plugins if not p.name.startswith("_")]

        if not local_plugins:
            warn(f"V {PLUGINS_DIR} nejsou žádné .py soubory.")
            choice = "manual"
        else:
            print(f"\n  Lokální pluginy v {PLUGINS_DIR}:\n")
            for i, p in enumerate(local_plugins, 1):
                content = p.read_text(errors="replace")
                fallback_match = PLUGIN_MATCH_FALLBACK.get(p.stem, "")
                auto_match = _extract_match_pattern(content) or fallback_match
                print(f"    [{i:2d}] {p.stem:<35} → {auto_match or '(neznámy)'}")

            sel = ask("Výběr (čísla, 'vse', nebo 'preskocit')", "vse").strip().lower()

            if sel in ("vse", "all", "*"):
                chosen = local_plugins
            elif sel in ("preskocit", "skip", ""):
                chosen = []
            else:
                indices = [int(x.strip()) - 1 for x in sel.split(",") if x.strip().isdigit()]
                chosen = [local_plugins[i] for i in indices if 0 <= i < len(local_plugins)]

            for p in chosen:
                content = p.read_text(errors="replace")
                match_pat = _extract_match_pattern(content) or PLUGIN_MATCH_FALLBACK.get(p.stem, "")
                if not match_pat:
                    match_pat = ask(f"  match_pattern pro {p.stem}", f"{p.stem.replace('_detector','')}.log")
                detectors.append({"plugin": p.stem, "match_pattern": match_pat, "enabled": True})
                ok(f"  {p.stem} → {match_pat}")

    if choice == "3" or choice == "manual":
        info("Detektory lze přidat později v sekci Nastavení → Detektory ve webovém UI.")
        if ask_yn("Přidat alespoň základní security detektor?", "ano"):
            detectors.append({
                "plugin": "detector_universal_security",
                "match_pattern": "auth.log*",
                "enabled": True,
                "params": {"threshold": 5},
            })
            ok("Přidán detector_universal_security → auth.log*")

    if not detectors:
        warn("Žádné detektory nebyly nakonfigurovány.")

    return detectors

# =============================================================================
# MQTT
# =============================================================================

def configure_mqtt() -> dict:
    section(6, TOTAL_STEPS, "MQTT integrace (volitelné)")
    hint("MQTT = publish/subscribe pro telemetrii a ovládání.")

    if not ask_yn("Zapnout MQTT?", "ne"):
        return {"mqtt": {"enabled": False}}

    return {
        "mqtt": {
            "enabled": True,
            "host": ask("MQTT broker host/IP", "localhost"),
            "port": int(ask("MQTT port", "1883")),
            "user": ask("MQTT uživatel (prázdné = bez auth)", ""),
            "pass": ask_pass("MQTT heslo", "zadat") or "",
            "topic_prefix": ask("Topic prefix", "sentinel"),
        }
    }

# =============================================================================
# HOME ASSISTANT
# =============================================================================

def configure_ha() -> dict:
    section(7, TOTAL_STEPS, "Home Assistant integrace (volitelné)")
    hint("HA token: Profil → Bezpečnost → Dlouhodobé přístupové tokeny → Vytvořit token")

    if not ask_yn("Zapnout Home Assistant?", "ne"):
        return {"homeassistant": {"enabled": False}}

    ha_url   = ask("HA URL", "http://homeassistant.local:8123")
    ha_token = ask_pass("HA Long-Lived Access Token", "zadat")
    notify   = ask("HA notify service (prázdné = bez push notifikací)", "")

    cfg = {"enabled": True, "url": ha_url, "token": ha_token}
    if notify:
        cfg["notify_service"] = notify
    return {"homeassistant": cfg}

# =============================================================================
# NOTIFIKACE
# =============================================================================

def configure_notifications() -> dict:
    section(8, TOTAL_STEPS, "Notifikační kanály (volitelné)")
    hint("Vyber co chceš použít — zbytek lze zapnout později v UI.")

    result = {}

    # MS Teams
    if ask_yn("MS Teams webhooky?", "ne"):
        result["teams_channels"] = {
            "enabled": True,
            "webhook_url": ask("Teams Webhook URL", ""),
        }
    else:
        result["teams_channels"] = {"enabled": False}

    # ntfy
    if ask_yn("ntfy push notifikace?", "ne"):
        result["ntfy"] = {
            "enabled": True,
            "url": ask("ntfy server URL", "https://ntfy.sh"),
            "topic": ask("ntfy topic", "sentinel"),
            "token": ask_pass("ntfy token (prázdné = bez auth)", "zadat") or "",
        }
    else:
        result["ntfy"] = {"enabled": False}

    # Gotify
    if ask_yn("Gotify notifikace?", "ne"):
        result["gotify"] = {
            "enabled": True,
            "url": ask("Gotify URL", "http://localhost:8080"),
            "token": ask_pass("Gotify App token", "zadat") or "",
        }
    else:
        result["gotify"] = {"enabled": False, "url": "", "token": ""}

    # E-mail SMTP
    if ask_yn("E-mail (SMTP) notifikace?", "ne"):
        result["smtp"] = {
            "enabled": True,
            "host": ask("SMTP host", "smtp.gmail.com"),
            "port": int(ask("SMTP port", "587")),
            "user": ask("SMTP uživatel / e-mail", ""),
            "pass": ask_pass("SMTP heslo / app password", "zadat") or "",
            "from": ask("Odesílatel", "sentinel@localhost"),
            "to":   ask("Příjemce", ""),
        }
    else:
        result["smtp"] = {
            "enabled": False, "host": "localhost", "port": 587,
            "user": "", "pass": "", "from": "sentinel@localhost", "to": "",
        }

    # Matrix
    if ask_yn("Matrix notifikace?", "ne"):
        result["matrix"] = {
            "enabled": True,
            "url":     ask("Matrix homeserver URL", "https://matrix.org"),
            "token":   ask_pass("Matrix access token", "zadat") or "",
            "room_id": ask("Room ID (např. !abc:matrix.org)", ""),
        }
    else:
        result["matrix"] = {"enabled": False, "url": "", "token": ""}

    return result

# =============================================================================
# INFRASTRUKTURA & BEZPEČNOST
# =============================================================================

def configure_infrastructure() -> dict:
    section(9, TOTAL_STEPS, "Infrastrukturní mapování (uzly)")
    hint("Každý uzel je server/zařízení jehož logy Sentinel zpracovává.")
    hint("Slouží k přiřazení log souborů k pojmenovaným serverům.")

    nodes = []
    print(f"\n  Aktuálně bude přidán výchozí uzel 'localhost'.")
    if ask_yn("Přidat další uzly teď?", "ne"):
        while True:
            name = ask("Název uzlu (prázdné = hotovo)", "")
            if not name:
                break
            pattern = ask(f"  Log pattern pro '{name}'", f"{name.lower()}.log")
            mgmt    = ask(f"  Management IP/host pro '{name}'", "localhost")
            nodes.append({"name": name, "pattern": pattern, "mgmt_node": mgmt})
            ok(f"  Přidán: {name} → {pattern}")

    nodes.insert(0, {"name": "localhost", "pattern": "*.log", "mgmt_node": "localhost"})

    # SSH execution
    ssh_key = ""
    if ask_yn("Nakonfigurovat SSH pro vzdálené příkazy (remediation)?", "ne"):
        ssh_key  = ask("Cesta k SSH klíči", "/opt/Sentinel/conf/.id_ed25519")
        ssh_user = ask("SSH uživatel", "root")
        ssh_jump = ask("SSH jump host (prázdné = žádný)", "")
        ssh_cfg = {"key_path": ssh_key, "user": ssh_user, "jump_host": ssh_jump}
    else:
        ssh_cfg = {"key_path": "", "user": "root", "jump_host": ""}

    return {
        "infrastructure_mapping": nodes,
        "ssh_execution": ssh_cfg,
    }

def configure_security() -> dict:
    section(10, TOTAL_STEPS, "Bezpečnostní nastavení")
    hint("Výchozí hodnoty jsou rozumné — změň jen pokud víš proč.")

    whitelist_raw = ask("Whitelist IP (vždy povoleny, čárkou)", "127.0.0.1")
    excluded_raw  = ask("Excluded client IPs (přeskočit v logu, čárkou)", "")

    return {
        "security": {
            "login_max_attempts": int(ask("Max pokusů o přihlášení před banem", "5")),
            "login_ban_time":     int(ask("Délka banu v sekundách", "300")),
            "rate_limit_chat":    int(ask("Rate limit chat požadavků/min", "60")),
            "rate_limit_upload":  int(ask("Rate limit upload požadavků/min", "10")),
            "whitelist": [ip.strip() for ip in whitelist_raw.split(",") if ip.strip()],
        },
        "excluded_client_ips": [ip.strip() for ip in excluded_raw.split(",") if ip.strip()],
    }

# =============================================================================
# GENEROVÁNÍ KONFIGURACE
# =============================================================================

def generate_config(
    cred_cfg: dict,
    ldap_cfg: dict,
    ai_cfg:   dict,
    detectors: list,
    mqtt_cfg:  dict,
    ha_cfg:    dict,
    notif_cfg: dict,
    infra_cfg: dict,
    sec_cfg:   dict,
):
    section(11, TOTAL_STEPS, "Zápis konfigurace")

    backup = backup_config()

    instance = ask("Název instance Sentinelu", "Sentinel-Core")

    config_data = {
        "instance_name": instance,
        "log_dir":             str(LOG_DIR),
        "plugin_dir":          str(PLUGINS_DIR),
        "data_dir":            str(DATA_DIR),
        "knowledge_base_file": str(KB_FILE),

        "web": cred_cfg["web"],

        "ldap": ldap_cfg["ldap"],

        "https": {"enabled": False},

        "ollama_url":       ai_cfg["ollama_url"],
        "ollama_model":     ai_cfg["ollama_model"],
        "ollama_num_ctx":   2048,
        "worker_threads":   ai_cfg["worker_threads"],

        "mqtt":          mqtt_cfg["mqtt"],
        "homeassistant": ha_cfg["homeassistant"],

        "teams_channels": notif_cfg["teams_channels"],
        "ntfy":           notif_cfg["ntfy"],
        "gotify":         notif_cfg["gotify"],
        "smtp":           notif_cfg["smtp"],
        "matrix":         notif_cfg["matrix"],

        "infrastructure_mapping": infra_cfg["infrastructure_mapping"],
        "ssh_execution":          infra_cfg["ssh_execution"],

        "detectors": detectors,

        "prompts": {
            "default": (
                "You are a concise log monitoring assistant.\n"
                "Analyze the entire current content of the monitoring log. "
                "Determine only actual problems, not normal states.\n"
                "For each detected problem, include what it is, where it is, "
                "affected systems, and severity.\n"
                "Only one issue per message. Max 8 sentences. Use HTML output. "
                "Do not introduce yourself. No questions.\nLog: {line}\n"
            ),
            "security": (
                "Jsi expert na kybernetickou bezpečnost. Analyzuj následující záznam z logu.\n"
                "Identifikuj pokusy o Brute-force, zneužití sudo nebo neoprávněné přístupy.\n"
                "Výstup v ČEŠTINĚ, formát HTML. ZAMĚŘ SE NA IP a USERNAME.\nLog: {line}\n"
            ),
            "remediation": (
                'SysAdmin. Node: {node} Error: {raw_line} '
                'Output ONLY JSON: {"description":"one sentence fix","command":"exact bash command or N/A"}'
            ),
        },

        "security": sec_cfg["security"],
        "excluded_client_ips": sec_cfg["excluded_client_ips"],
    }

    # AI HAT sekce — pouze pokud relevantní
    if ai_cfg.get("ai_hat", {}).get("enabled"):
        config_data["ai_hat"] = ai_cfg["ai_hat"]
    if ai_cfg.get("hailo_ollama", {}).get("enabled"):
        config_data["hailo_ollama"] = ai_cfg["hailo_ollama"]

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False,
                  allow_unicode=True, width=100)

    ok(f"Konfigurace zapsána: {CONFIG_PATH}")
    if backup:
        info(f"Záloha předchozí konfigurace: {backup}")

    return config_data

# =============================================================================
# SYSTEMD SLUŽBA
# =============================================================================

def configure_systemd():
    section(12, TOTAL_STEPS, "systemd služba")

    # Zjisti správný python3 (s přístupem k nainstalovaným balíčkům)
    python_bin = sys.executable
    pythonpath = ""

    # Zkontroluj zda chromadb je dostupné
    try:
        import chromadb  # noqa
        ok(f"chromadb dostupné přes {python_bin}")
    except ImportError:
        # Hledej v user site-packages
        import site
        for major, minor in [(3, 13), (3, 12), (3, 11), (3, 10)]:
            candidate = Path(f"/home/{os.environ.get('SUDO_USER','')}"
                             f"/.local/lib/python{major}.{minor}/site-packages")
            if candidate.exists():
                pythonpath = str(candidate)
                warn(f"chromadb nalezeno v {pythonpath}")
                break
        if not pythonpath:
            warn("chromadb nenalezeno — přidej ho ručně: pip3 install chromadb")

    svc_content = f"""[Unit]
Description=Sentinel System Orchestrator & AI Worker Pool
After=network.target syslog.target

[Service]
Type=notify
ExecStartPre=/bin/bash -c 'sqlite3 /var/lib/sentinel/sentinel_state.db "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true; rm -f /var/lib/sentinel/sentinel_state.db-wal /var/lib/sentinel/sentinel_state.db-shm'
ExecStart={python_bin} -m sentinel
WatchdogSec=120
Restart=always
RestartSec=5
User=root
WorkingDirectory=/opt/Sentinel
Environment="PYTHONUNBUFFERED=1"
{f'Environment="PYTHONPATH={pythonpath}"' if pythonpath else ''}

[Install]
WantedBy=multi-user.target
"""

    svc_path = Path("/etc/systemd/system/sentinel.service")
    svc_path.write_text(svc_content)
    ok(f"Zapsáno: {svc_path}")

    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "sentinel.service"], check=True)
        ok("sentinel.service povolena (enable).")
    except subprocess.CalledProcessError as e:
        err(f"systemd chyba: {e}")

    if ask_yn("Spustit sentinel.service teď?", "ano"):
        try:
            subprocess.run(["systemctl", "start", "sentinel.service"], check=True)
            import time; time.sleep(3)
            r = subprocess.run(["systemctl", "is-active", "sentinel.service"],
                               capture_output=True, text=True)
            status = r.stdout.strip()
            if status == "active":
                ok("sentinel.service běží.")
            else:
                warn(f"Stav: {status}. Zkontroluj: journalctl -u sentinel.service -n 30")
        except subprocess.CalledProcessError:
            err("Start selhal. Zkontroluj: journalctl -u sentinel.service -n 30")

# =============================================================================
# SHRNUTÍ
# =============================================================================

def print_summary(config_data: dict, cred_cfg: dict, hailo: dict, detectors: list):
    web = config_data.get("web", {})
    creds = cred_cfg.get("_credentials_summary", {})

    print(f"\n{C.BOLD}{C.GREEN}{'━'*60}{C.RESET}")
    print(f"{C.BOLD}{C.GREEN}  INSTALACE DOKONČENA{C.RESET}")
    print(f"{C.BOLD}{C.GREEN}{'━'*60}{C.RESET}\n")

    print(f"  {C.BOLD}Instance:{C.RESET}   {config_data.get('instance_name','?')}")
    print(f"  {C.BOLD}Config:{C.RESET}     {CONFIG_PATH}")
    print(f"  {C.BOLD}Web UI:{C.RESET}     http://0.0.0.0:{web.get('port', 5050)}")

    print(f"\n  {C.BOLD}Přihlašovací údaje:{C.RESET}")
    if creds.get("admin"):
        print(f"    Admin:   {C.BOLD}{creds['admin']}{C.RESET}")
    if creds.get("viewer"):
        print(f"    Viewer:  {C.BOLD}{creds['viewer']}{C.RESET}")

    ldap = config_data.get("ldap", {})
    if ldap.get("enabled"):
        print(f"\n  {C.BOLD}LDAP:{C.RESET}       {ldap.get('host')}:{ldap.get('port')} [{ldap.get('base_dn')}]")

    print(f"\n  {C.BOLD}Detektory ({len(detectors)}):{C.RESET}")
    for d in detectors:
        status = "✓" if d.get("enabled") else "–"
        print(f"    {status} {d['plugin']:<35} → {d.get('match_pattern','?')}")

    ai_model = (config_data.get("hailo_ollama", {}).get("model")
                or config_data.get("ollama_model", "?"))
    print(f"\n  {C.BOLD}AI model:{C.RESET}   {ai_model}")

    if hailo["detected"]:
        label = "AI HAT 2+ (LLM)" if hailo["is_10h"] else "AI HAT+ (CV)"
        status = "aktivní" if hailo["active"] else "detekován — nutný reboot"
        print(f"  {C.BOLD}Hailo NPU:{C.RESET}  {hailo['chip']} ({label}) — {status}")

    active_notifs = []
    for key in ["teams_channels", "ntfy", "gotify", "smtp", "matrix", "homeassistant", "mqtt"]:
        if config_data.get(key, {}).get("enabled"):
            active_notifs.append(key)
    if active_notifs:
        print(f"\n  {C.BOLD}Aktivní integrace:{C.RESET} {', '.join(active_notifs)}")

    print(f"\n  {C.BOLD}Další kroky:{C.RESET}")
    print(f"    1. Zkontroluj config:     nano {CONFIG_PATH}")
    print(f"    2. Web UI:                http://localhost:{web.get('port', 5050)}")
    print(f"    3. Logy:                  journalctl -u sentinel.service -f")
    print(f"    4. Přidat pluginy ručně:  {PLUGINS_DIR}")
    if hailo["detected"] and not hailo["active"]:
        print(f"\n  {C.YELLOW}[!] Hailo NPU vyžaduje reboot:{C.RESET} sudo reboot")
    print()

# =============================================================================
# MAIN
# =============================================================================

def main():
    check_root()
    print_banner()

    # Krok 0 — detekce hardwaru (před číslovanými kroky)
    print(f"{C.BOLD}Detekce hardwaru...{C.RESET}")
    is_rpi5 = detect_rpi5()
    hailo   = detect_hailo()

    if is_rpi5:
        ok("Raspberry Pi 5 detekován.")
    if hailo["detected"]:
        role   = "AI HAT 2+ (LLM)" if hailo["is_10h"] else "AI HAT+ (CV/Embeddingy)"
        status = "aktivní" if hailo["active"] else "nutný reboot"
        ok(f"Hailo {hailo['chip']} ({hailo['tops']} TOPS) — {role} — {status}")
    else:
        info("Hailo NPU nedetekován.")

    # Existující config?
    if CONFIG_PATH.exists():
        warn(f"Existující konfigurace: {CONFIG_PATH}")
        warn("Bude automaticky zálohována před přepsáním.")

    print(f"\n  {C.DIM}Průvodce instalace — {TOTAL_STEPS} kroků.{C.RESET}")
    print(f"  {C.DIM}Enter = akceptovat výchozí hodnotu v [závorkách].{C.RESET}\n")
    input(f"  {C.YELLOW}[Enter pro start]{C.RESET}")

    # Kroky
    setup_directories()
    cred_cfg  = configure_credentials()
    ldap_cfg  = configure_ldap()
    ai_cfg    = select_ai_backend(hailo, is_rpi5)
    detectors = setup_detectors()
    mqtt_cfg  = configure_mqtt()
    ha_cfg    = configure_ha()
    notif_cfg = configure_notifications()
    infra_cfg = configure_infrastructure()
    sec_cfg   = configure_security()

    config_data = generate_config(
        cred_cfg, ldap_cfg, ai_cfg, detectors,
        mqtt_cfg, ha_cfg, notif_cfg, infra_cfg, sec_cfg,
    )

    configure_systemd()
    print_summary(config_data, cred_cfg, hailo, detectors)

if __name__ == "__main__":
    main()

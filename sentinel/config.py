import os
import yaml
import subprocess
import secrets
from pathlib import Path

# --- Technical Config ---
VERSION = "2026.06.031"

def get_git_commit():
    try:
        repo_path = os.path.dirname(os.path.realpath(__file__))
        commit = subprocess.check_output(
            ['git', '-c', 'safe.directory=*', 'rev-parse', '--short', 'HEAD'],
            cwd=repo_path, stderr=subprocess.DEVNULL
        ).decode('ascii').strip()
        return commit
    except Exception:
        import time
        return hex(int(time.time()))[2:]

SUBVERSION = get_git_commit()
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = Path("/etc/sentinel/config.yaml")

# --- ASCII banner ---
BANNER = f"""
                   ##  
               ++########++  
              ++++###+++++++  
             +++++++++++-++-.  
            ++++++#++++++-+-  
             ++######+++++--  
             +++  ####+  -+-  
              ++++######++-  
              ++++#######+-#  
               ++++######++-+.-+  
              ++++++###+++##+---++#  
            +++++++++###+#######++++++++  
         -+++++++++++###+#####+#+++++----..-  
      ++-++++++++#######+######++++++++--..  .  
     ---++++##+++#####++####++++#++++---.....  
    --+++++############++###++++#+++---........  
   --++++++##++##########++++++++++----.........  
   --+++++#####++#####+#+++++++++++++-.-.........  
   --++++#####+########++++++-+++++-++--------.-..  
   ++++##########+####++++++-+++++++-+++---------.

              SENTINEL v{VERSION}
"""

# --- Global Default Variables ---
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
OLLAMA_MODEL = "athene-v2"
OLLAMA_API_KEY = ""
OLLAMA_NUM_CTX = 2048
LOG_DIR = "/var/log/sentinel/logs"
DATA_DIR = "/opt/Sentinel/data"
KB_FILE_PATH = "/opt/Sentinel/knowledge_base.txt"
MAIN_LOG_FILE = "/var/log/sentinel/sentinel.log"
OLLAMA_LOG_FILE = "/var/log/sentinel/sentinel-ollama.log"

# ---> ZDE JE KLÍČOVÁ ZMĚNA 1: Přidána výchozí složka pro pluginy
PLUGIN_DIR = "/opt/Sentinel/sentinel/plugins" 

INSTANCE_NAME = "Unknown"
TEAMS_ENABLED = False
HA_ENABLED = False
HA_URL = ""
HA_TOKEN = ""
HA_NOTIFY_SERVICE = "mobile_app_your_device"
HA_ACTION_SERVICE: str = ""   # 278: volitelná HA akce při kritickém alertu (napr. "light/turn_on")
HA_ACTION_ENTITY: str = ""    # 278: entita pro HA akci (napr. "light.office")

MQTT_ENABLED = False
MQTT_HOST = "192.168.1.1"
MQTT_PORT = 1883
MQTT_USER = ""
MQTT_PASS = ""
MQTT_TOPIC_PREFIX = "sentinel"

WATCH_PATTERNS = ["*.log"]
IGNORE_PATTERNS = ["*.swp", "*.swpx", "sms.txt", "hpc-values.log"]
WORKER_THREADS = 2

# Web Defaults
WEB_HOST = "0.0.0.0"
WEB_PORT = 5050
WEB_USER = "admin"
WEB_PASS = "admin"
WEB_VIEWER_USER = "viewer"
WEB_VIEWER_PASS = "viewer"

def _load_or_create_secret_key(path: str = "/var/lib/sentinel/secret_key") -> str:
    """235: Načte SECRET_KEY ze souboru, nebo vygeneruje a uloží nový. Přežije restart."""
    try:
        p = Path(path)
        if p.exists():
            key = p.read_text().strip()
            if len(key) >= 32:
                return key
        # Vygeneruj nový klíč a ulož
        key = secrets.token_hex(32)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(key)
            os.chmod(path, 0o600)
        except Exception:
            pass  # Fallback — klíč platí jen pro tuto session
        return key
    except Exception:
        return secrets.token_hex(32)

SECRET_KEY = _load_or_create_secret_key()

# QW1: Persistentní klientský API token — nikdy hardcoded
def _load_or_create_client_api_key(path: str = "/var/lib/sentinel/client_api_key") -> str:
    try:
        p = Path(path)
        if p.exists():
            key = p.read_text().strip()
            if len(key) >= 32:
                return key
        key = secrets.token_hex(32)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(key)
            os.chmod(path, 0o600)
        except Exception:
            pass
        return key
    except Exception:
        return secrets.token_hex(32)

CLIENT_API_KEY = _load_or_create_client_api_key()

# Security Defaults
SECURITY = {
    "login_max_attempts": 5,
    "login_ban_time": 300,
    "rate_limit_chat": 60,
    "rate_limit_upload": 10,
    "whitelist": ["127.0.0.1"]
}
# 232: Trusted reverse proxies — IP odkud je X-Forwarded-For důvěryhodná
TRUSTED_PROXIES: list = ["127.0.0.1", "::1"]
# 256: DB size alert threshold (MB)
DB_SIZE_ALERT_MB: int = 500
# 257: Synthetic HTTP health checks [ {name, url, timeout} ]
SYNTHETIC_CHECKS: list = []
# 273/274/275: Dodatečné notifikační kanály
NTFY_ENABLED: bool = False
NTFY_URL: str = ""          # např. https://ntfy.sh/my-topic
NTFY_TOKEN: str = ""
GOTIFY_ENABLED: bool = False
GOTIFY_URL: str = ""        # např. http://gotify.local
GOTIFY_TOKEN: str = ""
MATRIX_ENABLED: bool = False
MATRIX_URL: str = ""        # např. https://matrix.org/_matrix/client/v3/rooms/!id:matrix.org/send/m.room.message
MATRIX_TOKEN: str = ""      # Bearer token
GRAFANA_URL: str = ""       # 326: napr. http://grafana:3000
GRAFANA_API_KEY: str = ""  # 326: Bearer token
DISCORD_ENABLED: bool = False
DISCORD_WEBHOOK_URL: str = ""
TELEGRAM_ENABLED: bool = False
TELEGRAM_BOT_TOKEN: str = ""
TELEGRAM_CHAT_ID: str = ""
OPSGENIE_ENABLED: bool = False
OPSGENIE_API_KEY: str = ""
S3_ENDPOINT: str = ""         # 330: S3/MinIO URL (napr. http://minio:9000)
S3_BACKUP_BUCKET: str = ""    # 330: Bucket pro zálohy
S3_ACCESS_KEY: str = ""
S3_SECRET_KEY: str = ""
SMTP_ENABLED: bool = False
SMTP_HOST: str = "localhost"
SMTP_PORT: int = 587
SMTP_USER: str = ""
SMTP_PASS: str = ""
SMTP_FROM: str = "sentinel@localhost"
SMTP_TO: str = ""           # čárkami oddělené adresy

# LDAP Defaults
LDAP_ENABLED = False
LDAP_HOST = "localhost"
LDAP_PORT = 389
LDAP_USE_SSL = False
LDAP_BASE_DN = ""
LDAP_USER_LOGIN_ATTR = "uid"
LDAP_SEARCH_USER_DN = ""
LDAP_BIND_DN = None
LDAP_BIND_PASSWORD = None
LDAP_VIEWERS = []
LDAP_OPERATORS = []
LDAP_ADMINS = []
LDAP_SUPERADMINS = []
LDAP_USER_OBJECT_FILTER = None

# AI HAT+ / Hailo NPU (Hailo-8/8L — computer vision chips, embeddingy)
AI_HAT_ENABLED = False
AI_HAT_DEVICE = ""           # "hailo8" (26T) nebo "hailo8l" (13T)
AI_HAT_TOPS = 0
AI_HAT_HEF_PATH = ""         # Cesta k .hef embedding modelu
AI_HAT_USE_EMBEDDINGS = False

# Hailo AI HAT 2+ / Hailo-10H — LLM inference přes hailo-ollama
HAILO_OLLAMA_ENABLED = False
HAILO_OLLAMA_URL = "http://localhost:8000/v1/chat/completions"
HAILO_OLLAMA_MODEL = "qwen2.5-coder:1.5b"

# Dedikovaná URL pro embedding (nomic-embed-text přes CPU ollama).
# Když je HAILO_OLLAMA_ENABLED=True, hailo-ollama embeddingy nepodporuje —
# RAG musí volat CPU ollama na standardním portu 11434.
# Prázdný string = odvodit automaticky z OLLAMA_URL.
EMBEDDING_OLLAMA_URL = ""

# Dynamic Containers
INFRASTRUCTURE_MAPPING = []
DETECTORS = []
PROMPTS = {}
TEAMS_CHANNELS = {}
LOG_GROUPS = {}
ARGS = {"EXTERNAL_OLLAMA": True, "DEBUG_MODE": False}
CHROMADB_PATH = ""

# Webhook notifications (generic HTTP POST)
WEBHOOK_ENABLED = False
WEBHOOK_URL = ""
WEBHOOK_SECRET = ""

# Slack webhook (079)
SLACK_ENABLED = False
SLACK_WEBHOOK_URL = ""
SLACK_CHANNEL = ""  # optional override channel (e.g. #alerts)

# PagerDuty (078)
PAGERDUTY_ENABLED = False
PAGERDUTY_ROUTING_KEY = ""  # Integration key from PagerDuty service

# Prometheus metrics scraping
PROMETHEUS_ENABLED = False
PROMETHEUS_SCRAPE_TOKEN = ""
PROMETHEUS_PUSHGATEWAY_URL = ""  # 148: POST metrics to Prometheus pushgateway
FIM_ENABLED = False  # 176: File integrity monitoring
FIM_PATHS: list = []  # 176: Seznam sledovaných souborů (default v watcher.py)

# Database retention
DB_RETENTION_DAYS = 2
TELEMETRY_AGGREGATE_AFTER_HOURS = 24  # aggregate raw telemetry older than N hours (0 = disabled)
ANALYTICS = {}  # runtime override from config.yaml analytics section
HA_THRESHOLDS = {}  # runtime override from config.yaml ha_thresholds section

# SSH execution settings (for run_ssh_command_real in actions.py)
SSH_KEY_PATH = "/opt/Sentinel/conf/.id_ed25519"
SSH_USER = "root"
SSH_JUMP_HOST = ""  # Prázdný = bez jump hostu; "user@bastion.example.com" = ProxyJump

# 010: Přizpůsobitelné barvy kanálů {channel_upper: hex_color}
CHANNEL_COLORS: dict = {
    'SECURITY': '#dc3545',
    'INFRA': '#17a2b8',
    'ICINGA': '#17a2b8',
    'ROOT': '#ffc107',
    'LOGIN': '#6f42c1',
    'AGENT': '#0078d4',
}

# Auto-tagging rules: list of {plugin, host, channel, tag} dicts
AUTO_TAGS: list = []

# Escalation rules: list of {after_hours, severity, channels} dicts (bez Teams)
ESCALATION_RULES: list = []

# SLA pravidla: list of {channel, hours} — po N hodinách aktivní issue je "SLA breach"
SLA_RULES: dict = {}  # {channel_lower: hours}

# Inbound webhook token pro příjem alertů z externích systémů
INBOUND_WEBHOOK_TOKEN: str = ""
AUTO_REGISTER_TOKEN: str = ""  # Prázdný = vypnuto; agenti s tímto tokenem se auto-registrují

# Telemetry alerting rules: [{metric, above, below, channel}]
TELEMETRY_ALERTS: list = []
INFLUXDB: dict = {}

# Self-monitoring webhook — POST vlastního health statusu na ext. URL
SELF_MONITOR_WEBHOOK: str = ""

# SNMP Trap receiver (081)
SNMP_TRAP_ENABLED: bool = False
SNMP_TRAP_CFG: dict = {"port": 1162, "host": "0.0.0.0", "community": "", "channel": "infra", "oid_map": {}}

# Network topology (120)
TOPOLOGY_CFG: dict = {"manual_links": [], "snmp_targets": [], "snmp_poll_interval": 300}

# HTTPS / HTTP2 (129)
HTTPS_ENABLED: bool = False
HTTPS_CERT_FILE: str = ""
HTTPS_KEY_FILE: str = ""
HTTPS_USE_HTTP2: bool = False  # Hypercorn místo Werkzeug (vyžaduje pip install hypercorn)
SELF_MONITOR_INTERVAL: int = 300  # sekundy

# Weekly digest report
WEEKLY_REPORT_DAY: int = 0    # 0=Pondělí … 6=Neděle
WEEKLY_REPORT_HOUR: int = 8

# Auto-resolve: issues from ONLINE agents not updated in N hours are auto-resolved
AUTO_RESOLVE_HOURS = 4
# Auto-resolve: issues missing from N consecutive agent reports are auto-resolved
AUTO_RESOLVE_MISSING_COUNT = 3
# Per-channel issue expiry (025): {channel: days} — resolved after N days even without agent
ISSUE_EXPIRY_DAYS: dict = {}
AGENT_HEARTBEAT_TIMEOUT = 180  # 037: global fallback (seconds)
# 102: IP whitelist per-role — {role: ["192.168.0.0/24", ...]}; prázdný = vypnuto
IP_WHITELIST: dict = {}
# 082: Syslog UDP receiver
SYSLOG_RECEIVER: dict = {"enabled": False, "port": 514, "host": "0.0.0.0", "channel": "infra", "min_severity": 4}

# Auto-remediation: automatically propose fix actions for detected issues
AUTO_REMEDIATION_ENABLED = True
# Public status page (/status) — no auth required
STATUS_PAGE_ENABLED = True
# Auto-severity: classify new issues severity via LLM (async, adds ~2-5s delay)
AUTO_SEVERITY_ENABLED = False
# Auto-duplicate: flag new issues that are suspiciously similar to active ones (string match)
AUTO_DUPLICATE_ENABLED = True
# SSH-based update check: periodically SSH each agent to check for pending apt upgrades
SSH_UPDATE_CHECK_ENABLED = False
SSH_UPDATE_CHECK_INTERVAL = 3600  # seconds between checks

# Services that are known to fail harmlessly and should not generate alerts or remediation proposals
IGNORED_FAILED_SERVICES = ["motd-news.service", "apt-news.service"]

# IPs that should never appear in the "connected clients" panel (automated devices, not humans)
EXCLUDED_CLIENT_IPS: list = []

# 366: Issue history retention (days) — prune issue_history older than this
ISSUE_HISTORY_RETENTION_DAYS: int = 90
# 339: Display timezone for UI timestamps (pytz name, e.g. "Europe/Prague")
DISPLAY_TZ: str = ""
# 407: Heartbeat URL monitoring (list of {name, url, timeout_s})
HEARTBEAT_URLS: list = []
# 415: Gitea issue sync
GITEA_URL: str = ""
GITEA_TOKEN: str = ""
GITEA_REPO: str = ""  # e.g. "owner/repo"

def load_config():
    global OLLAMA_URL, OLLAMA_MODEL, OLLAMA_API_KEY, OLLAMA_NUM_CTX, LOG_DIR, DATA_DIR, KB_FILE_PATH, CHROMADB_PATH, PLUGIN_DIR
    global WORKER_THREADS, WEB_HOST, WEB_PORT, WEB_USER, WEB_PASS, WEB_VIEWER_USER, WEB_VIEWER_PASS, SECRET_KEY
    global SECURITY, INFRASTRUCTURE_MAPPING, DETECTORS, PROMPTS, TEAMS_CHANNELS, LOG_GROUPS
    global LDAP_ENABLED, LDAP_HOST, LDAP_PORT, LDAP_USE_SSL, LDAP_BASE_DN, LDAP_USER_LOGIN_ATTR
    global LDAP_SEARCH_USER_DN, LDAP_BIND_DN, LDAP_BIND_PASSWORD, LDAP_VIEWERS, LDAP_OPERATORS, LDAP_ADMINS, LDAP_SUPERADMINS, LDAP_USER_OBJECT_FILTER
    global INSTANCE_NAME, TEAMS_ENABLED, HA_ENABLED, HA_URL, HA_TOKEN, HA_NOTIFY_SERVICE
    global MQTT_ENABLED, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TOPIC_PREFIX
    global AI_HAT_ENABLED, AI_HAT_DEVICE, AI_HAT_TOPS, AI_HAT_HEF_PATH, AI_HAT_USE_EMBEDDINGS
    global HAILO_OLLAMA_ENABLED, HAILO_OLLAMA_URL, HAILO_OLLAMA_MODEL, EMBEDDING_OLLAMA_URL
    global WEBHOOK_ENABLED, WEBHOOK_URL, WEBHOOK_SECRET, DB_RETENTION_DAYS
    global AUTO_RESOLVE_HOURS, AUTO_RESOLVE_MISSING_COUNT
    global AUTO_REMEDIATION_ENABLED, AUTO_SEVERITY_ENABLED, AUTO_DUPLICATE_ENABLED
    global SSH_UPDATE_CHECK_ENABLED, SSH_UPDATE_CHECK_INTERVAL
    global IGNORED_FAILED_SERVICES, EXCLUDED_CLIENT_IPS, TRUSTED_PROXIES

    global CONFIG_PATH
    # Prefer writable override in DATA_DIR over read-only /etc path
    _override = Path(DATA_DIR) / "config.yaml"
    if _override.exists() and not (CONFIG_PATH.exists() and CONFIG_PATH.samefile(_override)):
        CONFIG_PATH = _override

    if not CONFIG_PATH.exists():
        print(f"[!] Warning: Config file missing at {CONFIG_PATH}")
        return

    try:
        with open(CONFIG_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[!] Error reading config: {e}")
        return

    # 245+290: Rekurzivně nahradí "{SECRET:ENV_VAR}" hodnoty z env proměnných
    # Po substituci var smazat z environ (290: prevence leakage do child procesů)
    _used_secret_vars: set = set()
    import re as _re_secret

    def _resolve_env_secrets(obj):
        if isinstance(obj, str):
            m = _re_secret.fullmatch(r'\{SECRET:([A-Za-z_][A-Za-z0-9_]*)\}', obj.strip())
            if m:
                _used_secret_vars.add(m.group(1))
                return os.environ.get(m.group(1), '')
            return obj
        if isinstance(obj, dict):
            return {k: _resolve_env_secrets(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_resolve_env_secrets(i) for i in obj]
        return obj

    data = _resolve_env_secrets(data)
    # 290: Smazat použité SECRET env proměnné z procesu (prevence leakage)
    for _var in _used_secret_vars:
        os.environ.pop(_var, None)

    # Basic Settings
    OLLAMA_URL = data.get("ollama_url", OLLAMA_URL)
    OLLAMA_MODEL = data.get("ollama_model", OLLAMA_MODEL)
    OLLAMA_API_KEY = data.get("ollama_api_key", OLLAMA_API_KEY)
    OLLAMA_NUM_CTX = data.get("ollama_num_ctx", OLLAMA_NUM_CTX)
    LOG_DIR = data.get("log_dir", LOG_DIR)
    PLUGIN_DIR = data.get("plugin_dir", PLUGIN_DIR) 
    DATA_DIR = data.get("data_dir", DATA_DIR)
    KB_FILE_PATH = data.get("knowledge_base_file", KB_FILE_PATH)
    CHROMADB_PATH = os.path.join(DATA_DIR, "chroma_db")
    WORKER_THREADS = data.get("worker_threads", WORKER_THREADS)
    LOG_GROUPS = data.get("log_groups", {})

    # Web Config
    web_conf = data.get("web", {})
    WEB_HOST = web_conf.get("host", WEB_HOST)
    WEB_PORT = web_conf.get("port", WEB_PORT)
    WEB_USER = web_conf.get("username", WEB_USER)
    # 347: Preferuj bcrypt hash (password_hash) před plaintextem (password)
    WEB_PASS = web_conf.get("password_hash") or web_conf.get("password", WEB_PASS)
    WEB_VIEWER_USER = web_conf.get("viewer_username", WEB_VIEWER_USER)
    WEB_VIEWER_PASS = web_conf.get("viewer_password_hash") or web_conf.get("viewer_password", WEB_VIEWER_PASS)
    SECRET_KEY = web_conf.get("secret_key", SECRET_KEY)

    # Security
    SECURITY.update(data.get("security", {}))
    # 232: Trusted proxies pro X-Forwarded-For
    _tp = data.get("trusted_proxies")
    if isinstance(_tp, list):
        TRUSTED_PROXIES = _tp
    
    # LDAP Config
    ldap_conf = data.get("ldap", {})
    LDAP_ENABLED = ldap_conf.get("enabled", False)
    LDAP_HOST = ldap_conf.get("host", "localhost")
    LDAP_PORT = ldap_conf.get("port", 389)
    LDAP_USE_SSL = ldap_conf.get("use_ssl", False)
    LDAP_BASE_DN = ldap_conf.get("base_dn", "")
    LDAP_USER_LOGIN_ATTR = ldap_conf.get("user_login_attr", "uid")
    LDAP_SEARCH_USER_DN = ldap_conf.get("search_user_dn", "")
    LDAP_BIND_DN = ldap_conf.get("bind_dn", None)
    LDAP_BIND_PASSWORD = ldap_conf.get("bind_password", None)
    
    # Rozšířené role
    LDAP_VIEWERS = ldap_conf.get("viewer_users", [])
    LDAP_OPERATORS = ldap_conf.get("operator_users", [])
    LDAP_ADMINS = ldap_conf.get("admin_users", [])
    LDAP_SUPERADMINS = ldap_conf.get("superadmin_users", [])
    LDAP_USER_OBJECT_FILTER = ldap_conf.get("user_object_filter", None)

    # --- DYNAMIC AGNOSTIC LOGIC ---
    INFRASTRUCTURE_MAPPING = data.get("infrastructure_mapping", [])
    DETECTORS = data.get("detectors", [])
    TEAMS_CHANNELS = data.get("teams_channels", {})
    
    # Prompts loading (100% Agnostic)
    loaded_prompts = data.get("prompts", {})
    PROMPTS.clear()
    PROMPTS.update(loaded_prompts)

    # Teams, Home Assistant, Other
    INSTANCE_NAME = data.get("instance_name", INSTANCE_NAME)
    
    teams_conf = data.get("teams_channels", {})
    TEAMS_ENABLED = teams_conf.get("enabled", False)
    TEAMS_CHANNELS = teams_conf
    
    ha_conf = data.get("homeassistant", {})
    HA_ENABLED = ha_conf.get("enabled", False)
    HA_URL = ha_conf.get("url", HA_URL)
    HA_TOKEN = ha_conf.get("token", HA_TOKEN)
    HA_NOTIFY_SERVICE = ha_conf.get("notify_service", HA_NOTIFY_SERVICE)
    global HA_ACTION_SERVICE, HA_ACTION_ENTITY
    HA_ACTION_SERVICE = ha_conf.get("action_service", HA_ACTION_SERVICE)
    HA_ACTION_ENTITY = ha_conf.get("action_entity", HA_ACTION_ENTITY)

    mqtt_conf = data.get("mqtt", {})
    MQTT_ENABLED = mqtt_conf.get("enabled", False)
    MQTT_HOST = mqtt_conf.get("host", MQTT_HOST)
    MQTT_PORT = mqtt_conf.get("port", MQTT_PORT)
    MQTT_USER = mqtt_conf.get("user", MQTT_USER)
    MQTT_PASS = mqtt_conf.get("pass", MQTT_PASS)
    MQTT_TOPIC_PREFIX = mqtt_conf.get("topic_prefix", MQTT_TOPIC_PREFIX)
    
    # AI HAT+ / Hailo NPU (Hailo-8/8L — embeddingy)
    ai_hat_conf = data.get("ai_hat", {})
    AI_HAT_ENABLED = ai_hat_conf.get("enabled", False)
    AI_HAT_DEVICE = ai_hat_conf.get("device", "")
    AI_HAT_TOPS = int(ai_hat_conf.get("tops", 0))
    AI_HAT_HEF_PATH = ai_hat_conf.get("hef_model_path", "")
    AI_HAT_USE_EMBEDDINGS = ai_hat_conf.get("use_for_embeddings", False)

    # Hailo AI HAT 2+ (Hailo-10H — LLM přes hailo-ollama)
    hailo_ollama_conf = data.get("hailo_ollama", {})
    HAILO_OLLAMA_ENABLED = hailo_ollama_conf.get("enabled", False)
    HAILO_OLLAMA_URL = hailo_ollama_conf.get("url", HAILO_OLLAMA_URL)
    HAILO_OLLAMA_MODEL = hailo_ollama_conf.get("model", HAILO_OLLAMA_MODEL)
    EMBEDDING_OLLAMA_URL = data.get("embedding_ollama_url", EMBEDDING_OLLAMA_URL)

    # Webhook
    wh_conf = data.get("webhook", {})
    WEBHOOK_ENABLED = wh_conf.get("enabled", False)
    WEBHOOK_URL = wh_conf.get("url", WEBHOOK_URL)
    WEBHOOK_SECRET = wh_conf.get("secret", WEBHOOK_SECRET)

    # Slack (079)
    global SLACK_ENABLED, SLACK_WEBHOOK_URL, SLACK_CHANNEL
    slack_conf = data.get("slack", {})
    SLACK_ENABLED = slack_conf.get("enabled", False)
    SLACK_WEBHOOK_URL = slack_conf.get("webhook_url", SLACK_WEBHOOK_URL)
    SLACK_CHANNEL = slack_conf.get("channel", SLACK_CHANNEL)
    global PAGERDUTY_ENABLED, PAGERDUTY_ROUTING_KEY
    pd_conf = data.get("pagerduty", {})
    PAGERDUTY_ENABLED = pd_conf.get("enabled", False)
    PAGERDUTY_ROUTING_KEY = pd_conf.get("routing_key", PAGERDUTY_ROUTING_KEY)

    # 273/274/275/277: ntfy, Gotify, SMTP, Matrix
    global NTFY_ENABLED, NTFY_URL, NTFY_TOKEN
    ntfy_conf = data.get("ntfy", {})
    NTFY_ENABLED = ntfy_conf.get("enabled", NTFY_ENABLED)
    NTFY_URL = ntfy_conf.get("url", NTFY_URL)
    NTFY_TOKEN = ntfy_conf.get("token", NTFY_TOKEN)
    global GOTIFY_ENABLED, GOTIFY_URL, GOTIFY_TOKEN
    gotify_conf = data.get("gotify", {})
    GOTIFY_ENABLED = gotify_conf.get("enabled", GOTIFY_ENABLED)
    GOTIFY_URL = gotify_conf.get("url", GOTIFY_URL)
    GOTIFY_TOKEN = gotify_conf.get("token", GOTIFY_TOKEN)
    global SMTP_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TO
    smtp_conf = data.get("smtp", {})
    SMTP_ENABLED = smtp_conf.get("enabled", SMTP_ENABLED)
    SMTP_HOST = smtp_conf.get("host", SMTP_HOST)
    SMTP_PORT = int(smtp_conf.get("port", SMTP_PORT))
    SMTP_USER = smtp_conf.get("user", SMTP_USER)
    SMTP_PASS = smtp_conf.get("pass", SMTP_PASS)
    SMTP_FROM = smtp_conf.get("from", SMTP_FROM)
    SMTP_TO = smtp_conf.get("to", SMTP_TO)
    global MATRIX_ENABLED, MATRIX_URL, MATRIX_TOKEN
    matrix_conf = data.get("matrix", {})
    MATRIX_ENABLED = matrix_conf.get("enabled", MATRIX_ENABLED)
    MATRIX_URL = matrix_conf.get("url", MATRIX_URL)
    MATRIX_TOKEN = matrix_conf.get("token", MATRIX_TOKEN)
    global GRAFANA_URL, GRAFANA_API_KEY
    gf_conf = data.get("grafana_annotations", {})
    GRAFANA_URL = gf_conf.get("url", GRAFANA_URL)
    GRAFANA_API_KEY = gf_conf.get("api_key", GRAFANA_API_KEY)
    global DISCORD_ENABLED, DISCORD_WEBHOOK_URL
    discord_conf = data.get("discord", {})
    DISCORD_ENABLED = discord_conf.get("enabled", DISCORD_ENABLED)
    DISCORD_WEBHOOK_URL = discord_conf.get("webhook_url", DISCORD_WEBHOOK_URL)
    global TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    tg_conf = data.get("telegram", {})
    TELEGRAM_ENABLED = tg_conf.get("enabled", TELEGRAM_ENABLED)
    TELEGRAM_BOT_TOKEN = tg_conf.get("bot_token", TELEGRAM_BOT_TOKEN)
    TELEGRAM_CHAT_ID = str(tg_conf.get("chat_id", TELEGRAM_CHAT_ID))
    global OPSGENIE_ENABLED, OPSGENIE_API_KEY
    og_conf = data.get("opsgenie", {})
    OPSGENIE_ENABLED = og_conf.get("enabled", OPSGENIE_ENABLED)
    OPSGENIE_API_KEY = og_conf.get("api_key", OPSGENIE_API_KEY)

    # Prometheus
    global PROMETHEUS_ENABLED, PROMETHEUS_SCRAPE_TOKEN, PROMETHEUS_PUSHGATEWAY_URL
    prom_conf = data.get("prometheus", {})
    PROMETHEUS_ENABLED = prom_conf.get("enabled", False)
    PROMETHEUS_SCRAPE_TOKEN = prom_conf.get("scrape_token", PROMETHEUS_SCRAPE_TOKEN)
    PROMETHEUS_PUSHGATEWAY_URL = prom_conf.get("pushgateway_url", "")  # 148

    # FIM (176)
    global FIM_ENABLED, FIM_PATHS
    fim_conf = data.get("fim", {})
    FIM_ENABLED = fim_conf.get("enabled", False)
    fim_paths = fim_conf.get("paths", [])
    if isinstance(fim_paths, list) and fim_paths:
        FIM_PATHS = fim_paths

    # 010: Channel colors
    global CHANNEL_COLORS
    cc = data.get("channel_colors", {})
    if isinstance(cc, dict):
        CHANNEL_COLORS.update({k.upper(): v for k, v in cc.items() if isinstance(v, str)})

    # Database retention
    DB_RETENTION_DAYS = int(data.get("db_retention_days", DB_RETENTION_DAYS))
    global TELEMETRY_AGGREGATE_AFTER_HOURS
    TELEMETRY_AGGREGATE_AFTER_HOURS = int(data.get("telemetry_aggregate_after_hours", TELEMETRY_AGGREGATE_AFTER_HOURS))
    global ANALYTICS, HA_THRESHOLDS, SSH_KEY_PATH, SSH_USER, SSH_JUMP_HOST
    ANALYTICS = data.get("analytics", {})
    HA_THRESHOLDS = data.get("ha_thresholds", {})
    ssh_conf = data.get("ssh_execution", {})
    SSH_KEY_PATH = ssh_conf.get("key_path", SSH_KEY_PATH)
    SSH_USER = ssh_conf.get("user", SSH_USER)
    SSH_JUMP_HOST = ssh_conf.get("jump_host", SSH_JUMP_HOST)
    global AUTO_TAGS, ESCALATION_RULES
    AUTO_TAGS = data.get("auto_tags", [])
    ESCALATION_RULES = data.get("escalation_rules", [])
    global SLA_RULES, INBOUND_WEBHOOK_TOKEN
    # SLA rules: list [{channel, hours}] → dict {channel: hours}
    sla_list = data.get("sla_rules", [])
    SLA_RULES = {r['channel'].lower(): float(r['hours']) for r in sla_list if isinstance(r, dict) and 'channel' in r and 'hours' in r}
    INBOUND_WEBHOOK_TOKEN = data.get("inbound_webhook", {}).get("token", INBOUND_WEBHOOK_TOKEN)
    global AUTO_REGISTER_TOKEN
    AUTO_REGISTER_TOKEN = data.get("auto_register_token", AUTO_REGISTER_TOKEN)
    global TELEMETRY_ALERTS, INFLUXDB, SELF_MONITOR_WEBHOOK, SELF_MONITOR_INTERVAL
    global WEEKLY_REPORT_DAY, WEEKLY_REPORT_HOUR
    TELEMETRY_ALERTS = data.get("telemetry_alerts", [])
    INFLUXDB = data.get("influxdb", {})
    sm = data.get("self_monitor", {})
    SELF_MONITOR_WEBHOOK = sm.get("webhook_url", SELF_MONITOR_WEBHOOK)
    SELF_MONITOR_INTERVAL = int(sm.get("interval_seconds", SELF_MONITOR_INTERVAL))
    wr = data.get("weekly_report", {})
    WEEKLY_REPORT_DAY = int(wr.get("day", WEEKLY_REPORT_DAY))
    WEEKLY_REPORT_HOUR = int(wr.get("hour", WEEKLY_REPORT_HOUR))
    AUTO_RESOLVE_HOURS = int(data.get("auto_resolve_hours", AUTO_RESOLVE_HOURS))
    AUTO_RESOLVE_MISSING_COUNT = int(data.get("auto_resolve_missing_count", AUTO_RESOLVE_MISSING_COUNT))
    global ISSUE_EXPIRY_DAYS
    _expiry = data.get("issue_expiry_days", {})
    if isinstance(_expiry, dict):
        ISSUE_EXPIRY_DAYS = {k.lower(): float(v) for k, v in _expiry.items()}
    global AGENT_HEARTBEAT_TIMEOUT
    AGENT_HEARTBEAT_TIMEOUT = int(data.get("agent_heartbeat_timeout", AGENT_HEARTBEAT_TIMEOUT))
    global IP_WHITELIST
    _ipwl = data.get("ip_whitelist", {})
    if isinstance(_ipwl, dict):
        IP_WHITELIST = {k.lower(): (v if isinstance(v, list) else [v]) for k, v in _ipwl.items()}
    global SYSLOG_RECEIVER
    _sl = data.get("syslog_receiver", {})
    if isinstance(_sl, dict):
        SYSLOG_RECEIVER.update(_sl)

    global SNMP_TRAP_ENABLED, SNMP_TRAP_CFG
    _snmp = data.get("snmp_trap", {})
    if isinstance(_snmp, dict) and _snmp:
        SNMP_TRAP_ENABLED = bool(_snmp.get("enabled", False))
        SNMP_TRAP_CFG = {**SNMP_TRAP_CFG, **_snmp}

    global TOPOLOGY_CFG
    _topo = data.get("topology", {})
    if isinstance(_topo, dict) and _topo:
        TOPOLOGY_CFG = {**TOPOLOGY_CFG, **_topo}

    global HTTPS_ENABLED, HTTPS_CERT_FILE, HTTPS_KEY_FILE, HTTPS_USE_HTTP2
    _https = data.get("https", {})
    if isinstance(_https, dict) and _https:
        HTTPS_ENABLED = bool(_https.get("enabled", False))
        HTTPS_CERT_FILE = str(_https.get("cert_file", ""))
        HTTPS_KEY_FILE = str(_https.get("key_file", ""))
        HTTPS_USE_HTTP2 = bool(_https.get("use_http2", False))

    AUTO_REMEDIATION_ENABLED = bool(data.get("auto_remediation_enabled", AUTO_REMEDIATION_ENABLED))
    AUTO_SEVERITY_ENABLED = bool(data.get("auto_severity_enabled", AUTO_SEVERITY_ENABLED))
    AUTO_DUPLICATE_ENABLED = bool(data.get("auto_duplicate_enabled", AUTO_DUPLICATE_ENABLED))
    SSH_UPDATE_CHECK_ENABLED = bool(data.get("ssh_update_check_enabled", SSH_UPDATE_CHECK_ENABLED))
    SSH_UPDATE_CHECK_INTERVAL = int(data.get("ssh_update_check_interval", SSH_UPDATE_CHECK_INTERVAL))
    ignored = data.get("ignored_failed_services")
    if isinstance(ignored, list):
        IGNORED_FAILED_SERVICES = ignored
    excluded_ips = data.get("excluded_client_ips")
    if isinstance(excluded_ips, list):
        EXCLUDED_CLIENT_IPS = excluded_ips

    # 366/407/415: New integration vars
    global ISSUE_HISTORY_RETENTION_DAYS, DISPLAY_TZ, HEARTBEAT_URLS
    global GITEA_URL, GITEA_TOKEN, GITEA_REPO
    ISSUE_HISTORY_RETENTION_DAYS = int(data.get("issue_history_retention_days", ISSUE_HISTORY_RETENTION_DAYS))
    DISPLAY_TZ = str(data.get("display_tz", DISPLAY_TZ))
    _hb = data.get("heartbeat_urls")
    if isinstance(_hb, list):
        HEARTBEAT_URLS = _hb
    gitea_conf = data.get("gitea", {})
    if isinstance(gitea_conf, dict) and gitea_conf:
        GITEA_URL = str(gitea_conf.get("url", GITEA_URL))
        GITEA_TOKEN = str(gitea_conf.get("token", GITEA_TOKEN))
        GITEA_REPO = str(gitea_conf.get("repo", GITEA_REPO))

    _validate_config(data)
    _schema_validate(data)

    # Fallback if config is missing a default prompt
    if "default" not in PROMPTS:
        PROMPTS["default"] = "Analyze this log entry: {line}"

    _apply_db_overrides()

_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "web": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "username": {"type": "string", "minLength": 1},
                "password": {"type": "string"},
                "password_hash": {"type": "string"},
            }
        },
        "worker_threads": {"type": "integer", "minimum": 1, "maximum": 64},
        "db_retention_days": {"type": "integer", "minimum": 1},
        "auto_resolve_hours": {"type": "integer", "minimum": 1},
        "sla_rules": {"type": "array", "items": {"type": "object"}},
        "detectors": {"type": "array"},
        "auto_tags": {"type": "array"},
        "escalation_rules": {"type": "array"},
        "telemetry_alerts": {"type": "array"},
    }
}

def _schema_validate(data: dict) -> None:
    """331: Jsonschema validace kritických polí config.yaml."""
    import logging as _log
    _vlog = _log.getLogger(__name__)
    try:
        import jsonschema as _js
        errors = list(_js.Draft7Validator(_CONFIG_SCHEMA).iter_errors(data))
        for err in errors:
            path = " > ".join(str(p) for p in err.absolute_path) or "root"
            _vlog.warning(f"[config schema] {path}: {err.message}")
            VALIDATION_WARNINGS.append({"level": "error", "message": f"Schema: {path}: {err.message}"})
    except ImportError:
        pass  # jsonschema není dostupný — přeskočit
    except Exception as e:
        _vlog.debug(f"_schema_validate: {e}")

_KNOWN_KEYS = {
    'instance_name', 'version', 'web', 'ldap', 'log_dir', 'plugin_dir', 'data_dir',
    'knowledge_base_file', 'log_groups', 'ollama_model', 'ollama_url', 'ollama_api_key',
    'ollama_num_ctx', 'embedding_ollama_url', 'hailo_ollama', 'ai_hat', 'worker_threads',
    'detectors', 'teams_channels', 'homeassistant', 'mqtt', 'webhook', 'prometheus',
    'analytics', 'ha_thresholds', 'ssh_execution', 'db_retention_days', 'auto_resolve_hours',
    'auto_resolve_missing_count', 'auto_remediation_enabled', 'ssh_update_check_enabled',
    'ssh_update_check_interval', 'ignored_failed_services', 'excluded_client_ips', 'prompts',
    'infrastructure_mapping', 'chromadb', 'security', 'auto_tags', 'escalation_rules',
    'sla_rules', 'inbound_webhook', 'telemetry_alerts', 'influxdb', 'self_monitor',
    'weekly_report', 'auto_register_token', 'issue_expiry_days', 'slack', 'pagerduty', 'snmp_trap', 'https', 'topology',
    'telemetry_aggregate_after_hours', 'agent_heartbeat_timeout', 'channel_colors', 'ip_whitelist',
    'syslog_receiver', 'ntfy', 'gotify', 'smtp', 'matrix', 'discord', 'telegram', 'opsgenie',
    'grafana_annotations',
    'issue_history_retention_days', 'display_tz', 'heartbeat_urls', 'gitea',
}

VALIDATION_WARNINGS: list = []   # populated by _validate_config(), readable via API

def _validate_config(data: dict):
    """Nekritická validace konfigurace — varuje na problémy ale nepadá."""
    global VALIDATION_WARNINGS
    import logging as _log
    _vlog = _log.getLogger(__name__)
    warns = []

    def _w(msg: str, level: str = 'warning'):
        warns.append({'level': level, 'message': msg})
        _vlog.warning(f"[config] {msg}")

    # Neznámé klíče
    unknown = set(data.keys()) - _KNOWN_KEYS
    for k in sorted(unknown):
        _w(f"Neznámý klíč: '{k}' — bude ignorován", 'info')
    # Výchozí heslo
    if not data.get('web', {}).get('password') or data.get('web', {}).get('password') == 'CHANGE_ME':
        _w("web.password je výchozí 'CHANGE_ME' — změňte před nasazením!", 'critical')
    # Port rozsah
    try:
        port = int(data.get('web', {}).get('port', 5050))
        if not (1 <= port <= 65535):
            _w(f"Neplatný web.port: {port}", 'error')
    except (TypeError, ValueError):
        _w("web.port není číslo", 'error')
    # Cesty
    for path_key in ('log_dir', 'plugin_dir', 'data_dir'):
        p = data.get(path_key)
        if p and not os.path.exists(p):
            _w(f"{path_key} neexistuje: '{p}'", 'warning')
    # Hailo URL formát
    hailo = data.get('hailo_ollama', {})
    if isinstance(hailo, dict) and hailo.get('enabled') and not str(hailo.get('url', '')).startswith('http'):
        _w("hailo_ollama.url nevypadá jako platná URL", 'warning')
    # SLA rules
    for rule in data.get('sla_rules', []):
        if not isinstance(rule, dict) or 'channel' not in rule or 'hours' not in rule:
            _w(f"Neplatné sla_rule: {rule}", 'warning')
    # Escalation rules
    for rule in data.get('escalation_rules', []):
        if not isinstance(rule, dict) or 'after_hours' not in rule:
            _w(f"Neplatné escalation_rule: {rule}", 'warning')
    # LDAP
    ldap = data.get('ldap', {})
    if isinstance(ldap, dict) and ldap.get('enabled'):
        if not ldap.get('host'):
            _w("LDAP enabled ale ldap.host není nastaven", 'error')
        if not ldap.get('base_dn'):
            _w("LDAP enabled ale ldap.base_dn není nastaven", 'error')
    # Detektory
    for det in data.get('detectors', []):
        if not isinstance(det, dict):
            _w(f"Neplatný detektor: {det}", 'warning')
        elif not det.get('plugin'):
            _w(f"Detektor bez plugin jména: {det}", 'warning')

    VALIDATION_WARNINGS = warns

def _apply_db_overrides():
    """Apply runtime integration toggles stored in DB (survive /etc read-only filesystem)."""
    global TEAMS_ENABLED, HA_ENABLED, MQTT_ENABLED, WEBHOOK_ENABLED
    try:
        from . import state as _state
        mapping = {
            'integration.teams': 'TEAMS_ENABLED',
            'integration.homeassistant': 'HA_ENABLED',
            'integration.mqtt': 'MQTT_ENABLED',
            'integration.webhook': 'WEBHOOK_ENABLED',
        }
        g = globals()
        for db_key, var in mapping.items():
            val = _state.get_setting(db_key)
            if val is not None:
                g[var] = (val == '1')
    except Exception:
        pass  # DB not ready yet during early boot — config.yaml values remain

load_config()

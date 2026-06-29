import os
import re
import hmac
import hashlib
import logging
import requests
import json
import time
import mmap
import urllib.request
import threading
from datetime import datetime, timezone
from collections import defaultdict, deque
from . import config

# --- Logging Setup ---
main_log_dir = os.path.dirname(config.MAIN_LOG_FILE)
if main_log_dir: 
    os.makedirs(main_log_dir, exist_ok=True)

logging.basicConfig(filename=config.MAIN_LOG_FILE, level=logging.INFO, format='[%(asctime)s] %(message)s')

ollama_log_dir = os.path.dirname(config.OLLAMA_LOG_FILE)
if ollama_log_dir: 
    os.makedirs(ollama_log_dir, exist_ok=True)

ollama_logger = logging.getLogger("ollama")
ollama_handler = logging.FileHandler(config.OLLAMA_LOG_FILE)
ollama_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s'))
ollama_logger.addHandler(ollama_handler)
ollama_logger.setLevel(logging.INFO)
ollama_logger.propagate = False

def log_message(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    print(f"[+] [{timestamp}] {str(msg).strip()}")
    logging.info(msg)

def read_file_mmap(file_path: str) -> str:
    """Reads the entire file efficiently using memory mapping."""
    if not os.path.exists(file_path): 
        return ""
    try:
        file_size = os.path.getsize(file_path)
        if file_size == 0: 
            return ""
        with open(file_path, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return mm.read().decode('utf-8', errors='replace')
    except Exception:
        try:
            with open(file_path, "r", errors="replace") as f: 
                return f.read()
        except: 
            return ""

def send_to_teams(message: str, channel_type: str = "general"):
    if not getattr(config, "TEAMS_ENABLED", False):
        return

    if not getattr(config, "TEAMS_CHANNELS", None): 
        return

    webhook_url = config.TEAMS_CHANNELS.get(channel_type)
    if not webhook_url:
        return

    formatted_message = message.replace(";", "<br>")
    
    replacements = {
        "Target:": "🎯 <b>Target:</b>", "target:": "🎯 <b>Target:</b>",
        "Source:": "📡 <b>Source:</b>", "source:": "📡 <b>Source:</b>",
        "Target Node:": "🎯 <b>Target Node:</b>", "Source IP:": "📡 <b>Source IP:</b>",
        "Node:": "🖥️ <b>Node:</b>", "node:": "🖥️ <b>Node:</b>",
        "Cluster:": "🗄️ <b>Cluster:</b>", "cluster:": "🗄️ <b>Cluster:</b>",
        "Problem:": "🐛 <span style='color:black; font-weight:bold'>Problem:</span>",
        "problem:": "🐛 <span style='color:black; font-weight:bold'>Problem:</span>",
        "Command:": "⌨️ <span style='color:black; font-weight:bold; font-family:monospace'>Command:</span>",
        "command:": "⌨️ <span style='color:black; font-weight:bold; font-family:monospace'>Command:</span>",
        "Description": "📝 <span style='color:black; font-weight:bold'>Description</span>",
        "Severity": "🌡️ <span style='color:black; font-weight:bold'>Severity</span>",
        "Status": "🚦 <b>Status</b>",
        "Warning:": "⚠️ <span style='color:orange; font-weight:bold'>Warning:</span>",
        "[!]": "⚠️",
        "Critical:": "🚨 <span style='color:red; font-weight:bold'>Critical:</span>",
        "PROBLEM": "🚨 <span style='color:red; font-weight:bold'>PROBLEM</span>",
        "Error:": "❌ <span style='color:red; font-weight:bold'>Error:</span>",
        "FAILED": "🔥 <span style='color:red; font-weight:bold'>FAILED</span>",
        "UNREACHABLE": "🔴 <span style='color:red; font-weight:bold'>UNREACHABLE</span>",
        "Resolved:": "✅ <span style='color:green; font-weight:bold'>Resolved:</span>",
    }
 
    for keyword, replacement in replacements.items():
        formatted_message = formatted_message.replace(keyword, replacement)

    payload = {
        "poster": "Sentinel",
        "location": "Channel",
        "body": { "messageBody": formatted_message }
    }

    if getattr(config, "ARGS", {}).get("DEBUG_MODE"):
        print(f"[DEBUG] Teams Payload ({channel_type}): {webhook_url}")
        return

    headers = {"Content-Type": "application/json; charset=utf-8"}
    
    try:
        response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status() 
    except Exception as e:
        log_message(f"[!] Error sending to Teams ({channel_type}): {e}")

# --- GENERIC WEBHOOK ---
def send_webhook(payload: dict):
    if not getattr(config, 'WEBHOOK_ENABLED', False) or not getattr(config, 'WEBHOOK_URL', ''):
        return
    if getattr(config, 'ARGS', {}).get('DEBUG_MODE'):
        return
    try:
        body = json.dumps(payload, default=str).encode()
        headers = {'Content-Type': 'application/json'}
        secret = getattr(config, 'WEBHOOK_SECRET', '')
        if secret:
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers['X-Sentinel-Signature'] = f'sha256={sig}'
        requests.post(config.WEBHOOK_URL, data=body, headers=headers, timeout=8)
    except Exception as e:
        log_message(f"[!] Webhook error: {e}")

# --- HOME ASSISTANT NOTIFICATIONS ---
def send_ha_alert(message, title="🚨 Sentinel Alert"):
    if not config.HA_ENABLED or not config.HA_URL or not config.HA_TOKEN: 
        return False
        
    headers = {
        "Authorization": f"Bearer {config.HA_TOKEN}", 
        "Content-Type": "application/json"
    }
    
    url = config.HA_URL.rstrip('/')
    if url.endswith("/api/services/notify/notify"):
        url = url.replace("/api/services/notify/notify", "")
        
    target_service = config.HA_NOTIFY_SERVICE.lstrip('/')
    if not url.endswith(f"/api/services/notify/{target_service}"):
        url += f"/api/services/notify/{target_service}"
        
    clean_message = re.sub(r'<[^>]+>', '', message)
    clean_message = clean_message.replace('&quot;', '"').replace('&#x27;', "'")

    instance_name = getattr(config, "INSTANCE_NAME", "Unknown")
    final_title = f"[{instance_name}] {title}"
        
    payload = {
        "message": clean_message,
        "title": final_title
    }
    
    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode('utf-8'), 
            headers=headers, 
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.getcode() == 200
    except Exception as e:
        log_message(f"[!] HA Notification failed: {e}")
        return False

# --- SECURITY MANAGER ---
class SecurityManager:
    def __init__(self):
        self.login_attempts = defaultdict(list)
        self.banned_ips = {}
        self.request_history = defaultdict(lambda: defaultdict(deque))
        # 103: API key brute-force tracking {key_prefix: [timestamps]}
        self._api_key_attempts: dict = defaultdict(list)
    
    def _get_whitelist(self): return config.SECURITY.get("whitelist", ["127.0.0.1"])
    def _get_max_login(self): return config.SECURITY.get("login_max_attempts", 5)
    def _get_ban_time(self): return config.SECURITY.get("login_ban_time", 300)
    def _get_limit(self, atype):
        defaults = {'chat': 60, 'upload': 10, 'ingest': 120}
        return config.SECURITY.get(f"rate_limit_{atype}", defaults.get(atype, 30))

    def _cleanup_attempts(self, ip):
        now = time.time()
        self.login_attempts[ip] = [t for t in self.login_attempts[ip] if t > now - self._get_ban_time()]

    def is_ip_banned(self, ip):
        if ip in self._get_whitelist(): return False
        if ip in self.banned_ips:
            if time.time() > self.banned_ips[ip]:
                del self.banned_ips[ip]
                return False
            return True
        return False

    def register_failed_login(self, ip):
        if ip in self._get_whitelist(): return
        now = time.time()
        self._cleanup_attempts(ip)
        self.login_attempts[ip].append(now)
        count = len(self.login_attempts[ip])
        max_attempts = self._get_max_login()
        log_message(f"Security: Failed login from {ip}. Attempt {count}/{max_attempts}")
        if count >= max_attempts:
            self.banned_ips[ip] = now + self._get_ban_time()
            log_message(f"Security Warning: IP {ip} BANNED for {self._get_ban_time()}s.")

    def check_rate_limit(self, ip, action_type):
        if ip in self._get_whitelist(): return True
        limit = self._get_limit(action_type)
        history = self.request_history[ip][action_type]
        now = time.time()
        while history and history[0] < now - 60: 
            history.popleft()
        if len(history) >= limit:
            log_message(f"Security: Rate limit exceeded for {ip} on {action_type}.")
            return False
        history.append(now)
        return True

    def check_api_key_rate_limit(self, key_prefix: str, ip: str) -> bool:
        """103: Rate-limit failed API key attempts per IP. Max 20 failed attempts/min → 5min block."""
        now = time.time()
        attempts = self._api_key_attempts[ip]
        # Prune entries older than 60s
        self._api_key_attempts[ip] = [t for t in attempts if now - t < 60]
        if len(self._api_key_attempts[ip]) >= 20:
            log_message(f"Security: API key brute-force detected from {ip} ({len(self._api_key_attempts[ip])} attempts/min)")
            return False
        self._api_key_attempts[ip].append(now)
        return True

security = SecurityManager()

def extract_recommended_command(llm_response: str) -> str:
    code_blocks = re.findall(r"\x60\x60\x60(?:bash|sh)?\n(.*?)\x60\x60\x60", llm_response, re.DOTALL)
    if code_blocks: return code_blocks[-1].strip()
    pattern = r"\*\*Recommended Command:\*\*\s*(?:\x60\x60\x60(?:bash)?\s*)?((?:(?!\x60\x60\x60).)+)(?:\x60\x60\x60)?"
    match = re.search(pattern, llm_response, re.IGNORECASE | re.DOTALL)
    if match: return match.group(1).strip()
    return "N/A"

def extract_problem(llm_response: str) -> str:
    pattern = r'\*\*Problem:\*\*\s*"([^"]+)"'
    match = re.search(pattern, llm_response, re.IGNORECASE | re.DOTALL)
    if match: return match.group(1).strip()
    lines = llm_response.split('\n')
    for line in lines:
        if "Problem:" in line or "Issue:" in line: return line.split(':', 1)[1].strip()
    return "Unknown Issue"

# ==============================================================================
# MQTT & HOME ASSISTANT AUTO-DISCOVERY MANAGER
# ==============================================================================
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

class SentinelMqttManager:
    def __init__(self):
        self.client = None
        self.connected = False
        self.ha_discovery_prefix = "homeassistant"
        
    def start(self):
        if not getattr(config, "MQTT_ENABLED", False):
            return
        if not MQTT_AVAILABLE:
            log_message("[!] MQTT povolen, ale chybi knihovna paho-mqtt. Zkuste pip install paho-mqtt.")
            return

        instance_id = getattr(config, "INSTANCE_NAME", "Sentinel").lower().replace(" ", "_")
        self.client = mqtt.Client(client_id=f"sentinel_core_{instance_id}")
        
        if config.MQTT_USER and config.MQTT_PASS:
            self.client.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
            
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
        try:
            log_message(f"Pripojovani k MQTT brokeru {config.MQTT_HOST}:{config.MQTT_PORT}...")
            self.client.connect_async(config.MQTT_HOST, config.MQTT_PORT, 60)
            self.client.loop_start()
        except Exception as e:
            log_message(f"[!] MQTT spojeni selhalo: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            log_message(f"[+] Uspesne pripojeno k MQTT brokeru na {config.MQTT_HOST}")
            self.publish("status", "online", retain=True)
            self._publish_ha_autodiscovery()
        else:
            log_message(f"[!] MQTT odmitlo pripojeni. Navratovy kod: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            log_message("[!] Ztrata spojeni s MQTT brokerem. Pokus o reconnect...")

    def publish(self, subtopic, payload, retain=False):
        if not self.connected or not self.client:
            return
        
        instance_id = getattr(config, "INSTANCE_NAME", "Sentinel").lower().replace(" ", "_")
        full_topic = f"{config.MQTT_TOPIC_PREFIX}/{instance_id}/{subtopic}"
        
        if isinstance(payload, dict):
            payload = json.dumps(payload)
            
        self.client.publish(full_topic, str(payload), retain=retain)

    def _publish_ha_autodiscovery(self):
        """Generates MQTT Auto-Discovery payloads so HA creates sensors instantly."""
        instance_name = getattr(config, "INSTANCE_NAME", "Sentinel")
        node_id = instance_name.lower().replace(" ", "_")
        device_info = {
            "identifiers": [f"sentinel_{node_id}"],
            "name": f"Sentinel ({instance_name})",
            "model": "Sentinel",
            "manufacturer": "FoxiK",
            "sw_version": getattr(config, "VERSION", "unknown")
        }

        # ROZŠÍŘENÝ SEZNAM SENZORŮ PRO PLNOHODNOTNÝ DASHBOARD V HA
        sensors = [
            {"id": "active_issues", "name": "Active Issues", "icon": "mdi:alert-circle", "unit": "issues"},
            {"id": "agent_issues", "name": "Agent Issues", "icon": "mdi:server-network", "class": "total_increasing"},
            {"id": "root_issues", "name": "Root Sessions", "icon": "mdi:shield-account", "class": "total_increasing"},
            {"id": "security_issues", "name": "Security & CVEs", "icon": "mdi:security", "class": "total_increasing"},
            {"id": "cpu_load", "name": "CPU Load", "icon": "mdi:cpu-64-bit", "unit": "%", "class": "measurement"},
            {"id": "ram_usage", "name": "RAM Usage", "icon": "mdi:memory", "unit": "%", "class": "measurement"},
            {"id": "disk_usage", "name": "Log Disk Usage", "icon": "mdi:harddisk", "unit": "%", "class": "measurement"},
            {"id": "swap_usage", "name": "Swap Usage", "icon": "mdi:swap-horizontal", "unit": "MB", "class": "measurement"},
            {"id": "db_size", "name": "Database Size", "icon": "mdi:database"},
            {"id": "threads", "name": "Active Threads", "icon": "mdi:chart-timeline-variant", "unit": "threads"},
            {"id": "ai_requests", "name": "Total AI Requests", "icon": "mdi:robot-outline", "unit": "req", "class": "total_increasing"},
            {"id": "ai_latency", "name": "AI Avg Latency", "icon": "mdi:timer-outline", "unit": "s", "class": "measurement"},
            {"id": "queue_depth", "name": "AI Queue Depth", "icon": "mdi:tray-full", "unit": "tasks"},
            {"id": "active_clients", "name": "Connected Clients", "icon": "mdi:account-network", "unit": "clients"},
            {"id": "rag_status", "name": "RAG Status", "icon": "mdi:brain"},
            {"id": "uptime", "name": "Uptime", "icon": "mdi:clock-outline"}
        ]

        for s in sensors:
            topic = f"{self.ha_discovery_prefix}/sensor/sentinel_{node_id}/{s['id']}/config"
            state_topic = f"{config.MQTT_TOPIC_PREFIX}/{node_id}/telemetry"
            
            payload = {
                "name": f"{instance_name} {s['name']}",
                "unique_id": f"sentinel_{node_id}_{s['id']}",
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.{s['id']} }}}}",
                "icon": s['icon'],
                "device": device_info
            }
            if "unit" in s: payload["unit_of_measurement"] = s["unit"]
            if "class" in s: payload["state_class"] = s["class"]

            self.client.publish(topic, json.dumps(payload), retain=True)

mqtt_manager = SentinelMqttManager()

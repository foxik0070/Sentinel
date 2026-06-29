# Sentinel Commander – Instalační příručka

## Rychlý start

```bash
cd /opt/Sentinel
sudo bash install.sh
```

Skript automaticky detekuje OS, nainstaluje systémové závislosti, Python balíček,
vytvoří adresáře a zaregistruje systemd service.

---

## Podporované platformy

| OS                          | Python  | Poznámka                                 |
|-----------------------------|---------|------------------------------------------|
| Debian 12 / Ubuntu 22.04+   | 3.11+   | Plná podpora                             |
| Raspberry Pi OS (Bookworm)  | 3.11+   | Plná podpora                             |
| RHEL / Rocky / Alma 9       | 3.9+    | Standardní instalace                     |
| RHEL / Rocky / Alma 8       | 3.9     | Vyžaduje explicitně `python3.9-devel`    |

---

## Manuální instalace (krok za krokem)

### 1. Systémové závislosti

**Debian/Ubuntu/Raspberry Pi OS:**
```bash
sudo apt update
sudo apt install -y build-essential python3-dev python3-pip git curl
```

**RHEL 9 / Rocky 9:**
```bash
sudo dnf install -y gcc gcc-c++ python3-devel git curl
```

**RHEL 8 / Rocky 8:**
```bash
sudo dnf install -y gcc gcc-c++ python39 python39-devel git curl
# Dále používej python3.9 místo python3
```

### 2. Python balíček

```bash
cd /opt/Sentinel
sudo python3 -m pip install -e . --break-system-packages
sudo python3 -m pip install paho-mqtt --break-system-packages
```

> `setup.py` automaticky detekuje OS a přidá `pysqlite3-binary` na starých systémech
> (RHEL 8/9, Ubuntu Focal/Bionic), kde je SQLite < 3.35 (potřebuje ChromaDB).

### 3. Adresáře

```bash
sudo mkdir -p /var/log/sentinel/logs /opt/Sentinel/data /var/lib/sentinel
sudo chown $USER:$USER /var/log/sentinel/logs /opt/Sentinel/data /var/lib/sentinel
```

> **Pozn.:** Stavová SQLite DB (`sentinel_state.db`) je od v2026.06.006 v
> `/var/lib/sentinel/` — MIMO inotify-sledovaný `/var/log/sentinel/logs`. Když je
> DB uvnitř sledovaného adresáře, každý zápis budí watcher a soutěží o I/O s log
> churnem → `sqlite3.connect()` tuhne → watchdog restart. Lze přepsat přes
> `SENTINEL_DB_DIR`. `sentinel_init.py` adresář vytvoří automaticky.

### 4. Konfigurace

```bash
nano /opt/Sentinel/config.yaml
```

Klíčové sekce:
```yaml
server:
  host: "0.0.0.0"
  port: 5050

auth:
  secret_key: "<náhodný řetězec>"
  superadmin_password: "<silné heslo>"

mqtt:
  enabled: true           # vyžaduje paho-mqtt
  host: "192.168.x.x"
  port: 1883

ollama:
  enabled: false          # pokud nemáš Ollama server
  host: "http://localhost:11434"
```

### 5. Systemd service

```bash
sudo cp /etc/systemd/system/sentinel.service /etc/systemd/system/sentinel.service.bak 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel
sudo systemctl status sentinel
journalctl -u sentinel -f
```

---

## Ověření instalace

```bash
bash /opt/Sentinel/check.sh
```

Výstup ukáže `[OK]` / `[CHYBÍ]` pro každý soubor a adresář.

---

## Aktualizace

```bash
cd /opt/Sentinel
git pull
sudo python3 -m pip install -e . --break-system-packages
sudo systemctl restart sentinel
```

---

## Odinstalace

```bash
sudo systemctl disable --now sentinel
sudo rm /etc/systemd/system/sentinel.service
sudo systemctl daemon-reload
sudo rm -rf /var/log/sentinel
# Zachov /opt/Sentinel/data pokud chceš databázi
```

---

## Řešení problémů

### ModuleNotFoundError po aktualizaci

```bash
sudo python3 -m pip install -e /opt/Sentinel --break-system-packages --force-reinstall
sudo systemctl restart sentinel
```

### MQTT odpojeno (i když broker běží)

Chybí knihovna:
```bash
sudo python3 -m pip install paho-mqtt --break-system-packages
sudo systemctl restart sentinel
journalctl -u sentinel -n 20 | grep -i mqtt
```

### ChromaDB / SQLite chyba na RHEL 8/9

```bash
sudo python3 -m pip install pysqlite3-binary --break-system-packages
sudo systemctl restart sentinel
```

### WatchdogSec timeout

Sentinel posílá systemd notify přes `watchdog.py`. Pokud neodpovídá včas,
service se restartuje. Zkontroluj logy:
```bash
journalctl -u sentinel --since "10 minutes ago"
```

---

## Doplňkové komponenty

### Ollama (lokální LLM)

```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.2
ollama pull nomic-embed-text   # pro RAG
```

V `config.yaml`:
```yaml
ollama:
  enabled: true
  host: "http://localhost:11434"
  model: "llama3.2"
```

### piper-tts (volitelné – pro TTS na RPi)

```bash
pip3 install piper-tts --break-system-packages
sudo mkdir -p /usr/share/piper
# Stáhni cs_CZ-jirka-medium.onnx z https://huggingface.co/rhasspy/piper-voices
```

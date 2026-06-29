# SENTINEL COMMANDER — Kompletní dokumentace

**Verze:** v2026.06.022  
**Jazyk:** Čeština  
**Autor:** FoxiK  

---

## Obsah

1. [Přehled systému](#1-přehled-systému)
2. [Architektura](#2-architektura)
3. [Tok dat](#3-tok-dat)
4. [Instalace a konfigurace](#4-instalace-a-konfigurace)
5. [Uživatelská příručka — UI](#5-uživatelská-příručka--ui)
6. [Agenti](#6-agenti)
7. [Pluginy a detektory](#7-pluginy-a-detektory)
8. [AI a analýza](#8-ai-a-analýza)
9. [Telemetrie a metriky](#9-telemetrie-a-metriky)
10. [Notifikace a integrace](#10-notifikace-a-integrace)
11. [Bezpečnost a přístupová práva](#11-bezpečnost-a-přístupová-práva)
12. [SSH a akce](#12-ssh-a-akce)
13. [Databáze — schéma](#13-databáze--schéma)
14. [REST API — kompletní referenční příručka](#14-rest-api--kompletní-referenční-příručka)
15. [Konfigurace — kompletní reference config.yaml](#15-konfigurace--kompletní-reference-configyaml)
16. [Programátorská příručka](#16-programátorská-příručka)
17. [Systemd, watchdog, provoz](#17-systemd-watchdog-provoz)
18. [Řešení problémů](#18-řešení-problémů)

---

## 1. Přehled systému

**Sentinel Commander** je hybridní monitorovací systém pro Linux infrastrukturu s integrovanou AI analýzou. Kombinuje pasivní sledování log souborů (inotify pull) s aktivním reportingem vzdálených agentů (push přes HTTP) a lokálním LLM inferenčním enginem (Ollama / Hailo NPU).

### Co Sentinel dělá

- **Monitoruje log soubory** v reálném čase pomocí inotify — při každé změně předá nové řádky registrovaným pluginům (detektorům)
- **Přijímá reporty od agentů** — vzdálené Python skripty POST-ují alerty na `/api/v1/agent/ingest`
- **Analyzuje incidenty pomocí AI** — lokální LLM (Ollama nebo Hailo NPU) navrhuje příčiny, opravy a runbooky
- **Koreluje a klasifikuje** — automaticky detekuje duplicity, skupinuje příbuzné incidenty, přiřazuje severity
- **Odesílá notifikace** — MS Teams, Home Assistant, MQTT, Slack, PagerDuty, vlastní webhook
- **Navrhuje a provádí opravy** — SSH příkazy, ansible playbooks, auto-remediace
- **Sbírá telemetrii** — CPU, RAM, disk, teploty, síťové metriky, UPS, GPU, SMART

### Klíčové vlastnosti

| Vlastnost | Popis |
|-----------|-------|
| AI backend | Hailo-10H NPU (hailo-ollama), lokální Ollama, externí OpenAI-compatible proxy |
| RAG znalostní báze | ChromaDB + nomic-embed-text, BM25 fallback |
| Databáze | SQLite 3 (WAL mode, connection pooling) |
| Frontend | Čistý JS bez frameworku, Socket.IO, Chart.js |
| Auth | Local basic auth nebo LDAP (OpenLDAP, LLDAP) |
| RBAC | viewer → admin → superadmin |
| Responsivita | PC i mobilní zařízení |

---

## 2. Architektura

### Komponentový diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        SENTINEL SERVER                          │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │  inotify     │    │  Flask + SocketIO │    │  AI Worker   │  │
│  │  watcher.py  │───▶│  (port 5050)     │◀──▶│  (asyncio)   │  │
│  └──────────────┘    └──────────────────┘    └──────────────┘  │
│         │                    │                      │           │
│         ▼                    ▼                      ▼           │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │  Plugin      │    │  SQLite DB       │    │  Ollama /    │  │
│  │  Manager     │───▶│  (WAL mode)      │    │  Hailo NPU   │  │
│  └──────────────┘    └──────────────────┘    └──────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
         ▲                    ▲
         │                    │
┌─────────────────┐  ┌─────────────────────┐
│  Log soubory    │  │  Vzdálení agenti    │
│  /var/log/...   │  │  POST /api/ingest   │
└─────────────────┘  └─────────────────────┘
```

### Soubory a adresáře

```
/opt/Sentinel/
├── sentinel/                 # Hlavní Python balíček
│   ├── __main__.py           # Vstupní bod (python3 -m sentinel)
│   ├── config.py             # Konfigurace (globální proměnné + reload)
│   ├── watcher.py            # inotify sledování log souborů + FIM
│   ├── plugin_manager.py     # Dynamický loader a dispatcher pluginů
│   ├── chat_service.py       # Hlavní servisní třída: AI, maintenance loop, notifikace
│   ├── actions.py            # SSH exec, AI akce, safety checker
│   ├── analytics.py          # Prediktivní analytika (Mann-Kendall, lineární regrese)
│   ├── rag.py                # RAG (ChromaDB + BM25 fallback)
│   ├── auth.py               # LDAP + Basic auth
│   ├── safety.py             # Bezpečnostní klasifikátor příkazů
│   ├── topology.py           # Síťová topologie (SNMP/CDP)
│   ├── utils.py              # Utilities (HA, MQTT, notifikace)
│   ├── snmp_trap.py          # SNMP trap receiver (UDP)
│   ├── syslog_receiver.py    # Syslog UDP receiver
│   ├── state.py              # Facade — re-exportuje state_*.py
│   ├── state_base.py         # DB inicializace, připojení, fronty
│   ├── state_issues.py       # Issues (problems), telemetrie, thresholdy, runbooky
│   ├── state_agents.py       # Agenti, FIM, snooze rules, SSH log
│   ├── plugins/              # Detektory (pluginy)
│   │   ├── base.py           # BaseDetector ABC
│   │   ├── security_detector.py
│   │   ├── services_detector.py
│   │   ├── storage_detector.py
│   │   ├── system_detector.py
│   │   ├── capacity_detector.py
│   │   ├── ha_detector.py
│   │   ├── temperature_detector.py
│   │   ├── availability_detector.py
│   │   ├── audit_detector.py
│   │   ├── port_detector.py
│   │   └── detector_universal_security.py
│   ├── routes/               # Flask Blueprints
│   │   ├── agents.py         # /api/agents/*, /api/v1/agent/ingest
│   │   ├── actions.py        # /api/v1/actions/*, /api/ssh/*, /api/ansible/run
│   │   ├── issues.py         # /api/issues/*, /api/modal_issues/*, /api/analyze/*
│   │   ├── system.py         # /api/metrics, /api/predictions/*, /api/config/*
│   │   ├── integrations.py   # /api/integrations/*, /api/inbound/*
│   │   ├── export.py         # /api/export/*
│   │   └── chat.py           # /api/chat, /api/chat/stream
│   ├── static/               # Statické soubory (JS, CSS, ikony)
│   │   ├── script-core.js    # Chat, log viewer, základní UI
│   │   ├── script-agents.js  # Agent health dashboard, agent detail
│   │   ├── script-modals.js  # Modální okna (issues, comments, triage...)
│   │   ├── script-ui.js      # Dashboard, Tools modal, connection status
│   │   ├── i18n.js           # Lokalizace (CZ/EN)
│   │   ├── style.css         # Hlavní stylesheet
│   │   └── *.min.js/css      # Minifikované verze
│   └── templates/
│       ├── index.html        # Hlavní aplikace
│       └── login.html        # Přihlašovací stránka
├── config.yaml.example       # Šablona konfigurace
├── HISTORY.md                # Changelog
├── README.md                 # Stručný přehled
├── install.sh                # Instalační skript
├── service/
│   ├── sentinel.service      # systemd unit
│   └── hailo-ollama.service  # hailo-ollama NPU service
└── docs/
    └── SENTINEL_COMPLETE_DOCUMENTATION.md   # Tento dokument
```

### Hlavní vlákna (threads)

| Vlákno | Účel | Interval |
|--------|------|----------|
| Flask + SocketIO | HTTP server, WebSocket | kontinuální |
| inotify Observer | Sledování log souborů | event-driven |
| AI Worker | Zpracování AI požadavků z fronty | event-driven |
| Telemetry Flush | Batch zápis telemetrie do DB | každých 5 s |
| Maintenance Loop | Snooze rules, FIM, self-metriky, health snapshots | každých 30 s |
| SNMP Trap Receiver | UDP port 162 | event-driven |
| Syslog Receiver | UDP port 514 | event-driven |
| Agent Heartbeat | Kontrola offline agentů | každých 50 s |
| Watchdog | systemd SD_NOTIFY ping | každých 60 s |

---

## 3. Tok dat

### 3.1 Pull monitorování (log soubory)

```
Log soubor změní se
        │
        ▼
inotify event → watcher.LogHandler.on_modified()
        │
        ▼
plugin_manager.dispatch(filepath, new_lines)
        │
        ├──▶ security_detector.py  → fail2ban, SSH bruteforce, CVE
        ├──▶ services_detector.py  → systemd selhání
        ├──▶ storage_detector.py   → disk full, zpool errors
        ├──▶ system_detector.py    → OOM, kernel panic
        ├──▶ capacity_detector.py  → kapacita, threshold
        ├──▶ ha_detector.py        → Home Assistant sensory
        ├──▶ temperature_detector.py → teploty HW
        └──▶ vlastní pluginy...
                │
                ▼
        api.report_problem(key, payload)
                │
                ▼
        state.save_problem(key, data)  →  tabulka problems (SQLite)
                │
                ├──▶ Socket.IO emit("new_alert")  →  UI refresh
                ├──▶ AI Worker (asyncio queue)  →  analýza
                └──▶ Notifikace (Teams/HA/MQTT/Slack...)
```

### 3.2 Push monitorování (vzdálení agenti)

```
Vzdálený agent
        │
        POST /api/v1/agent/ingest
        │  Authorization: Bearer <token>
        │  {hostname, events: [{plugin, status, message}], metrics: {cpu_pct, ram_pct, ...}}
        │
        ▼
routes/agents.py:agent_ingest_payload()
        │
        ├──▶ Ověření tokenu z DB
        ├──▶ Aktualizace heartbeatu (agents.last_seen = now, status = ONLINE)
        ├──▶ Zpracování metrics{} → save_telemetry_snapshot() + check_agent_thresholds()
        ├──▶ Zpracování events[]
        │       ├── Přiřazení kanálu (security/root/agent)
        │       ├── save_problem(key, payload)
        │       └── auto-resolve chybějících issues
        └──▶ Response: {status, processed, config_update?}
```

### 3.3 AI pipeline

```
Trigger (nový issue, chat dotaz, replay)
        │
        ▼
chat_service.execute_ollama(prompt, num_ctx, max_tokens)
        │
        ├── Hailo NPU (hailo-ollama:8000)?  →  NPU inference
        │          fallback ↓
        └── Ollama CPU (:11434)?           →  CPU inference
                   fallback ↓
                   Streaming SSE response
                           │
                           ▼
                   Výsledek → UI chat / issue.ai_analysis
```

### 3.4 Tok telemetrie

```
Zdroj metriky (plugin / agent / self)
        │
        ▼
state.save_telemetry(metric, value, category)
        │
        ▼
_telemetry_buffer[] (in-memory, thread-safe)
        │  flush každých 5s
        ▼
INSERT INTO telemetry (timestamp, category, metric, value)
        │
        ├──▶ Anomaly detection (3σ)  →  issue pokud anomálie
        ├──▶ Telemetry alerts (pevné thresholdy z config)
        ├──▶ Per-agent thresholdy (agent_thresholds)
        └──▶ InfluxDB export (neblokující thread)
```

---

## 4. Instalace a konfigurace

### 4.1 Požadavky

| Komponenta | Verze | Povinná |
|-----------|-------|---------|
| Python | 3.11+ | ✓ |
| SQLite | 3.35+ | ✓ |
| Ollama | libovolná | doporučená |
| ChromaDB | ≥0.4 | pro RAG |
| pysqlite3-binary | - | starší SQLite |
| hailo-ollama | - | pro NPU |
| ansible | - | pro playbook runner |

### 4.2 Instalace

```bash
# Klonování
git clone <repo> /opt/Sentinel
cd /opt/Sentinel

# Závislosti
pip3 install -r requirements.txt

# Konfigurace
cp config.yaml.example /etc/sentinel/config.yaml
nano /etc/sentinel/config.yaml

# Systemd
cp service/sentinel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sentinel

# Spuštění pro vývoj
python3 -m sentinel -e
```

### 4.3 Parametry spuštění

```
python3 -m sentinel [OPTIONS]

  -e, --external-ollama   Používat externí Ollama (výchozí: lokální)
  -d, --debug             Debug režim (verbose logging)
  --port PORT             Web port (default: 5050)
  --host HOST             Web host (default: 0.0.0.0)
  --config PATH           Cesta k config.yaml
```

---

## 5. Uživatelská příručka — UI

### 5.1 Přihlášení

URL: `http://sentinel-server:5050/login`

- Výchozí přihlašovací údaje: `admin` / `admin` (nutno změnit v config)
- Alternativně LDAP přihlášení (pokud nakonfigurováno)
- Na přihlašovací stránce je odkaz **"Zobrazit veřejný dashboard"** → `/status`

### 5.2 Hlavní rozhraní

Rozhraní se skládá ze tří hlavních oblastí:

```
┌──────────────────────────────────────────────────────────┐
│  HEADER: Logo | Záznamy z Logů | Agenti | Root | Security│
│          Client status | Notifikace | Uživatel           │
├────────────────┬─────────────────────────────────────────┤
│                │                                         │
│  TOOLS PANEL   │           CHAT                          │
│  (levý panel)  │    (AI asistent, log viewer)            │
│                │                                         │
│  ▸ Dashboard   │                                         │
│  ▸ LOG Viewer  │                                         │
│  ▸ Agenti      │                                         │
│  ▸ SSH/Akce    │                                         │
│  ▸ Notifikace  │                                         │
│  ▸ Settings    │                                         │
│  ▸ Monitoring  │                                         │
│  ▸ Nástroje    │                                         │
└────────────────┴─────────────────────────────────────────┘
```

### 5.3 Issues modal (Incident Matrix)

Otevřete kliknutím na badge v headeru:

- **Záznamy z Logů (infra)** — incidenty z log souborů
- **Záznamy z Agentů (agent)** — reporty vzdálených agentů
- **Root záznamy (root)** — root shell sessions
- **Security záznamy (security)** — bezpečnostní incidenty

**Toolbar issues modalu:**

| Prvek | Funkce |
|-------|--------|
| Filter input | Filtrování po hostu, pluginu, zprávě, #tagu |
| `Alt+F` | Fokus na filter |
| AI Souhrn | AI analýza všech aktuálních issues |
| Korelace | AI root cause korelace issues |
| Clustery | Algoritmické auto-clustering příbuzných issues |
| 🔔 | Nastavení notifikací pro kanál |
| Triage | Prioritní seřazení issues |
| Výběr | Bulk mode — hromadné akce |
| Hodiny | Zobrazit/skrýt odložené issues |

**Issue karta obsahuje:**

- Časová značka, název pluginu, occurrence counter (×N)
- Hostname + zkrácená zpráva (hover = plná zpráva)
- Barevný štítek (manuálně přiřaditelný)
- Severity badge (critical/high/medium/low)
- Tagy (#tag)
- Závislosti badge
- Ikona: 💬 komentář | 🔗 závislosti | ✨ autofix | 💻 SSH | 🏷️ tag | ✗ false positive | 🔍 podobné | ↗ sdílet | 🗑️ smazat | ↕ fullscreen
- ⠿ drag handle pro přeřazení pořadí

**Fullscreen detail issue:**
Klik na ↕ ikonu → fullscreen overlay se čtyřmi sekcemi:
- Vlevo: detail (host, plugin, timestamp, status, plná zpráva, tagy)
- Vlevo dole: komentáře + timeline + formulář pro přidání komentáře
- Vpravo: AI analýza (tlačítko Spustit AI)
- Vpravo dole: podobné historické incidenty

**Workflow stavů issue:**

```
active → acknowledged (tlačítko ✓✓)
       → validating  (automaticky po AI analýze)
       → resolved    (auto-resolve nebo manuálně)
       → snoozed     (odloženo do konkrétního času)
```

**Stránkování (Virtual scroll):**
Issues se načítají po 50. Pokud je více, zobrazí se tlačítko "Načíst dalších X z N zbývajících".

**Mobile swipe gesta (na zařízeních <850px):**
- Swipe doprava → acknowledge issue
- Swipe doleva → smazat issue (s potvrzením)

**Bulk akce (Výběr mode):**
- Vše / Nic
- Potvrdit (acknowledge)
- Ignorovat
- Smazat
- Hromadná severita
- Hromadné přiřazení uživateli

### 5.4 Dashboard

Otevřít: Tools Panel → Dashboard

Zobrazuje:
- **Stat karty**: Celkem issues, Aktivní, Snoozed, Online agenti, Offline agenti
- **Systém**: CPU load, RAM, procesy, uptime Sentinelu
- **Teploty hostů**: sparkline grafy top-6 nejžhavějších hostů
- **Trend chart**: 7denní trend issues (Chart.js)
- **Donut chart**: Issues podle kanálu
- **Top pluginy**: nejaktivnější detektory
- **Nedávné incidenty**: posledních 10 issues

**Nastavení widgetů**: tlačítko ⚙ (sliders) → zaškrtávací seznam widgetů (perzistováno v localStorage)

**Veřejný dashboard**: tlačítko "Veřejný" → `/status` (bez přihlášení)

### 5.5 LOG Viewer

Otevřít: Tools Panel → LOG Viewer

- **Strom log souborů** vlevo: skupiny (`log_groups` z config)
- **Prohlížeč** vpravo: obsah souboru (monospaced, 32 000 řádků)
- **Toolbar**: hledat/zvýraznit, filtr úrovně (ERROR/WARN/INFO/DEBUG), přejít na konec, kopírovat, stáhnout, zalamování

**Test detektoru (ikona zkumavky ⚗):**
Spodní panel s testovacím nástrojem:
- Vlevo: seznam aktivních custom patternů (zaškrtnout pro test)
- Po otevření: automaticky načte prvních 4000 znaků aktuálního logu
- Vpravo: výsledky shod (zelená = match, červená = žádná shoda)
- "Obnovit z logu": znovu načte obsah logu
- "Spustit test": spustí vybrané patterny nad textem

### 5.6 Tools Modal — záložky

Otevřít: Tools Panel → Monitoring & Nástroje

| Záložka | Obsah |
|---------|-------|
| Agent Health | Tabulka agentů se stavem, score, statistikami |
| Srovnat | Porovnání 2 agentů vedle sebe (telemetrie diff) |
| Alert Timeline | Heatmap alertů v čase (hod × den) |
| Plugin Statistiky | Tabulka pluginů s count, channel, FP/TP |
| Graf | Plugin dependency graph |
| Config diff | Porovnání aktuálního config s šablonou |
| Mapa | Síťová topologie agentů (skupiny + stav) |
| Changelog | Git log posledních commitů |
| AI Trend | 7/14/30 denní AI trend report |
| Kapacita | Kapacitní předpověď + AI analýza upgrade/resize |
| Srovnání | Porovnání dvou časových oken telemetrie |
| Patterns | Pattern editor (regex custom patterny) + AI návrh |
| Maintenance Windows | Plánovaná okna údržby (snooze rules) |
| KB Reindex | Reindex RAG znalostní báze |
| Historie | Prohledávání historie vyřešených issues |
| Suprese | Pravidla pro potlačení alertů (glob host+plugin) |
| False Positive | Seznam označených false positives |
| Dep Graph | Graf závislostí issues |
| Wiki | Interní wiki (Markdown stránky) |

### 5.7 Agent Health Dashboard

Záložka "Agent Health" v Tools modal.

Každý agent má řádek s:
- Status badge (ONLINE/OFFLINE)
- Hostname
- Health score (0-100)
- Alerty 24h / 7d / celkem
- Data lag (ms)
- Verze agenta (SHA)
- Skupina
- Poslední ping
- Tlačítka: detail, SSH, Maintenance, Group maintenance

**Agent detail modal** (klik na agenta nebo název):
- Metadata (status, IP adresy, kategorie, verze, skupina, registered_at, last_seen)
- Telemetrické grafy posledních 24h (Chart.js)
- Aktivní issues tohoto agenta
- Sekce Skupina (úprava skupiny)
- Sekce Heartbeat timeout (per-agent override)
- Sekce Poznámky (volný text)
- Sekce Maintenance (jednorázová: 30 min / 2 hod / 8 hod)
- Sekce Plánovaná okna údržby (recurring, per-host)
- Sekce Per-Agent Thresholdy (quick-buttons CPU/RAM/Disk + vlastní)
- Sekce Štítky/Labels (key=value tagy)
- Sekce Nainstalované balíčky (on-demand přes SSH)
- Sekce CVE / Security scan (apt/dnf security updates)
- Sekce HW metriky (net/GPU/SMART/UPS)
- Tlačítko Regenerovat token (jen superadmin)

**Batch SSH modal** (tlačítko "Batch SSH" v Agent Health):
- Checkboxy pro výběr agentů (zelená/červená tečka = online/offline)
- Input pro příkaz (musí být v allowlistu)
- Tlačítka "Vše" / "Nic"
- Výsledky per host s OK/FAIL indikátorem a výstupem

### 5.8 Chat (AI asistent)

Pravá část UI. AI asistent odpovídá na dotazy, analyzuje incidenty, navrhuje opravy.

**Rychlé příkazy:**

| Příkaz | Akce |
|--------|------|
| `stav` | Přehled aktivních a validujících issues |
| `pending` | Seznam čekajících AI akcí |
| `sys` | Stav systému (CPU, RAM, AI model) |
| `analyzovat [název logu]` | Hloubková AI analýza konkrétního logu |
| `LIVE [dotaz]` | Dotaz nad aktuálními issues (přidá živý kontext) |

**LIVE tag:**
Prefix `LIVE` nebo `[LIVE]` před dotazem automaticky přidá top-30 aktivních issues jako kontext do AI promptu. Příklad: `LIVE Proč je infrastruktura nestabilní?`

**AI analýza logu:**
Kliknutím na soubor v LOG Vieweru a následně "Analyzovat" spustí AI analýzu.

**Streaming odpovědi:**
Odpovědi AI se streamují přes Server-Sent Events (SSE). Tlačítko "Zkopírovat poslední odpověď".

**Markdown rendering:**
Odpovědi AI jsou renderovány jako markdown (bold, nadpisy, inline kód, bullet listy, code bloky se zvýrazněním syntaxe).

### 5.9 SSH a akce

**SSH Modal** (z headeru nebo agent detailu):
- Výběr hostu, příkaz (musí být v allowlistu)
- Výstup: streaming přes SSE nebo blokující

**SSH bezpečnost:**
1. Příkaz musí být v Allowed Commands (allowlist)
2. Safety klasifikátor (LLM nebo heuristika) blokuje rizikové příkazy
3. Každá akce je logována do `ssh_execute_log`

**Ansible Playbook Runner** (`/api/ansible/run`):
- Vstup: hostname, cesta k playbooku (.yaml/.yml), extra_vars
- Backend: sestaví `ansible-playbook` příkaz, spustí lokálně
- Výstup: stdout/stderr

### 5.10 Stav spojení modal

Klik na zelený online badge v headeru.

Zobrazuje:
- Server: hostname, verze Sentinelu, port, WS klienti
- AI: model, backend (NPU/CPU), počet requestů, průměrná latence
- Integrace: MQTT Připojeno/Vypnuto, Home Assistant Připojeno/Vypnuto, MS Teams Vypnuto/Zapnuto
- DB size, uptime, aktivní issues
- Auto-refresh každých 30 s

### 5.11 O systému Sentinel

Klik na "FoxiK 2026" v headeru.

Zobrazuje: popis systému, proč vznikl, autor FoxiK, kontakt.

**Klik na logo (štít):**
Zavolá AI pro sarkastický vtip o aktuálním stavu infrastruktury → zobrazí se jako toast (6 sekund).

**Klik na instance badge** (HOME/WORK/...):
Otevře dokumentaci Sentinelu na `https://sentinel-docs.example.com`.

### 5.12 Veřejný status dashboard

URL: `/status` (bez přihlášení)

Zobrazuje základní stav infrastruktury: stav agentů, počty issues, uptime. Konfigurovatelné přes `status_page.enabled` v config.

---

## 6. Agenti

### 6.1 Typy agentů

| Typ | Kategorie | Popis |
|-----|-----------|-------|
| Standardní agent | `agent` | Vzdálený Python skript, POST na /ingest |
| Sentinel-Alert | `alert` | Speciální agent pro síťová zařízení |
| HW agent | `hw` | Hardware monitoring (teploty, senzory) |

### 6.2 Registrace agenta

**Manuální registrace** (web UI, Settings → Agenti):
1. Zadej hostname a volitelně kategorii
2. Klikni Registrovat
3. Zobraz se token — zkopíruj nebo naskenuj QR kód
4. QR kód obsahuje JSON: `{hostname, token, ingest_url}`

**Auto-registrace** (config):
```yaml
auto_register_token: "sdileny-tajny-token"
```
Agent s tímto tokenem se automaticky zaregistruje při prvním ingest.

**Regenerace tokenu** (agent detail, jen superadmin):
Starý token okamžitě přestane fungovat.

### 6.3 Ingest payload

Agenti POSTují na `POST /api/v1/agent/ingest`:

```
Authorization: Bearer <agent-token>
Content-Type: application/json
```

```json
{
  "hostname": "srv01",
  "version": "abc1234",
  "data_timestamp": "2026-06-09T12:00:00Z",
  "events": [
    {
      "plugin": "services_detector",
      "status": "active",
      "message": "nginx.service selhalo"
    },
    {
      "plugin": "services_detector",
      "status": "ok",
      "message": "nginx.service běží normálně"
    }
  ],
  "metrics": {
    "cpu_pct": 85.2,
    "ram_pct": 70.1,
    "disk_pct": 45.0,
    "net_rx": 1234567,
    "net_tx": 987654,
    "gpu_pct": 30.0,
    "ups_battery": 95.0,
    "load_avg": 2.1
  }
}
```

**Pole:**
- `hostname` — povinné, musí odpovídat registrovanému hostu
- `version` / `agent_sha` — SHA commit nebo verze agentního skriptu (zobrazí se v badge)
- `data_timestamp` — čas vzniku dat (pro výpočet data lag)
- `events[]` — pole alertů; `status: "ok"` nebo `"resolved"` automaticky resolves issue
- `metrics{}` — volitelné raw metriky → uloží se do telemetrie + zkontrolují thresholdy

**Odpověď:**
```json
{
  "status": "success",
  "processed": 2,
  "config_update": {"key": "value"}
}
```
Pole `config_update` je přítomno pokud admin odeslal konfiguraci agentovi.

### 6.4 Heartbeat a offline detekce

- Každý POST na `/ingest` aktualizuje `agents.last_seen` a `status = ONLINE`
- Heartbeat monitoring thread kontroluje každých 50 s
- Pokud agent nepošle nic do `heartbeat_timeout` sekund (default: 180 s), status = OFFLINE
- Per-agent override: `agents.heartbeat_timeout` (nastavitelné v UI)
- `ignore_offline = true` → agent nebude označen offline

### 6.5 Maintenance mode

**Jednorázový** (UI tlačítka): 30 min / 2 hod / 8 hod
- Nastaví `agents.maintenance_until = now + X minutes`
- Během maintenance: nové issues se neukládají (status != ok/resolved)

**Plánovaný per-host** (Plánovaná okna údržby):
- Přidá záznam do `snooze_rules` s `hosts = hostname`
- Aktivuje se každou minutu přes `apply_snooze_rules()`
- Snooze rules mohou být globální (hosts = NULL) nebo per-host

### 6.6 Per-agent thresholdy

Nastavitelné v agent detail (quick-buttons nebo vlastní):
- `metric_pattern`: glob pattern pro název metriky (např. `cpu_pct`, `disk_*`)
- `above`: alert pokud hodnota > threshold
- `below`: alert pokud hodnota < threshold
- `channel`: kanál výsledného issue

Kontrola probíhá při každém ingest payloadu s `metrics{}` polem.
Issue key: `THRESH|hostname|rule_id`

### 6.7 Health score

Kompozitní skóre 0–100 pro každého agenta:
```
score = 100
- lag_penalty (max 40): data lag v ms / 6000
- alert_penalty (max 30): počet 24h alertů × 3
- offline: -40
- maintenance: -20
- ignore_offline = false + offline: -10
```

---

## 7. Pluginy a detektory

### 7.1 Architektura pluginů

Každý plugin dědí z `BaseDetector` (sentinel/plugins/base.py):

```python
class BaseDetector:
    def __init__(self, name, config_params=None):
        self.name = name
        # ...

    def process_line(self, line: str, filename: str) -> list[dict]:
        """Vrátí seznam issue payloadů pro daný log řádek."""
        raise NotImplementedError
```

Plugin manager dynamicky načítá pluginy z adresáře `plugins/` a dispatchuje nové log řádky na registrované pluginy.

### 7.2 Přiřazení pluginů k log souborům

V `config.yaml`, sekce `detectors`:

```yaml
detectors:
  - plugin: security_detector
    pattern: ".*/secure$"
  - plugin: services_detector
    pattern: ".*/syslog$"
  - plugin: storage_detector
    pattern: ".*/zpool.log$"
```

Pole `pattern` je regulární výraz na celou cestu k souboru.

### 7.3 Vestavěné pluginy

#### security_detector.py
Detekuje bezpečnostní incidenty v auth logách:
- Fail2ban bany a unban
- SSH bruteforce (příliš mnoho pokusů z jedné IP)
- Sudo zneužití
- Neúspěšné přihlášení
- Neoprávněný přístup
- Možné průniky

Výstup → kanál `security`

#### services_detector.py
Detekuje selhání systemd services:
- `Failed to start X.service`
- `service entered failed state`
- `segfault`
- OOM Killer aktivace

Při detekci zkusí auto-remediaci (`systemctl restart service`).

#### storage_detector.py
Sleduje diskové problémy:
- ZFS/ZPool errory
- Disk full (df -h)
- I/O errory
- Smart warning

#### system_detector.py
Systémové anomálie:
- Kernel panic
- Out of memory
- Hardware errors

#### capacity_detector.py
Kapacitní monitorování:
- Plnící se disk (lineární regrese → TTC)
- Rostoucí RAM usage
- Load average spike

#### ha_detector.py
Home Assistant senzory:
- Čte stavy entit přes HA REST API
- Ukládá do telemetrie (kategorie `HomeAssistant`)
- Alert při překročení prahů z `ha_thresholds`
- Cyklický polling v pravidelných intervalech

#### temperature_detector.py
Teplotní monitoring:
- Čte teploty z log souborů nebo přes SSH
- Ukládá do telemetrie (kategorie `Hardware`)
- Alert při přehřátí

#### availability_detector.py
Dostupnost hostů a služeb:
- Ping check
- Port check (TCP)
- Výsledek → issue v kanálu `agent`

#### audit_detector.py
Audit logů (auditd):
- Privilegovaná operace
- Změny souborů
- Sudo eskalace

#### port_detector.py
Neoprávněné porty:
- Detekuje porty mimo povolený seznam
- Alert → kanál `security`

#### detector_universal_security.py
Univerzální bezpečnostní detektor:
- Zachytí auth pokusy, CVE náznaky, různé formáty bezpečnostních logů

### 7.4 Custom patterny (Pattern Editor)

Vlastní regex patterny bez psaní Pythonu.

- Přidat přes UI: Tools → Patterns → formulář nebo AI Navrhnout
- Pattern je Pythonový regex testovaný na každém log řádku
- Match → vytvoří se issue v daném kanálu a pluginu

**AI návrh patternů:**
Tlačítko "Navrhnout" → AI analyzuje 20 nejčastějších issues bez existujícího patternu a navrhne regex patterny.

### 7.5 Plugin hot-reload

`POST /api/plugins/reload` nebo tlačítko v Settings → znovu načte pluginy bez restartu Sentinelu.

---

## 8. AI a analýza

### 8.1 AI backendy

Sentinel podporuje tři AI backendy (priorita: Hailo → Ollama → external):

| Backend | URL | Konfigurace |
|---------|-----|-------------|
| Hailo-10H NPU | `http://localhost:8000` | `hailo_ollama.enabled: true` |
| Lokální Ollama | `http://localhost:11434` | výchozí |
| External OpenAI-compatible | libovolná | `ollama.url: http://...` |

**Přepínání modelů za běhu:**
Settings → Hailo/Ollama model → dropdown s dostupnými modely → Apply.

### 8.2 RAG (Retrieval-Augmented Generation)

**Znalostní báze:**
- Umístění: `/opt/Sentinel/admindocs/` (Markdown soubory)
- Formáty: `.md`, `.txt`, `.pdf`, `.docx`, `.csv`
- ChromaDB vektory v `CHROMADB_PATH`
- Embedding model: `nomic-embed-text` (přes Ollama nebo hailo)

**Fallback BM25:**
Pokud ChromaDB není dostupný nebo vrátí prázdné výsledky, použije se BM25-like TF×IDF textové vyhledávání.

**KB Reindex:**
Tools → KB Reindex → tlačítko nebo `POST /api/rag/reindex`.

**KB Search:**
Tools → KB → fulltext vyhledávání (plain grep bez RAG).

**Upload souborů do KB:**
Soubor se nahraje na server a přidá do embedding indexu.

### 8.3 AI analýza incidentů

Spouštěče:
1. Automaticky při vzniku nového kritického issue
2. Manuálně — tlačítko "Replay" v issue kartě
3. Batch AI analýza všech issues

Prompt obsahuje:
- Posledních N log řádků (kontext)
- Historická podobná issues (RAG)
- Stav agenta
- Dostupné opravy (allowed commands)

Výsledek může obsahovat navrhovaný příkaz → vytvoří se `action` čekající na schválení.

### 8.4 AI Souhrn (Batch analýza)

Tlačítko "AI Souhrn" v issues modal toolbar:
- Posílá posledních 30 issues z aktuálního kanálu do LLM
- LLM vytvoří přehled situace v infrastruktuře
- Výsledek se zobrazí v chatu i v issues modalu

### 8.5 AI Korelace

Tlačítko "Korelace" v issues modal:
- AI analyzuje issues a identifikuje skupiny se společnou příčinou
- Výsledek: skupiny + pravděpodobná příčina + doporučená akce

### 8.6 Auto-clustering (algoritmické)

Tlačítko "Clustery" v issues modal:
Bez AI — algoritmicky seskupí issues:
1. **Plugin cluster**: stejný plugin na 2+ různých hostech v 30min okně
2. **Host cluster**: 2+ issues ze stejného hostu v 30min okně

Volitelně pojmenuje root cause pomocí AI (jeden prompt pro všechny clustery).

### 8.7 AI Trend Report

Tools → AI Trend (záložka):
- Posílá top pluginy a statistiky za zvolené období (7/14/30 dní) do LLM
- LLM vytvoří textový trend report s pozorováními

### 8.8 AI Kapacitní plánování

Tools → Kapacita → "AI analýza":
- Agreguje telemetrii per host za zvolené období
- LLM navrhne HOST/PROBLÉM/DOPORUČENÍ/PRIORITA bloky
- Barevné karty: červená=high, oranžová=medium, zelená=low

### 8.9 Kapacitní předpověď (bez AI)

Tools → Kapacita → "Předpověď kapacity":
- Linear regression na disk/RAM metrikách za zvolené období
- TTL (Time-To-Limit): kdy dojde místo nebo RAM
- Status: critical (<24h), warning (<72h), ok

### 8.10 AI infra vtip

Klik na logo (štít) v headeru:
- `POST /api/analyze/infra_joke`
- AI vygeneruje sarkastický vtip o aktuálním stavu (počet issues, offline agenti)
- Toast se zobrazí na 6 sekund

### 8.11 AI Runbooky

Pro každý issue typ může existovat AI-generovaný runbook:
- `POST /api/runbooks/generate` → LLM vygeneruje krok-za-krokem instrukce
- Runbook se uloží do DB a zobrazí se v issue timeline
- `GET /api/runbooks` — seznam všech runbooků

### 8.12 Detekce duplikátů

Při ingest každého nového issue (pokud `auto_duplicate_detection: true`):
- Embedding cosine similarity porovnání s posledními 50 issues
- Pokud podobnost > prah → nové issue se sloučí s existujícím
- Badge "MERGE" v UI

### 8.13 Auto-severity klasifikace

Pokud `auto_severity_enabled: true`:
- LLM klasifikuje severity nového issue (critical/high/medium/low)
- Automaticky přiřadí severity badge

---

## 9. Telemetrie a metriky

### 9.1 Ukládání telemetrie

Tabulka `telemetry`: `(timestamp, category, metric, value)`

**Kategorie:**
- `sentinel` — self-metriky Sentinelu (RAM, threads, load...)
- `HomeAssistant` — HA senzory
- `Hardware` — teploty
- `hostname` — metriky agenta (cpu_pct, ram_pct, disk_pct...)
- vlastní kategorie z config

**Batch insert:**
Metriky se bufferují v paměti a zapisují každých 5 sekund (batch insert pro výkon).

**Retention:**
Starší telemetrie se automaticky průměruje (min/max/avg per hodinu) a prune raw data.
Konfigurace: `db_retention_days`, `telemetry_aggregate_after_hours`.

### 9.2 Anomaly detection (3σ)

Při každém batch insertu:
- Pro každou metriku se vypočítá průměr a odchylka za posledních 24h
- Pokud nová hodnota > průměr + 3σ → issue `telemetry_anomaly`
- Cooldown: 1 hodina per metrika

### 9.3 Telemetry alerting rules (pevné thresholdy)

V `config.yaml`:
```yaml
telemetry_alerts:
  - metric: "cpu_pct"
    above: 90
    channel: security
  - metric: "disk_*"
    above: 85
    channel: agent
```
Kontrola při každém batch insertu. Cooldown 1 hodina.

### 9.4 Sentinel self-metriky

Automaticky sbírány každou minutu (kategorie `sentinel`):
- `sentinel.ram_mb` — RAM usage procesu
- `sentinel.threads` — počet aktivních vláken
- `sentinel.queue_depth` — délka AI fronty
- `sentinel.issues` — počet aktivních issues
- `sentinel.agents_online` — počet online agentů
- `sentinel.load1` — systémový load average

### 9.5 Grafy a vizualizace telemetrie

**Sparklines v headeru:**
Mini grafy posledních 24h pro kritické metriky.

**Agent detail grafy:**
Telemetrické grafy per agent za posledních 24h (Chart.js).

**Predikce:**
`GET /api/predictions` — anomálie, TTC, varování pro všechny metriky.

**Kapacitní předpověď:**
`GET /api/predictions/capacity?days=3` — linear regression per metrika.

**Host Heatmap:**
Heatmap host × den × počet alertů za 7/14/30 dní.

**Alert Timeline Heatmap:**
Heatmap hodina × den za posledních 7 dní.

**Health Score History:**
Hourly snapshot health score per agent za 7/30 dní.

### 9.6 Porovnání dvou časových oken

Tools → Srovnání:
- Zvolit metriku, délku okna A (baseline) a B (aktuální)
- Výpočet avg/min/max + delta + %
- `POST /api/telemetry/compare`

### 9.7 Exporty telemetrie

| Endpoint | Formát | Popis |
|----------|--------|-------|
| `/api/export/telemetry.csv` | CSV | Telemetrie s filtry `?days=7&category=HomeAssistant` |
| `/api/export/grafana_dashboard.json` | JSON | Grafana dashboard pro import |
| `/api/export/prometheus_rules.yaml` | YAML | Prometheus alerting rules z SLA/escalation |
| `/metrics` | Prometheus exposition | Gauge metriky pro scraping |

**Prometheus pushgateway (148):**
Konfigurace `prometheus.pushgateway_url` → Sentinel periodicky PUTuje self-metriky.

**InfluxDB export:**
Konfigurace `influxdb.url/token/org/bucket` → telemetrie se exportuje do InfluxDB v2.

---

## 10. Notifikace a integrace

Všechny integrace lze přepínat za běhu přes UI (Connection modal → Integrace, nebo Nastavení notifikací).

### 10.1 MS Teams

```yaml
teams_channels:
  enabled: true
  security: "https://outlook.office.com/webhook/..."
  agent: "https://..."
  general: "https://..."   # fallback pro nepokryté kanály
```

### 10.2 Home Assistant

```yaml
homeassistant:
  enabled: true
  url: "http://homeassistant:8123"
  token: "long-lived-access-token"
  notify_service: "mobile_app_telefon"
  # 278: HA action při critical alertu (optional)
  action_service: "light/turn_on"    # např. light/turn_on, switch/turn_on
  action_entity:  "light.office"     # entity_id
```

Push notifikace: `notify.{notify_service}` při nových issues.
HA action: volá `/api/services/{action_service}` pro security/root alerty.

### 10.3 MQTT

```yaml
mqtt:
  enabled: true
  host: "192.168.2.202"
  port: 1883
  user: "sentinel"
  pass: "heslo"
  topic_prefix: "sentinel"
```

### 10.4 Slack

```yaml
slack:
  enabled: true
  webhook_url: "https://hooks.slack.com/..."
  channel: "#monitoring"
```

### 10.5 PagerDuty

```yaml
pagerduty:
  enabled: true
  routing_key: "integration-key"
```

### 10.6 ntfy.sh

```yaml
ntfy:
  enabled: true
  url: "https://ntfy.sh/muj-topic"
  token: ""   # Bearer token pokud je topic chráněný
```

Priority: `high` pro security/root, `default` ostatní.

### 10.7 Gotify

```yaml
gotify:
  enabled: true
  url: "http://gotify.lan"
  token: "aplikacni-token"
```

Priority 9 pro security/root, 5 ostatní.

### 10.8 SMTP Email

```yaml
smtp:
  enabled: true
  host: "smtp.gmail.com"
  port: 587        # 587 = STARTTLS, 465 = SSL (viz SMTP_SSL flag)
  user: "uzivatel@gmail.com"
  pass: "heslo-nebo-app-password"
  from: "sentinel@mujserver.cz"
  to: "admin@firma.cz,ops@firma.cz"
```

### 10.9 Matrix/Element

```yaml
matrix:
  enabled: true
  url: "https://matrix.org/_matrix/client/v3/rooms/!id:matrix.org/send/m.room.message"
  token: "syt_bearer_token"
```

### 10.10 Webhook (vlastní)

```yaml
self_monitor:
  enabled: true
  webhook_url: "https://myserver.com/sentinel-health"
  interval: 300
  secret: "hmac-secret"
```

POST na URL s JSON payloadem Sentinelu (health, statistiky).
Podpis: `X-Sentinel-Signature: hmac-sha256`.

### 10.7 Inbound webhook (příjem alertů)

**Generický webhook:**
```
POST /api/inbound/webhook?token=<INBOUND_WEBHOOK_TOKEN>
Content-Type: application/json
{"host": "srv01", "plugin": "mujdetektor", "message": "Chyba XYZ", "severity": "high"}
```

**Grafana webhook (184):**
```
POST /api/inbound/grafana?token=<token>
```
Podporuje oba formáty:
- Legacy (pre-v8): `{state, ruleName, message}`
- Unified alerting (v8+): `{alerts: [{status, labels, annotations, fingerprint}]}`

**AlertManager webhook (194):**
```
POST /api/inbound/alertmanager?token=<token>
```
Prometheus AlertManager webhook formát: `{alerts: [{status, labels, annotations, fingerprint}]}`

### 10.8 SNMP Trap Receiver

Naslouchá na UDP 162 (vyžaduje root nebo cap_net_bind_service):
```yaml
snmp_trap:
  enabled: true
  port: 162
  community: "public"
```
SNMP trapy se konvertují na issues v kanálu `agent`.

### 10.9 Syslog UDP Receiver

```yaml
syslog_receiver:
  enabled: true
  port: 514
```
Syslog zprávy (RFC3164/RFC5424) se zpracovají jako log řádky.

---

## 11. Bezpečnost a přístupová práva

### 11.1 Autentizace

**Local auth** (config.yaml sekce `web`):
```yaml
web:
  username: "admin"
  password: "silne-heslo-minimum-12-znaku"
  viewer_username: "viewer"
  viewer_password: "viewer-heslo"
```
> **VAROVÁNÍ:** Výchozí heslo `admin` způsobí CRITICAL log warning a UI banner. `sentinel_init.py` odmítne pokračovat s výchozím heslem.

**LDAP:**
```yaml
ldap:
  enabled: true
  host: "ldap.example.com"
  port: 389
  use_ssl: false
  base_dn: "dc=example,dc=com"
  user_login_attr: "uid"
  bind_dn: "cn=service,dc=example,dc=com"
  bind_password: "heslo"
  admin_users: ["admin1", "admin2"]
  superadmin_users: ["root"]
  viewer_users: ["monitor"]
```

### 11.2 Role (RBAC)

| Role | Může |
|------|------|
| **viewer** | Číst issues, dashboard, grafy, chat (jen číst) |
| **admin** | Viewer + acknowledge, tagging, SSH, maintenance, config view |
| **superadmin** | Admin + regenerovat tokeny, mazat uživatele, manage API keys, revoke sessions |

### 11.3 Brute-force ochrana

Platí pro **oba** login mechanismy — formulářový login i Basic auth:
```yaml
security:
  login_max_attempts: 5    # počet pokusů před banem
  login_ban_time: 300      # délka banu v sekundách
  whitelist: ["127.0.0.1"] # IP nikdy nebanovat (localhost)
```
Po 5 selhání z jedné IP → 429 Too Many Requests po dobu 5 minut.

### 11.4 CSRF ochrana

Každý POST/PUT/DELETE request musí obsahovat `X-CSRF-Token` header. Token je automaticky přidáván JS wrapperem `window.fetch`. Agentní API (`/api/v1/`) je exempt (Bearer token autentizace).

### 11.5 REST API klíče

Správa: Settings → API Keys (jen superadmin).

```
POST /api/apikeys
{"name": "CI Monitor", "scope": "read"}
```

Scopes: `read`, `write`, `admin`. Klíče jsou ukládány jako SHA-256 hash — raw token se zobrazí jen jednou.

Použití:
```
GET /api/v1/issues
X-API-Key: sentinel_xxxx
```

### 11.6 Rate limiting

```yaml
security:
  rate_limit_chat: 60      # max AI dotazů/min na IP
  rate_limit_upload: 10    # max uploadů/min
  rate_limit_ingest: 120   # max ingest requestů/min od agenta
```

### 11.7 Správa sessions

Settings → Sessions (admin+):
- Seznam aktivních sessions (user, IP, last seen)
- Revoke konkrétní session → okamžitá invalidace (persistentní v DB)
- Session GC každou hodinu (>24h neaktivní sessions smazány)

### 11.6 IP whitelist per-role

```yaml
security:
  ip_whitelist:
    - "192.168.1.0/24"
    - "10.0.0.0/8"
```

Admin a superadmin přístup pouze z těchto podsítí.

### 11.7 File Integrity Monitoring (FIM, 176)

```yaml
fim:
  enabled: true
  paths:
    - /etc/passwd
    - /etc/shadow
    - /etc/sudoers
    - /etc/ssh/sshd_config
```

FIM kontroluje SHA-256 hash každou minutu. Při změně → issue v kanálu `security`, plugin `file_integrity_monitor`, severity `high`.

### 11.8 Suppress rules (Alert suppression)

Tools → Suprese:
- Globální pravidla pro potlačení alertů (host glob + plugin glob)
- Volitelná expirační lhůta
- Příklad: `host: "proxmox*", plugin: "*storage*"` → suppresuje storage alerty z Proxmox hostů

### 11.9 False Positive management

- Issue karta → ikona ✗ → označit jako false positive
- False positive se uloží do `false_positive_patterns`
- Budoucí issues s obdobnou zprávou se automaticky filtrují
- Správa: Tools → False Positive

---

## 12. SSH a akce

### 12.1 SSH konfigurace

```yaml
ssh:
  key_path: "/opt/Sentinel/conf/.id_ed25519"
  user: "root"
  jump_host: ""  # "user@bastion.example.com"
```

SSH opcí vždy: `-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes`

### 12.2 Allowed Commands (allowlist)

Každý SSH příkaz musí být v allowlistu. Správa přes UI (Settings → Allowed Commands) nebo API.

```json
{
  "pattern": "systemctl restart *",
  "description": "Restart systemd service",
  "auto_execute": false,
  "risk_max": 30
}
```

- `auto_execute: true` → auto-remediace může spustit bez schválení
- `risk_max` — maximální povolené riziko (0-100)
- Export/import: JSON

### 12.3 Safety klasifikátor

Před každým SSH příkazem:
1. Zkontroluje allowlist (fnmatch pattern matching)
2. Safety score (LLM nebo heuristika) — blokuje příkazy nad `risk_max`
3. Blokuje nebezpečné příkazy: `rm -rf /`, `dd if=/dev/zero`, `fork bombs`, atd.

### 12.4 SSH Execute

**Blocking (synchronní):**
```
POST /api/ssh/execute
{"host": "srv01", "command": "systemctl restart nginx"}
```

**Streaming (SSE):**
```
POST /api/ssh/stream
{"host": "srv01", "command": "journalctl -n 100 -f"}
→ Server-Sent Events stream
```

**Batch SSH (145):**
```
POST /api/ssh/batch
{"hosts": ["srv01", "srv02", "srv03"], "command": "uptime"}
→ Paralelní exec, max 50 hostů, 10 vláken
```

### 12.5 SSH Session Recording

Každá SSH akce je logována do `ssh_execute_log`:
- command, actor, executed_at, success, output (full)

Zobrazení: agent detail → SSH History.

### 12.6 Auto-remediace

Při detekci selhání service nebo disk problému:
1. Sentinel vytvoří navrhovanou akci (příkaz)
2. Zkontroluje allowlist a `auto_execute` příznak
3. Pokud `auto_execute = true` → spustí automaticky (jeden pokus)
4. Pokud selže → AUTOFAIL badge v issue kartě
5. Manuální schválení: Pending Actions modal

### 12.7 Ansible Playbook Runner (181)

```
POST /api/ansible/run
{
  "host": "srv01",
  "playbook": "playbooks/deploy.yml",
  "extra_vars": "env=production"
}
```

Backend sestaví a spustí:
```bash
ansible-playbook playbooks/deploy.yml -i srv01, -u root --private-key /opt/Sentinel/conf/.id_ed25519 --extra-vars "env=production" --one-line
```

Cesta k playbooku musí obsahovat jen alfanumerika, `/`, `_`, `-`, `.` a končit `.yaml` nebo `.yml`.

---

## 13. Databáze — schéma

SQLite 3, WAL mode. Cesta: `/var/lib/sentinel/sentinel_state.db` (nebo `SENTINEL_DB_DIR`).

### Tabulka: problems

Hlavní tabulka issues/incidentů.

| Sloupec | Typ | Popis |
|---------|-----|-------|
| id | INTEGER PK | Unikátní ID |
| key | TEXT UNIQUE | `AGENT\|hostname\|plugin` nebo `INFRA\|...` |
| status | TEXT | active / validating / acknowledged / resolved / snoozed |
| channel_type | TEXT | infra / agent / security / root |
| host | TEXT | Zdrojový hostname |
| plugin_name | TEXT | Název detektoru |
| last_line | TEXT | Poslední log řádek / zpráva |
| first_seen | TEXT | ISO timestamp prvního výskytu |
| last_seen | TEXT | ISO timestamp posledního výskytu |
| missing_count | INTEGER | Počet po sobě jdoucích absencí (auto-resolve) |
| occurrence_count | INTEGER | Celkový počet výskytů |
| severity | TEXT | critical / high / medium / low / NULL |
| acknowledged_by | TEXT | Uživatel který potvrdil |
| snoozed_until | TEXT | ISO timestamp odložení |
| merged_into | TEXT | Klíč nadřazeného issue (merge) |
| assignee | TEXT | Přiřazený uživatel |
| label_color | TEXT | Hex barva štítku |
| expiry_hours | REAL | Automatická expirace (hodiny) |
| ai_analysis | TEXT | AI analýza (JSON) |
| details | TEXT | Dodatečné detaily (JSON) |

### Tabulka: agents

| Sloupec | Typ | Popis |
|---------|-----|-------|
| id | INTEGER PK | - |
| hostname | TEXT UNIQUE | Hostname agenta |
| token | TEXT | Bearer token (SHA-256 se nikdy neodesílá) |
| status | TEXT | ONLINE / OFFLINE |
| category | TEXT | agent / hw / alert |
| last_seen | TEXT | Poslední heartbeat |
| registered_at | TEXT | Datum registrace |
| ignore_offline | INTEGER | 0/1 |
| notes | TEXT | Volné poznámky |
| agent_version | TEXT | SHA nebo verze agentního kódu |
| agent_group | TEXT | Skupina agenta |
| maintenance_until | TEXT | ISO timestamp konce maintenance |
| last_data_lag_ms | INTEGER | Data lag v ms |
| labels | TEXT | JSON slovník {key: value} |
| heartbeat_timeout | INTEGER | Per-agent timeout v sekundách (NULL = globální) |
| ip_addresses | TEXT | JSON pole IP adres |
| web_ui_url | TEXT | URL webového UI agenta (HW typ) |

### Tabulka: telemetry

| Sloupec | Typ | Popis |
|---------|-----|-------|
| id | INTEGER PK | - |
| timestamp | TEXT | ISO timestamp |
| category | TEXT | Kategorie metriky |
| metric | TEXT | Název metriky |
| value | REAL | Číselná hodnota |

Index: `(metric, timestamp)`

### Tabulka: agent_thresholds

| Sloupec | Typ | Popis |
|---------|-----|-------|
| id | INTEGER PK | - |
| hostname | TEXT | Agent hostname |
| metric_pattern | TEXT | Glob pattern pro metriku |
| above | REAL | Alert nad touto hodnotou |
| below | REAL | Alert pod touto hodnotou |
| channel | TEXT | Výsledný kanál issue |
| created_by | TEXT | Uživatel |

### Tabulka: snooze_rules

| Sloupec | Typ | Popis |
|---------|-----|-------|
| id | INTEGER PK | - |
| name | TEXT | Název pravidla |
| channels | TEXT | `*` nebo `INFRA,AGENT` |
| start_hour | INTEGER | Začátek (hodina 0-23) |
| end_hour | INTEGER | Konec (hodina 0-23) |
| days | TEXT | `*` nebo `0,1,2,3,4` (Po-Pá) |
| hosts | TEXT | `*` nebo CSV hostname (per-host, 207) |
| enabled | INTEGER | 0/1 |

### Tabulka: suppress_rules

Alert suppression rules:

| Sloupec | Typ | Popis |
|---------|-----|-------|
| host_pattern | TEXT | Glob pro hostname |
| plugin_pattern | TEXT | Glob pro plugin |
| reason | TEXT | Důvod |
| expires_at | TEXT | ISO timestamp expirace (NULL = permanent) |

### Tabulka: actions

AI navrhované SSH akce:

| Sloupec | Typ | Popis |
|---------|-----|-------|
| id | INTEGER PK | - |
| problem_key | TEXT | Klíč zdrojového issue |
| command | TEXT | SSH příkaz |
| cluster | TEXT | Hostname cíle |
| status | TEXT | pending / approved / rejected / executed / resolved_auto |
| risk_score | INTEGER | 0-100 |
| ai_explanation | TEXT | Popis akce od AI |

### Tabulka: allowed_commands

| Sloupec | Typ | Popis |
|---------|-----|-------|
| pattern | TEXT | fnmatch glob |
| description | TEXT | Popis |
| auto_execute | INTEGER | 0/1 |
| risk_max | INTEGER | Max riziko |
| note | TEXT | Poznámka |

### Tabulka: issue_comments

| Sloupec | Typ | Popis |
|---------|-----|-------|
| problem_key | TEXT | Klíč issue |
| author | TEXT | Autor komentáře |
| text | TEXT | Text |
| created_at | TEXT | Timestamp |

### Tabulka: issue_tags

| Sloupec | Typ | Popis |
|---------|-----|-------|
| problem_key | TEXT | Klíč issue |
| tag | TEXT | Tag text |
| created_by | TEXT | Autor |

### Tabulka: ssh_execute_log

| Sloupec | Typ | Popis |
|---------|-----|-------|
| hostname | TEXT | Cílový host |
| command | TEXT | Příkaz |
| actor | TEXT | Uživatel |
| executed_at | TEXT | Timestamp |
| success | INTEGER | 0/1 |
| output | TEXT | Výstup (full) |

### Tabulka: health_snapshots

| Sloupec | Typ | Popis |
|---------|-----|-------|
| hostname | TEXT | Agent |
| score | INTEGER | Health score |
| timestamp | TEXT | Timestamp snapshotu |

### Tabulka: runbooks

| Sloupec | Typ | Popis |
|---------|-----|-------|
| issue_type | TEXT UNIQUE | Typ issue |
| content | TEXT | Markdown obsah runbooku |
| generated_at | TEXT | Timestamp |

### Tabulka: wiki_pages

| Sloupec | Typ | Popis |
|---------|-----|-------|
| slug | TEXT UNIQUE | URL identifikátor |
| title | TEXT | Nadpis |
| content | TEXT | Markdown obsah |
| author | TEXT | Autor |
| updated_at | TEXT | Datum úpravy |

### Tabulka: kv_settings

Key-value úložiště pro nastavení:

| Sloupec | Typ | Popis |
|---------|-----|-------|
| key | TEXT PK | Klíč |
| value | TEXT | JSON hodnota |

Příklady klíčů: `predictions.hidden_sensors`, `channel_colors`, `notify_channels`.

### Tabulka: config_history

Posledních 5 verzí config.yaml (MD5 hash, obsah).

### Tabulka: api_keys

| Sloupec | Typ | Popis |
|---------|-----|-------|
| name | TEXT | Název klíče |
| key_hash | TEXT | SHA-256 hash klíče |
| scope | TEXT | read / write / admin |
| created_by | TEXT | Autor |
| created_at | TEXT | Timestamp |
| last_used | TEXT | Poslední použití |

### Tabulka: user_roles

| Sloupec | Typ | Popis |
|---------|-----|-------|
| username | TEXT UNIQUE | Uživatelské jméno |
| role | TEXT | viewer / admin / superadmin |

---

## 14. REST API — kompletní referenční příručka

**Autentizace:** HTTP Basic nebo `X-API-Key: sentinel_xxxx` header.

**Base URL:** `http://sentinel-server:5050`

---

### 14.1 Issues a incidenty

#### `GET /api/v1/issues`
Vrátí všechny aktivní issues.

**Response:**
```json
{
  "issues": [
    {
      "key": "AGENT|srv01|services_detector",
      "status": "active",
      "channel_type": "agent",
      "host": "srv01",
      "plugin_name": "services_detector",
      "last_line": "nginx.service selhalo",
      "last_seen": "2026-06-09T12:00:00Z",
      "severity": "high",
      "tags": ["nginx", "web"]
    }
  ]
}
```

---

#### `GET /api/modal_issues/<channel>`
HTML pro modal okno issues (interní, používá frontend).

Parametry: `?snoozed=1&offset=50`

---

#### `POST /api/issues/<key_b64>/acknowledge`
Potvrdí issue.

---

#### `POST /api/issues/<key_b64>/severity`
Nastaví severity.
```json
{"severity": "critical"}
```

---

#### `POST /api/issues/<key_b64>/tags`
Přidá tag.
```json
{"tag": "databaze"}
```

#### `DELETE /api/issues/<key_b64>/tags`
Odstraní tag.
```json
{"tag": "databaze"}
```

---

#### `POST /api/issues/<key_b64>/comments`
Přidá komentář.
```json
{"text": "Restartuji nginx..."}
```

#### `GET /api/issues/<key_b64>/comments`
Vrátí komentáře.

---

#### `GET /api/issues/<key_b64>/timeline`
Komentáře + akce + acknowledge eventy seřazené chronologicky.

---

#### `POST /api/issues/<key_b64>/merge`
Sloučí issue do jiného.
```json
{"target_key_b64": "base64..."}
```

---

#### `POST /api/issues/<key_b64>/depends`
Přidá závislost.
```json
{"depends_on_b64": "base64..."}
```

---

#### `GET /api/issues/<key_b64>/similar`
Podobné historické incidenty (embedding cosine similarity).

---

#### `POST /api/issues/<key_b64>/reanalyze`
Znovu spustí AI analýzu.

---

#### `POST /api/issues/<key_b64>/false_positive`
Označí jako false positive.

---

#### `POST /api/issues/<key_b64>/delete`
Smaže issue.

---

#### `POST /api/issues/delete_all/<channel>`
Smaže všechny issues v kanálu. `channel` ∈ {agent, root, security, infra}

---

#### `POST /api/issues/bulk_acknowledge`
```json
{"keys_b64": ["aaa", "bbb"]}
```

---

#### `POST /api/issues/bulk_severity`
```json
{"keys_b64": ["aaa"], "severity": "high"}
```

---

#### `POST /api/issues/bulk_assign`
```json
{"keys_b64": ["aaa"], "assignee": "jan.novak"}
```

---

#### `GET /api/issues/history`
Historie vyřešených issues s filtry:
`?channel=security&host=srv01&plugin=fail2ban&from=2026-01-01&to=2026-06-09&limit=100`

---

### 14.2 AI analýza

#### `POST /api/analyze/trend_report`
AI trend report.
```json
{"days": 7}
```

#### `POST /api/analyze/correlate`
AI root cause korelace.
```json
{"channel": "agent"}
```

#### `POST /api/analyze/auto_clusters`
Algoritmické auto-clustering.
```json
{"channel": "agent", "window_min": 30, "use_ai": true}
```

#### `POST /api/analyze/infra_joke`
Sarkastický vtip o infrastruktuře.

#### `GET /api/runbooks`
Seznam runbooků.

#### `POST /api/runbooks/generate`
Generování runbooku.
```json
{"issue_type": "services_detector"}
```

---

### 14.3 Agenti

#### `GET /api/agents/list`
Všichni registrovaní agenti (bez tokenů).

#### `POST /api/agents/register`
Registrace agenta.
```json
{"hostname": "srv01", "category": "agent"}
```
Response: `{"status": "ok", "token": "hex...", "hostname": "srv01"}`

#### `POST /api/agents/delete`
```json
{"hostname": "srv01"}
```

#### `GET /api/agents/health`
Agenti s health score a statistikami.

#### `GET /api/agents/<hostname>/detail`
Detail agenta + heartbeat_timeout.

#### `GET /api/agents/<hostname>/issues`
Aktivní issues agenta.

#### `GET /api/agents/<hostname>/telemetry`
Telemetrické grafy agenta.
`?hours=24&metrics=cpu_pct,ram_pct`

#### `GET /api/agents/<hostname>/health_history`
Health score history.
`?days=30`

#### `POST /api/agents/<hostname>/maintenance`
Nastavení maintenance.
```json
{"minutes": 30}
// nebo clear:
{"clear": true}
```

#### `POST /api/agents/group/<group>/maintenance`
Hromadná maintenance skupiny.

#### `POST /api/agents/<hostname>/group`
Nastavení skupiny.
```json
{"group": "production"}
```

#### `POST /api/agents/<hostname>/notes`
Uložení poznámky.
```json
{"notes": "Tento server má starý kernel"}
```

#### `GET /api/agents/<hostname>/labels`
Štítky agenta.

#### `POST /api/agents/<hostname>/labels`
Nastavení štítků.
```json
{"labels": {"env": "prod", "rack": "R01"}}
```

#### `GET /api/agents/<hostname>/thresholds`
Per-agent thresholdy.

#### `POST /api/agents/<hostname>/thresholds`
Přidání thresholdu.
```json
{"metric_pattern": "cpu_pct", "above": 90, "channel": "agent"}
```

#### `DELETE /api/agents/thresholds/<id>`
Smazání thresholdu.

#### `GET/POST /api/agents/<hostname>/heartbeat-timeout`
GET: vrátí aktuální timeout.
POST: nastavení timeoutu.
```json
{"timeout": 300}
// nebo reset:
{"timeout": null}
```

#### `POST /api/agents/<hostname>/ping`
TCP/ICMP ping agenta z Sentinelu.

#### `POST /api/agents/<hostname>/packages`
Nainstalované balíčky přes SSH.
```json
{"filter": "nginx"}
```

#### `POST /api/agents/<hostname>/cve_scan`
CVE/security scan přes SSH.

#### `POST /api/agents/<hostname>/hw_metrics`
HW metriky přes SSH.
```json
{"type": "net"}  // net / gpu / smart / ups
```

#### `POST /api/agents/<hostname>/regenerate-token`
Regenerace tokenu (superadmin).

#### `POST /api/v1/agent/ingest`
Agent push endpoint (viz sekce 6.3).

#### `GET /api/agents/geomap`
Geografická mapa agentů (IP → geolocation).

#### `GET /api/agents/compare`
Srovnání dvou agentů.
`?a=srv01&b=srv02`

---

### 14.4 SSH a akce

#### `POST /api/ssh/execute`
Synchronní SSH exec.
```json
{"host": "srv01", "command": "uptime"}
```

#### `POST /api/ssh/stream`
SSE streaming SSH exec.
```json
{"host": "srv01", "command": "journalctl -n 50"}
```
→ Server-Sent Events

#### `POST /api/ssh/batch`
Batch SSH na více hostů.
```json
{"hosts": ["srv01", "srv02"], "command": "uptime"}
```

#### `POST /api/ansible/run`
Ansible playbook runner.
```json
{"host": "srv01", "playbook": "playbooks/update.yml", "extra_vars": ""}
```

#### `GET /api/v1/actions`
Seznam čekajících akcí.

#### `POST /api/v1/actions/<id>/review`
Schválení/zamítnutí akce.
```json
{"action": "approve"}
// nebo:
{"action": "reject"}
```

#### `POST /api/v1/actions/<id>/execute`
Manuální spuštění.

#### `GET /api/v1/allowed-commands`
Allowlist příkazů.

#### `POST /api/v1/allowed-commands`
Přidání pravidla.
```json
{"pattern": "systemctl restart *", "description": "...", "auto_execute": false, "risk_max": 30}
```

#### `DELETE /api/v1/allowed-commands/<id>`
Smazání pravidla.

#### `GET /api/v1/allowed-commands/export`
Export allowlistu (JSON).

#### `POST /api/v1/allowed-commands/import`
Import allowlistu.

---

### 14.5 Telemetrie a predikce

#### `GET /api/predictions`
Predikce trendů pro všechny metriky.
`?show_hidden=1`

#### `POST /api/predictions/toggle_hidden`
Skrytí/zobrazení metriky.
```json
{"metric": "cpu_pct"}
```

#### `GET /api/predictions/capacity`
Kapacitní předpověď (linear regression).
`?days=3`

#### `POST /api/telemetry/compare`
Porovnání dvou časových oken.
```json
{
  "metric": "cpu_pct",
  "baseline_hours": 48,
  "baseline_len": 24,
  "current_hours": 0,
  "current_len": 24
}
```

#### `GET /api/alerts/host_heatmap`
Host heatmap data.
`?days=7`

#### `GET /api/alerts/timeline`
Alert timeline heatmap.

#### `GET /api/health/history`
Health score history.
`?hostname=srv01&days=30`

---

### 14.6 Konfigurace

#### `GET /api/config/view`
Aktuální config (citlivé hodnoty maskovány).

#### `POST /api/config/update`
Aktualizace konfigurace.
```json
{"key": "instance_name", "value": "PROD"}
```

#### `GET /api/config/diff`
Diff aktuálního config s šablonou.

#### `GET /api/config/history`
Posledních 5 verzí config.

#### `GET /api/config/backup`
Stáhnout config.yaml.

#### `POST /api/config/restore`
Nahrát nový config.yaml (multipart).

#### `GET /api/config/validate`
Validace konfigurace.

---

### 14.7 Integrace

#### `GET /api/integrations/<name>/status`
Stav integrace. `name` ∈ {mqtt, homeassistant, teams, slack, pagerduty, webhook}

#### `POST /api/integrations/<name>/toggle`
Zapnout/vypnout integraci.

#### `POST /api/integrations/<name>/test`
Test integrace (odešle test zprávu).

#### `POST /api/integrations/<name>/save`
Uložení konfigurace integrace.
```json
{"host": "192.168.2.202", "port": 1883, "user": "sentinel", "pass": "..."}
```

#### `POST /api/inbound/webhook?token=<TOKEN>`
Příjem generických alertů.

#### `POST /api/inbound/grafana?token=<TOKEN>`
Příjem Grafana alertů (legacy + unified).

#### `POST /api/inbound/alertmanager?token=<TOKEN>`
Příjem Prometheus AlertManager alertů.

---

### 14.8 Export

#### `GET /api/export/telemetry.csv`
CSV export telemetrie.
`?days=7&category=HomeAssistant`

#### `GET /api/export/incidents.csv`
CSV export incidentů.

#### `GET /api/export/incidents.html`
HTML report incidentů (tisknutelný).

#### `GET /api/export/incidents.md`
Markdown report.

#### `GET /api/export/audit.csv`
Audit trail CSV.

#### `GET /api/export/db_backup`
SQL dump databáze.

#### `GET /api/export/grafana_dashboard.json`
Grafana dashboard JSON.

#### `GET /api/export/prometheus_rules.yaml`
Prometheus alerting rules.

#### `GET /metrics`
Prometheus exposition format.
`?token=<scrape_token>`

---

### 14.9 Reporting

#### `GET /api/reports/monthly_trend`
Měsíční trend.
`?months=3`

#### `GET /api/reports/sla_compliance`
SLA compliance report.
`?days=30`

#### `GET /api/reports/plugin_efficiency`
Efektivita pluginů (TP/FP).
`?days=30`

#### `POST /api/reports/capacity_plan`
AI kapacitní plánování.
```json
{"days": 7}
```

---

### 14.10 Pluginy

#### `GET /api/plugins/stats`
Statistiky pluginů.

#### `POST /api/plugins/reload`
Hot-reload pluginů.

#### `POST /api/plugins/toggle`
Zapnout/vypnout plugin.

#### `POST /api/plugins/toggle_notify`
Toggle notifikace pro plugin.

#### `GET /api/plugins/graph`
Plugin dependency graph data.

---

### 14.11 Custom patterny

#### `GET /api/patterns`
Seznam custom patternů.

#### `POST /api/patterns`
Přidání patternu.
```json
{"name": "Fail2ban", "plugin": "security_detector", "pattern": "Ban \\d+\\.\\d+\\.\\d+\\.\\d+", "channel": "security"}
```

#### `DELETE /api/patterns/<id>`
Smazání.

#### `POST /api/patterns/<id>/toggle`
Zapnout/vypnout.

#### `POST /api/patterns/test`
Test regexu.
```json
{"pattern": "Ban \\d+", "text": "Ban 192.168.1.1"}
```

#### `POST /api/patterns/suggest`
AI návrh patternů z historických issues.

---

### 14.12 Snooze rules (Maintenance Windows)

#### `GET /api/snooze/rules`
Seznam pravidel.

#### `POST /api/snooze/rules`
Přidání pravidla.
```json
{"name": "Nočni údržba", "start_hour": 2, "end_hour": 6, "channels": "*", "days": "0,1,2,3,4", "hosts": "srv01,srv02"}
```

#### `DELETE /api/snooze/rules/<id>`
Smazání.

#### `POST /api/snooze/rules/<id>/toggle`
Zapnout/vypnout.
```json
{"enabled": true}
```

---

### 14.13 Suppress rules

#### `GET /api/suppress/rules`
Seznam pravidel.

#### `POST /api/suppress/rules`
Přidání.
```json
{"host_pattern": "proxmox*", "plugin_pattern": "*storage*", "reason": "Plánovaná migrace"}
```

#### `DELETE /api/suppress/rules/<id>`
Smazání.

---

### 14.14 RAG a znalostní báze

#### `GET /api/rag/status`
Stav RAG systému (indexed, model, atd.)

#### `POST /api/rag/reindex`
Reindex.

#### `POST /api/kb/search`
Fulltext vyhledávání.
```json
{"query": "jak restartovat nginx"}
```

#### `POST /api/kb/upload`
Nahrání souboru do KB (multipart).

---

### 14.15 Wiki

#### `GET /api/wiki`
Seznam stránek.

#### `GET /api/wiki/<slug>`
Obsah stránky.

#### `POST /api/wiki/<slug>`
Vytvoření/úprava stránky.
```json
{"title": "Postup při výpadku DB", "content": "# Postup\n..."}
```

#### `DELETE /api/wiki/<slug>`
Smazání.

---

### 14.16 Systém

#### `GET /api/metrics`
Systémové metriky (dashboard data).

#### `GET /api/sys_info`
HTML systémového monitoru.

#### `POST /api/system/logrotate`
Trigger logrotate.

#### `GET /api/system/errors`
Systémové chyby z DB.

#### `GET /api/system/ssh-config`
Aktuální SSH konfigurace.

#### `POST /api/system/ssh-config`
Uložení SSH konfigurace.

#### `POST /api/system/ssh-test`
Test SSH připojení.

#### `GET /api/changelog`
Git log.

#### `GET /api/history`
Historie systémových událostí.

#### `GET /api/topology/data`
Síťová topologie data.

#### `GET /api/connection/status`
Stav spojení (server info + integrace).

---

### 14.17 Uživatelé a session

#### `GET /api/users/list`
Seznam uživatelů.

#### `GET /api/users/roles`
Role uživatelů.

#### `POST /api/users/roles`
Přiřazení role.
```json
{"username": "jan.novak", "role": "admin"}
```

#### `DELETE /api/users/roles/<username>`
Odebrání role.

#### `GET /api/sessions`
Aktivní sessions.

#### `DELETE /api/sessions/<id>`
Revoke session.

---

### 14.18 API klíče

#### `GET /api/apikeys`
Seznam klíčů.

#### `POST /api/apikeys`
Vytvoření klíče.
```json
{"name": "CI pipeline", "scope": "read"}
```

#### `DELETE /api/apikeys/<id>`
Smazání.

---

### 14.19 Veřejná stránka

#### `GET /status`
Veřejný status dashboard (bez přihlášení).

#### `GET /api/docs`
Swagger UI dokumentace.

#### `GET /api/openapi.json`
OpenAPI 3.0 spec.

---

## 15. Konfigurace — kompletní reference config.yaml

```yaml
# ── Základní nastavení ────────────────────────────────────────────────────────
instance_name: "HOME"        # Název instance (zobrazuje se v UI)
web_host: "0.0.0.0"         # Bind adresa
web_port: 5050               # Port
web_user: "admin"            # Basic auth username
web_pass: "silne-heslo"      # Basic auth password
web_viewer_user: "viewer"    # Viewer username
web_viewer_pass: "viewer"    # Viewer password
secret_key: ""               # Flask secret key (auto-generuje se)
worker_threads: 2            # Počet AI worker vláken
data_dir: "/opt/Sentinel/data"
log_dir: "/var/log/sentinel/logs"
kb_file_path: "/opt/Sentinel/knowledge_base.txt"

# ── AI backend ────────────────────────────────────────────────────────────────
ollama:
  url: "http://localhost:11434/v1/chat/completions"
  model: "qwen2.5-coder:1.5b"
  api_key: ""                # Pro external OpenAI-compatible proxy
  num_ctx: 2048              # Context window

# ── Hailo NPU ────────────────────────────────────────────────────────────────
hailo_ollama:
  enabled: false
  url: "http://localhost:8000/v1/chat/completions"
  model: "qwen2.5-coder:1.5b"

# ── Log sledování ─────────────────────────────────────────────────────────────
watch_patterns:
  - "*.log"
ignore_patterns:
  - "*.swp"
  - "sentinel.log"

# Skupiny log souborů (zobrazují se ve stromu v LOG Vieweru)
log_groups:
  "Auth logy":
    - "/var/log/auth.log"
    - "/var/log/secure"
  "System":
    - "/var/log/syslog"
    - "/var/log/messages"

# ── Detektory ────────────────────────────────────────────────────────────────
detectors:
  - plugin: security_detector
    pattern: ".*/auth\\.log$"
  - plugin: services_detector
    pattern: ".*/syslog$"
  - plugin: storage_detector
    pattern: ".*/zpool\\.log$"

# Mapování logfile → label (pro infrastructure grouping)
infrastructure_mapping:
  - name: "PRODUCTION"
    pattern: "*prod*"
    mgmt_node: "mgmt.prod.example.com"

# ── MS Teams ─────────────────────────────────────────────────────────────────
teams_channels:
  security: "https://outlook.office.com/webhook/..."
  agent: "https://..."

# ── Home Assistant ────────────────────────────────────────────────────────────
homeassistant:
  enabled: true
  url: "http://homeassistant:8123"
  token: "eyJ..."
  notify_service: "mobile_app_telefon"

# Thresholdy pro HA sensory
ha_thresholds:
  "sensor.cpu_temperature":
    above: 80
    channel: security
  "sensor.disk_usage":
    above: 90

# ── MQTT ──────────────────────────────────────────────────────────────────────
mqtt:
  enabled: true
  host: "localhost"
  port: 1883
  user: "sentinel"
  pass: "heslo"
  topic_prefix: "sentinel"

# ── Slack ─────────────────────────────────────────────────────────────────────
slack:
  enabled: false
  webhook_url: "https://hooks.slack.com/..."
  channel: "#monitoring"

# ── PagerDuty ────────────────────────────────────────────────────────────────
pagerduty:
  enabled: false
  routing_key: "integration-key"

# ── ntfy.sh ──────────────────────────────────────────────────────────────────
ntfy:
  enabled: false
  url: "https://ntfy.sh/muj-topic"
  token: ""

# ── Gotify ───────────────────────────────────────────────────────────────────
gotify:
  enabled: false
  url: "http://gotify.lan"
  token: "aplikacni-token"

# ── SMTP Email ───────────────────────────────────────────────────────────────
smtp:
  enabled: false
  host: "smtp.gmail.com"
  port: 587       # 587=STARTTLS, 465=SSL
  user: ""
  pass: ""
  from: "sentinel@domena.cz"
  to: "admin@domena.cz"

# ── Matrix/Element ───────────────────────────────────────────────────────────
matrix:
  enabled: false
  url: "https://matrix.org/_matrix/client/v3/rooms/!id:matrix.org/send/m.room.message"
  token: ""

# ── Webhook (self-monitoring) ─────────────────────────────────────────────────
self_monitor:
  enabled: false
  webhook_url: "https://myserver.com/sentinel-health"
  interval: 300              # sekund
  secret: "hmac-secret"

# ── Inbound webhook token ────────────────────────────────────────────────────
inbound_webhook_token: "tajny-token-pro-prichozi-alerty"

# ── Prometheus ───────────────────────────────────────────────────────────────
prometheus:
  enabled: false
  scrape_token: "scrape-token"
  pushgateway_url: ""        # 148: URL pushgateway, např. http://localhost:9091

# ── File Integrity Monitoring ─────────────────────────────────────────────────
fim:
  enabled: false             # 176
  paths:
    - /etc/passwd
    - /etc/shadow
    - /etc/sudoers
    - /etc/ssh/sshd_config
    - /etc/crontab

# ── LDAP autentizace ─────────────────────────────────────────────────────────
ldap:
  enabled: false
  uri: "ldaps://ldap.example.com"
  base_dn: "dc=example,dc=com"
  bind_dn: "cn=service,dc=example,dc=com"
  bind_password: "heslo"
  user_login_attr: "uid"     # nebo "sAMAccountName" pro AD
  user_object_filter: null   # null = auto (inetOrgPerson nebo person)
  groups:
    viewer: "cn=sentinel-viewer,ou=groups,dc=example,dc=com"
    admin: "cn=sentinel-admin,ou=groups,dc=example,dc=com"
    superadmin: "cn=sentinel-super,ou=groups,dc=example,dc=com"

# ── Bezpečnost ───────────────────────────────────────────────────────────────
security:
  login_max_attempts: 5      # brute-force: počet pokusů před banem
  login_ban_time: 300        # délka banu v sekundách (300 = 5 min)
  rate_limit_chat: 60        # max AI req/min per IP
  rate_limit_upload: 10      # max upload req/min
  rate_limit_ingest: 120     # max ingest req/min
  whitelist:
    - "127.0.0.1"            # lokální admin nikdy nebanován

# Per-role IP whitelist (volitelné) — prázdné = vypnuto
ip_whitelist:
  admin: ["192.168.0.0/24"]
  superadmin: ["10.0.0.1/32"]

# Trusted reverse proxies pro X-Forwarded-For
trusted_proxies:
  - "127.0.0.1"
  - "::1"

# ── SSH ───────────────────────────────────────────────────────────────────────
ssh_execution:
  key_path: "/opt/Sentinel/conf/.id_ed25519"
  user: "root"
  jump_host: ""              # "user@bastion.example.com"

# ── InfluxDB ─────────────────────────────────────────────────────────────────
influxdb:
  url: "http://localhost:8086"
  token: "influx-token"
  org: "myorg"
  bucket: "sentinel"

# ── Analytika ─────────────────────────────────────────────────────────────────
analytics:
  critical_ttc_hours: 24    # TTC < 24h → CRITICAL
  warning_ttc_hours: 72     # TTC < 72h → WARNING

# ── Reporting ────────────────────────────────────────────────────────────────
daily_report_hour: 8        # Denní report v 8:00
weekly_report:
  day: 0                    # Pondělí (0=Po, 6=Ne)
  hour: 8

# ── Database retention ───────────────────────────────────────────────────────
db_retention_days: 2        # Prune resolved issues starší N dní
telemetry_aggregate_after_hours: 24  # Aggregate raw data po N hodinách

# ── Telemetry alerts (pevné thresholdy) ──────────────────────────────────────
telemetry_alerts:
  - metric: "cpu_pct"
    above: 90
    channel: agent
  - metric: "disk_*"
    above: 85
    channel: agent

# ── SLA pravidla ─────────────────────────────────────────────────────────────
sla_rules:
  security: 4              # security issues max 4 hodiny
  agent: 24

# ── Auto-resolve ─────────────────────────────────────────────────────────────
auto_resolve_hours: 4      # Issue bez aktivity → auto-resolve po N hodinách
auto_resolve_missing_count: 3  # Agent nepošle issue N×krát → auto-resolve

# ── Auto-severity ────────────────────────────────────────────────────────────
auto_severity_enabled: false   # LLM klasifikace severity při ingest

# ── Auto-duplicate detekce ───────────────────────────────────────────────────
auto_duplicate_detection: true # Embedding similarity detekce duplikátů

# ── Auto-registrace agentů ────────────────────────────────────────────────────
auto_register_token: ""    # Sdílený token pro auto-registraci

# ── Heartbeat timeout ─────────────────────────────────────────────────────────
agent_heartbeat_timeout: 180   # Sekund do offline stavu (globální default)

# ── Barvy kanálů ─────────────────────────────────────────────────────────────
channel_colors:
  SECURITY: "#dc3545"
  AGENT: "#0078d4"
  INFRA: "#28a745"
  ROOT: "#ffc107"

# ── AI prompty (přepsání výchozích) ──────────────────────────────────────────
prompts:
  remediation: |
    Jsi expert na Linux administraci. Analyzuj problém a navrhni příkaz pro opravu.
  analyze: |
    Shrň incident stručně a technicky.

# ── Status stránka ───────────────────────────────────────────────────────────
status_page:
  enabled: true
  title: "Infrastructure Status"

# ── SNMP Trap Receiver ───────────────────────────────────────────────────────
snmp_trap:
  enabled: false
  port: 162
  community: "public"

# ── Syslog Receiver ──────────────────────────────────────────────────────────
syslog_receiver:
  enabled: false
  port: 514

# ── Eskalační pravidla ────────────────────────────────────────────────────────
escalation_rules:
  - channel: security
    hours: 1              # Po 1 hodině bez acknowledge → zvýšit severity
    action: severity_up
  - channel: agent
    hours: 4
    action: notify_teams

# ── Auto-tag pravidla ─────────────────────────────────────────────────────────
auto_tag_rules:
  - pattern: "*nginx*"
    tags: ["web", "nginx"]
  - pattern: "*fail2ban*"
    tags: ["security", "bruteforce"]
```

---

## 16. Programátorská příručka

### 16.1 Přidání vlastního pluginu

1. Vytvořte soubor `sentinel/plugins/muj_plugin.py`:

```python
from .base import BaseDetector
from .. import api

class MujPlugin(BaseDetector):
    def __init__(self, name, config_params=None):
        super().__init__(name, config_params)
        self.name = name

    def process_line(self, line: str, filename: str) -> list[dict]:
        issues = []
        if "KRITICKÁ CHYBA" in line:
            api.report_problem(
                key=f"MUJ|{filename}|kriticky",
                payload={
                    "status": "active",
                    "channel_type": "agent",
                    "host": self._extract_host(filename),
                    "plugin_name": self.name,
                    "last_line": line[:500],
                }
            )
        return issues

    def _extract_host(self, filename):
        # Extrahuj hostname z cesty k souboru
        return filename.split("/")[-1].replace(".log", "")
```

2. Přidejte do `config.yaml`:
```yaml
detectors:
  - plugin: muj_plugin
    pattern: ".*/muj-app\\.log$"
```

3. Znovu načtěte pluginy: `POST /api/plugins/reload`

### 16.2 Použití API v externích skriptech

```python
import requests

BASE = "http://localhost:5050"
AUTH = ("admin", "heslo")

# Načti aktivní issues
resp = requests.get(f"{BASE}/api/v1/issues", auth=AUTH)
issues = resp.json()["issues"]

# Reportuj vlastní issue
requests.post(f"{BASE}/api/inbound/webhook?token=TOKEN",
    json={
        "host": "mujserver",
        "plugin": "my_check",
        "message": "Databáze neodpovídá",
        "severity": "critical"
    }
)
```

### 16.3 Struktura state.py

`state.py` je façade — re-exportuje všechny funkce z `state_base.py`, `state_issues.py` a `state_agents.py`.

**Klíčové funkce:**

```python
# Issues
state.save_problem(key, payload)        # Uložení/aktualizace issue
state.mark_resolved(key)                # Vyřešení issue
state.get_active_issues()               # Všechny aktivní issues
state.get_snoozed_count()               # Počet odložených

# Telemetrie
state.save_telemetry(metric, value, category)  # Buffered insert
state.save_telemetry_snapshot(category, dict)  # Sync insert
state.get_metric_history(metric, limit=288)    # Historická data

# Agenti
state.get_all_agents()                  # Všichni agenti
state.verify_agent_token(hostname, token)
state.update_agent_lag(hostname, lag_ms)
state.check_agent_thresholds(hostname, metrics_dict)

# Nastavení
state.get_setting(key, default)
state.set_setting(key, value)

# DB
state.db_lock                           # threading.Lock()
state._get_conn()                       # Vrátí SQLite connection
state.DB_FILE                           # Cesta k DB souboru
```

### 16.4 Chat Service API (interní)

`chat_service.py` je centrální servisní třída:

```python
service.execute_ollama(prompt, num_ctx=2048, max_tokens=500)
service.log_event(event_type, message, level=INFO, user=None)
service.chat_queue_depth               # Délka AI fronty
service.conversation_history           # Posledních N zpráv
service._send_notification(key, channel, host, message)
```

### 16.5 API modul (plugin API)

Pluginy používají `api` modul:

```python
from .. import api

# Reportování problému
api.report_problem(key, payload)

# Uložení telemetrie
api.save_telemetry("cpu_pct", 85.2, category="myhost")
api.save_telemetry_snapshot("myhost", {"cpu_pct": 85.2, "ram_pct": 70.1})

# Logování
api.logger.info("Plugin: ...")
api.logger.error("Plugin error: ...")
```

---

## 17. Systemd, watchdog, provoz

### 17.1 systemd unit

```ini
[Unit]
Description=Sentinel Commander
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=sentinel
Group=sentinel
WorkingDirectory=/opt/Sentinel
ExecStart=/usr/bin/python3 -m sentinel -e
WatchdogSec=600s
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 17.2 Watchdog mechanismus

Sentinel odesílá `WATCHDOG=1` na systemd notify socket každých 60 sekund.

Pokud watchdog selže → systemd posílá SIGABRT → faulthandler vypíše backtrace všech vláken do journalu → systemd restartuje proces.

### 17.3 Logování

- Aplikační log: `/var/log/sentinel/sentinel.log`
- Ollama log: `/var/log/sentinel/sentinel-ollama.log`
- systemd journal: `journalctl -u sentinel -f`

### 17.4 DB umístění

Výchozí: `/var/lib/sentinel/sentinel_state.db`

Override:
```bash
SENTINEL_DB_DIR=/mnt/fast-ssd python3 -m sentinel
```

**Důvod** oddělení od `/var/log/`: DB zápisy by spouštěly inotify eventy → nekonečná smyčka.

### 17.5 Aktualizace

```bash
cd /opt/Sentinel
git pull
pip3 install -r requirements.txt --upgrade
systemctl restart sentinel
```

Sentinel podporuje hot-reload pluginů bez restartu (`POST /api/plugins/reload`).

---

## 18. Řešení problémů

### 18.1 Sentinel neodpovídá

```bash
journalctl -u sentinel -n 100
systemctl status sentinel
```

Typické příčiny:
- Watchdog timeout → restart serveru (zkontroluj AI latenci)
- DB lock → zkontroluj zda neběží jiný proces se stejnou DB

### 18.2 Agent offline

1. Zkontroluj heartbeat_timeout: výchozí 180s, možná příliš krátké
2. `curl -X POST http://sentinel:5050/api/v1/agent/ingest -H "Authorization: Bearer TOKEN" -d '{"hostname":"srv01","events":[]}'`
3. Zkontroluj firewall: port 5050 přístupný z agenta

### 18.3 AI neodpovídá

1. `GET /api/hailo-ollama/status` — stav NPU
2. `curl http://localhost:11434/api/tags` — dostupné Ollama modely
3. Zkontroluj `ollama.url` v config

### 18.4 LDAP nefunguje

1. `ldapsearch -H ldaps://ldap.example.com -D "cn=service,..." -w heslo -b "dc=..." "(uid=admin)"`
2. Zkontroluj `ldap.uri` — prefix `ldaps://` je povinný pro SSL
3. Pro OpenLDAP nastav `user_object_filter: null`

### 18.5 ChromaDB chyba

```
pysqlite3.dbapi2.OperationalError: table ... has 3 columns but 4 were supplied
```

Řešení: `pip3 install pysqlite3-binary` — zajistí novější SQLite pro ChromaDB.

### 18.6 FIM false alarmy

Pokud FIM hlásí změny v souborech které jsi neměnil:
- Zkontroluj cron joby nebo backup skripty modifikující /etc
- Přidej soubor do výjimek (odstraň z `fim.paths`)

### 18.7 Diagnostika výkonu

```python
# DB query časy
GET /api/metrics  → data.system.db_size_kb
GET /api/system/errors  → systémové chyby

# Telemetrie Sentinelu (pokud zapnuta)
category = "sentinel"
metriky: ram_mb, threads, queue_depth
```

---

## Příloha A: Klávesové zkratky

| Zkratka | Akce |
|---------|------|
| `?` | Zobrazit seznam zkratek |
| `Alt+F` | Fokus na filter v issues modal |
| `Esc` | Zavřít fullscreen issue detail |
| `F11` | Fullscreen live tail |
| `Enter` | Odeslat chat zprávu |

---

## Příloha B: Typy issue klíčů

| Prefix | Příklad | Zdroj |
|--------|---------|-------|
| `AGENT\|` | `AGENT\|srv01\|nginx_detector` | Agent ingest |
| `INFRA\|` | `INFRA\|karolina\|security` | Log soubory |
| `THRESH\|` | `THRESH\|srv01\|3` | Per-agent threshold |
| `TALERT\|` | `TALERT\|agent\|cpu_pct` | Telemetry alert |
| `INBOUND\|` | `INBOUND\|grafana\|DiskFull` | Inbound webhook |
| `GRAFANA\|` | `GRAFANA\|instance\|alert\|fp8` | Grafana webhook |
| `AM\|` | `AM\|srv01\|NodeDown\|ab12` | AlertManager |
| `FIM\|` | `FIM\|/etc/passwd` | File integrity |
| `snmp_trap:` | `snmp_trap:192.168.1.1:oid` | SNMP trap |

---

## Příloha C: Kanály (channel_type)

| Kanál | Popis | Barva |
|-------|-------|-------|
| `infra` | Log soubory, infrastruktura | modrá |
| `agent` | Vzdálení agenti | zelená |
| `security` | Bezpečnostní incidenty | červená |
| `root` | Root shell sessions | žlutá |

---

*Dokument vygenerován: 2026-06-09*  
*Verze Sentinelu: v2026.06.022*  
*Počet API endpointů: ~120*  
*Počet DB tabulek: 30*

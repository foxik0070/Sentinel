# Přispívání do Sentinel Commander

## Rychlý start

```bash
git clone https://github.com/foxik0070/Sentinel
cd Sentinel
pip install -r requirements.txt
make build      # minifikuje JS/CSS
make test       # JS check + ruff + pytest
```

## Architektura

```
sentinel/
├── __main__.py          # Entry point, systemd watchdog, argumenty
├── config.py            # Načítání config.yaml, defaults, ENV secrets
├── auth.py              # Flask auth: session, CSRF, IP, LDAP
├── chat_service.py      # Flask app init, blueprinty, SocketIO, AI routing
├── notifier.py          # Odchozí notifikace (Teams/Slack/ntfy/SMTP/...)
├── scheduler.py         # Background maintenance loop (cleanup, reports)
├── ssh_utils.py         # SSH hardening: build_ssh_cmd(), known_hosts
├── state.py             # Re-export z state_base/issues/agents
├── state_base.py        # DB init, init_db(), schéma, lock
├── state_issues.py      # Issues CRUD, sessions, API klíče, cache
├── state_agents.py      # Agents CRUD, telemetrie, health score
├── actions.py           # SSH exekuce, auto-remediace
├── safety.py            # AI command guardrails (standalone, testovatelné)
├── rag.py               # ChromaDB, embedding, knowledge base
├── watcher.py           # inotify log sledování, FIM
├── plugin_manager.py    # Plugin hot-reload
├── analytics.py         # Reporting, trendy
├── plugins/             # Detektory (ha_detector, capacity_detector, ...)
├── routes/              # Flask blueprinty
│   ├── main.py          # /, /login, /logout, SocketIO events
│   ├── issues.py        # Issues CRUD, HTML generování
│   ├── agents.py        # Agent CRUD, ingest (/api/v1/agent/ingest)
│   ├── system.py        # Config, SSH key, /status, /healthz
│   ├── actions.py       # SSH streaming SSE
│   ├── chat.py          # Chat, AI, file upload
│   ├── export.py        # CSV/HTML exporty
│   └── integrations.py  # Webhook toggle/save/test
├── static/              # JS, CSS (*.min.js buildí se, nejsou v gitu)
└── templates/           # Jinja2 šablony
```

### Tok dat

```
Log soubory (inotify)
  └─► plugins/*_detector.py
        └─► state.save_problem()  ──► SQLite (WAL)
                                        │
Agenti (POST /api/v1/agent/ingest)  ────┘
                                        │
                              ┌─────────▼──────────┐
                              │  scheduler.py       │
                              │  (každých 30s loop) │
                              └─────────┬──────────┘
                                        │ notifier.py
                                        ▼
UI (index.html + 4× script-*.js) ◄── REST / SocketIO
```

## Vývojový workflow

### Před commitem
```bash
make test   # JS syntax + ESLint no-redeclare + ruff + pytest (164 testů)
make build  # terser + uglifycss (min.js nejsou v gitu — buildí se při deploy)
```

### Přidání nového notifikačního kanálu
1. Přidej `_send_xxx()` do `sentinel/notifier.py`
2. Zavolej ji z `send_notification()` (dodržuj vzor)
3. Přidej config defaulty do `sentinel/config.py`
4. Přidej test endpoint do `routes/integrations.py` (allowed set)

### Přidání nového detektoru
1. Vytvoř `sentinel/plugins/my_detector.py` s `class MyDetector(BaseDetector)`
2. Zaregistruj v `config.yaml` pod `detectors:`
3. Hotovo — plugin_manager ho načte automaticky

### Bezpečnostní pravidla
- Žádné hardcoded credentials (použij `{SECRET:ENV_VAR}` v config.yaml)
- SSH příkazy výhradně přes `ssh_utils.build_ssh_cmd()` — nikdy ručně
- HTML generované v Pythonu musí používat `html.escape()` na každý uživatelský vstup
- Nové API endpointy musí mít `@requires_auth` + CSRF je řešen globálně pro POST

## Testování

```bash
python -m pytest tests/ -v              # všechny testy
python -m pytest tests/test_routes.py   # jen API endpointy
python -m pytest tests/test_safety.py   # AI guardrails
```

Testy používají temp SQLite DB — žádný vliv na produkci.

## Konfigurace

Viz `config.yaml.example` — komentovaný, všechny možnosti.
ENV secrets: `my_password: "{SECRET:MY_ENV_VAR}"` v config.yaml.

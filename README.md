# Sentinel Commander

![Sentinel Commander](sentinel_master.png)

![Version](https://img.shields.io/badge/version-v2026.06.031-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-cyan.svg)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![Tests](https://img.shields.io/badge/tests-192%20passing-green)

**Hybrid AI Log Monitor & Analyzer for Linux Infrastructure**

Sentinel Commander is an advanced AI-powered monitoring system for Linux and enterprise infrastructure. It combines a **Pull** approach (inotify log tailing + SSH orchestration) with a **Push** approach (remote Python agents POST alerts) into a single unified dashboard.

---

## Features

| Category | What it does |
|---|---|
| **Log monitoring** | inotify tailing, plugin system (hot-reload), pattern matching |
| **AI analysis** | Ollama LLM integration, Hailo NPU (hailo-ollama), ChromaDB RAG |
| **AI Autofix** | SSH-based remediation with safety classifier, modal approval, AI confidence score |
| **AI insights** | RAG learning from resolved issues, daily digest, eval suite, per-user chat memory, token tracking |
| **Push agents** | REST ingest: sentinel-agent nodes (`/api/v1/agent/ingest`), Windows agents (`/api/ingest/windows`) |
| **Alerts** | 13 channels — Teams, Slack, ntfy, SMTP, Telegram, Matrix, HA, Gotify, PagerDuty, MQTT, Syslog, Webhook, SMS |
| **Security** | LDAP/AD auth, 2FA TOTP, bcrypt passwords, CSRF, API keys, audit trail, **least-privilege SSH remediation** (dedicated `sentinel` user + sudo whitelist) |
| **Observability** | Prometheus `/metrics`, Swagger UI `/api/docs`, health `/healthz`, SLO error budgets, DNS/webhook delivery monitoring |
| **Dashboard** | Real-time Socket.IO web UI, topology map, analytics, runbooks, drag-drop widgets |
| **CLI** | `sentinel-cli` — stdlib-only client (status, issues, ack/resolve, agents, digest, slo) via REST API |

---

## Quick Start

### Requirements

- Python 3.13+
- [Ollama](https://ollama.ai) (local LLM) or Hailo NPU
- SQLite (built-in)

### Install

```bash
git clone https://github.com/foxik0070/Sentinel /opt/Sentinel
cd /opt/Sentinel
pip install -r requirements.txt
cp config.yaml.example /etc/sentinel/config.yaml
# Edit config.yaml — set password, secret_key, log paths
python sentinel_init.py   # initialize DB + systemd service
```

Or use the interactive installer:

```bash
sudo bash install.sh
```

### Run

```bash
# Via systemd (recommended)
systemctl enable --now sentinel

# Or directly
python -m sentinel --config /etc/sentinel/config.yaml
```

Web UI: `http://localhost:5050`

---

## Configuration

All configuration is in `config.yaml`. See `config.yaml.example` for all options with comments.

Critical values to set:

```yaml
web:
  password: CHANGE_ME          # bcrypt-hashed or plain (auto-hashed on first start)
  secret_key: CHANGE_ME        # generate: python3 -c "import secrets; print(secrets.token_hex(32))"
```

Sensitive values can be loaded from environment variables:

```yaml
web:
  password: "{SECRET:WEB_PASS}"
```

---

## Architecture

```
Log files (inotify) ──► plugins/*_detector.py ──► SQLite WAL
Agents   (POST /api/v1/agent/ingest)  ──────────────────────┤
Windows  (POST /api/ingest/windows)   ──────────────────────┘
                                                         │
                                              scheduler.py (30s loop)
                                                         │ notifier.py
                                                         ▼
Web UI (Socket.IO) ◄──── REST API ◄──── Flask blueprints
```

### Directory structure

```
sentinel/
├── __main__.py          # Entry point, systemd watchdog
├── config.py            # Config loading, ENV secrets
├── auth.py              # Session, CSRF, LDAP, 2FA
├── chat_service.py      # Flask app init, blueprints, SocketIO
├── notifier.py          # Outbound notifications (13 channels)
├── scheduler.py         # Background maintenance loop
├── safety.py            # AI command guardrails
├── rag.py               # ChromaDB, embeddings, knowledge base
├── watcher.py           # inotify log tailing, FIM
├── plugin_manager.py    # Plugin hot-reload
├── analytics.py         # Reporting, trends
├── plugins/             # Detector plugins
├── routes/              # Flask blueprints (issues, agents, chat, ...)
├── static/              # JS, CSS
└── templates/           # Jinja2 templates
```

---

## Testing

```bash
make test   # ruff + pytest (192 tests)
make build  # minify JS/CSS
```

---

## Documentation

Full documentation (EN + CS): **https://sentinel-docs.foxik-iot.cz**

---

## Related Modules

| Module | Description |
|---|---|
| [sentinel-agent](https://github.com/foxik0070/sentinel-agent) | Push agent for monitored Linux nodes |
| [sentinel-agent-windows](https://github.com/foxik0070/sentinel_agent_windows) | PowerShell agent for Windows monitoring (Event Log + WMI) |
| [sentinel-plugins-hpc](https://github.com/foxik0070/sentinel-plugins-hpc) | HPC cluster detector plugins (HPC / universal) |
| [sentinel-alert](https://github.com/foxik0070/sentinel-alert) | Network security dashboard |
| [sentinel-app](https://github.com/foxik0070/sentinel-app) | Android mobile client |
| [sentinel-console](https://github.com/foxik0070/sentinel-console) | TUI terminal client |
| [sentinel-overhealth](https://github.com/foxik0070/sentinel-overhealth) | Pull orchestrator |
| [sentinel-hw](https://github.com/foxik0070/sentinel-hw) | RPi hardware robot |
| [sentinel-docs](https://github.com/foxik0070/sentinel-docs) | Documentation |

---

## License

MIT — see [LICENSE](LICENSE). Copyright © 2026 foxik0070.

# Sentinel Commander

![Sentinel Commander](sentinel_master.png)

![Version](https://img.shields.io/badge/version-v2026.08.001-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-cyan.svg)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![Tests](https://img.shields.io/badge/tests-1050%20passing-green)

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
| **AI diagnostics** | Fixed read-only command catalog — the model picks IDs, never writes shell; executes and interprets real output |
| **AI verification** | Every fix attempt is re-checked after ~15 min (deterministic, time-based); failures feed back so the same command is flagged next time |
| **AI safety** | Prompt-injection defence for untrusted log content, hourly action cap, loop detection, hallucination check, full decision audit trail |
| **AI correlation** | Causal chains, change correlation, cascade detection, cross-host patterns, incident timelines, ranked hypotheses |
| **Sub-threshold detection** | Silent degradation (regression + r²), missing signals, per-host baselines, distributed brute-force, false-alarm mining |
| **Push agents** | REST ingest: sentinel-agent nodes (`/api/v1/agent/ingest`), Windows agents (`/api/ingest/windows`) |
| **Alerts** | 13 channels — Teams, Slack, ntfy, SMTP, Telegram, Matrix, HA, Gotify, PagerDuty, MQTT, Syslog, Webhook, SMS |
| **Security** | LDAP/AD auth, 2FA TOTP, bcrypt passwords, CSRF, API keys, audit trail, **least-privilege SSH remediation** (dedicated `sentinel` user + sudo whitelist) |
| **Observability** | Prometheus `/metrics`, Swagger UI `/api/docs`, health `/api/status_check`, SLO error budgets, DNS/webhook delivery monitoring |
| **Dashboard** | Real-time Socket.IO web UI, topology map, analytics, runbooks, drag-drop widgets |
| **CLI** | `sentinel-cli` — stdlib-only client (status, issues, ack/resolve, agents, digest, slo) via REST API |

---

## Quick Start

### Requirements

> Monitored hosts need a small amount of preparation for the AI diagnostics —
> see [docs/host-setup.md](docs/host-setup.md).

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
│
│   # AI layer (2026.07)
├── ai_guard.py          # Prompt-injection defence, action cap, loop detection
├── ai_verify.py         # Hallucination check against known infrastructure
├── ai_profiles.py       # Context-window profiles per task
├── ai_runtime.py        # Response cache, consistency, token budget, routing
├── diagnostics.py       # Fixed read-only catalog — AI picks IDs, not shell
├── fix_verify.py        # Did the fix actually work? (deterministic)
├── remediation.py       # Graduated ladder: observe → reload → restart → reboot
├── remediation_plan.py  # Rollback, contextual risk, dry-run, work queue
├── policy.py            # Block explanation, allowlist/auto-execute proposals
├── escalation.py        # Escalation with context (what was already tried)
├── correlate.py         # Change correlation, causal chains
├── incident_analysis.py # Common denominator, timeline, cascades, hypotheses
├── trend_detect.py      # Silent degradation, missing signals
├── baseline.py          # Per-host normal, seasonality, auth-log audit
├── alert_quality.py     # False-alarm detection from history
├── playbooks.py         # Procedures learned from manual fixes
├── foresight.py         # Capacity forecast, weekly outlook
├── unmatched.py         # Sampling of log lines nobody catches
├── rag_utils.py         # Compression, hybrid search, citations, chunking
├── knowledge.py         # Runbooks, prevention, training pairs, KB transfer
├── infra_audit.py       # Config drift, zombies, certs, post-reboot, docs check
├── dependencies.py      # Inferred host dependencies, blast radius, shutdown sim
│
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

| Document | What it covers |
|---|---|
| [docs/host-setup.md](docs/host-setup.md) | **Preparing a monitored host so the AI features work** — `sentinel` user, `systemd-journal` group, sudoers scope, required packages |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Operational pitfalls, including the AI layer |
| [docs/api-changelog.md](docs/api-changelog.md) | New endpoints per release |
| [docs/SENTINEL_COMPLETE_DOCUMENTATION.md](docs/SENTINEL_COMPLETE_DOCUMENTATION.md) | Complete reference (CS), section 8.14 explains how the AI reasons |

> **Without the host setup above, Sentinel still reports problems but cannot
> investigate them** — diagnostics return nothing and the AI answers from a
> single log line. Start there.

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

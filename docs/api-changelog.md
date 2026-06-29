# Sentinel API Changelog

Tento dokument zaznamenává breaking changes a nové endpointy mezi verzemi.

## v2026.06.022 (2026-06-11)

### Nové endpointy
- `GET /api/search?q=<text>` — globální fulltext vyhledávání
- `GET /api/analytics/forecast` — predikce počtu issues (lineární regrese)
- `GET /api/issues/<key_b64>/postmortem` — AI postmortem markdown
- `GET /api/issues/<key_b64>/markdown` — issue jako Markdown
- `POST /api/v1/ingest/bulk` — hromadný ingest alertů
- `GET /api/agents/<hostname>/health_score` — composite health score
- `POST /api/admin/validate_url` — SSRF URL validace
- `GET /api/admin/security_check` — security headers grade
- `POST /api/admin/log_level` — runtime změna log levelu
- `GET /api/admin/audit_trail` — unified audit trail
- `POST /api/admin/backup/download` — stáhnout DB+config zálohu
- `POST /api/admin/aggregate_telemetry` — manuální agregace telemetrie
- `GET /api/admin/db_stats` — DB statistiky
- `POST /api/admin/prune` — manuální prune DB
- `GET /api/timezone/info` — info o DISPLAY_TZ
- `POST /api/timezone/convert` — konverze timestampů
- `GET /api/config/history/diff?from=X&to=Y` — diff mezi snapshoty configu
- `GET/POST /api/2fa/setup|enable|disable|status` — 2FA management
- `GET /api/agents/<hostname>/ssh_keys` — SSH known_hosts
- `POST /api/agents/<hostname>/ssh_keys/rescan` — rescan SSH klíče
- `POST /api/agents/rotate_all_tokens` — hromadná rotace agent tokenů

### Změny
- `GET /api/config/view` — hesla/tokeny vráceny jako `***` (breaking: klienti nesmí spoléhat na plaintext)
- `POST /api/apikeys` — nové scopy `read:issues`, `write:actions`, `admin:users` (staré `read/write/admin` stále fungují)
- Notifikace: titulky mají prefix `[INSTANCE_NAME]`

## v2026.06.013–021 (2026-06-10–11)

### Nové endpointy
- `/api/analytics/resolution_time` — průměrná doba řešení per plugin
- `/api/analytics/flapping` — top flapping issues
- `/api/analytics/alert_fatigue` — alert fatigue stats
- `/api/analytics/changes_since_login` — změny od posledního přihlášení
- `/api/admin/aggregate_telemetry` — telemetry aggregation
- `/api/integrations/<name>/status|toggle|save|test` — správa integrací (ntfy, gotify, smtp, matrix, discord, telegram, opsgenie)
- `/api/inbound/zabbix` — Zabbix webhook
- `/api/agents/<hostname>/scheduled_actions` — pending akce
- `/api/agents/<hostname>/ssh_keys` — SSH known_hosts management

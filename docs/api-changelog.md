# Sentinel API Changelog

Tento dokument zaznamenává breaking changes a nové endpointy mezi verzemi.

## v2026.06.031 (2026-07-25)

### Nové endpointy
- `POST /api/issues/<key_b64>/recheck` — deterministické ověření platnosti issue (body `{force, ai}`)
- `POST /api/issues/export_csv` — CSV export vybraných issues
- `GET /api/analyze/daily_digest` — poslední AI denní digest
- `POST /api/analyze/daily_digest` — vygenerovat digest hned (admin)
- `POST /api/ai/eval/run` — spustit AI eval suite na pozadí (admin)
- `GET /api/ai/eval/results` — historie eval běhů + skóre
- `GET /api/ai/token_stats` — denní statistika AI tokenů (30 dní)
- `GET /api/analytics/slo?days=N` — SLO uptime + error budget per host
- `GET /api/webhooks/deliveries?limit=N` — log outbound webhook doručení (admin)
- `POST /api/dns/check` — manuální DNS kontrola (admin)
- `GET /api/predictions/capacity?days=N` — kapacitní forecast (lineární regrese, TTC)
- `POST /api/telemetry/compare` — porovnání metriky baseline vs aktuální okno
- `GET /api/agents/<hostname>/scheduled_actions` — pending akce agenta
- `POST /api/agents/<hostname>/hw_metrics` — HW metriky přes SSH (net/gpu/smart/ups)
- `POST /api/agents/<hostname>/cve_scan` — SSH scan bezpečnostních aktualizací
- `DELETE /api/agents/<hostname>/ssh_keys` — smazat known_hosts záznam
- `GET /api/config/history/diff?from=X&to=Y` — unified diff mezi config snapshoty

### Změny konfigurace
- `ssh_execution.user` — při hodnotě jiné než `root` se remediační příkazy automaticky prefixují `sudo -n` (least-privilege; whitelist řeší `/etc/sudoers.d/sentinel` na hostech). Diagnostika (df, systemctl status) běží bez sudo.
- `ssh_execution.auth_sock` — cesta k ssh-agent socketu (šifrovaný SSH klíč).
- Nové klíče: `dns_checks`, `slo_targets`, `lifecycle.*` (stale TTL / recheck prahy), `ai_digest_hour`, `ai_timeout_seconds`, `rag_learn_resolved`, `process_rotated_logs`.
- `snmp_poll` — aktivní SNMP polling OID → telemetrie (`enabled`, `interval`, `targets[].{host,name,community,version,category,oids[]}`; `delta: true` pro countery, v3 přes `secname`/`auth_*`/`priv_*`). Vyžaduje net-snmp (`apt install snmp`).

### Změny chování
- `issue_history` má nové sloupce `resolve_reason`, `resolved_by` (migrace při startu).
- Plugin může deklarovat `REQUIREMENTS = [...]`; chybějící závislost → plugin se nenačte s hláškou.

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

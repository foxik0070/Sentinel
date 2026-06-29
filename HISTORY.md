# Historie změn

## [2026.06.022] - 2026-06-11

**Souhrn:** Masivní milestone — zbývající ~50 TODO položek, nové testy (security + integration), aktualizace dokumentace.

### Nové funkce — Bezpečnost
- **350** — Secrets masking: `/api/config/view` maskuje password/token/secret/api_key jako `***`
- **353** — Audit 403/401 přístupů do `sentinel_errors` (detekce skenování)
- **354** — SSRF ochrana: `/api/admin/validate_url` odmítne privátní IP rozsahy
- **356** — Rate limit `/api/analyze/*`: max 10 req/min per IP
- **359** — Security headers test: `/api/admin/security_check` vrací grade A/B/C/D

### Nové funkce — Výkon & Stabilita
- **366** — `prune_issue_history(days=90)` + volání ze scheduleru; retenční politika pro issue historii
- **367** — VACUUM po >10k smazaných záznamech v `prune_telemetry` + `prune_issue_history`
- **369** — HTTP cache headers pro statiku: ETag + max-age + 304 conditional GET
- **371** — Telemetry write batching pro `save_telemetry_snapshot()` přes buffer
- **372** — WS message dedup: duplikátní zprávy stejného typu v 1s okně přeskočeny
- **373** — `/api/v1/ingest/bulk`: pole alertů najednou (méně HTTP overhead)
- **374** — Startup time profiling: trvání init fází logováno
- **375** — Memory watchdog: background thread, RSS >1.5GB → warning + telemetrie

### Nové funkce — Analytics & Monitoring
- **314** — Log parser efektivita report v Tools → tracking `sentinel.lines_parsed_per_min`
- **339** — Timezone display config: `DISPLAY_TZ`, `/api/timezone/info`, `/api/timezone/convert`
- **398** — Composite health score per host: `/api/agents/<hostname>/health_score` (0-100, A-D grade)
- **399** — Issue forecast: `/api/analytics/forecast` s lineární regresí (7 dní výhled)
- **405** — Incident postmortem: `/api/issues/<key>/postmortem` AI-generovaný Markdown
- **407** — Heartbeat URL monitoring: `HEARTBEAT_URLS` config, ping v scheduleru
- **409** — SSL certifikát expiry check (<14 dní → security issue)

### Nové funkce — Integrace
- **351** — Agent token bulk rotation: `/api/agents/rotate_all_tokens`
- **373** — `/api/v1/ingest/bulk` endpoint
- **415** — Gitea issue sync: `GITEA_URL/TOKEN/REPO`, critical issue → Gitea repo
- **425** — Webhooks na issue lifecycle (CREATED/ACKNOWLEDGED/RESOLVED)

### Nové funkce — UI/UX
- **377** — Issue copy as Markdown: `/api/issues/<key>/markdown` + JS tlačítko
- **387** — Chat suggested queries: kontextové chips pod input area
- **393** — Toast queue: max 3 viditelné, stack overflow → zahazuje nejstarší

### Testy
- **tests/test_security.py** — 10 security testů: brute force, API scopes, hostname injection, secrets masking
- **tests/test_integration.py** — 7 integration testů: celý issue lifecycle v reálné DB
- **tests/bench_dashboard.py** — performance benchmark dashboardu
- **Makefile** — přidán `make ci` target (lint + test)
- Celkem: **118 testů OK**

---

## [2026.06.021] - 2026-06-11

**Souhrn:** Dávka 10 — Runbooks UI, Keyboard+ARIA, Grafana annotations, SSH known_hosts UI, S3 backup, Config schema validace, Graceful shutdown, SIGHUP hot-reload, Instance name v alertech, Log level endpoint.

### Nové funkce
- **305** — Runbooks tab v Tools s CRUD seznamem + otevření v runbook modalu
- **308** — ARIA `role="dialog"`, `aria-modal`, `aria-labelledby` na všechny `.modal-overlay` při init; Escape handler pro zavírání existoval
- **326** — Grafana annotations: `_send_grafana_annotation()` při critical/security alertu, config `grafana_annotations.url/api_key`
- **328** — SSH known_hosts UI v agent detailu: zobrazení klíčů, Rescan, Delete; API endpointy `/api/agents/<h>/ssh_keys`
- **330** — S3/MinIO backup: `/api/admin/backup/download` (tar.gz) + `/api/admin/backup/s3` (upload na S3)
- **331** — Config schema validace (jsonschema): kritická pole web.port, worker_threads, db_retention_days atd.
- **335** — Graceful SIGTERM: flush telemetry buffer + MQTT `sentinel/status: offline` event
- **336** — SIGHUP hot-reload rozšířen: reloaduje i watcher patterns + pluginy (DETECTORS, LOG_GROUPS)
- **337** — Instance name jako prefix do všech notifikačních titulků (`[Instance] CHANNEL alert`)
- **338** — `/api/admin/log_level` GET/POST — změna log levelu za běhu bez restartu

---

## [2026.06.020] - 2026-06-11

**Souhrn:** Moderní interaktivní grafy s min/max/avg — dashboard trend chart, timeline chart, agent detail telemetrie.

### Grafy — přepracování
- **Dashboard trend chart** — průměrná přerušovaná linie, tooltip zobrazuje celkem+MAX/MIN marker, stacked bar se správnými barvami kanálů
- **Dashboard donut** — cutout 68%, střed zobrazuje celkový počet issues, tooltip s procenty, hover efekt
- **Alert timeline chart** (Tools → Alert Timeline) — totéž jako dashboard: avg linie, MIN/MAX v tooltipu
- **Agent detail telemetrie sparklines** — min/max/avg badge nad každým grafem, avg přerušovaná linie v grafu, interaktivní tooltip s hodnotou

---

## [2026.06.019] - 2026-06-11

**Souhrn:** Dávka 10 — Discord/Telegram/Opsgenie, Zabbix inbound, analytics tab, health trend chart, agent drift alert, config snapshot diff, bugfix joke_log.

### Nové funkce
- **301+303** — Analytics tab v Tools: SLA resolution time tabulka + alert fatigue Chart.js bar chart
- **315** — Agent offline duration tracking: délka offline uložena do telemetrie při reconnectu
- **318** — Health snapshot trend: Chart.js line chart (score+issues 7 dní) na dashboardu
- **320** — Agent version drift alert: issue při registraci starší 30 dní
- **321** — Discord webhook (`_send_discord`, Embeds format s barvou dle severity)
- **322** — Telegram bot notifikace (`_send_telegram`, sendMessage API)
- **323** — Opsgenie integrace (`_send_opsgenie`, Events API v2)
- **325** — Zabbix inbound webhook `/api/inbound/zabbix` (flat JSON Zabbix Media Type format)
- **333** — Config snapshot diff: endpoint `/api/config/history/diff?from=X&to=Y` + rozšířený config_diff tab se selektory snapshotů

### Opraveno
- **Joke log bug**: `ChatService` nebyl importován v `api_infra_joke` — `except Exception: pass` tiše spolkl `NameError`, vtipy z dblclick se neukládaly do `joke_log`. Opraveno přidáním `from ..chat_service import ChatService as _CS`.

---

## [2026.06.018] - 2026-06-11

**Souhrn:** Dávka 10 — API key scopes, SocketIO backpressure, flapping widget, audit trail, self-health alert, weekly digest, scoping pro API klíče.

### Nové funkce
- **287** — API key fine-grained scopes: `read:issues`, `write:actions`, `admin:users` + zpětná kompatibilita; UI select aktualizován
- **299** — SocketIO backpressure: `frontend_queue = Queue(maxsize=500)`, `_enqueue_frontend()` s drop-oldest; `put_nowait()` v actions.py
- **302** — Flapping issues widget na dashboardu: async `_loadFlappingWidget()` s `/api/analytics/flapping`
- **311** — Audit trail viewer v Settings: tlačítko + inline panel `/api/admin/audit_trail` (config+SSH+actions)
- **312** — AI queue backlog alert: pokud `queue_depth > 50` → SENTINEL_SELF_HEALTH issue
- **316** — Weekly digest rozšířen: flapping issues + průměrná doba řešení (`get_flapping_issues`, `get_resolution_time_stats`)

### Potvrzeno hotové
- **307** — Dark/light theme toggle ikona (moon) v headeru existuje od dřívějška
- **310** — Triage view toggle button v issues modalu existuje od dřívějška
- **317** — Prometheus pushgateway implementován v _save_sentinel_self_metrics (148)
- **319** — False positive hit_count increment v api.py + zobrazení v FP tabulce

---

## [2026.06.017] - 2026-06-11

**Souhrn:** Dávka 10 — bezpečnost, výkon, DB management UI, session timeout.

### Bezpečnost
- **285** — Auto-register rate limit: max 10 pokusů/min per IP na auto-registraci agenta
- **286** — Session role refresh z DB každých 5 min (detekuje změny role za běhu)
- **348** — Session absolute timeout: session vyprší po 12h (konfig. `security.session_max_hours`)

### Výkon
- **289** — SMTP port 465 SSL: `smtplib.SMTP_SSL()` pro port 465, STARTTLS zůstává pro 587
- **290** — Env var cleanup: `{SECRET:ENV_VAR}` proměnné smazány z `os.environ` po substituci
- **297** — Batch SSH per-host timeout: `timeout=15s` v `/api/ssh/batch` (dříve 30s blokovalo ostatní hostitele)
- **298** — WAL checkpoint tuning: `wal_autocheckpoint=200` (bylo 500), `PRAGMA synchronous=NORMAL`, explicitní checkpoint po prune_telemetry

### DB Management UI (313 + 300)
- **300** — `/api/admin/aggregate_telemetry` endpoint + `/api/admin/db_stats` endpoint
- **313** — DB panel v Settings modal: velikost + počty záznamů (problems/history/telemetry), tlačítka „Prune nyní" a „Agregovat telemetrii"
- **304** — Potvrzeno hotové (changes since login banner byl v script-core.js od dřívějška)

---

## [2026.06.016] - 2026-06-11

**Souhrn:** Password hashing (bcrypt), issues cache lock, composite DB indexy.

### Bezpečnost & Výkon

- **Bcrypt password hashing (347)** — `_check_password()` v `auth.py` detekuje `$2b$` prefix a ověřuje přes bcrypt; plaintext fallback pro zpětnou kompatibilitu. Config: `web.password_hash: "$2b$12$..."` (priorita před `web.password`). Nový endpoint `/api/config/hash_password` + UI tlačítko „Hash hesla" v Settings vygeneruje hash připravený ke vložení do config.yaml. Viewer analogicky přes `web.viewer_password_hash`.
- **Issues cache lock (364)** — `_issues_cache_lock = threading.Lock()` s double-checked locking vzorem: rychlá čtecí cesta bez locku (GIL-safe), zápis + rebuild vždy pod lockem. Brání souběžnému rebuild cache z více vláken.
- **Composite DB indexy (365)** — přidány `idx_problems_plugin_ch_ts (plugin_name, channel_type, last_seen)` a `idx_issue_hist_plugin_ts (plugin_name, resolved_at)` do `init_db()`. Vytvořeny v existující DB automaticky při startu.

---

## [2026.06.015] - 2026-06-10

**Souhrn:** Čtyři prioritní položky z bezpečnostní analýzy — 2FA/TOTP, watcher thread-safety, notifier retry queue s exponential backoffem a per-severity throttling.

### Nové funkce

- **2FA / TOTP (346)** — celý stack: pyotp, DB tabulka `user_totp`, funkce `totp_setup/enable/disable/verify` ve `state_issues.py`, dvou-krokový login flow v `routes/main.py` (platné přihlášení → TOTP krok), endpointy `/api/2fa/status|setup|enable|disable`, UI panel v Settings modal s QR kódem (base64 PNG, qrcode lib). Funguje s Google Authenticator / Authy. Admin může deaktivovat 2FA libovolnému uživateli.
- **Watcher thread-safety (361)** — `LogHandler._file_positions` chráněn `threading.Lock` (`_pos_lock`); read a write pozice, delete a moved eventi — vše přes lock. Brání race condition při logrotaci a souběžném zpracování inotify eventů z více vláken.
- **Notifier retry queue (362)** — `_with_retry()` wrapper spouští každý kanál; při výjimce zařadí do `_retry_queue` (deque maxlen=200). Background vlákno `NotifierRetry` zkouší znovu s delays 30s/120s/300s (max 3 pokusy), poté `logger.warning`.
- **Notifier per-severity throttle (363)** — `_THROTTLE_BY_SEV` dict: `critical/security/root` 15min, `high` 1h, `medium/low/agent/infra` 4h. Nahrazuje hardcoded `THROTTLE_SECONDS=3600` pro všechny kanály.

### Závislosti

- `pyotp>=2.9.0` — TOTP implementace (RFC 6238)
- `qrcode>=8.2` + `pillow` — generování QR kódů jako PNG

---

## [2026.06.014] - 2026-06-10

**Souhrn:** Bezpečnostní hardening kolo 2 — opravy kritických nálezů z celkové bezpečnostní analýzy (brute-force na form login, XSS v AI odpovědích, hostname validace SSH, config backup, validace int parametrů) + oprava setup wizardu.

### Bezpečnost

- **Brute-force ochrana na form login (281)** — `/login` POST nyní kontroluje `is_ip_banned()` (vrací 429) a registruje selhání přes `register_failed_login()`; dříve šel formulářový login zcela mimo ochranu, která kryla jen Basic auth. IP ban po 5 pokusech na 300 s (konfigurovatelné v `security.login_max_attempts/login_ban_time`).
- **XSS v AI odpovědích (283)** — `routes/issues.py`: AI reply v `/api/analyze/active_issues`, `/api/analyze/trend_report` a AI korelaci šel do `innerHTML` bez `html.escape()`. AI cituje obsah logů → útočníkem řízený text v lozích mohl injektovat HTML/JS do admin session. Nyní všechny AI reply escapovány; chybové hlášky taktéž.
- **Hostname validace v SSH endpointech (282)** — `_valid_host()` regex `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,253}$` v `/api/ssh/execute`, `/api/ssh/stream` a `/api/ssh/batch`; brání injection přes host parametr.
- **Config restore backup (284)** — `/api/config/restore` před přepsáním zálohuje aktuální config do `/var/lib/sentinel/config_backups/config_<ts>.yaml` (drží 10 nejnovějších).
- **Validace integer parametrů (288)** — 20 výskytů `min(int(request.args.get(...)), MAX)` bez spodní meze nahrazeno `int_param(value, default, 1, MAX)`; záporné hodnoty už nemohou generovat neplatné SQL `datetime()` intervaly a nevalidní vstup vrací default místo HTTP 500.

### Opraveno

- **Setup wizard `sentinel_init.py`** — generoval config nekompatibilní s `config.py`: sekce `teams` → `teams_channels`, `home_assistant` → `homeassistant`, `mqtt.password` → `mqtt.pass`, LDAP `viewers` → `viewer_users`. Doplněn dotaz na admin/viewer hesla (odmítne výchozí „admin"), sekce ntfy + stuby gotify/smtp/matrix, odstraněny neznámé klíče (`chromadb_path`, `log_file`).
- **Sparkline fetch** — `days=0.04` (neplatný int) → `days=1` v `_drawAgentListSparklines()`.

---

## [2026.06.013] - 2026-06-10

**Souhrn:** Dokončení zbývajících TODO položek 250–280 — analytické reporty, sparklines v agent listu, integrace Gotify/Matrix/ntfy/SMTP, HA action config, plánované akce v agent detailu, oprava resolution time trackingu.

### Nové funkce

- **Telemetry query cache (250)** — `/api/dashboard` sparklines dotaz cachován 5 minut (`_dashboard_sparklines_cache`).
- **Issue resolution time stats (258)** — opraveno `_archive_problem()`: nyní ukládá `first_seen` z `problems` do `issue_history`; `/api/analytics/resolution_time` vrací reálná data.
- **Top flapping issues (259)** — `/api/analytics/flapping` — issues které se nejčastěji opakují.
- **Alert fatigue report (260)** — `/api/analytics/alert_fatigue` — false positive stats per plugin.
- **Change detection po přihlášení (262)** — `/api/analytics/changes_since_login` — počet nových/vyřešených issues od poslední session.
- **Log parser error rate (263)** — watcher.py trackuje `sentinel.lines_parsed_per_min` v telemetrii.
- **Mini CPU/RAM sparklines v agent listu (264)** — funkce `_drawAgentListSparklines()` kreslí Chart.js mini grafy do canvas elementů v agent tabulce.
- **Záložka "Plánované akce" v agent detailu (269)** — `_appendScheduledActionsSection()` + `/api/agents/<hostname>/scheduled_actions` endpoint.
- **Gotify integrace UI (274)** — status/toggle/save/test endpointy + zobrazení v Connection modal.
- **Matrix integrace UI (277)** — status/toggle/save/test endpointy + zobrazení v Connection modal.
- **HA Action config (278)** — `HA_ACTION_SERVICE` + `HA_ACTION_ENTITY` v config.yaml; `send_ha_action()` v notifier.py volán pro security/root alerty.
- **ntfy/SMTP v Connection modal** — přidány jako řádky v Integrace sekci.

### Opraveno

- `_archive_problem()` nyní správně propaguje `first_seen` do `issue_history`, což umožňuje výpočet doby řešení v analytics.
- `load_config()` nyní načítá ntfy/gotify/smtp/matrix/ha_action sekce z config.yaml.
- Integrations status/toggle/save endpointy rozšířeny o ntfy, gotify, smtp, matrix.

---

## [2026.06.012] - 2026-06-10

**Souhrn:** Bezpečnostní hardening (CSRF, SSH, tokeny, secrets), refaktoring architektury (scheduler, notifier extrakce), audit kódu a opravy UI (mobilní responsivita, UNKNOWN kategorie, rozbité modaly).

### Opraveno (bugfix)

- **`_DASH_WIDGETS` duplicitní deklarace** — `SyntaxError` způsoboval odmítnutí celého `script-ui.min.js`; žádné modaly nefungovaly. Přejmenováno na `_SYS_SECTION_CATS` v `script-modals.js`.
- **UNKNOWN kategorie v issues** — HA detector ukládal `"cluster":"UNKNOWN"` do JSON details; groupovací logika ho brala jako platnou hodnotu. Opraveno v `routes/issues.py`.
- **LIVE chat kontext `plugin_name=?`** — endpoint `/api/v1/issues` nevracel `plugin_name`. Přidáno.
- **CSP blokoval cdnjs.cloudflare.com** — highlight.js nefungoval. Přidán do Content-Security-Policy.
- **Header z-index** — chyběl `position: relative`; z-index 200 neměl efekt. Opraveno.
- **Mobilní responsivita issues karet** — `[data-issue-card]` není flex container, starý mobile CSS `flex-direction:column` neměl efekt. Přidány třídy `.issue-row-inner`, `.issue-content-area`, `.issue-actions`; na mobilu se akční tlačítka wrapují pod obsah.
- **Vtip (logo)** — AI vracel "Generuji vtip:" prefix místo samotného vtipu. Přepracováno na předgenerované šablony s reálnými daty (offline servery, plugin names, issue counts), bez AI latence.

### Bezpečnost

- **CSRF ochrana** — token v session + cookie (SameSite=Strict) + globální `window.fetch` wrapper přidává `X-CSRF-Token` ke všem POST/PUT/DELETE requestům automaticky.
- **Hardcoded token odstraněn** — `sentinel_secret_token_2026` nahrazen auto-generovaným persistentním tokenem v `/var/lib/sentinel/client_api_key` (mode 600).
- **SSH hardening** — nový `sentinel/ssh_utils.py`: `build_ssh_cmd()` nahradil 4 výskyty `StrictHostKeyChecking=no` za `accept-new` + `UserKnownHostsFile`; `scan_host_key()` spustí `ssh-keyscan` při registraci agenta.
- **X-Forwarded-For** — `get_real_ip()` čte reálnou IP klienta za reverzní proxy, pouze z `TRUSTED_PROXIES` (konfigur. v config.yaml).
- **Revokované sessions v DB** — `revoked_sessions` tabulka; revokace přežije restart.
- **Varování na výchozí hesla** — CRITICAL log + UI banner pokud `WEB_PASS == "admin"`.
- **SECRET_KEY persistentní** — načítán ze souboru `/var/lib/sentinel/secret_key`, generován jednou.
- **HMAC podpis webhooků** — `_verify_webhook_auth()` podporuje `X-Hub-Signature-256` i token query param + replay ochrana přes `X-Webhook-Timestamp`.
- **Audit trail konfigurace** — tabulka `config_audit` (kdo, kdy, IP, jaké klíče) při každém config update.
- **Hostname validace** — regex `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$` v register a ingest endpointech.
- **SSH command pre-validace** — `_pre_validate_ssh_command()` ověří allowlist v `actions.py` před SSH voláním.
- **ENV secrets v config.yaml** — podpora `{SECRET:ENV_VAR}` syntaxe, rekurzivní substituace.

### Výkon

- **DB indexy** — přidány `idx_problems_severity` a `idx_telemetry_cat_metric_ts` (composite).
- **`get_active_issues()` cache** — TTL 5s in-memory cache; invalidace při `save_problem()` a `mark_resolved()`. Méně DB dotazů při 30s polling.
- **Agent badge cache** — fetch max 1× za 10s místo při každém render.
- **Conversation history limit** — max 100 zpráv.
- **WebSocket watchdog** — 45s ticho → force reconnect.
- **Geo-IP cache a session GC** — hodinový cleanup v scheduleru.

### Přidáno

- **`sentinel/notifier.py`** — odchozí notifikace (Teams, Webhook, PagerDuty, Slack, ntfy.sh, Gotify, SMTP, HA) extrahovány z `ChatService`; standalone `send_notification()`.
- **`sentinel/scheduler.py`** — background maintenance loop extrahován z `ChatService`; `Scheduler` class se třemi úrovněmi (minutová, hodinová, noční).
- **`sentinel/ssh_utils.py`** — centrální SSH bezpečnostní modul.
- **ntfy.sh notifikace** — `NTFY_ENABLED`, `NTFY_URL`, `NTFY_TOKEN` v config.yaml.
- **Gotify notifikace** — `GOTIFY_ENABLED`, `GOTIFY_URL`, `GOTIFY_TOKEN`.
- **SMTP email** — `SMTP_ENABLED`, `SMTP_HOST/PORT/USER/PASS/FROM/TO`, STARTTLS.
- **Issues bulk CSV export** — tlačítko v bulk baru + `Alt+E` shortcut.
- **Chat export do Markdown** — tlačítko v input area.
- **Dashboard live clock** — hodinky v záhlaví dashboardu.
- **`Alt+A`** — bulk acknowledge, **`Alt+E`** — CSV export (klávesové zkratky).
- **DB size alert** — `_run_sentinel_health_checks()`: varování pokud DB > `DB_SIZE_ALERT_MB`.
- **Synthetic HTTP health check** — `SYNTHETIC_CHECKS: [{name, url, timeout}]` v config.yaml.
- **No-agent alert** — critical issue pokud žádný agent neodesílá heartbeat >5 min.
- **SIGHUP handler** — `config.load_config()` bez restartu.
- **Agent deployment helper** — `_showDeployHelper(hostname)` generuje install one-liner.
- **Hodinový vtip log** — v "O systému Sentinel" záložka "Historie vtipů (24h)".
- **`/healthz` endpoint** — JSON health probe pro Kubernetes/UptimeKuma (DB check, HTTP 503 při chybě).
- **`/status` přepracován** — modernní design, filtrace hw/alert agentů, auto-refresh 30s.

### CI/CD & Kvalita

- **`.gitea/workflows/ci.yml`** — Gitea Actions: pytest + node --check + make build.
- **`pre-push` git hook** — lokální záchranná síť (JS check + pytest).
- **`requirements.txt`** — 13 pinovaných závislostí.
- **`.min.js` mimo git** — build artefakty odstraněny z repo, buildí se při deploy.
- **`eslint.config.js`** — `no-redeclare=error` zachytí duplicitní JS deklarace.
- **`pyproject.toml`** — ruff konfigurace, `make lint` target.
- **12 route testů** — Flask test client: status, issues, agents, CSRF, hostname injection.
- **`CONTRIBUTING.md`** — architektura ASCII diagram, vývojový workflow, bezpečnostní pravidla.
- **21× `except: pass`** → `logger.warning()` ve `state_issues.py` a `chat_service.py`.

## [2026.06.011] - 2026-06-09

**Souhrn:** Dokončení všech [A] položek z todo.md — fullscreen issue detail, kapacitní předpověď, porovnání oken telemetrie, Prometheus pushgateway, CVE scanner, file integrity monitoring, Ansible runner, HW metriky (net/GPU/SMART/UPS).

### Přidáno

- **137** — Issue fullscreen overlay: klik na ↕ ikoně → celá obrazovka s detailem issue, AI analýzou, komentáři a podobnými incidenty (Esc pro zavření)
- **148** — Prometheus pushgateway: `prometheus.pushgateway_url` v config.yaml → periodický PUT sentinel metrik
- **150** — Porovnání dvou časových oken telemetrie: tab "Srovnání" v Tools, výpočet delta a % rozdílu
- **151** — Kapacitní předpověď: `/api/predictions/capacity` + tlačítko "Předpověď kapacity" v tab Kapacita (linear regression, TTL do plného disku/RAM)
- **171** — CVE scanner: `/api/agents/<hostname>/cve_scan` → `apt list --upgradable | grep security` nebo `dnf --security check-update` přes SSH, výsledky v agent detail
- **176** — File Integrity Monitoring: `watcher.fim_check()` volaná každou minutu, SHA-256 hash kritických souborů, alert při změně (channel: security)
- **181** — Ansible playbook runner: `/api/ansible/run` → validace cesty, sestavení ansible-playbook příkazu, streaming výstupu
- **197-200** — HW metriky přes SSH: `/api/agents/<hostname>/hw_metrics` pro net (/proc/net/dev), GPU (nvidia-smi/rocm-smi), SMART (smartctl), UPS (apcaccess/upsc); panel v agent detail

### Konfigurace

- `config.yaml.example` rozšířen: `prometheus.pushgateway_url`, sekce `fim:` (enabled, paths)
- `config.py`: nové globální proměnné `PROMETHEUS_PUSHGATEWAY_URL`, `FIM_ENABLED`, `FIM_PATHS`

## [2026.06.010] - 2026-06-09

**Souhrn:** Oprava 22 chyb z chyby.md + 8 nových TODO funkcí — Grafana/AlertManager webhook příjem, Sentinel self-metriky, virtual scroll issues, mobile swipe, responsivní charts, chat LIVE tag, LOG Viewer vylepšení, dashboard settings.

### Opraveno (chyby.md)

- **#2** — `auto_clusters`: naive/aware datetime mismatch → `_parse_ts` strippuje TZ pro konzistentní porovnání
- **#3** — Inline komentář se mazal: `refreshModalIssuesContent` přeskočí re-render při focus v inputu nebo neprázdném textu
- **#4/#22** — UNKNOWN skupiny → OSTATNÍ; `delete_all` pro infra maže všechny non-agent/security/root issues
- **#5** — Responsivita: CSS media queries pro issues modal (max-height dle viewport, toolbar wrap)
- **#6** — `_try_auto_remediate` NameError: lazy import `check_command_allowed` z state_agents
- **#7** — LOG Viewer detektor: auto-načtení log řádků, popis panelu, inline formulář, název souboru
- **#8** — QR kód: `requestAnimationFrame` + viditelný fallback text
- **#9** — Dashboard: odkaz "Veřejný" → /status, nastavení widgetů (hide/show)
- **#10** — Agent health tab: auto-refresh 30s, clearInterval při zavření
- **#11/#12** — Záložky Heatmap a Geo Mapa odstraněny z Tools modalu
- **#14** — Similar incidents modal: `background:var(--bg)`, border, padding
- **#15** — Připojení klienti: odstraněn externí ISP fetch (ip-api.com)
- **#16** — Stav spojení: intRow nezobrazuje host/port/URL
- **#17** — AI timeout: skryta chybová zpráva, jemný hint
- **#18** — Instance badge: klik → sentinel-docs.example.com
- **#19** — O systému Sentinel: redesign bez repozitářů
- **#20** — Chat LIVE tag: enrichuje dotaz o kontext aktivních issues
- **#21** — Klik na logo → AI sarkastický vtip (toast 6s)
- **#23** — Login: odkaz na /status
- **#24** — AI markdown v chatu: `_mdRender()` (bold, heading, code, bullets)

### Přidáno (TODO)

- **184** — Grafana webhook příjem (`/api/inbound/grafana`): legacy i unified alerting formát
- **194** — AlertManager webhook příjem (`/api/inbound/alertmanager`): Prometheus AM formát
- **204** — Sentinel self-metriky: RAM, threads, queue, issues, agents_online, load1 → telemetrie každou minutu
- **223** — Mobilní swipe na issue kartách: pravý swipe = acknowledge, levý = delete
- **225** — Responsivní charts: CSS media queries pro canvas v Tools modalu
- **226** — Virtual scroll issues: stránkování po 50, tlačítko "Načíst více"
- **228** — HTTP caching: bylo již implementováno (označeno [X])

### Technické

- `routes/integrations.py` — nové endpointy `/api/inbound/grafana` a `/api/inbound/alertmanager`
- `chat_service.py` — nová metoda `_save_sentinel_self_metrics()`
- `routes/issues.py` — `generate_modal_issues_html` s offset/limit, fix `delete_all` pro infra
- `state_issues.py` — fix `check_agent_thresholds` lazy import
- `script-core.js` — `_enrichWithLiveContext()`, `_mdRender()`, `_detAddSubmit()`
- `script-modals.js` — `_initSwipeGestures()`, `_loadMoreIssues()`, refresh ochrana inputů
- `style.css` — responsivní media queries pro issues modal a charts

## [2026.06.009] - 2026-06-09

**Souhrn:** Maintenance window per-host, per-agent thresholdy s vynucením, batch SSH na více agentů, zobrazení balíčků přes SSH, heartbeat timeout v UI, QR kód pro registraci, AI návrh regex patternů, AI kapacitní plánování, auto-clustering issues.

### Přidáno

- **Maintenance window per-host (207)** — `snooze_rules` tabulka rozšířena o sloupec `hosts` (CSV hostů; NULL = globální). `apply_snooze_rules()` filtruje UPDATE dle hostname. Formulář Maintenance Windows má nové pole "Hosts". Agent detail modal má sekci "Plánovaná okna údržby" s pre-fill hostname a vlastním seznamem oken.

- **Per-agent CPU/RAM alert threshold s vynucením (141)** — nová funkce `check_agent_thresholds(hostname, metrics_dict)` v `state_issues.py`: při každém ingest payloadu s polem `metrics: {}` zkontroluje pravidla z tabulky `agent_thresholds`, vytvoří issue při překročení nebo vyřeší při návratu do normy. Quick-buttons CPU >90%, RAM >90%, Disk >85% v agent detail modalu.

- **Labels per-agent (142)** — označeno [X], bylo hotové od TODO 038.

- **Batch SSH na více agentů (145)** — endpoint `POST /api/ssh/batch`: paralelní SSH přes `ThreadPoolExecutor` (max 10 vláken, limit 50 hostů), safety + allowlist check, logy per host. Nový modal "Batch SSH" v agent health pane s checkboxy agentů (online/offline indikátor), výsledky per host s OK/FAIL barvami.

- **Nainstalované balíčky přes SSH (146)** — endpoint `POST /api/agents/<hostname>/packages`: spustí `dpkg-query` s fallbackem na `rpm -qa`, parsuje výstup, podporuje live `filter` parametr. V agent detail modalu sekce "Nainstalované balíčky" s on-demand načtením a inline filtrem.

- **Heartbeat timeout per-agent v UI (153)** — sekce v agent detail modalu s numerickým inputem (30–86400 s), zobrazuje aktuální hodnotu nebo "(globální default)". Tlačítka Uložit a Reset. Funkce `_saveHeartbeatTimeout()` a `_clearHeartbeatTimeout()`.

- **QR kód pro registraci agenta (155)** — přidána offline QR knihovna `qrcode.min.js` (qrcodejs, ~20 KB, MIT). Token modal nyní generuje QR kód 160×160 px s payloadem `{hostname, token, ingest_url}`. Bezpečnostní upozornění vedle QR.

- **AI návrh regex patternů z historických issues (158)** — v Pattern Editor modalu nová sekce "AI návrh patternů" s tlačítkem "Navrhnout". `_suggestPatterns()` volá existující `/api/patterns/suggest`, renderuje karty s name/plugin/pattern/reason a tlačítkem jedním klikem přidat. `_applySuggestion(i)` přidá pattern a označí jako "✓ Přidáno".

- **AI kapacitní plánování (163)** — nový tab "Kapacita" v Tools modalu. Endpoint `POST /api/reports/capacity_plan`: agreguje telemetrii (cpu_pct, ram_pct, disk_pct aj.) per host, posílá AI, AI vrátí strukturované HOST/PROBLÉM/DOPORUČENÍ/PRIORITA bloky. UI renderuje barevné karty (high=červená, medium=oranžová, low=zelená) + collapsible celý AI výstup.

- **Auto-clustering issues (168)** — endpoint `POST /api/analyze/auto_clusters`: algoritmické seskupení aktivních issues — (1) stejný plugin na 2+ hostech v 30min okně, (2) stejný host s 2+ issues v 30min okně. Volitelně AI pojmenuje root cause jedním promptem pro všechny clustery. Tlačítko "Clustery" (zelené) v issues toolbar, výsledky inline v modalu.

### Technické změny

- `state_base.py` — migrace `hosts` sloupce do `snooze_rules` (CREATE TABLE + ALTER pro existující DB)
- `state_issues.py` — nová `check_agent_thresholds()`, nový `hosts` parametr v `add_snooze_rule()`
- `routes/agents.py` — ingest zpracovává `metrics` pole, nový `/packages` endpoint, `/api/ssh/batch`
- `routes/issues.py` — nový `/api/analyze/auto_clusters`
- `routes/system.py` — nový `/api/reports/capacity_plan`
- `routes/actions.py` — nový `/api/ssh/batch`
- `sentinel/static/qrcode.min.js` — přidána QR knihovna

## [2026.06.008] - 2026-06-08

**Souhrn:** Konfigurace integrací přímo v modalu Notifikace, per-detektor/kanál notify toggles, oprava modalu Stav spojení (uptime, DB size, auto-refresh), heatmap popis, AI analýza per kategorie, oprava UNKNOWN kategorie.

### Přidáno

- **Integrace — konfigurace v modalu Notifikace & Integrace** — každý tab (MQTT, HA, Teams, Webhook, Slack, PagerDuty) má inline config formulář s tlačítky Uložit a Test. Nový endpoint `POST /api/integrations/<name>/save` zapisuje do paměti i config.yaml. Status endpoint rozšířen o plné hodnoty pro předvyplnění. MQTT a HA sekce odstraněny ze Settings modalu (odkaz tam zůstal).
- **Per-detektor notify toggle** — každý plugin v Plugin Stats má sloupec 🔔 (klikatelná ikona). Nový endpoint `POST /api/plugins/toggle_notify` uloží `notify: true/false` do YAML. `state_issues.py` kontroluje příznak před odesláním HA/MQTT notifikace.
- **Per-kanál notify toggle** — tlačítko 🔔 vedle tlačítka Korelace v issues modalu otevírá modal „Nastavení notifikací" se dvěma sekcemi: Kanály (infra/agent/security/root) a Integrace (zapnout/vypnout). Nové endpointy `GET /api/channels/notify` a `POST /api/channels/<ch>/notify/toggle`.
- **Bell ikona v issue kartách** — jemná 🔔 ikona vedle názvu detektoru v každé issue kartě, klik otevře Nastavení notifikací.
- **Heatmap popis** — info box nad canvasem vysvětluje co heatmap zobrazuje a jak ji číst.

### Opraveno

- **Modal Stav spojení — uptime statický** — JS četl `st.uptime_seconds` (z `d.stats`), ale API vrací `uptime_seconds` v `d.server`. Opraveno.
- **Modal Stav spojení — DB size = 0** — backend volal `getattr(state, 'DB_PATH', None)` (neexistuje), opraveno na `state_base.DB_FILE`.
- **Modal Stav spojení — redesign** — přidány stat karty (Uptime / Aktivní issues / DB size), auto-refresh každých 30 s, AI statistiky (requests, errors, latence), formát DB size KB/MB.
- **AI Souhrn/Korelace — pouze aktuální kategorie** — obě funkce předávají `currentOpenChannel` backendu; backend filtruje issues dle channel_type. Výsledek vždy jde do chatu + thinking bubble při zpracování.
- **UNKNOWN kategorie pro availability/ha detektor** — `channel_type` v DB je uppercase (`INFO`, `INFRA`, `CLUSTERS`), mapa barev v `script-agents.js` hledala lowercase. Opraveno: normalizace na lowercase + mapování `info → infra`, `clusters → infra`. Správné barvy pro všechny kategorie.
- **Bell tlačítko 2× vyšší** — globální CSS `button { display:flex; padding:12px 20px }` způsoboval výšku. Změněno na `<span>` s `display:inline-block` — není ovlivněn globálním button CSS.
- **UNKNOWN v plugin stats** — SQL filtr `lower(plugin_name) != 'unknown'` v obou dotazech v `get_plugin_stats()`.
- **Detector UNKNOWN v issue kartě** — `(i.get('plugin_name') or 'unknown').upper()` → `(i.get('plugin_name') or i.get('channel_type') or '?').upper()`.

---

## [2026.06.007] - 2026-06-04

**Souhrn:** f2b/security záznamy per technologie, UX provádění akcí, kopírování tokenů, sentinel-alert satellite, agent re-afirmace, doladění instalátoru.

### Přidáno

- **Security/f2b — všechny záznamy per technologie** — `detector_security` (HPC) drží plný seznam záchytů (IP, typ, počet) a ukládá ho do detailu issue; karta SEC issue má rozbalovací `<details>` se všemi záznamy dané infrastruktury (Karolina, Barbora, CS…). Žádné stovky samostatných issue.
- **Kopírování tokenu** — tlačítko „Kopírovat" u všech modalů generujících token (registrace agenta/alert-node/HW i inline net-registrace) přes `safeCopyText()` (clipboard + fallback okno pro ruční kopii).
- **Integrace — konfigurace v modalu** — u MQTT a HomeAssistant lze v integračním modalu nastavit hodnoty (host/port/user/topic, URL/notify service) a uložit (přes `/api/config/update`, zápis do config.yaml + reload). Toggle a Test už existovaly. Secret pole (heslo/token) se NEzobrazují a prázdná hodnota je nepřepíše → žádné prosakování sensitivních údajů.

### Opraveno

- **Provedení akce (SSH/pending)** — výstup se zobrazí i u tichých příkazů (`systemctl restart` → „exit 0, bez výstupu") a modal se nezavírá hned; uživatel vidí výsledek.
- **Sdílení issue** — clipboard-first s fallback oknem (již dříve, potvrzeno).

### Agenti / Satellite

- **sentinel-agent** — re-afirmuje všechny aktivní issues každý cyklus, aby je server po restartu „nezapomněl" (delta-only push je nechával auto-resolvnout). Platí pro WORK i HOME agenta.
- **sentinel-alert** — aktualizace na novou verzi (mikrotik/pihole/proxy_monitor), oprava ingest URL satellite (`/api/v1/agent/ingest`).

### Instalátor

- `sentinel_init.py`: vytváří `/var/lib/sentinel`, generuje službu s `WatchdogSec=900` a `ExecStartPre` (wal_checkpoint).

---

## [2026.06.006] - 2026-06-04

**Souhrn:** Stabilizace HPC instance (auto.hpc.cz) — odstranění příčin "UI offline": deadlock AI semaforu, kontence DB na hot read-path, a zahlcení dev serveru spojeními. Plus přístup k root relacím pro admina, oprava velikosti DB v modalu, rychlejší načítání a diagnostika watchdog pádů.

### Opraveno

- **Deadlock AI semaforu (pravděpodobně původní "dotaz na AI → umřelo, pomůže jen kill -9")** — `execute_ollama()` interně bere `llm_semaphore`. Endpointy `/api/analyze/correlate`, `active_issues` a `trend_report` braly stejný `Semaphore(1)` JEŠTĚ PŘED voláním `execute_ollama` → re-entrantní zabrání → trvalý deadlock → veškeré AI viselo → `stop-sigterm timeout → SIGKILL`. Odstraněna všechna vnější `llm_semaphore.acquire()` z `routes/issues.py`; serializaci řeší výhradně `execute_ollama`.
- **DB kontence → zatuhnutí webu** — `get_pending_actions()` volal `prune_expired_actions()` (zápis pod `db_lock`) na hot read-path (každý `/api/status_check` poll). Kolidovalo s agent ingestem → request vlákna zatuhla v SQLite → accept-loop hladověl → "offline". Prune odstraněn z `get_pending_actions` (expiraci dělá background `action_cleanup_loop`).
- **Velikost DB = 0 v modalu Stav spojení** — `/api/connection/status` četl neexistující `state.DB_PATH`. Opraveno na `state.DB_FILE`.
- **Ollama HTTP timeout 600s → 90s** — jedno zaseknuté volání drželo workera (a semafor) až 10 minut a roztáčelo connection-storm. Bezpečně ohraničeno.
- **`_loadSparklineData is not defined`** — `script-core.js` volal funkci definovanou až v `script-modals.js` (načítá se později). Iniciální volání odloženo na `window.load` + `typeof` guard.

### Přidáno

- **Root relace viditelné i pro roli `admin`** (dřív jen `superadmin`) — `generate_modal_issues_html` v `routes/issues.py`.
- **`api.add_root_audit()`** — idempotentní (jeden aktivní záznam per server+ip, žádné duplikáty každých 5 min) + reverzní DNS (audit ukazuje `IP (hostname)` = kdo to je).
- **`faulthandler.enable()`** — při watchdog SIGABRT vypíše tracebacky všech vláken do journalu (diagnostika tuhnutí; funguje i při drženém GILu).
- **Dashboard polling 5s → 30s** (`script-core.js`) — nižší trvalá zátěž.

### Poznámky k nasazení (specifické pro auto.hpc.cz, mimo tento repozitář)

- nginx: `limit_conn 10/IP`, `proxy_read_timeout 120s`, `proxy_next_upstream off`, přímé servírování `/static/` s cache (ochrana proti connection-storm + rychlejší assety).
- HPC detektory (`sentinel-plugins-hpc`) a sběrové skripty (`Overhealth`) — viz jejich repozitáře.

---

## [2026.06.005] - 2026-06-02

**Souhrn:** Oprava LDAP přihlášení (fallback přes přímý ldap3 bind), oprava mizejících skupin logů po config reload, oprava chat inputu jako heslo, oprava DOMContentLoaded v deferred skriptech.

### Opraveno

- **LDAP přihlášení selhávalo po config reloadu** — po detekci změny `config.yaml` watcherem se volal `load_config()`, ale `ldap_manager` (flask-ldap3-login) se znovu neinicializoval → zůstal `None` → přihlášení selhálo tiše. Opraveno: `_reinit_ldap()` v `watcher.py` po každém reloadu configu.
- **LDAP fallback přes přímý ldap3 bind** — přidána záložní cesta v `check_auth()`: pokud `ldap_manager` je `None`, provede se přímý `search + bind` přes `ldap3` (bez flask-ldap3-login). Funguje pro lldap i OpenLDAP.
- **Skupiny logů zmizely po reloadu** — inotify `IN_MODIFY` firuje při prvním zapsaném bajtu souboru (ne po `close()`). `load_config()` četl neúplný `config.yaml` → `LOG_GROUPS = {}`. Opraveno: `time.sleep(1.0)` před čtením v `ConfigHandler.on_modified()`.
- **Chat input nabízel uložení jako heslo** — `name="sentinel-chat"` + `<input type="password">` v settings modalu na stejné stránce spustilo password manager. Opraveno: `type="search"` (browser neasociuje se credentials) + `autocomplete="new-password"` na všech password fieldech v settings.
- **DOMContentLoaded v deferred skriptech** — s `defer` atributem se skripty spouštějí po `DOMContentLoaded`, takže `addEventListener('DOMContentLoaded', cb)` uvnitř deferred skriptu nikdy nevyprší. Opraveno: `_onReady()` helper v `script-core.js` a `script-modals.js` (kontroluje `document.readyState`).
- **rpizero2 false alarm** — server byl v `DEFAULT_DOWN_SERVERS` (očekávaně offline), přestože je normálně online. Odstraněn ze seznamu.
- **CSS pro `input[type="search"]`** — po změně typu chat inputu ztratil styl (`flex:1`, barvy, padding). Přidán selektor vedle `input[type="text"]`.

---

## [2026.06.004] - 2026-06-02

**Souhrn:** Oprava autofixu, oprava Socket.IO offline badge za reverzním proxy, výkonnostní optimalizace načítání, nové testy.

### Opraveno

- **`execute_ollama` (EXTERNAL_OLLAMA větev)** — parametr `messages` byl ignorován; vždy se posílalo `[{"role": "user", "content": prompt}]`. Autofix volá `execute_ollama(prompt=None, messages=[system+user])`, takže API dostalo `content: null` → prázdná odpověď → "AI Error (No response field)". Nyní se `messages` použije pokud je nastaven.
- **Autofix system prompt** — upraven aby vždy vracel reálný bash příkaz (diagnostický nebo opravný), nikoliv `N/A`.
- **Socket.IO offline badge za reverzním proxy** — `transports: ['websocket']` znemožňovalo připojení přes proxy (router, Cloudflare) bez WebSocket upgrade podpory. Změněno na `['polling', 'websocket']` s `upgrade: true` — Socket.IO začíná přes HTTP long-polling (prochází každým proxy) a automaticky upgraduje na WebSocket pokud je k dispozici.

### Výkon

- **Statické soubory — Cache-Control** — změněno z `max-age=600` (10 min) na `max-age=31536000, immutable` (1 rok). Soubory mají `?v=subversion` versioning, takže cache je bezpečně invalidována při každém deploymentu.
- **`defer` na externích skriptech** — všech 7 `<script src>` tagů dostalo atribut `defer`. Prohlížeč parsuje a kreslí HTML okamžitě, skripty se stahují paralelně na pozadí a spouštějí se až po dokončení parsování.
- **`<link rel="preload">`** — přidány preload hinty pro kritické soubory (`fa.min.css`, `style.min2.css`, `socket.io.js`, `script-core.min.js`) — prohlížeč začne stahovat dříve než HTML parser discovery scan normálně dosáhne.
- **Gzip komprese** — Flask-Compress byl již nakonfigurován (level 6, min 2 KB), ověřeno že je aktivní pro JS/CSS/JSON/HTML odpovědi (~75% úspora přenosu).

### Testy

- **`tests/test_v006_features.py`** — 27 nových testů pro funkce z verze 006:
  - `TestTelemetrySave` (4 testy) — ověří že `save_telemetry_snapshot()` skutečně zapisuje do SQLite (oprava kritické chyby chybějícího INSERT)
  - `TestTelemetryBuffer` (2 testy) — buffer flush do DB, prázdný buffer bez pádu
  - `TestFalsePositiveMatching` (8 testů) — fnmatch logika vzorů, kompletní test `_is_false_positive()` s reálnou DB
  - `TestIssueDependsOn` (3 testy) — `depends_on` sloupec existuje, JSON round-trip, více závislostí
  - `TestSocketIOTransport` (4 testy) — polling transport přítomen, polling před websocket, upgrade enabled
  - `TestCacheControlHeaders` (3 testy) — `max-age=31536000`, `immutable`, absence staré hodnoty 600
  - `TestDeferredScripts` (3 testy) — všechny external scripty mají `defer`, preload hinty přítomny
- **`tests/run_tests.sh`** — přidán krok `[5/5]` pro nový test soubor

---

## [2026.06.003-hpc] - 2026-06-01

**Souhrn:** Nasazení na HPC produkční instanci (auto.hpc.cz) — kompatibilita s Rocky Linux 9.7, OpenLDAP, OpenAI-compatible Ollama proxy.

### HPC instance (auto.hpc.cz)

- **Python 3.12** — source běží přes `python3.12 -m sentinel -e` (Rocky Linux 9.7 má Python 3.9 systémový)
- **RAG / embeddingy** — opravena URL `/v1/embeddings` (OpenAI-compatible server) + parsování `data[0].embedding`
- **LDAP** — OpenLDAP vyžaduje `ldaps://` prefix v `host` poli; odstraněn hardcoded `objectClass=inetOrgPerson` (LLDAP-specific), volitelný `ldap.user_object_filter` v configu
- **`api.py`** — `DB_PATH` přejmenováno na `DB_FILE` v `state_base.py`; aliasováno pro zpětnou kompatibilitu
- **`routes/issues.py`** — ošetřeny NULL hodnoty (`plugin_name`, `host`, `last_line`) ze starší DB při renderování issue karet
- **HPC pluginy** — deduplication klíče po zdrojové IP (security) / username (login_compute) místo `hash(celý řádek)`
- **`routes/chat.py`** — limit vstupu pro group/single analýzu (posledních 8 000 / 30 000 znaků) — prevence blokování Flask threadů
- **Jazyk odpovědí** — prompty detekují jazyk uživatelského dotazu (EN→EN, CS→CS)
- **Config** — `infrastructure_mapping`, `detectors`, `prompts` doplněny do `/etc/sentinel/config.yaml`

---

## [2026.06.003] - 2026-06-01

**Souhrn:** 120 — Síťová topologie ze SNMP/CDP dat, Canvas force-directed graf.

### Přidáno

- **120 — Síťová topologie**: `topology.py` — builder z agentů + manuálních linků + SNMP CDP/LLDP.
- **API** `GET /api/topology/data` — vrátí nodes + edges pro vizualizaci.
- **Canvas force-directed graf** v Tools "Mapa" tab — iterativní simulace, skupiny jako uzly sítě, barvy dle stavu, legenda.
- **SNMP polling** background thread (spustí se pokud nakonfigurováno `topology.snmp_targets`).
- **Config** `topology.manual_links`, `topology.snmp_targets`, `topology.snmp_poll_interval`.
- **snmpwalk subprocess fallback** — pokud není nainstalován, polling se přeskočí.

---

## [2026.06.002] - 2026-06-01

**Souhrn:** Implementace 10 TODO položek: FP klasifikátor, Similar Incidents, Dep Graph, Geo Mapa, SNMP trap, Async AI worker, HTTPS/HTTP2, Settings rozšíření, UI opravy.

### Přidáno

- **057 — False Positive klasifikátor**: FP vzory v DB, auto-potlačení matching issues, správa v Tools tab.
- **059 — Similar incidents**: Jaccard text similarity nad issue_history, lupa ikona na každé kartě.
- **081 — SNMP trap receiver**: UDP listener, minimální BER parser, OID→channel mapping, bez externích závilostí.
- **118 — Geografická mapa**: Leaflet.js + OpenStreetMap, ip-api.com geolokace veřejných IP, cache 1h.
- **119 — Dependency graph**: Canvas-based vizualizace issue závislostí, barevné uzly dle stavu.
- **126 — Async AI worker**: asyncio event loop místo ThreadPoolExecutor, asyncio.Semaphore(1) pro Hailo.
- **129 — HTTPS/HTTP2**: SSL/TLS podpora v chat_service.py, hypercorn fallback pro HTTP/2, volba v sentinel_init.py.

### Opraveno

- **Chat input autofill**: -webkit-autofill CSS override (bílý text na bílém pozadí).
- **Settings**: Rozšířen o MQTT, HA, LDAP, Hailo, Log Dir sekce + restart checkbox.
- **api/config/update**: YAML load/update/write, podpora nested klíčů (mqtt.*, ldap.*, hailo_ollama.*).

---

## [2026.06.001] - 2026-06-01

**Souhrn:** Issue závislosti (depends_on) — správa závislostí mezi issues, modal, API.

### Přidáno

- **Issue závislosti (023)**: Nový sloupec `depends_on` (JSON array) v tabulce `problems`. Každé issue může záviset na N jiných issues.
- **API endpointy**: `GET/POST/DELETE /api/issues/<key>/depends`, `GET /api/issues/<key>/blocked_by`.
- **UI badge**: Issue karta zobrazuje oranžový badge s počtem závislostí (kliknutím otevře modal).
- **UI tlačítko**: Admin/superadmin vidí ikonu řetězu pro správu závislostí přímo z karty.
- **Depends modal**: Přehled na čem issue závisí + co blokuje, přidání/odebrání závislostí.

---

## [2026.05.061] - 2026-05-31

**Souhrn:** Monitoring modal — heatmap přepracována na Canvas, Graf opraven (Chart.js), UI vylepšení.

### Opraveno

- **Graf nefungoval**: `<script>` injektovaný přes `innerHTML` prohlížeč nevykoná. Přepsáno — Chart.js inicializace probíhá přímo v JS po vložení HTML. Totéž v Srovnat (agent compare charts).
- **Heatmap přepracována**: Ošklivá HTML tabulka nahrazena Canvas-based vizualizací (GitHub-styl). Barevná škála intenzity 0–maxVal, číselné hodnoty v buňkách, popisky hostů + dnů. Legenda pod grafem.

### Přidáno / Vylepšeno

- **Monitoring modal — záložky**: Odstraněny redundantní inline `style="color:..."` z tab tlačítek — `.tools-tab.active` nyní správně zvýrazní aktivní záložku.
- **Patterns inline editor**: Přidat/toggle/smazat/test regex přímo v pane bez otevírání dalšího modalu.
- **Srovnat inline tab**: `agent-compare-modal` přesunut jako tab `tools-pane-srovnat` s Chart.js grafy (opraveno inicializování).
- **Report**: Karta se 2 sloupci, date picker, preset tlačítka Dnes/7d/30d/90d, export sekce.
- **Log Viewer**: Level filter (ERROR/WARN/INFO/DEBUG), Tail, Copy, počítadlo řádků.
- **Znalostní báze**: Sekce indexovaných souborů z `/api/kb/files`.

---

## [2026.05.060] - 2026-05-31

**Souhrn:** Opravy UI, SSH stream, config přístup, správa sítě vylepšena.

### Opraveno

- **SSH stream Permission denied**: `api_ssh_stream` četl z neexistujícího `config.SSH_CONFIG` (prázdný dict → žádný `-i` klíč). Opraveno na `config.SSH_KEY_PATH` / `SSH_USER` / `SSH_JUMP_HOST`.
- **Config z UI pro admin**: `/api/config/update`, `/api/system/ssh-config`, `/api/system/ssh-key` blokovaly uživatele s rolí `admin` (vyžadovaly `superadmin`). Opraveno na `not in ('admin', 'superadmin')`.
- **sentinel-ai-vision API nepřipojeno**: JS čekal pole `d.connected`, zařízení vrací `d.status='online'`. Opraveno: `d.connected || d.status === 'online'`.
- **Header badge výška**: FA bell má vyšší aspect ratio → badge notifikací byl o ~2px vyšší. Přidáno `height:22px; box-sizing:border-box` na `.badge`.
- **Správa sítě — první otevření**: `sat-panel-alert` chyběl `display:none` → oba panely viditelné naráz.
- **Alert nodes nenačteny**: `loadSentinelAlertAgents` měl `saLoadingInProgress` guard a `modal.style.display` check blokující load; přepsáno stejným vzorem jako `loadSentinelHWDevices` (přímý fetch, žádné guardy). Původní `fetchSentinelAlertNetwork` měl 5s timeout který při studeném startu vypršel.
- **Modal otvírání agentů/alert**: `openAgentManager` a `openSentinelAlertModal` sjednoceny — delegují přes `switchSatTab('agents'/'alert')` s `loadData=true`, stejný vzor jako HW tab.

### Přidáno

- **Správa sítě — registrační modal**: Inline formuláře odstraněny z panelů; tab bar dostal tlačítko **"+ Registrovat"** (vpravo). Otevírá malý modal adaptující se dle aktivní záložky (Agent / Alert Node / HW) s polem URL, tlačítkem **Test spojení** a zobrazením tokenu.
- **Endpoint `/api/system/test-url`**: HTTP dostupnost URL (pro registrační modal, timeout 6s).

---

## [2026.05.058] - 2026-05-30

**Souhrn:** Finalizace TODO, nové testy, opravy, sync pluginů, dokumentace.

### Přidáno / Opraveno

- **Testy**: 6 nových testů pro funkce v2026.05.052–057 (agent labels, heartbeat_timeout, telemetry aggregation, issue expiry, settings)
- **Issue expiry fix**: SQLite julianday() porovnání + přepočet na sekundy
- **Překlady**: chybějící `kb_choose_file`, `kb_drop_hint`, `kb_indexed_files` (CS + EN)
- **Plugins sync**: audit_detector, ha_detector, port_detector, services_detector aktualizovány v sentinel-plugins repozitáři

---

## [2026.05.057] - 2026-05-30

**Souhrn:** Notifications modal, sjednocení integrací, PagerDuty, tools panes inline, AI pattern suggest.

### Přidáno

- **Notifications modal**: tři separátní ikony (MQTT/Teams/HA) → jedna ikona 🔔 → unified modal se záložkami MQTT/Teams/HA/Webhook/Slack/PagerDuty
- **Tools modal**: záložky Heatmap/Graf/Config diff/Topology/Changelog/AI Trend/Patterns jsou inline panes
- **Plugin Graf**: rozšířen o plugin dependency + agent graph + alert distribution
- **001** theme per-user (DB + sync při načtení)
- **004** fullscreen live tail (button + F11)
- **045** SSH multi-command (`;`) s per-subcmd allowlist check
- **055** POST /api/patterns/suggest — AI navrhne regex z historických issues
- **070** GET /api/export/prometheus_rules.yaml z SLA/escalation
- **078** PagerDuty Events v2 API

---

## [2026.05.056] - 2026-05-30

**Souhrn:** v2026.05.056 — tools modal inline panes (přechodná verze).

---

## [2026.05.055] - 2026-05-30

**Souhrn:** SSH key manager UI, AI output fix, modal z-index fix.

### Přidáno / Opraveno

- **SSH key manager**: Settings → SSH klíč (superadmin) — fingerprint, upload klíče, config user/jump
- **AI výstup**: odstraněno html.escape() z AI batch/korelace/trend, prompt upraven bez "Výstup v HTML"
- **Modal z-index**: WeakMap prevence infinite loop v MutationObserver

---

## [2026.05.054] - 2026-05-30

**Souhrn:** Push notifikace, sticky toolbar, issue collapse, telemetry compare, logrotate UI, API key brute-force, reports, SSH z issue karty, AI výsledky do chatu.

### Přidáno

- **Push notifikace** (`007`): `_checkPushNotification()` zapojena do `updateStatus()` — prohlížeč zobrazí notifikaci při nárůstu alertů
- **Sticky toolbar** (`008`): toolbar v issues modalu má `position:sticky; top:0` — zůstává viditelný při scrollování
- **Collapsed/expanded issue karty** (`009`): klik na kartu (mimo tlačítka) ji schová/rozbalí; CSS `.collapsed` třída
- **Telemetry compare** (`068`): tlačítko „Porovnat" v graph modalu → overlay druhé metriky na stejný Chart.js graf (pravá osa Y)
- **Logrotate UI trigger** (`093`): `POST /api/system/logrotate` spustí `logrotate -f /etc/logrotate.d/sentinel`
- **API key brute-force ochrana** (`103`): `check_api_key_rate_limit()` — max 20 neplatných pokusů/min per IP → 429
- **Monthly trend report** (`111`): `GET /api/reports/monthly_trend` — počty issues per kanál za 12 měsíců
- **SLA compliance report** (`112`): `GET /api/reports/sla_compliance` — % issues v SLA + aktivní porušení
- **Plugin efficiency report** (`113`): `GET /api/reports/plugin_efficiency` — ack rate, high severity, resolved per plugin
- **SSH tlačítko na issue kartě**: terminál ikona na každé issue kartě (admin+) → přímé otevření SSH modalu na daný host
- **AI výsledky do chatu**: `_batchAiAnalyze()` a `_correlateAiAnalyze()` posílají výsledek do chatu (`appendMessage`) — výsledek zůstane i po zavření modalu; 3min AbortController timeout
- **Queue detail opraven**: `/api/queue/details` vrací `pending` = `chat_queue_depth` (LLM fronta) + `db_pending` (DB task queue)

---

## [2026.05.053] - 2026-05-30

**Souhrn:** LDAP fix, config history, heartbeat per-agent, health score, SSH recording, allowed-commands I/E, telemetry batch, keyboard shortcuts.

### Opraveno

- **LDAP login regrese** (`099`): `ldap_manager` se nastavoval do `chat_service` namespace místo `auth` — `check_auth` v `auth.py` ho nikdy neviděl; opraveno přes `_auth_mod.ldap_manager = ...`

### Přidáno

- **Config history** (`092`): snapshot se ukládá při startu + při každé změně config.yaml; UI `/api/config/history` fungovalo, chyběl jen startup save
- **Heartbeat timeout per-agent** (`037`): sloupec `heartbeat_timeout` v `agents`; watchdog používá per-agent hodnotu nebo global fallback (`agent_heartbeat_timeout` v config.yaml); `GET/POST /api/agents/<h>/heartbeat-timeout`
- **Agent health score** (`039`): výpočet composite score v `get_agent_health()` — status/lag/alerty/maintenance; nový endpoint `GET /api/agents/<h>/health-score` s grade A–D; zobrazení v agent detail modal
- **SSH session recording** (`047`): output limit zvýšen 2KB→8KB; kliknutelný záznam v SSH History otvírá detail v novém okně; `GET /api/agents/<h>/ssh_history/<id>`
- **Allowed commands import/export** (`048`): `GET /api/v1/allowed-commands/export` → JSON download; `POST /api/v1/allowed-commands/import?mode=merge|replace`
- **Telemetry batch insert** (`127`): `save_telemetry()` bufferuje záznamy; background thread `_telemetry_flush_loop` flushuje každých 5s; redukce DB zápisu pro high-freq metriky
- **Keyboard shortcuts** (`002`): stisk `?` → overlay s přehledem zkratek; `Esc` zavírá overlay/modal; `r/s/a/n/1-4` pro rychlou navigaci

### Technické

- `state._telemetry_buffer`, `_telemetry_buffer_lock`, `_telemetry_flush_loop()`, `_flush_telemetry_buffer()`
- `state.get_agent_labels()`, `set_agent_labels()`, `get_agent_health()` rozšířen o `health_score`
- DB migrace: `agents.heartbeat_timeout INTEGER DEFAULT NULL`
- `config.yaml.example`: `agent_heartbeat_timeout`

---

## [2026.05.052] - 2026-05-30

**Souhrn:** Issue expiry per-kanál, telemetry agregace, SSH streaming, agent labels, Slack webhook, DB vacuum.

### Přidáno

- **Issue expiry per-kanál** (`025`): `issue_expiry_days` v config.yaml; active issues starší než N dní auto-resolved bez ohledu na agenta; per-channel granularita (infra/agent/security/root)
- **Telemetry aggregation** (`066`): `aggregate_telemetry(hours)` v state.py; raw záznamy starší než N hodin komprimovány do jednoho průměru per metric per hodinu; spouštěno v cleanup loop (03:00); konfigurovatelné `telemetry_aggregate_after_hours`
- **SSH output streaming** (`046`): `POST /api/ssh/stream` SSE endpoint; SSH modal zobrazuje výstup průběžně přes `fetch+ReadableStream` místo blokujícího čekání; safety + allowlist guard zůstává
- **Agent labels/metadata** (`038`): sloupec `labels` (JSON) v tabulce `agents`; `GET/POST /api/agents/<hostname>/labels`; UI v agent detail modalu — zobrazení, přidání, odebrání štítků; labels vráceny i v `/api/agents/<hostname>/detail`
- **Slack webhook** (`079`): sekce `slack:` v config.yaml; `_send_notification` odesílá do Slacku; `/api/integrations/slack/status`, toggle, test
- **DB vacuum** (`130`): potvrzen — existuje od v2026.05.048 (`daily_cleanup_loop`, neděle 03:00)

### Technické

- `state.aggregate_telemetry(raw_after_hours)`, `state.get_agent_labels()`, `state.set_agent_labels()`
- `config.ISSUE_EXPIRY_DAYS`, `config.TELEMETRY_AGGREGATE_AFTER_HOURS`, `config.SLACK_ENABLED/WEBHOOK_URL/CHANNEL`
- DB migrace: `ALTER TABLE agents ADD COLUMN labels TEXT DEFAULT '{}'`
- `config.yaml.example` rozšířen o `slack:`, `issue_expiry_days:`, `telemetry_aggregate_after_hours:`

---

## [2026.05.051] - 2026-05-30

**Souhrn:** Refaktoring architektury — `chat_service.py` (5994 ř.) rozdělen do Flask Blueprintů.

### Technické

- **Blueprint architektura**: `setup_routes()` nahrazena registrací 8 blueprintů; routy přesunuty do `sentinel/routes/` balíčku
- **`sentinel/auth.py`**: extrahována autentizační vrstva (`JsonFormatter`, `requires_auth`, `check_auth`, LDAP helper, session tracking, `_REVOKED_SESSIONS`)
- **`sentinel/routes/main.py`**: hlavní stránka, login/logout, SocketIO events
- **`sentinel/routes/issues.py`**: všechny `/api/issues/*`, snooze, suppress, bulk-ack, AI korelace
- **`sentinel/routes/agents.py`**: správa agentů, sentinel-hw, sentinel-alert, hailo-ollama, ingest
- **`sentinel/routes/actions.py`**: AI akce, allowed-commands, SSH execute
- **`sentinel/routes/system.py`**: sys info, config, patterns, RAG, session management, Prometheus metrics
- **`sentinel/routes/export.py`**: CSV/MD/HTML/SQL exporty
- **`sentinel/routes/integrations.py`**: Teams/HA/MQTT/Webhook integrace, inbound webhook
- **`sentinel/routes/chat.py`**: AI chat, SSE streaming, log analýza, file upload
- `chat_service.py` zkrácen z **5994 → 1840 řádků** (−69 %)
- 116 testů prošlo bez změny

---

## [2026.05.050] - 2026-05-30

**Souhrn:** Config validace, agent auto-registration, RAG hot-reload z UI, sparklines v topbar, favicon badge s počtem alertů.

### Přidáno

- **Config validace** (`091`): `_validate_config()` volaná po každém `load_config()`; detekuje neznámé klíče, výchozí heslo `CHANGE_ME`, neplatný port, neexistující cesty, špatné SLA/escalation rules; pouze WARNING log, ne fatální chyba
- **Agent auto-registration** (`036`): `auto_register_token` v config.yaml; agent pošle tento token → Sentinel ho automaticky zaregistruje a vygeneruje unikátní token; prázdné = vypnuto
- **RAG hot-reload z UI** (`058`): `POST /api/rag/reindex` spustí re-indexaci v background threadu; `GET /api/rag/status` vrátí stav; tlačítko "Re-index KB" v Settings modal s polling statusu každé 2s
- **Sparklines v topbar** (`069`): mini Canvas sparkline v Issues badge (12h trend počtu alertů); data z `health_snapshots`; aktualizace každých 5 minut
- **Favicon badge** (`006`): Canvas API dynamicky překresluje favicon — červené číslo s celkovým počtem alertů; title baru aktualizován na `(N) Sentinel Commander`; aktualizováno při každém `updateStatus()`

### Technické

- `_validate_config()` s `_KNOWN_KEYS` sada v config.py
- `AUTO_REGISTER_TOKEN` v config.py; auto-reg v ingest endpointu před `verify_agent_token`
- `_updateFaviconBadge(count)`, `_loadSparklineData()`, `_drawSparkline()` v script.js
- `reindexRag()` s async polling `GET /api/rag/status`

---

## [2026.05.049] - 2026-05-30

**Souhrn:** Session management, CSP hlavičky, bulk acknowledge, issue assignee, AI trend report.

### Přidáno

- **Session management** (`101`): tabulka `active_sessions`; sledování aktivních přihlášení (username, role, IP, user agent, last_seen); superadmin může revokovat libovolnou session; revokovані UUID v in-memory blacklistu; `prune_stale_sessions(24h)` v cleanup loop; odkaz v Settings modalu
- **CSP hlavičky** (`104`): `after_request` handler přidá `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` ke každé Flask response
- **Bulk acknowledge** (`024`): tlačítko "Potvrdit" v bulk action baru; `POST /api/issues/bulk_acknowledge`; potvrdí všechny vybrané issues naráz
- **Issue assignee** (`021`): sloupec `assigned_to` v problems; `POST /api/issues/<kb64>/assign`; `GET /api/users/list`; badge `@username` na kartě; kliknutím otevře picker uživatelů; `@—` pro rychlé přiřazení (admin+)
- **AI trend report** (`056`): `POST /api/analyze/trend_report?days=7`; LLM analyzuje top pluginy, hosté, SLA violations; tlačítko "AI Trend" v Tools modal; výsledek v changelog modal

### Technické

- `active_sessions` tabulka v DB; `session_register()`, `session_touch()`, `session_remove()`, `list_sessions()`, `revoke_session()`, `prune_stale_sessions()`
- `_REVOKED_SESSIONS` in-memory set; `_SESSION_TOUCH_TS` throttle dict (touch max 1×/min)
- Session UUID ukládán do Flask session jako `_suuid`; registrace při loginu, mazání při logout
- `assign_issue(key, username)` s idempotentní DB migrací `assigned_to` sloupce

---

## [2026.05.048] - 2026-05-30

**Souhrn:** Triage view, audit CSV, SSH history, AI korelace, Grafana export, maintenance notifikace, per-agent thresholds, self-monitor webhook, issue merge, týdenní digest. Fix: AI Souhrn zobrazuje výsledek přímo v modal okně.

### Přidáno

- **Issue triage view**: `GET /api/issues/triage` — urgency score = severity×3 + SLA ratio×2 + occurrence score; tlačítko "🔥 Triage" zobrazí seřazený panel přímo v issues modal
- **Audit trail CSV**: `GET /api/export/audit.csv` — action_audit + actions JOIN, admin+
- **SSH history per host**: `GET /api/agents/<hostname>/ssh_history`; zobrazeno v agent detail modalu (SSH History sekce)
- **AI korelace (root cause)**: `POST /api/analyze/correlate` — LLM grupuje issues dle příčiny; tlačítko "Korelace" vedle AI Souhrn
- **Grafana dashboard export**: `GET /api/export/grafana_dashboard.json` — Grafana JSON s panely pro Prometheus metriky Sentinelu
- **Maintenance notifikace**: při vstupu agenta do maintenance → notifikace přes HA/webhook/MQTT
- **Per-agent thresholds**: tabulka `agent_thresholds`; `GET/POST /api/agents/<hostname>/thresholds`, `DELETE /api/agents/thresholds/<id>`; UI v agent detail modalu (přidat/smazat)
- **Self-monitoring webhook**: `self_monitor.webhook_url` v config.yaml; Sentinel posílá vlastní health JSON každých N sekund
- **Issue merge**: `POST /api/issues/<kb64>/merge` — linked issue → `merged_into` + resolved; `merged_into` sloupec v problems tabulce
- **Týdenní digest**: `weekly_report.day/hour` v config.yaml; obsah: top recurring, SLA violations, offline agenti
- **Fix AI Souhrn**: výsledek se zobrazí přímo v issues modal jako barevný panel (ne v chatu)

### Technické

- `ssh_execute_log`, `agent_thresholds` tabulky; `merged_into` sloupec v problems
- `SELF_MONITOR_WEBHOOK`, `SELF_MONITOR_INTERVAL`, `WEEKLY_REPORT_DAY/HOUR` v config.py
- `state.log_ssh_execute()`, `get_ssh_history()`, `merge_issues()`, `get_triage_issues()`
- `state.set_agent_threshold()`, `get_agent_thresholds()`, `delete_agent_threshold()`
- `_run_self_monitor_webhook()`, `_send_weekly_report()` metody ChatService

---

## [2026.05.047] - 2026-05-30

**Souhrn:** Recurring detection, agent config push, telemetry alerts, dashboard layout, topology, changelog, pattern editor, InfluxDB, health history, SSH modal (admin+).

### Přidáno

- **Recurring issues**: issue s `occurrence_count >= 3` za 24h → automaticky tag `recurring` + bump severity na `high`
- **Agent config push**: `POST /api/agents/<hostname>/config` uloží JSON; při dalším ingestu vrácen v response jako `config_update`; tabulka `agent_config_queue`
- **Telemetry alerting rules**: `telemetry_alerts:` v config.yaml — pevné thresholdy (above/below) per fnmatch metriky; throttle 1h; vytváří TALERT issue
- **Dashboard widget layout**: `openDashLayout()` — toggle viditelnosti sys monitor sekcí; stav v localStorage; automaticky aplikován po každém refresh sys monitoru
- **Síťová mapa agentů** (topology): modal s kartami agentů seskupenými do skupin; barva = stav; data lag badge; klik → agent detail
- **Changelog**: `GET /api/changelog` — git log posledních 40 commitů; modal s ikonami dle typu (feat/fix/chore/docs)
- **Log Pattern Editor**: UI pro přidání custom regexů; regex tester; toggle/delete; tabulka `custom_patterns`; `GET/POST /api/patterns`, `DELETE/toggle /api/patterns/<id>`, `POST /api/patterns/test`
- **InfluxDB export**: `influxdb:` sekce v config.yaml; každý telemetrický snapshot zapisuje do InfluxDB line protocol přes HTTP (non-blocking thread)
- **Health Score Historie**: tabulka `health_snapshots` (hourly); `GET /api/health/history`; Chart.js graf score+issues v modal (kliknutím na score circle v sys monitor)
- **SSH modal (admin/superadmin only)**: `POST /api/ssh/execute` — host + command přes allowlist + safety classifier; modal otevíratelný z agent detail (tlačítko SSH); výstup v monospace poli
- **i18n**: nové klíče CS+EN pro všechny nové funkce

### Technické

- `agent_config_queue`, `health_snapshots`, `custom_patterns` tabulky v DB
- `TELEMETRY_ALERTS`, `INFLUXDB`, `SLA_RULES` v config.py
- `_write_influxdb()` non-blocking background thread
- `_save_health_snapshot()` voláno každou hodinu z cleanup loop
- SSH endpoint: role guard admin+, safety + allowlist check

---

## [2026.05.046] - 2026-05-30

**Souhrn:** Komentářové šablony, error logging do DB, SLA tracking, host heatmap, inbound webhook, plugin dependency graph, config diff.

### Přidáno

- **Komentářové šablony**: tabulka `comment_templates`; API `GET/POST /api/comments/templates`, `DELETE /api/comments/templates/<id>`; tlačítko "Šablona" v comment input → popup picker vyplní text
- **Sentinel error log**: Python `_DBErrorHandler` zachycuje ERROR/CRITICAL ze všech sentinel loggerů → tabulka `sentinel_errors`; `GET /api/system/errors`; odkaz "Chyby systému" v sys monitor (admin+); prune po 7 dnech
- **SLA tracking**: `sla_rules:` v config.yaml (channel → hours); badge na issue kartě — oranžový (≤25% zbývá), červený "SLA +Nh" (po vypršení)
- **Host heatmap**: `GET /api/alerts/host_heatmap?days=7`; barevná matice host × den s počty alertů; tlačítko Heatmap v Tools; výběr 7/14/30 dní
- **Inbound webhook**: `POST /api/inbound/webhook?token=X` — mapuje Grafana/Alertmanager/Zabbix JSON na `save_problem()`; klíče: host, plugin, message, severity, status; `inbound_webhook.token` v config.yaml
- **Plugin dependency graph**: `GET /api/plugins/graph` — nodes (log, plugin, channel) + edges; vizualizace v Tools modal jako třísloupkový layout
- **Config diff**: `GET /api/config/diff` — unified diff current config vs. example; barevné zobrazení v modalu; tlačítko v Tools
- **i18n**: nové klíče CS+EN pro templates, errors, heatmap, SLA, config diff

### Technické

- `comment_templates` a `sentinel_errors` tabulky v DB
- `SLA_RULES: dict`, `INBOUND_WEBHOOK_TOKEN: str` v config.py
- DB error handler: `_DBErrorHandler(logging.Handler)` registrován na `logging.getLogger('sentinel')`
- `state.get_host_heatmap()`, `get_comment_templates()`, `add_comment_template()`, `get_sentinel_errors()`, `prune_sentinel_errors()`

---

## [2026.05.045] - 2026-05-29

**Souhrn:** Issue workflow (acknowledged), SSH jump host, plugin hot-reload, telemetrie grafy v agent detail, escalation pravidla, logrotate, REST API klíče, issue timeline.

### Přidáno

- **Issue acknowledged stav**: žlutý border, badge `✓ POTVRZENO — uživatel`; tlačítko ✓✓ na kartě; API `POST /api/issues/<kb64>/acknowledge|unacknowledge`; zahrnut v `get_active_issues()`
- **SSH jump host (ProxyJump)**: `ssh_execution.jump_host` v config.yaml; SSH cmd rozšířen o `-J bastion` pokud nastaven
- **Plugin hot-reload**: `POST /api/plugins/reload` — znovu načte pluginy bez restartu; tlačítko v Settings modal (superadmin)
- **Telemetrie grafy v agent detail**: Chart.js sparklines pro top-4 metriky agenta (24h); zobrazeny v agent detail modalu
- **Escalation pravidla**: `escalation_rules:` v config.yaml; background loop (60s) zvyšuje severity issues starších než N hodin; notifikace přes HA/webhook/MQTT (bez Teams)
- **Logrotate**: `/etc/logrotate.d/sentinel` — daily, rotate 14, compress, copytruncate; install.sh to vytváří automaticky
- **REST API klíče**: tabulka `api_keys` (name, scope, hash, expiry); `POST /api/apikeys` vrátí raw token (jednou); DB ověření v `requires_auth`; management UI v Settings (superadmin); scope: read/write/admin → viewer/admin/superadmin
- **Issue timeline**: `GET /api/issues/<kb64>/timeline` — chronologická osa: komentáře + auto-remediace + action audit + acknowledge + tagy; zobrazena v comments modalu přes tlačítko "Timeline"
- **i18n**: nové klíče CS+EN pro acknowledge, escalation, API keys, timeline, plugin reload

### Technické

- `acknowledged_by` + `acknowledged_at` sloupce v `problems` tabulce
- `api_keys` tabulka s SHA-256 hashem tokenu
- `state.verify_api_key()`, `create_api_key()`, `list_api_keys()`, `delete_api_key()`
- `state.acknowledge_issue()`, `unacknowledge_issue()`
- `state.get_issue_timeline()` — UNION komentáře + auto-remediace + action audit + tagy

---

## [2026.05.044] - 2026-05-29

**Souhrn:** Issue prioritizace, auto-remediace service/mount selhání, issue tagging, tag cloud, agent detail modal, batch AI analýza, API dokumentace (OpenAPI/Swagger), action audit log UI, occurrence counter, agent data lag tracking, enhanced daily digest.

### Přidáno

- **Issue severity (priorita)**: sloupec `severity` (low/medium/high/critical) v `problems` tabulce; barevný badge na kartě (🔴🟠🟡⚪); popup picker kliknutím (admin+); API `POST /api/issues/<kb64>/severity`
- **Auto-remediace**: jednoráz. SSH oprava při novém selhání služby (`systemctl restart *.service`) nebo mount problému (`mount -a`); podmínka: příkaz musí být v `allowed_commands` s `auto_execute=1`; úspěch → stav `OVĚŘOVÁNÍ`; selhání → nové issue `AUTOFAIL|...` s badge `⚡ AUTO-OPRAVA SELHALA` a severity=critical
- **Výchozí allowed_commands**: seed při prázdné tabulce — `systemctl restart *.service`, `mount -a`, `df -h`, `systemctl status *.service` (auto_execute), + manuální příkazy pro schválení
- **Issue tagging**: tabulka `issue_tags`; API `GET/POST /api/issues/<kb64>/tags`, `DELETE /api/issues/tags/<id>`, `GET /api/issues/tags/all|counts`; tag pills na kartách; klik na tag filtruje; tag modal (přidat/smazat); `#tag` filtr v search baru
- **Auto-tag pravidla**: sekce `auto_tags:` v `config.yaml`; fnmatch glob na plugin/host/channel; tag přiřazen automaticky při novém issue
- **Tag cloud**: tlačítko 🏷 v issues toolbar → floating panel; velikost textu proporcionální počtu; klik filtruje issues
- **Agent detail modal**: klik na agenta otevře modal s info tabulkou (lag, verze, skupina, registrace), statistikami alertů 24h/7d/total, seznamem aktivních issues se severity barvami
- **Batch AI analýza**: tlačítko "AI Souhrn" v issues modal → `POST /api/analyze/active_issues`; max 50 issues → LLM souhrn s akcemi; výsledek v chat
- **OpenAPI/Swagger**: `GET /api/docs` (Swagger UI), `GET /api/openapi.json` — ~30 endpointů zdokumentováno se schématy
- **Action audit log UI**: tlačítko v Akce & AI Návrhy → modal s plným audit logem; fulltextový filter; barevné event badges; API `GET /api/actions/audit_log`
- **Occurrence counter**: sloupec `occurrence_count` v `problems`; badge `×N` na kartě + "od DD.MM HH:MM" datum prvního výskytu
- **Agent data lag**: sloupec `last_data_lag_ms`; ingest počítá rozdíl `ingest_time − data_timestamp` z payloadu; zobrazeno v Agent Health (zelená/oranžová/žlutá dle zpoždění)
- **Agent version v health řádku**: SHA verze v podtitulku agenta v health dashboardu
- **Enhanced daily digest**: top 5 pluginů, top 5 hostů, jmenovitý seznam offline agentů
- **Agent self-check API**: `GET /api/agents/<hostname>/issues`, `GET /api/agents/<hostname>/telemetry`
- **i18n**: nové klíče pro severity, auto-remediaci, tagy, batch AI, agent detail (CS + EN)

---

## [2026.05.043] - 2026-05-29

**Souhrn:** Výkon DB, UX vylepšení, anomaly detection, backup, rozšířená konfigurace.

### Přidáno

- **plugin_name / host / last_line jako sloupce**: migrace `problems` tabulky, backfill, indexy — odstraněn pomalý `json_extract`
- **Maint windows UX**: klikatelné dny týdne (Po–Ne) místo číselného textpole; čitelné zobrazení v seznamu
- **Bulk maintenance skupiny**: tlačítka 30m / 2h / ✕ v group header Agent Health; API `POST /api/agents/group/<group>/maintenance`
- **Resolve notifikace pro security**: při `ok`/`resolved` statusu i auto-reconcile — odešle `✅ VYŘEŠENO` přes Teams/HA/webhook
- **Telemetry anomaly detection**: `save_telemetry_snapshot()` detekuje spike >3σ od 24h průměru (min 30 vzorků, throttle 1h) → issue `TELEMETRY_ANOMALY`
- **DB backup**: `GET /api/export/db_backup` — SQL dump přes `sqlite3.backup()`, odkaz v sys monitor (superadmin)
- **SSH konfigurace**: sekce `ssh_execution:` v `config.yaml` — `key_path`, `user` s fallbackem na defaults
- **Denní report čas**: `analytics.daily_report_hour` v `config.yaml` (default 8)

---

## [2026.05.042] - 2026-05-29

**Souhrn:** Nové funkce — telemetry CSV, HA thresholds, alert suppression rules, agent version tracking, WebSocket reconnect.

### Přidáno

- **Telemetry CSV export**: `GET /api/export/telemetry.csv?days=7&category=HomeAssistant&metric=` — odkaz v status table vedle incidents CSV
- **HA sensor thresholdy konfigurovatelné**: sekce `ha_thresholds:` v `config.yaml` — battery, disk/server/RPi teploty, napětí, proud, 3D tisk; fallback na původní hardcoded hodnoty
- **Alert suppression rules**: tabulka `suppress_rules` (host_pattern glob + plugin_pattern glob) — filtruje `get_active_issues()`; UI tab "Suprese" v Tools modalu (admin/superadmin); API `GET/POST/DELETE /api/suppress/rules`
- **Agent version tracking**: sloupec `agent_version` v `agents` tabulce; ingest zachytí SHA z top-level `version`/`agent_sha` fieldu nebo z eventu `agent_core_updater`; zobrazeno v agent detail modalu
- **WebSocket reconnection**: explicitní `io()` konfigurace (15 pokusů, backoff 1–15 s); badge zobrazuje "Reconnecting N/15…"; `reconnect_failed` → výzva k reloadu; po reconnectu: `updateStatus()` + restart live tail SSE

### Opraveno

- **KeyError `'ingest'`**: `request_history` byl `defaultdict` s pevnými klíči `{chat, upload}` — přístup na `'ingest'` padil celý ingest endpoint → všichni agenti offline; opraveno na `defaultdict(deque)`
- **sentinel-ai-vision "Invalid hostname"**: `/api/sentinel-hw/<hostname>/live` odmítal hostname bez prefixu `sentinel-hw-`; opraveno na DB lookup `category='hw'`

---

## [2026.05.041] - 2026-05-29

**Souhrn:** Bezpečnostní fix SSH klíče + opravy UI chyb.

### Opraveno

- **#9 SSH akce — klíč a uživatel**: `actions.py` nyní používá `-i /opt/Sentinel/conf/.id_ed25519 -l root`; klíč odebrán z git trackingu, `conf/` přidáno do `.gitignore`
- **#1 Modal skupiny pluginů**: `<details>` skupiny si pamatují open stav při 3s auto-refreshi modalu
- **#2 RAG badge**: ukazuje `Vector` / `Text` bez zbytečného prefixu `RAG:`
- **#3 AI latence**: latence se zapisuje i při `GeneratorExit` (přerušený SSE stream)
- **#4 Integration modal**: tlačítka Toggle/Test mají flex layout a stejnou šířku
- **#5 Verze**: opravena na `2026.05.041` v `config.py`
- **#6 Historie issues**: UNION s `problems` tabulkou → zobrazuje i aktivní issues s badge AKTIVNÍ/VYŘEŠEN
- **#7 Animace AI**: `analyzeFile` / `analyzeGroup` zobrazují thinking bubble při čekání
- **#8 Action tlačítka**: uniformní 32×32px flex layout v pending actions tabulce

---

## [2026.05.040] - 2026-05-29

**Souhrn:** Oprava 21 chyb z chyby.md + nové funkce (notifikace, Prometheus, sparklines, KB upload).

### Opraveno

- **#1 Modal filter/bulk výběr**: chyběly `data-issue-card` atributy v `generate_modal_issues_html()` — filter, checkboxy a bulk operace nyní fungují; přidán okamžitý refresh po smazání/ignorování
- **#5 Agent Health — datum registrace**: backfill `registered_at` z `last_seen` pro starší agenty; ON CONFLICT v `register_new_agent()` zachovává původní datum místo přepsání
- **#7 Root audit — garbage IP**: smazáno 344 záznamů (timestamps jako `16`, `12`; tmux sessions); server-side regex zpřísněn na IPv4/hostname
- **#8 Predikce — výběr senzorů**: toggle skrytí senzoru (👁 ikona), uložení v `kv_settings`, reset; sekce "skryté senzory"
- **#9 "Spolupracovníci"**: opraven překlad tabu `other_collaborator_tab`
- **#13 Root audit — špatný formát**: server-side IP regex preferuje IPv4, odmítá timestampy (12:01 → "Neznámá IP")
- **#14 Kopírování — Browser restriction**: přidána `safeCopyText()` s `execCommand` fallbackem a modal pro ruční kopírování
- **#18 Autofix**: opraven system/user prompt (bez ukázkového JSONu v user zprávě); post-processing odmítá placeholder text
- **#21 Více IP adres**: `ip_addresses` JSON sloupec v agents tabulce, ukládáno při každém ingestu, zobrazeno v detail modalu

### Přidáno

- **#4 Alert timeline redesign**: heatmap přetočena (řádky = dny, sloupce = hodiny); KB tab přepracován s drag&drop uploadem souborů, listingem a mazáním
- **Automatické notifikace** (`_send_notification()`): při novém security/root/clusters alertu odešle přes Teams/webhook/HA; throttling 1x/hod na klíč
- **Prometheus `/metrics` endpoint**: sentinel_info, active_issues, agent_online, telemetry gauges; auth přes scrape_token nebo session
- **Dashboard temperature sparklines**: top-6 hostů dle teploty, SVG sparkline grafy bez Chart.js
- **KB upload/listing/delete API**: `POST /api/kb/upload`, `GET /api/kb/files`, `POST /api/kb/delete`
- **DB VACUUM**: jednorázový (22→16 MB) + týdenní automatický ve watchdogu

### Technická oprava

- `request.json` → `request.get_json(silent=True) or {}` na 5 endpointech (ochrana před 500 při non-JSON body)

---

## [2026.05.034] - 2026-05-27

**Souhrn:** Oprava watchdog chyby — agent s timezone-naive `last_seen` způsoboval error každou minutu.

### Opraveno

- **Watchdog datetime crash** (`state.py`): `sentinel-hw-rpizero2` měl uložený `last_seen` bez timezone info; porovnání s `datetime.now(timezone.utc)` házelo `can't subtract offset-naive and offset-aware datetimes` každou minutu; opraveno přidáním `replace(tzinfo=timezone.utc)` pro naive datetime po parsování

---

## [2026.05.033] - 2026-05-27

**Souhrn:** Oprava chatu — odpověď přepsána chybou po dokončení streamu; přidán `hailo_done` flag a `reader.cancel()` po přijetí `done`.

### Opraveno

- **Chat "přepsání odpovědi chybou"** (`chat_service.py`, `script.js`): po úspěšném streamu hailo-ollama přišel `done:true`, JS finalizoval odpověď, ale pak `reader.read()` zavolal znovu a zachytil exception při uzavření spojení → catch blok přepsal celou odpověď textem „Chyba komunikace"; opraveno dvojitě: (1) JS po `ev.done` okamžitě volá `reader.cancel()` a vrátí se, (2) server nastaví `hailo_done=True` a při exception po dokončení ignoruje chybu bez spuštění CPU fallbacku

---

## [2026.05.032] - 2026-05-27

**Souhrn:** Oprava chatu — hailo-ollama `/v1/chat/completions` odmítá `stream:true`; přepnuto na `/api/chat` s nativním Ollama formátem.

### Opraveno

- **Chat "communication error"** (`chat_service.py`): streaming chat posílal `stream:true` na `/v1/chat/completions` — hailo-ollama vrátil 400 `"streaming not supported on this endpoint"`; opraveno přepnutím na `/api/chat` (odvozeno z URL) s nativním Ollama wire formátem (`message.content` místo `choices[0].delta.content`, `done:true` jako stop signál); fallback na CPU ollama při chybě NPU zachován

---

## [2026.05.031] - 2026-05-27

**Souhrn:** Agent detail panel — metadata, issue statistiky, poznámky a regenerace tokenu přímo z UI.

### Přidáno

- **`/api/agents/<hostname>/detail`** (`chat_service.py`): vrací metadata agenta (status, last_seen, registered_at), počet aktivních issues, počet resolved issues za 7 dní, posledních 10 issues
- **`/api/agents/<hostname>/notes`** (`chat_service.py`): uloží poznámku do `agents.notes` sloupce (admin+)
- **`/api/agents/<hostname>/regenerate-token`** (`chat_service.py`): vygeneruje nový token a zapíše do DB; vrátí nový token pro zobrazení v token modalu (superadmin only)
- **Agent detail modal** (`script.js`): kliknutí na agenta nyní zobrazí: status badge, last_seen, registered_at, počet issues, resolved za 7 dní; posledních 10 aktivních issues; editovatelná poznámka; tlačítko Regenerovat token (superadmin)

---

## [2026.05.030] - 2026-05-27

**Souhrn:** Tlačítko „Test" v integračním modalu — ověření funkčnosti Teams, HA, MQTT, Webhook bez čekání na reálný alert.

### Přidáno

- **Test notifikace** (`chat_service.py`, `script.js`): každý integrační modal (Teams, Home Assistant, MQTT, Webhook) nyní obsahuje tlačítko **Test** vedle Toggle; endpoint `/api/integrations/<name>/test` odešle testovací zprávu přímo (bypasses `ENABLED` flag) a vrátí výsledek; výstup se zobrazí pod tlačítkem (✅ OK nebo ❌ chyba)

---

## [2026.05.029] - 2026-05-27

**Souhrn:** Confirm modal pro spuštění akcí — místo `confirm()` se zobrazí plný modal s příkazem, serverem a risk skóre; skutečná SSH exekuce (ne dry run).

### Změněno

- **Confirm execute modal** (`index.html`, `script.js`): kliknutí na ▶ v panelu Akcí & AI Návrhů otevře modální okno zobrazující příkaz, node, cluster, risk badge, důvod a varování o nevratnosti akce; tlačítko **Spustit** provede akci, výstup SSH se zobrazí přímo v modalu; `_actionCache` zásobuje modal daty bez dalšího fetch
- **Skutečná exekuce** (`chat_service.py`, `state.py`): endpoint `/api/v1/actions/<id>/execute` nyní před voláním SSH nastaví mode=`approved` (`state.approve_action_mode()`), čímž zruší dry_run guard v `run_ssh_command_real` — akce se skutečně provede přes SSH

---

## [2026.05.028] - 2026-05-27

**Souhrn:** Kompletní přepis `hailo_models.py` — Unicode TUI, htop-style HW bary, TPS srovnávací graf, NPU statistiky, disk usage.

### Změněno

- **`hailo_models.py` — TUI rewrite** (440 → 619 řádků):
  - **Unicode box drawing** (`┌─┐│└┘`) v `box()` pro modální okna stahování/mazání
  - **`draw_header()`**: htop-style CPU/RAM progressbary s `█`/`░` znaky, síťový RX/TX (MB/s), NPU arch + FW verze (`hailortcli fw-control identify`), hailo-ollama service status (●ONLINE/●OFFLINE), počet stažených modelů, disk usage (GB), uptime systému
  - **`draw_detail()`**: TPS bar chart relativní vůči max TPS celé databáze, typ/zaměření/vydání/kontext, česky popsaný detail modelu
  - **`draw_compare()`** — nový pohled přepínaný klávesou `[S]`: všechny modely seřazené od nejrychlejšího, ASCII bar graf výkonu vedle každého modelu, ● = staženo, legenda
  - **`TYPE_COLORS`**: barevné mapování podle kategorie modelu (LLM=cyan, Coder=green, Logic=yellow, Instruct/Agent=magenta, Vision=blue, Audio=bright)
  - **`MODEL_DB`**: pole `tps` změněno z string na float, přidáno `size_gb` (float) pro programatický výpočet
  - **`disk_usage_mb()`**: nová helper funkce pro součet velikosti souborů v `MODELS_DIR`
  - **`htop_bar()` / `bar()`**: extrahované pomocné funkce pro konzistentní kreslení progress barů
  - **Scroll indikátor** `▐` pro dlouhé seznamy modelů
  - **`argparse`** s `--url` a `--models-dir`, `get_hailo_info()` a `_hailo_svc_cache` zachovány
  - Veškerý text v češtině s diakritikou

---

## [2026.05.027] - 2026-05-27

**Souhrn:** Nasazení sentinel-agentů na všechny hosty, oprava konfigurace, výluky HW zařízení z panelu klientů.

### Přidáno

- **Masové nasazení agentů** (`pct exec/push`): sentinel-agent nainstalován na 16 LXC kontejnerů (pihole, komga, audiobookshelf, uptimekuma, mariadb, navidrome, octoprint, spoolman, lldap, proxmox-backup-server, gitea, jellyfin, motioneye, downloader, minecraft, nextcloud); každý s vlastním tokenem a konfigurací odpovídající službám a mountům
- **`excluded_client_ips`** (`config.py`, `chat_service.py`): konfigurovatelný seznam IP adres hardwarových zařízení, která se nemají zobrazovat v panelu připojených klientů; výchozí 192.168.2.110 (sentinel-hw rpizero2)
- **`IGNORED_FAILED_SERVICES`** (`config.py`): konfigurovatelný seznam services ignorovaných při detekci i auto-remediaci (výchozí: motd-news.service, apt-news.service)
- **Auto-resolve `PORTS|*` issues**: port_detector nyní resolví PORTS alert, jakmile se port list stabilizuje (předtím donekonečna refreshoval `last_seen`)
- **Reconciliation `SERVICE_FAILED|*` issues**: services_detector na konci každého scanu resolví service issues, které nejsou v aktuálním logu

### Opraveno

- **Agent config — root_login_ignore_ips**: přidáno 192.168.2.115 na všechny hosty (rpi5, rpi, docs, proxy, server, semaphore)
- **Server mounts config**: oprava formátu mountů (list stringů → list objektů s `path:` a `severity:`)
- **Modal integrace**: toggle po přepnutí refreshuje obsah modalu (status tečka a popis se okamžitě aktualizuje)

---

## [2026.05.026] - 2026-05-26

**Souhrn:** Oprava toggleu integrací (Teams, HA, MQTT, Webhook) na read-only filesystému a oprava zobrazení stavu po přepnutí.

### Opraveno

- **Integration toggle errno 30** (`chat_service.py`, `state.py`, `config.py`): endpoint `/api/integrations/<name>/toggle` se pokoušel zapisovat do `/etc/sentinel/config.yaml` na read-only FS; přepnut na in-memory přepínání (`setattr(config, ...)`) s persistencí do SQLite (`kv_settings` tabulka); `_apply_db_overrides()` obnoví stav při restartu
- **Status po toggleu neaktuální** (`script.js`): modal integrace po přepnutí neukazoval nový stav (tečka a popis zůstaly staré); `toggleIntegration()` nyní po úspěchu volá `openIntegrationModal()` pro refresh obsahu

---

## [2026.05.025] - 2026-05-26

**Souhrn:** Auto-resolve issues — issues se automaticky resolví, pokud je agent přestane hlásit. Dvě vrstvy: ingest reconciliation (rychlá, po 3 chybějících reportech) a time-based záchranná síť (ONLINE agent bez update déle než N hodin).

### Přidáno

- **`reconcile_agent_issues(hostname, reported_keys)`** (`state.py`): po každém ingestu porovná aktivní issues v DB s tím, co agent aktuálně hlásí; issue chybějící v N po sobě jdoucích reportech (`AUTO_RESOLVE_MISSING_COUNT`, default 3) je automaticky resolved
- **Time-based auto-resolve** (`state.py`, `auto_resolve_old_problems`): aktivní issues z ONLINE agentů, které nebyly aktualizovány déle než `AUTO_RESOLVE_HOURS` hodin (default 4), jsou automaticky resolved — záchytná síť pro pluginy, které nevysílají explicitní OK status
- **`AUTO_RESOLVE_HOURS`** a **`AUTO_RESOLVE_MISSING_COUNT`** (`config.py`): konfigurovatelné přes `config.yaml` (`auto_resolve_hours`, `auto_resolve_missing_count`)
- **SocketIO `issue_resolved`** (`chat_service.py`, `script.js`): server emituje event při auto-resolve; frontend okamžitě aktualizuje UI

---

## [2026.05.024] - 2026-05-26

**Souhrn:** Oprava sentinel-hw proxy (session-based auth) a odstraněn dead-code duplikátních standalone modálů.

### Opraveno

- **sentinel-hw proxy `/api/sentinel-hw/<hostname>/live`** (`chat_service.py`): zařízení (RPi Zero 2) používá Flask session auth, ne Bearer token; přidána `_hw_get_session()` — přihlásí se přes `/login` (zkouší config credentials, fallback `admin/sentinel`), cachuje session v `_hw_sessions`, při expiraci se automaticky znovu přihlásí
- **Prázdné tools panely — agent health, alert timeline, plugin statistiky** (`index.html`): odstraněny 4 staré standalone modály s duplicitními HTML ID (`#maint-modal`, `#agent-health-modal`, `#timeline-modal`, `#plugin-stats-modal`); `getElementById` vracel první (skrytý) element místo tools pane — dead code způsoboval prázdné panely

---

## [2026.05.023] - 2026-05-26

**Souhrn:** Opravy prázdných dashboardů, špatného počtu agentů, RAG modalu a bugu s připojenými klienty. Audit instalace.

### Opraveno

- **`state.py` — špatný název sloupce** (`created_at` → `last_seen`): `get_agent_health()`, `get_alert_timeline()`, `get_plugin_stats()` používaly neexistující sloupec `created_at`; nahrazeno `last_seen`
- **`state.py` — plugin_name sloupec neexistuje**: `plugin_name` je uložen v JSON poli `details`; opraveno na `json_extract(details, '$.plugin_name')` v SQL a `json.loads(details)['plugin_name']` v Pythonu
- **Počet agentů (10/11 → 9/8)**: badge JS, `api_dashboard` a `get_detailed_metrics()` nově filtrují `sentinel-hw-*` a `sentinel-alert` z počtu agentů — jsou to satelitní uzly, ne standardní agenti
- **RAG modal — "unknown"**: `api_rag_info` volal špatné klíče; přepsáno na `rag.rag_system.get_metrics()` s klíči `rag_model`, `rag_db_items`, `rag_chunks_loaded`
- **Připojení klienti — sentinel-hw jako "admin"**: `requires_auth` decorator trackoval všechny autentizované požadavky; přidán skip pro agent paths (`/api/v1/`, `/api/sentinel-hw/`, `/api/sentinel-alert`)
- **Connection modal — AI sekce odstraněna**: zobrazuje pouze server a integrace; AI engine sekce odebrána
- **Maintenance windows redesign**: flex layout s labely, zaoblené rohy
- **Integration modal** (`script.js`, `i18n.js`): async fetch stavu, tabulka detailů, toggle pro admin/superadmin

### Přidáno

- **`/api/integrations/<name>/status`** (`chat_service.py`): endpoint vrací stav konkrétní integrace s citlivými daty filtrovanými (tokeny zkráceny, hesla skryta)
- **7 nových testů** (`tests/test_improvements.py`): MQTT pole, HA token nezveřejněn, Teams bez webhook URLs, webhook URL zkrácena, webhook secret skryt, struktura connection status

---

## [2026.05.022] - 2026-05-26

**Souhrn:** Integration modal s detaily spojení a novým endpoint `/api/integrations/<name>/status`.

### Přidáno

- **Integration Status endpoint** (`chat_service.py`): `GET /api/integrations/<name>/status` vrací podrobný stav každé integrace (mqtt/ha/teams/webhook/rag/ai) s filtrovanými citlivými hodnotami
- **Integration modal redesign** (`script.js`, `i18n.js`, `index.html`): klik na integraci otevírá modal s tabulkou detailů a togglem; šířka 500px; admin/superadmin vidí přepínač

---

## [2026.05.021] - 2026-05-26

**Souhrn:** Connection status modal, viewer/operator role enforcement v pending actions, operator bez delete/ignore, theme persistence bez flickeru, regenerace tokenů pro sentinel-alert agenty.

### Přidáno

- **Connection Status modal** (`chat_service.py`, `script.js`, `index.html`): klik na online badge v záhlaví otevře modal s přehledem — hostname, port, verze, uptime, WS klienti, velikost DB, AI backend/URL/model/statistiky, stav integrací (MQTT host:port, HA URL, Teams)
- **Backend proxy `/api/connection/status`**: agreguje data ze serverové konfigurace a metrik, bezpečně je zpřístupní frontendu

### Opraveno

- **Viewer/operator — pending actions modal** (`script.js`): tlačítka Execute/Edit/Re-analyze/Review/Delete jsou skryta pro `window.currentRole === 'viewer'`
- **Operator role — delete/ignore záznamy** (`chat_service.py`): ignore a delete ikony v issues HTML renderovány pouze pro `admin`/`superadmin`; operator a viewer je nevidí (dříve operator mohl ignorovat)
- **Theme persistence bez flickeru** (`index.html`, `script.js`): `toggleTheme()` ukládá volbu do `localStorage`; inline `<script>` v `<head>` aplikuje třídu před prvním vykreslením — žádné bliknutí bílé při načtení
- **Regenerace tokenu sentinel-alert agentů** (`chat_service.py`, `script.js`): revoke-token nyní generuje nový token (ne NULL) a vrací ho; `revokeTokenSA()` zobrazuje nový token přes `showTokenModal()`
- **Verze** povýšena na `2026.05.021`

---

## [2026.05.020] - 2026-05-26

**Souhrn:** Opravy Sentinel Satellites — badge počítá HW i Alert uzly, proxy pro live data senzorů, kopírovatelný token při registraci HW, regenerace tokenu při revoke, plný překlad HISTORY.md do češtiny.

### Opraveno

- **Badge Sentinel Satellites** (`script.js`): `updateSentinelAlertBadge()` nyní fetchuje zároveň `/api/sentinel-alerts/list` i `/api/sentinel-hw/list` a zobrazuje součet obou typů uzlů; barva odznáčku odráží online/offline stav celé skupiny
- **Live data senzorů HW zařízení** (`chat_service.py`, `script.js`): přidán backend proxy endpoint `GET /api/sentinel-hw/<hostname>/live` — server stahuje `/api/live` z `web_ui_url` zařízení a vrací data klientovi; odstraněn přímý fetch z browseru (CORS/síťové problémy)
- **Token při registraci HW zařízení** (`script.js`): `registerNewSentinelHW()` nyní zobrazuje token přes `showTokenModal()` místo `alert()` — token je kopírovatelný, zobrazí se jen jednou
- **Regenerace tokenu při revoke** (`chat_service.py`, `script.js`): `POST /api/sentinel-hw/<hostname>/revoke-token` nyní generuje nový token (místo NULL) a vrací ho; `revokeHWToken()` zobrazuje nový token přes `showTokenModal()`

### Přidáno

- **Celá HISTORY.md přeložena do češtiny**: záznamy .001–.016 (dříve anglicky) přeloženy; celý soubor je nyní v češtině
- **Verze** povýšena na `2026.05.020`

---

## [2026.05.019] - 2026-05-26

**Souhrn:** Velký UI refaktoring — unifikovaný modal Monitoring & Nástroje, standalone modaly pro sys info/ignorované/RAG/frontu/historii/role/integrace, animace „přemýšlení" v chatu, přístupová práva (viewer/operator/admin/superadmin), auto-mazání starých záznamů, kopírovatelný token agenta po registraci, limit 2048 tokenů pro analýzu souborů.

### Přidáno

- **Unifikovaný modal „Monitoring & Nástroje"** (`index.html`, `script.js`): Agent Health, Alert Timeline, Plugin Statistiky, Maintenance Windows a KB Reindex jsou nyní v jednom tabbed modalu; rychlé menu uklidněno — jedna položka místo pěti
- **Report modal vylepšen**: tlačítka Export Markdown a Export CSV přesunuta přímo do footeru Report modalu; odstraněna ze seznamu rychlých akcí
- **Sys Info modal** (`/api/sys_info`): klik na „Info o serveru" otevírá standalone modal místo výpisu do chatu
- **Ignored modal** (`/api/ignored`, `/api/ignored/<key_b64>`): seznam ignorovaných záznamů ve vlastním modalu s tlačítkem „Sledovat"; odebrání přes REST DELETE
- **RAG Info modal** (`/api/rag/info`): klik na RAG odznáček v hlavičce otevírá modal se stavem znalostní báze (status, docs, chunks, provider, model, cesty)
- **Queue Details modal** (`/api/queue/details`): klik na fronta-odznáček otevírá modal s detaily fronty (pending, workers, latence, celkem požadavků)
- **History modal** (`/api/history`): klik na číslo verze vedle loga otevírá modal s renderovaným HISTORY.md
- **Role modal** (`/api/users/roles` GET/POST/DELETE): klik na role-odznak otevírá správu rolí; superadmin může přidávat/měnit/mazat role; ostatní role vidí info o kontaktu admina
- **Integration Toggle modal** (`/api/integrations/<name>/toggle`): klik na odznáčky Teams / Home Assistant / MQTT otevírá modal s přepínačem online/offline; změna se zapíše do `config.yaml` a ihned načte
- **Token modal** po registraci agenta: po úspěšné registraci se zobrazí dedikovaný modal s tokenem + tlačítko Kopírovat (clipboard API + fallback); token se zobrazí jen jednou
- **Animace „přemýšlení"** v chatu: po odeslání dotazu se zobrazí Sentinel ikona s animovanými tečkami; nahrazena odpovědí AI
- **Přístupové role** (`state.py`, `chat_service.py`): tabulka `user_roles` v DB; `check_auth()` kontroluje DB override před výchozí rolí; `_role_for_user()` helper; LDAP větev rozlišuje viewer/operator/admin/superadmin; `get_all_user_roles()`, `set_user_role()`, `delete_user_role()`
- **Auto-mazání starých problémů** (`state.auto_resolve_old_problems(days)`): volá se každých 60s z cleanup loopu; maže záznamy starší N dní (status != active/validating) a záznamy s missing_count > 50

### Změněno

- **Delete/ignore/unignore** příkazy vrací `{"silent": true}` → žádný výpis do chatu, jen tichý refresh UI
- **Limit souboru pro AI analýzu**: obsah souboru zkrácen na 8 192 znaků (~2 048 tokenů) před odesláním do LLM; platí pro chat i `analyze_single_file`
- **Welcome message** v chatu: odstraněna sekce „Dostupné příkazy"; čistý minimalistický pozdrav
- **CSS**: přidány styly `.tools-tab` (záložky tabbed modalu) a `.thinking-bubble` (animace přemýšlení)
- **i18n**: přidáno ~40 nových klíčů v cs+en pro všechny nové modaly a funkce
- **Verze** povýšena na `2026.05.019`

---

## [2026.05.018] - 2026-05-26

**Summary:** Dashboard overview modal — mission control pohled s grafy, statistikami a přehledem systému.

### Added

- **Dashboard modal** (`sentinel/state.py`, `sentinel/chat_service.py`, `sentinel/static/script.js`, `sentinel/templates/index.html`):
  - `GET /api/dashboard` — aggreguje data z aktivních issues, agentů, AI metrik, plugin statistik, nedávných alertů; odpovídá v jednom JSON objektu
  - `state.get_recent_issues(limit)` — posledních N aktivních issues řazeno dle `last_seen`
  - `state.get_queue_depth()` — počet pending položek v `task_queue`
  - **Stat cards** (6): Aktivní alerty, Odloženo, Agenti, Čekající akce, AI latence, Uptime
  - **System mini-bars**: CPU/RAM/Disk s barevnými progress bary (zelená/žlutá/červená dle zátěže)
  - **7-day trend bar chart** (Chart.js stacked, data z `/api/alerts/timeline`) + **Channel donut chart**
  - **Top 5 aktivních pluginů** (dnes / celkem) + **Recent 6 issues** feed s channel badges
  - Refresh tlačítko; `Promise.all` pro paralelní fetch dashboard + timeline dat
  - i18n: 21 nových klíčů v cs+en

---

## [2026.05.017] - 2026-05-26

**Summary:** Issue comments — přidat textové poznámky k alertům přímo v UI.

### Added

- **Issue comments** (`sentinel/state.py`, `sentinel/chat_service.py`, `sentinel/static/script.js`, `sentinel/templates/index.html`):
  - `issue_comments` DB tabulka: `id, problem_key, author, text, created_at` (indexováno na `problem_key`)
  - `GET /api/issues/<key_b64>/comments` — seznam komentářů k danému alertu
  - `POST /api/issues/<key_b64>/comments` — přidat komentář (author = přihlášený uživatel, max 2000 znaků)
  - `DELETE /api/issues/comments/<id>` — smazat komentář (admin+)
  - `GET /api/issues/comment_counts` — mapa `{key_b64: count}` pro badge aktualizaci
  - Ikonka komentáře (`fa-comment-dots`) na každé issue kartě — kliknutím se otevře modal s vláknem
  - Po přidání komentáře se ikonka změní na plnou s čítačem; `loadCommentCounts()` se volá po každém refreshi issues modalu
  - Klávesová zkratka: `Ctrl+Enter` odesílá komentář
  - i18n: 8 nových klíčů v cs+en

---

## [2026.05.016] - 2026-05-26

**Souhrn:** Heatmapa časové osy alertů, přehled zdraví agentů, maintenance windows (automatický plánovač snooze), vylepšení auditu root přístupů, statistiky pluginů a živý log tail.

### Přidáno

- **Alert Timeline / Heatmapa** (`sentinel/state.py`, `sentinel/chat_service.py`, `sentinel/static/script.js`): `GET /api/alerts/timeline?days=N` (max 30) vrací hodinová data heatmapy a denní počty dle kanálu. Modal zobrazuje barevnou heatmapu 24×N dní (zelená→oranžová→červená dle intenzity) a skládaný denní sloupcový graf (Chart.js). Souhrnné statistiky: celkem alertů, nejaktivnější den, nejaktivnější hodina. Přepínání zobrazení 7/14/30 dní.
- **Přehled zdraví agentů** (`sentinel/state.py`, `sentinel/chat_service.py`): `GET /api/agents/health` vrací všechny registrované agenty obohacené o počty alertů na agenta (24h/7d/celkem) a čas posledního alertu. Modal zobrazuje kartu pro každého agenta s indikátorem online/offline, relativním časem posledního výskytu a čítači alertů.
- **Maintenance Windows / Snooze Scheduler** (`sentinel/state.py`, `sentinel/chat_service.py`): DB tabulka `snooze_rules` (name, channels, start/end hour, days, enabled). `state.apply_snooze_rules()` volána každých 60s z `daily_cleanup_loop` — automaticky odkládá odpovídající aktivní záznamy do konce okna. CRUD API: `GET/POST /api/snooze/rules`, `DELETE /api/snooze/rules/<id>`, `POST /api/snooze/rules/<id>/toggle`. UI modal s formulářem pro přidání a seznamem pravidel se zobrazením aktivního okna.
- **Vylepšení Root Auditu** (`sentinel/static/script.js`, `sentinel/templates/index.html`): Sloupec Trvání (Xh Ym Zs), statistický řádek (aktivní/celkem), filtrační checkbox pouze aktivní, export CSV na straně klienta. Opraveno pevně zakódované "AKTIVNÍ" → `t('root_active_badge')`.

### Změněno

- **Verze** povýšena na `2026.05.016`.

---

## [2026.05.015] - 2026-05-26

**Souhrn:** Modal statistik pluginů, živý log tail (SSE streaming), dokončení i18n (všechny řetězce UI se nyní správně překládají v CS i EN).

### Přidáno

- **Modal statistik pluginů** (`sentinel/chat_service.py`, `sentinel/state.py`, `sentinel/static/script.js`, `sentinel/templates/index.html`): `GET /api/plugins/stats` vrací počty alertů na plugin seskupené dle `plugin_name` z tabulky `problems` — dnes, posledních 7 dní, celkem a čas posledního výskytu. Přístupné přes tlačítko "Plugin Statistiky" v postranním panelu rychlých akcí. Tabulka zvýrazní pluginy s dnešními detekcemi červeně.
- **Živý Log Tail (SSE)** (`sentinel/chat_service.py`, `sentinel/static/script.js`, `sentinel/templates/index.html`): SSE endpoint `GET /api/logs/tail/<filename>` streamuje posledních 50 řádků log souboru při připojení, poté každou sekundu polluje nový obsah. Automaticky se znovu připojuje při výpadku. Každý soubor v LOG Vieweru nyní zobrazuje ikonu satelitní antény otevírající dedikovaný live-tail modal s přepínačem automatického scrollování a tlačítkem smazat. Validace cesty přes `_safe_log_path()`.
- **i18n klíče pro nové funkce** (`sentinel/static/i18n.js`): `plugin_stats`, `plugin_col`, `today_col`, `week_col`, `total_col`, `last_seen_col`; `live_tail`, `live_tail_btn`, `live_tail_connecting`, `live_tail_connected`, `live_tail_live`, `live_tail_reconnecting`, `live_tail_autoscroll` — v obou jazycích `cs` a `en`.

### Změněno

- **Seznam souborů LOG Vieweru** (`sentinel/static/script.js`): Každá položka souboru nyní má tlačítko ikony živého tailu vedle oblasti kliknutí pro zobrazení; názvy souborů v seznamu jsou nyní escapovány HTML přes `_escape()`.

---

## [2026.05.014] - 2026-05-26

**Souhrn:** BM25-style RAG textové vyhledávání, bezpečnostní zpevnění (zabezpečení symlinkových cest, limit nahrávání), webhook notifikace, retence DB, hromadný výběr záznamů, tisknutelný HTML+CSV report s filtry, modal Nastavení, KB reindex jedním kliknutím, teplotní odznak Hailo NPU, opravy AI chatu (pouze angličtina, formát zpráv hailo, ochrana před halucinacemi).

### Přidáno

- **BM25-style TF×IDF textové záložní vyhledávání** (`sentinel/rag.py`): Pokud embedding ChromaDB není připraven (indexace) nebo nevrací výsledky, `_text_fallback()` nyní skóruje chunky pomocí TF×IDF (IDF předpočítáno při načtení přes `_build_idf_index()`). Bonus za shodu fráze ×3, bonus za řádek záhlaví ×2. Nahrazuje jednoduché skórování překryvem slov.
- **`POST /api/kb/reindex`** (`sentinel/chat_service.py`): Spouští `build_kb.py` v background threadu (admin+). Okamžitě vrací `{"status": "started"}`. Tlačítko v záhlaví spouští tuto akci.
- **Webhook notifikace** (`sentinel/utils.py`, `sentinel/api.py`, `sentinel/actions.py`): Generický HTTP POST s volitelnou hlavičkou `X-Sentinel-Signature` (HMAC-SHA256). Spouští se při AI návrzích. Konfigurace: `webhook.enabled`, `webhook.url`, `webhook.secret`.
- **Retence DB** (`sentinel/config.py`, `sentinel/chat_service.py`): Konfigurační klíč `db_retention_days` (výchozí 30). Denní maintenance smyčka ve 03:00 maže telemetrii starší než N dní přes `state.prune_telemetry(days=retention)`.
- **Hromadný výběr záznamů** (`sentinel/static/script.js`, `sentinel/templates/index.html`): Přepínač hromadného módu v modalu záznamů — přidá checkboxy ke každé kartě. Panel Vybrat vše, Ignorovat (vybrané), Smazat (vybrané).
- **Filtr záznamů** (`sentinel/static/script.js`, `sentinel/templates/index.html`): Živý textový filtr v modalu záznamů. Přetrvává a znovu se aplikuje po obnovení obsahu modalu.
- **Tisknutelný HTML report s filtry** (`sentinel/chat_service.py`): `GET /api/export/incidents.html` — samostatná tisknutelná stránka. Query parametry: `channels=`, `plugins=`, `statuses=`, `host=` pro selektivní export. Otevírá se z modalu "Tisk Reportu", kde uživatel zaškrtne požadované kategorie/pluginy/stavy.
- **Export CSV** (`sentinel/chat_service.py`): `GET /api/export/incidents.csv` — všechny aktivní záznamy jako RFC 4180 CSV.
- **`GET /api/issues/meta`** (`sentinel/chat_service.py`): Vrací živé kanály, pluginy a stavy z aktuálních aktivních záznamů. Používán modal filtru Tisk Reportu k naplnění dynamických zaškrtávacích políček.
- **Modal Nastavení** (`sentinel/templates/index.html`, `sentinel/static/script.js`): Ikona ozubeného kola v záhlaví (pouze superadmin). Editovatelná konfigurační pole (model, Hailo URL, porty, počet dní retence) podložená `GET/POST /api/config/view|update`.
- **`GET /api/config/view`, `POST /api/config/update`** (`sentinel/chat_service.py`): Čtení/zápis vybraných konfiguračních hodnot za běhu (superadmin). Zapisuje zpět do `/etc/sentinel/config.yaml`.
- **Teplota Hailo NPU** (`sentinel/chat_service.py`): `_get_hailo_fw_info()` spouští `hailortcli sensor-info` pro čtení teploty čipu NPU. `render_sys_monitor_html()` zobrazuje barevný teplotní odznak: zelená < 70°C, žlutá < 85°C, červená ≥ 85°C. Cache 30 s.
- **Seskupování alertů se sbalením** (`sentinel/chat_service.py`): `get_status_html()` seskupuje záznamy dle `plugin_name`. Skupiny s více než 3 záznamy sbalí přebytečné karty za JS přepínač.
- **MIT Licence** (`LICENSE`): Licence pro volné použití přidána do kořene repozitáře.

### Změněno

- **`call_ai_knowledge_base`** (`sentinel/chat_service.py`): Odstraněna instrukce "STRICTLY on documentation context" způsobující halucinace, když RAG vrátil nepříbuzné chunky. Přidána kontrola `has_context` — kontext zahrnut jen pokud je neprázdný a netriviální. Prompt nyní říká, aby odpovídal z obecné Linux/HPC odbornosti, pokud je kontext nepříbuzný. Sjednoceny kódové větve hailo/non-hailo.
- **File chat** (`sentinel/chat_service.py`): Větev aktivního souboru nyní používá split zpráv `system`/`user` pro hailo cestu (vyhýbá se chybě stripování nových řádků). Změněno "Output in CZECH" na "Answer in ENGLISH".
- **`analyze_group_complex`** (`sentinel/chat_service.py`): Cesty souborů pro členy log skupiny nyní procházejí přes `_safe_log_path()` pro zabezpečení symlinkových cest.
- **`.gitignore`**: Přidány vzory `chyba_*`, `resume.sh`, `claude.sh`.
- **`config.yaml.example`**: Přidána sekce `webhook` a `db_retention_days`.

### Opraveno

- **AI halucinace na nepříbuzné dotazy** (`sentinel/chat_service.py`): Dotaz "Kdo je sentinel-user?" dříve vrátil 83s odpověď s nepříbuznou systémovou dokumentací. Opraveno odstraněním STRICTLY zámku a přidáním `has_context` ochrany.
- **File chat CZECH output**: Změněno na angličtinu pro konzistenci s ostatním UI.
- **File chat hailo cesta**: Používal raw stringový prompt (všechny nové řádky odstraněny → zkomolený kontext). Nyní používá správný formát zpráv.

### Bezpečnost

- **`_safe_log_path()`** (`sentinel/chat_service.py`): Kontrola `os.path.realpath()` zajistí, že vyřešená cesta zůstane v `LOG_DIR`. Používáno v `set_active_log`, `view_log`, `analyze_single_file` a `analyze_group_complex`.
- **Limit velikosti nahrávání**: `upload_file()` čte maximálně `_MAX_UPLOAD_BYTES` (5 MB) + 1 byte pro detekci příliš velkých souborů bez bufferování celého nahrávání.
- **`secure_filename`**: Aplikováno na všechna uživatelem zadaná jména souborů přes werkzeug.

### Odstraněno

- `chyba_sentinel` — debugovací zachytávací soubor
- `resume.sh` — pomocník pro Claude session
- `config.yaml.bak` — přebytečná záloha

---

## [2026.05.013] - 2026-05-25

**Souhrn:** Plná i18n UI (CS/EN), oprava echo bugy, optimalizace promptů pro qwen-coder, anglické AI odpovědi, htop rozšíření hailo_models.py, oprava cesty konfigurace, trvalá volba modelu, kompletní přepis build_kb.py.

### Přidáno

- **UI i18n — čeština/angličtina** (`sentinel/static/i18n.js`, `sentinel/templates/index.html`, `sentinel/static/script.js`): Plné dvojjazyčné rozhraní. Čeština je výchozí jazyk. Kompaktní tlačítko `EN/CS` v záhlaví přepíná jazyk a ukládá výběr do `localStorage`. Implementováno přes HTML atributy `data-i18n`, `data-i18n-placeholder`, `data-i18n-title` zpracovávané přes `applyI18n()`. Dynamické JS řetězce nahrazeny voláními `t(key, vars)` (~110 klíčů napříč 90 překlady). Podmíněné Jinja2 titulky řešeny přes vypočítané klíče atributů: `data-i18n-title="{{ 'teams_active' if teams_enabled else 'teams_disabled' }}"`.
- **`i18n.js`** (`sentinel/static/i18n.js`): Nový soubor. Základní API: `t(key, vars)` s interpolací `{placeholder}`, `applyI18n()`, `toggleLang()`, `_updateLangBtn()`. Načítán před `script.js`. `DOMContentLoaded` automaticky spouští `applyI18n()`.
- **CSS tlačítka jazyka** (`sentinel/static/style.css`): Hover styly `#lang-btn` — přechod barvy rámečku a textu při najetí myší.
- **hailo_models.py — htop rozšíření**: Přidány 3 nové pomocné funkce: `get_hailo_info()` (čte verzi FW + architekturu z `hailortcli`, cachováno globálně), `get_disk_stats(path)` (statvfs využití disku), `get_hailo_service_status()` (pinguje hailo-ollama API, výsledek cachován 5 s pro zamezení blokování TUI). `draw_top_stats()` rozšířena o dva nové řádky: `NVM [bar] použito/celkem` diskový bar a informační řádek `NPU HAILO10H FW:5.3.0  hailo-ollama: ● RUNNING  Sentinel active: qwen2.5-coder:1.5b`. Seznam modelů: aktivní model (z `/etc/sentinel/config.yaml`) zvýrazněn žlutě s markery `>`. Záhlaví a seznam posunuty o 2 řádky dolů.
- **Trvalá volba modelu** (`sentinel/chat_service.py`): `api_hailo_ollama_set_model` nyní zapisuje vybraný model zpět do `/etc/sentinel/config.yaml` přes regex substituci po aktualizaci v paměti. Změna přežije restart Sentinelu.
- **`build_kb.py` — kompletní přepis**: Nová architektura:
  - **Extraktory**: `.md`, `.txt`, `.rst` (podtrhávací záhlaví → `##`), `.docx` (styly záhlaví + tabulka → Markdown), `.pdf` (pypdf), `.xlsx/.csv` (pandas Markdown tabulky), `.yaml/.yml` (parsováno + citlivé klíče redigovány), `.conf/.ini` (inline redakce hesel)
  - **Chunker**: rozdělení na všech úrovních záhlaví (`#` až `######`), příliš velké sekce rozděleny dle odstavců s překryvem 300 znaků mezi sousedními chunky pro kontinuitu přeshraničního kontextu
  - **META sekce Sentinel**: automaticky generována z živého `/etc/sentinel/config.yaml` (sanitizováno) + seznam pluginů + index dokumentů
  - **MD5 deduplikace**: identické chunky přeskakovány napříč všemi zdroji
  - **CLI**: `-s/--sources`, `-o/--output`, `--no-meta`, `--dry-run`, `-v/--verbose`
  - **Výstup průběhu**: počet chunků na soubor, součty na adresář, závěrečný souhrn s počtem znaků, velikostí, uplynulým časem
- **Bootstrap `knowledge_base.txt`**: Vytvořen z `docs/` (3 dokumenty, 38 chunků, 34 KB). RAG automaticky indexuje při restartu.

### Změněno

- **`execute_ollama`** (`sentinel/chat_service.py`): Přidán parametr `max_tokens=None`; předán do payloadu hailo-ollama, pokud je nastaven.
- **`call_ai_knowledge_base`** (`sentinel/chat_service.py`): Hailo cesta nyní používá správný split zpráv `system`/`user` (vyhýbá se echo buze způsobené plochým formátem jedné zprávy se stripováním nových řádků). Slice historie změněn z `[-5:]` na `[-5:-1]` — vylučuje aktuální zprávu, která byla již přidána před tímto voláním. Systémový prompt změněn z češtiny na **angličtinu se strukturovanou instrukcí výstupu** ("Use clear structure: short paragraphs or bullet points. Be concise."). Standardní cesta (non-hailo) aktualizována identicky.
- **Autofix prompt** (`sentinel/chat_service.py`): Přepnuto na formát `messages` s úzkým systémovým promptem ("Linux SysAdmin. Output ONLY valid JSON, no other text.") a uživatelskou zprávou ve stylu JSON-completion. Limit `max_tokens=200`. Konfigurační override `chat_autofix` odstraněn z `/etc/sentinel/config.yaml`, takže je aktivní nový výchozí kód.
- **Nápravný prompt** (`/etc/sentinel/config.yaml`): Nahrazen verbose víceřádkový šablona jednořádkovou: `'SysAdmin. Node: {node} Error: {raw_line} Output ONLY JSON: {"description":"one sentence fix","command":"exact bash command or N/A"}'`. `ollama_service.py` hailo payload omezen na `max_tokens=200` pro `ai_request` úlohy, `max_tokens=512` pro ostatní.
- **Prompt analýzy jednoho souboru** (`sentinel/chat_service.py`): Zkrácen, přidáno "max 4 věty", angličtina.
- **Prompt skupinové analýzy** (`sentinel/chat_service.py`): Zkrácen, přidáno "max 5 vět", angličtina.
- **Startovací zpráva** (`sentinel/__main__.py`): Nyní zobrazuje `config.HAILO_OLLAMA_MODEL` pokud je hailo povoleno, místo vždy zobrazovat CPU zálohu `config.OLLAMA_MODEL`.
- **`install.sh`**: `CONFIG_FILE` změněno z `$SENTINEL_DIR/config.yaml` na `/etc/sentinel/config.yaml`. `/etc/sentinel` přidáno do smyčky `mkdir -p` v kroku 4.
- **`check.sh`**: Cesta konfigurace aktualizována na `/etc/sentinel/config.yaml`. Odstraněna duplicitní položka `/opt/Sentinel/config.yaml`.

### Opraveno

- **Echo buga** (`sentinel/chat_service.py`): Model vracel přesný vstup uživatele jako svou odpověď. Příčina 1 — `conversation_history.append()` se spouští před `call_ai_knowledge_base`, takže aktuální zpráva se v kontextu objevila dvakrát. Příčina 2 — `prompt.replace('\n', ' ')` zkolaboval celý 369-znakový flat blob, což způsobilo, že malý qwen model opakoval poslední viděný text. Oprava: správný split system/user + slice `[-5:-1]`.
- **hailo_models.py `import re`**: Přidán `import re as _re` pro podporu regex parsování `get_active_sentinel_model()`.

---

## [2026.05.012] - 2026-05-25

**Souhrn:** Modal Autofix, unified panel Akce & AI Návrhy, Allowed Commands DB, autonomní spouštění, UI polish (kompaktní rychlé akce, tenké scrollbary, sloučená tlačítka).

### Přidáno

- **Modal Autofix** (`sentinel/chat_service.py`, `sentinel/static/script.js`, `sentinel/templates/index.html`): Tlačítko kouzelné hůlky v seznamech záznamů nyní otevírá dedikovaný modal místo směrování přes chat. Modal zobrazuje spinner při AI analýze, poté vykreslí kartu výsledku (popis + příkaz + tlačítko kopírovat + odznak rizika + tlačítka Fronta/Re-analyzovat). Tlačítko "Odeslat do chatu" přidá výsledek do historie chatu. Opravena chyba b64 kódování — tlačítko hůlky nyní předává payload přes atribut `data-payload` a dekóduje pomocí `atob()`.
- **Unified tlačítko "Akce & AI Návrhy"** (`sentinel/templates/index.html`, `sentinel/static/script.js`): Sloučena dvě samostatná tlačítka postranního panelu ("Čekající akce" + "AI Návrhy") do jednoho. Tlačítko zobrazuje inline odznak s počtem čekajících akcí. Otevírá unified pending-actions modal.
- **Správa akcí v pending-actions modalu** (`sentinel/static/script.js`): Každý řádek akce nyní má tlačítka Spustit ▶, Upravit ✏️, Prohlédnout 👁, Smazat 🗑. Inline úpravy příkazu bez zavírání modalu. Spuštění volá nový endpoint `/api/v1/actions/<id>/execute`.
- **Allowed Commands DB & UI** (`sentinel/state.py`, `sentinel/chat_service.py`, `sentinel/templates/index.html`, `sentinel/static/script.js`):
  - Nová tabulka `allowed_commands`: `pattern` (fnmatch glob), `description`, `auto_execute`, `risk_max`, `note`, `created_at`.
  - Plné CRUD API: `GET/POST /api/v1/allowed-commands`, `PUT/DELETE /api/v1/allowed-commands/<id>`.
  - Modal správy přístupný přes "⚙️ Allowed Commands" v zápatí panelu akcí.
- **Autonomní spouštění** (`sentinel/actions.py`): Po AI návrhu nápravného příkazu `check_command_allowed()` zkontroluje příkaz vůči povolené listině. Pokud `auto_execute=True` a `risk_score ≤ risk_max`, příkaz se spustí okamžitě bez schválení člověkem. Výsledek zaznamenán do audit trailu a odeslán do Teams.
- **Chatový příkaz `save_action`** (`sentinel/chat_service.py`): Zařadí výsledek autofix přímo z chatu jako čekající akci. Dekóduje b64 JSON payload obsahující `command` + `description`, spustí klasifikátor bezpečnosti, vytvoří `dry_run` čekající akci.
- **Nové API endpointy** (`sentinel/chat_service.py`):
  - `POST /api/v1/actions/<id>/delete` — smazání čekající akce
  - `POST /api/v1/actions/<id>/execute` — okamžité spuštění akce (admin+)
  - `POST /api/v1/actions/<id>/update-command` — úprava příkazu na místě (admin+)
- **Info NPU firmware v sys monitoru** (`sentinel/chat_service.py`): Výstup `hailortcli fw-control identify` (verze firmware, architektura) cachován a zobrazen v řádku panelu AI Engine.
- **`raw_line` uložen v akcích** (`sentinel/state.py`, `sentinel/actions.py`): Původní řádek logu uložen do sloupce `actions.raw_line`. Tlačítko "Re-analyzovat" v modalu čekajících akcí používá `raw_line` pokud je dostupný, jinak se vrátí k `reason`.

### Změněno

- **Panel rychlých akcí** (`sentinel/static/style.css`): Šířka panelu 280→260px. Obě sekce (rychlé akce + log skupiny) se scrollují nezávisle. Rychlé akce omezeny na `max-height: 42%`. Písmo a odsazení zmenšeny pro kompaktní vzhled.
- **Globální stylování scrollbaru** (`sentinel/static/style.css`): Unified tenký 4px scrollbar ve všech posuvných oblastech — průhledná stopa, tmavý thumb odpovídající pozadí panelu, zvýraznění při najetí myší.
- **Handler `autofix_text`** (`sentinel/chat_service.py`): Detekuje a dekóduje b64 payloady (pro starší kódové cesty). Vylepšena výstupní HTML karta: tlačítko kopírovat na bloku příkazu, tlačítka akcí Fronta/Re-analyzovat.
- **Chatový příkaz `pending`** (`sentinel/chat_service.py`): Nyní vrací kompaktní inline zprávu s počtem + tlačítko pro otevření modalu Akce místo vykreslování plného seznamu karet v chatu.

### Opraveno

- **Kódování payloadu tlačítka hůlky** (`sentinel/chat_service.py`): Dříve tlačítko hůlky kódovalo text záznamu jako base64, ale předávalo ho v raw formátu do handleru `autofix_text`, který ho zpracovával jako prostý text — AI přijala zkomolený b64 místo skutečné chyby. Opraveno použitím `openAutofixModal(b64)` + dekódováním `atob()` v JS modalu.
- **Detekce Hailo-10H NPU** (`sentinel/ollama_service.py`, `sentinel/chat_service.py`): Všechny kontroly aktivity NPU nyní používají `os.path.exists('/sys/module/hailo1x_pci')` navíc k `/dev/hailo0`. Hailo-10H (AI HAT 2+) používá PCIe driver `hailo1x_pci` — žádný node `/dev/hailo0` není vytvořen.

---

## [2026.05.011] - 2026-05-25

**Souhrn:** Plná integrace Hailo AI HAT 2+ (hailo-ollama 5.3.0) — LLM backend, přepínač modelů, izolace embeddingů, inicializační průvodce, testy, service soubory.

### Přidáno

- **LLM backend Hailo AI HAT 2+** (`sentinel/config.py`, `sentinel/ollama_service.py`): Konfigurační proměnné `HAILO_OLLAMA_ENABLED/URL/MODEL`. Pokud je povoleno, všechny LLM inference jsou směrovány do hailo-ollama (port 8000, kompatibilní s OpenAI). CPU ollama zůstává na portu 11434 pro embeddingy (nomic-embed-text není podporován hailo-ollama).
- **Izolace URL embeddingu** (`sentinel/config.py`, `sentinel/rag.py`): Nový konfigurační klíč `EMBEDDING_OLLAMA_URL`. RAG vždy používá tuto URL (nebo odvozuje z `OLLAMA_URL`) pro `nomic-embed-text` — zajišťuje použití CPU ollama i při zpracovávání LLM provozu přes hailo-ollama.
- **Přepínač modelů za běhu** (`sentinel/chat_service.py`, `sentinel/static/script.js`):
  - `GET /api/hailo-ollama/status` — vrací stav povolení, aktuální model, modely z hailo-ollama `/api/tags`, dostupnost, příznak aktivity NPU
  - `POST /api/hailo-ollama/model` — přepíná aktivní hailo model za běhu (admin+); bez nutnosti restartu
  - Informační panel sekce AI Engine: inline rozbalovací seznam modelů pro všechny známé modely 5.3.0 s indikátorem stavu NPU
- **Podpora Hailo-10H v inicializačním průvodci** (`sentinel_init.py`): `detect_hailo()` nyní rozlišuje Hailo-10H (AI HAT 2+, PCIe `1e60:000b`, LLM) od Hailo-8/8L (počítačové vidění). Detekuje binárku `hailo-ollama`. `select_ai_backend()` nabízí dedikovanou hailo-ollama volbu se seznamem modelů; `generate_config()` zapisuje sekci `hailo_ollama:`.
- **TUI hailo_models.py** (`hailo_models.py`): Přesunut do `/opt/Sentinel`. Přidány CLI argumenty `--url`/`--models-dir` (env: `HAILO_OLLAMA_URL`, `OLLAMA_MODELS`). Opravena výchozí cesta modelů na `/mnt/nvme/hailo_system/models`. Zápatí zobrazuje aktivní URL a adresář modelů. Přidán plný docstring modulu s příklady použití.
- **Referenční service soubory** (`service/`): `hailo-ollama.service`, `ollama.service`, `open-webui.service` — referenční kopie s env `OLLAMA_MODELS`, `TimeoutStartSec=90`, `StandardOutput=journal`. Nasazení přes `sudo cp service/*.service /etc/systemd/system/ && sudo systemctl daemon-reload`.
- **Test suite** (`tests/`): 58 automatizovaných testů napříč 5 moduly:
  - `test_safety.py` (13): ochrana AI-akcí
  - `test_config.py` (9): výchozí hodnoty a load_config()
  - `test_state.py` (18): DB schéma, ON CONFLICT, ověření tokenu, fronta úloh, watchdog práh 180s
  - `test_hailo.py` (13): směrování hailo-ollama, argparse, kontrakty detect_hailo()
  - `test_rag.py` (5): výběr URL embeddingu, záložní přechod 404→textové vyhledávání

### Změněno

- **ollama_service.py**: `process_single_task()` nyní má tři cesty: hailo-ollama → externí Ollama → lokální binárka. `ollama_monitor()` kontroluje endpoint `/models` hailo-ollama pokud `HAILO_OLLAMA_ENABLED`. `_log_hailo_status()` hlásí jak Hailo-10H LLM, tak Hailo-8/8L embedding čip.

---

## [2026.05.010] - 2026-05-22

**Souhrn:** UI Sentinel Satellites (HW Devices & Alert Nodes), integrace fyzického zařízení Sentinel HW, individuální konfigurace LED, oprava MQTT brokeru a webové UI pro konfiguraci HW.

### Přidáno

- **Sentinel Satellites – záložka HW Devices** (`sentinel/templates/index.html`, `sentinel/static/script.js`): Přepracován existující modal Sentinel-Alert do dvouzáložkového panelu. Záložka "Alert Nodes" zachovává existující registrační postup sentinel-alert. Nová záložka "HW Devices" umožňuje registraci fyzických Sentinel HW zařízení (RPi roboti) s hostname a URL webového UI.
- **Modal detailu zařízení** (`sentinel/templates/index.html`, `sentinel/static/script.js`): Kliknutím na řádek agenta nebo HW zařízení se otevírá modal s detailem. U agentů zobrazuje aktivní záznamy filtrované dle hostname. U HW zařízení navíc načítá živá data senzorů (stav, osvětlení v luxech, přítomnost, počet záznamů) přímo z endpointu `/api/live` webového UI zařízení přes cross-origin fetch.
- **REST API Sentinel HW** (`sentinel/chat_service.py`): Čtyři nové autentizované endpointy pro správu HW zařízení:
  - `GET /api/sentinel-hw/list` — seznam všech registrovaných HW zařízení (hostname prefix `sentinel-hw-`) se stavem, last_seen, počtem active_issues a web_ui_url
  - `POST /api/sentinel-hw/register` — registruje nové zařízení, automaticky přidá prefix `sentinel-hw-` k hostname, generuje 32-byte hex token, ukládá web_ui_url do pole `agents.notes`; vyžaduje roli `superadmin`
  - `POST /api/sentinel-hw/<hostname>/revoke-token` — obnoví token pro zařízení
  - `POST /api/sentinel-hw/<hostname>/delete` — odstraní záznam zařízení
- **Migrace schématu tabulky Agents** (`sentinel/state.py`): Idempotentní migrace `ALTER TABLE agents ADD COLUMN notes TEXT DEFAULT ''` přidána do `_ensure_schema()`. Používáno pro uložení `web_ui_url` u HW zařízení bez narušení schématu u existujících nasazení.
- **Filtrování seznamu agentů** (`sentinel/static/script.js`, `loadAgentsList`): Tabulka agentů již nezobrazuje záznamy `sentinel-alert-*` a `sentinel-hw-*` — tyto jsou spravovány v dedikovaném UI Satellites.
- **Aktualizace ikony odznáčku** (`sentinel/templates/index.html`): Ikona odznáčku v horní liště změněna z `fa-tower-broadcast` na `fa-satellite`; sekce přejmenována z "Sentinel-Alert Network" na **"Sentinel Satellites"** v celém UI.

### Opraveno

- **MQTT Odpojeno**: Pythonová knihovna `paho-mqtt` chyběla v systému, způsobila tiché přeskakování MQTT připojení navzdory dostupnému brokeru. Opraveno instalací `paho-mqtt` přes pip. Sentinel se znovu připojí k brokeru na `192.168.2.202:1883` při dalším spuštění.

### Externální — projekt Sentinel HW (`/home/foxik/git/sentinel-hw`)

Následující práce byla provedena v doprovodném projektu fyzického zařízení:

- **Webové UI** (`web_ui.py`): Nová Flask aplikace na portu 5055 se session-based autentizací. 8-záložkový SPA (Přehled / LEDs / Senzory / Oči / Chování / Připojení / Logy / Testy). Log ring-buffer (deque 500), deep-merge ukládání konfigurace, validace GPIO pinů s detekcí kolizí.
- **Individuální konfigurace LED** (`drivers/leds.py`): `set_status_individual(status, scale, individual)` — dvoufázový algoritmus: nejprve vyhodnoceny přímé LED (react_to list), poté propojené LED kopírují cílovou barvu (index `link_to`). Zabraňuje cyklickým závislostem; řetězové linky nejsou záměrně podporovány.
- **Klient SentinelAPI Polling** (`drivers/sentinel_api.py`): `_poll_once()` extrahován pro testovatelnost. Sleduje množinu `_known_keys`; spouští callback `on_new_incident` pouze pro nově vzniklé klíče záznamů. Thread-safe s `threading.Lock`.
- **Lokální simulace** (`tests/`): `mock_hardware.py` (MockDisplay, MockLEDs, MockBuzzer, …), `mock_chat_service.py` (HTTP server simulující `/api/v1/issues` s inject endpointem pro scénáře), `run_local.py` (monkey-patche drivery před importem, volitelný příznak `--mock-api`).
- **Automatizované testy**: 46 testů napříč `test_leds.py` (10), `test_sentinel_api.py` (18), `test_web_ui.py` (18) — vše prochází.

---

## [2026.05.009] - 2026-05-18

### Přidáno
- **Optimalizace centrálního API**: Přidán explicitní alias `resolve_problem(key)` v `api.py` odkazující na `state.mark_resolved(key)`. Zabraňuje pádům daemona za běhu při spouštění mechanismu auto-healing u moderních detektorů.
- **Watchdog Inotify Core**: Implementován handler události `on_moved` v `watcher.py`. Poskytuje plnou nativní podporu pro atomické přepínání souborů pomocí `os.replace`, eliminuje potřebu spoléhat se na krkolomné triky se souborovým systémem.
- **Log Aggregator & Deduplicator**: Implementován in-memory buffer v `system_detector.py` pro omezení spamu v logu. Pokud se stejná chyba opakuje vícekrát na uzlu, odešle se pouze jeden komprimovaný report formátovaný jako `(X events) Last: <text>`.

### Změněno
- **Universal Watcher**: Kompletně odstraněno pevně zakódované pole `_snapshot_files` z `watcher.py`. Resety ukazatele souborů nyní fungují plně dynamicky na základě změn stavu inotify a snížení velikosti souboru.
- **Směrování webového UI**: Přepracována filtrovací matice uvnitř metod `generate_modal_issues_html` a `status_check` v `chat_services.py`. Zobrazení záznamů v "Security Center" nyní plně respektuje přiřazený `channel_type` a nevyžaduje starý nucený prefix `AGENT|`.
- **Kanalizace záznamů**: Všechny výstupní struktury pocházející z `AUDIT_DET_ECTOR` (bezpečnostní aktualizace, zranitelnosti debsecan a příznaky restartu) jsou nyní striktně směrovány do kanálu `security`.

### Opraveno
- **Pád při víceřádkovém ZFS**: Opraveno parsování logu v `storage_detector.py`. Když `zpool status -x` vrací víceřádkový výpis chyby, detektor již nespadne ani nespamuje databázi, ale bezpečně spojí řádky pomocí bezpečného oddělovače.
- **Výpadek webového UI**: Vyřešen problém, kdy nově generované logy z konkurenčního asynchronního Python orchestrátoru se nepromítly do panelu záznamů kvůli slepotě watchdogu vůči atomickým zápisům a nesprávnému přiřazení kanálu modalu.

## 2026.05.008

**Souhrn:** Unifikovaný MQTT telemetrický payload, rozšíření sady senzorů Home Assistant, živý stavový odznak MQTT brokeru v UI a odolnost vůči chybám při přetypování na float.

### Funkce a vylepšení

* **Unifikovaná smyčka telemetrického vysílání:** Migrován veškerý MQTT messaging do jedné synchronizované 15-sekundové background smyčky (`mqtt_telemetry_loop`) v `chat_service.py`. Zajišťuje univerzální přenos kompletního víceklíčového JSON payloadu, zcela řeší chybu stavu "Unknown" (Neznámý) v Home Assistant způsobenou fragmentovanými aktualizacemi stavu.
* **Rozšířená sada auto-discovery pro Home Assistant:** Rozšířena MQTT discovery architektura pro okamžité generování 13 nativních entit v Home Assistant. Přidána explicitní podpora, ikony a přesné třídy stavů pro: využití disku logu, swap prostor, velikost databáze, aktivní vlákna serveru, celkové AI požadavky, průměrná AI latence, hloubka AI fronty, aktivní připojené klienty, stav RAG enginu a uptime serveru.
* **Živý odznak stavu MQTT v UI:** Integrována dynamická ikona sítě přímo do záhlaví webového UI (`index.html`). Odznak reaguje v reálném čase na životní cyklus brokeru, svítí zeleně (`#107c10`) s CSS stínem při aktivitě a bliká výstražně červeně (`var(--error)`) při výpadku připojení.

### Opravy chyb a refaktorování

* **Oprava přetypování desetinných čísel:** Opravena kritická výjimka `ValueError: invalid literal for int() with base 10: '0.0'` způsobující úplné zastavení MQTT backend threadu při sběru metrik. Implementovány bezpečné parsovací wrappery `int(float(...))` pro zpracování desetinných hodnot kódovaných jako řetězce.
* **Synchronizace serializace stavu API:** Vylepšen REST endpoint `/api/status_check` pro explicitní zpřístupnění backendových konfiguračních proměnných (`mqtt_enabled` a `mqtt_connected`) do JS runtime smyčky frontendu, umožňující přesné vykreslení stavového odznáčku.
* **Čištění telemetrického znečištění:** Odstraněny starší izolované MQTT publikovací hooky z `state.py` napříč logikou `save_telemetry_snapshot`, `mark_resolved`, `delete_problem` a `save_problem` pro eliminaci race conditions a zamezení znečištění dat vůči nové centralizované telemetrické matici.

## 2026.05.007

**Souhrn:** Přímý P2P chat v reálném čase, 24/7 Android background service, dynamické UI téma a implementace routování dle Device-ID.

### Funkce a vylepšení

* **Přímý P2P chat klient (Admin-to-Client):** Navržen real-time peer-to-peer messagingový protokol pomocí privátních místností Flask-SocketIO. Administrátoři nyní mohou zahájit přímé, volatile (bez serverové historie) konverzace s libovolným připojeným klientem (Web nebo mobilní) přímo z matice aktivních klientů.
* **24/7 Android Background Service:** Integrována `flutter_background_service` pro nasazení persistentní Android Foreground Service. Mobilní aplikace nyní může udržovat aktivní WebSocket připojení, zajišťující příjem kritických alertů a přímých zpráv přes push notifikace i při zavřené, ukončené aplikaci nebo zamčené obrazovce.
* **Routování pomocí unikátního Device ID (UUID):** Přepracovány backendové a frontendové sledovače připojení na použití persistentního mapování `device_id` místo IP adres. Zaručuje přesné směrování zpráv na mobilní zařízení, která často přepínají sítě (Wi-Fi/LTE) a zabraňuje echo efektům zpráv při více zařízeních přihlášených pod stejným uživatelským jménem.
* **Dynamický Theme Engine (Světlý/Tmavý mód):** Kompletně refaktorováno mobilní UI pro podporu přepínání mezi světlým a tmavým módem za chodu. Eradikovány pevně zakódované hex barvy (`0xff161616`, `Colors.white`) napříč všemi obrazovkami (Dashboardy, Modaly, Chat Bubbles) ve prospěch reaktivních vazeb `Theme.of(context)` spravovaných `StorageService`.
* **Přepínač Background Service:** Zaveden dedikovaný přepínač v mobilním nastavení umožňující administrátorům ručně povolit nebo pozastavit 24/7 background listener, poskytující granulární kontrolu nad spotřebou baterie zařízení versus dostupností v reálném čase.
* **Interaktivní UI Chat Triggers:** Aktualizován webový UI (`script.js`) a mobilní UI (`info_screen.dart`) se stromem klientských tabulek. Dynamická ikona chatu se nyní objevuje vedle aktivních klientů a inteligentně skrývá pro fyzické zařízení, na kterém uživatel aktuálně pracuje, pro zabránění smyček sebeposílání.

### Opravy chyb a refaktorování

* **Oprava pádu Provider Lifecycle:** Opravena kritická výjimka `SentinelProvider was used after being disposed`. Oddělen kód pro načítání dat `refreshIssues` a `refreshMetrics` od sekvence biometrického auto-přihlášení, zabraňující pádu aplikace při ničení obrazovky `LoginGate` v průběhu rychlé navigace.
* **Migrace knihovny notifikací:** Upgradována a refaktorována implementace `flutter_local_notifications` pro soulad se striktními změnami syntaxe `v21.0.0`, nahrazeny poziční argumenty povinnými pojmenovanými parametry (`channelId`, `channelName`).
* **Chyby kompilace konstantních dekorací:** Opraveno více selhání kompilace `Invalid constant value` a `Color can't be assigned to BorderSide` ve Flutter widget stromu způsobených aplikováním modifikátorů `const` na dynamicky vyhodnocované vlastnosti tématu.
* **Bezpečnost LDAP/API hlaviček:** Zajištěno, že mobilní aplikace univerzálně předává hlavičku `X-Device-ID` spolu s `X-Client-User` a záložnými Basic Auth hodnotami, zabraňující smyčkám 401 Unauthorized při handshaku background socketu.

## 2026.06.006

**Souhrn:** Představení nativní Android aplikace, vylepšení mobilního API a optimalizace bezpečného autentizačního toku.

### Funkce a vylepšení

* **Představení Sentinel Client (Android):** Spuštěna první oficiální nativní Android doprovodná aplikace (`sentinel-app`) vytvořená ve Flutter. Aplikace poskytuje plně funkční mobilní velitelské centrum pro práci s Sentinel infrastrukturou s moderním tmavým UI.
* **Biometrické zabezpečení & autentizace (`local_auth`):** Integrována hardwarová biometrická autentizace (otisk prstu/rozpoznání obličeje) do Android klienta. Aplikace bezpečně ukládá přihlašovací údaje a vyžaduje úspěšné biometrické ověření pro zjednodušený přístup k dashboardu bez hesla.
* **Autentizace API klíčem (`X-API-Key`):** Přepracován Python backend (`chat_service.py`) pro podporu bezpečné autentizační metody hlavičkovým API klíčem navržené speciálně pro externí klienty a agenty. Eliminuje potřebu přenášet přihlašovací údaje prostým textem přes Basic Auth po síti pro každý požadavek.
* **Hybridní sledování sessions (Connection Tracker):** Upgradován globální connection tracker pro plynulé rozlišování mezi uživateli webového UI a uživateli mobilní aplikace. Mobilní klienti jsou automaticky označeni suffixem `(Mobil)` v seznamu aktivních připojení.
* **Unifikovaný nativní JSON endpoint (`/api/v1/issues`):** Implementován dedikovaný vysokovýkonný JSON endpoint navržený pro obejití vrstev HTML formátování. Endpoint doručuje surová SQLite data záznamů (včetně dvojitě mapovaných atributů `channel_type` a `channelType`) pro spolehlivé parsování pro silně typované mobilní datové modely (`IssueModel.fromJson`).
* **Real-time renderování mobilní telemetrie:** Android aplikace integruje interaktivní real-time widgety (`SysMonitorWidget`) zrcadlící stavové odznáčky webového UI. Zahrnuje barevné indikátory závažnosti, počty aktivních klientů, AI latenci a hloubku fronty, vše automaticky obnovováno bez zásahu uživatele.
* **Interaktivní mobilní matice záznamů:** Navržena drill-down architektura pro mobilní dashboard. Klepnutím na libovolný stavový odznáček (`LOGS`, `AGENTS`, `ROOT`, `SECURITY`) se otevírá dedikovaná obrazovka `IssueDetailsScreen` zobrazující parsované logy s akčními tlačítky pro AI Autofix, sdílení, ignorování a mazání záznamů přímo z telefonu.
* **Nativní push notifikace:** Implementovány systémové Android push notifikace (`flutter_local_notifications`). Aplikace nyní může přijímat background alarmy ze Sentinel core s dedikovaným přepínačem a testovací funkcionalitou vestavěnou přímo v mobilním nastavení.
* **Redesign mobilního AI chatu:** Transformováno mobilní chatové rozhraní pro elegantní zpracování raw Ollama výstupů. Přidán vlastní HTML parser (`_cleanHtml`) odstraňující formátovací tagy (`<b>`, `<br>`), prezentující AI odpovědi v čistých, čitelných chat bubblech s odlišnými vizuálními identitami pro uživatele a Sentinel Daemon.

### Opravy chyb a refaktorování

* **Zabránění přetečení mobilního viewportu:** Opraveny kritické výjimky renderování (`Vertical viewport was given unbounded height` a horizontální přetečení `AppBar`) nahrazením vnořených struktur `ListView` za `CustomScrollView` (`SliverFillRemaining`), `Expanded` a `FittedBox` wrappery, zajišťující stabilní renderování napříč všemi Android obrazovkami.
* **Zabránění destrukci UI komponent:** Migrován navigační core mobilní aplikace na architekturu `IndexedStack`. Zabraňuje destruktivnímu přestavování obrazovek při přepínání záložek, zachovává živý stav dashboardů a historií chatů při výrazném zlepšení výkonu.
* **Záložní Basic Auth (API Safety Net):** Zpevněn mobilní `api_service.dart` pro bezpečný přenos Basic Auth přihlašovacích údajů spolu s API klíčem jako záložní mechanismus, zabraňující tichým 401 Unauthorized výpadkům při neshodě ověření klíče.
* **Oprava inicializace biometrického kontextu:** Přesunuto spouštění biometrického promptu do lifecycle hooku `WidgetsBinding.instance.addPostFrameCallback`, zabraňující nativním Android `FragmentActivity` pádům způsobeným voláním hardwarových dialogů před plným načtením UI shellu.

## 2026.05.005

**Souhrn:** Přechod na stavovou správu vícookénkového UI, profilování síťových portů, ochrana před duplicitními notifikacemi a centralizovaná migrace modalu logů.

### Funkce a vylepšení

* **Architektura vícedoménových oken:** Rozšířeny UI odznáčky v záhlaví a serverové stavové správce pro podporu 4 plně nezávislých, izolovaných monitorovacích kategorií (`LOGS OK`, `AGENTS: OK`, `ROOT: OK`, `SECURITY: OK`). Kliknutím na libovolný odznáček se spustí dedikovaná maticová modalová zobrazení pro danou doménu, výrazně snižující únavu z alertů a uvolňující hlavní AI konzoli pro nezamotanou interakci.
* **Monitorování síťových socketů & profilování driftu:** Upgradován vzdálený agent daemon pro sestavení izolovaného profilového snímku baseline TCP/UDP naslouchajících socketů přes diagnostický nástroj `ss -tulpn`. Sentinel okamžitě spustí varování, kdykoli dojde k neautorizované expozici síťového socketu nebo úpravám naslouchání za bezpečnostními firewallem hostitele po inicializaci.
* **Anti-flapping alertů & stavové filtry:** Přepracována telemetrická smyčka agenta i serverová vrstva validace databáze (`state.save_problem`) pro striktní model stavového delta trackingu. Telemetrické smyčky a notifikace jsou potlačeny, dokud metrika infrastruktury nebo profil služby neprojde skutečným přechodem stavu.
* **Zpevnění notifikací Home Assistant & MS Teams:** Extraheny hluboké stavové indikátory při SQLite dotazech pro sledování životního cyklu alertů. Push notifikace směrované do Home Assistant a kritické Teams webhooky jsou přísně synchronizovány a omezeny na nově registrované nebo znovu otevřené aktivní výjimky, zcela eliminující duplicitní spam zpráv při aktualizacích daemona nebo restartech serveru.
* **Centralizovaná migrace logovacího panelu:** Oddělen strukturální `stav` panel monitorování logů od hlavního scrollovacího AI chat feedu, přesunut do autonomního modálního okna (kanál `infra`). Zachovány kompletní programové hooky pro real-time návrhy spuštění `Autofix`, hromadné zkracování a sdílení událostí přímo z izolovaného zobrazení.
* **Sjednocení UI estetiky:** Zpevněny JS frontendové vykreslovače odznáčků (`updateStatus()`) pro vizuální zarovnání sledovače root session se zelenými vlastnostmi ustáleného stavu (`ROOT: OK`) platformy, kdykoli jsou na uzlech clusteru detekovány nulové aktivní shelly.

### Opravy chyb a refaktorování

* **Robustní substring routování pluginů:** Přepnuty přísné textové podmínky rovnosti uvnitř `agent_ingest_payload` na flexibilní substring matching (`'root_monitor' in p_check`), eliminující kritická nesprávná umístění ingestion, kde vzdálené prefixy (např. `AGENT_`) způsobovaly přetékání dat do obecných front agentů místo bezpečných root kanálů.
* **Strukturální přepisy SQL konfliktů:** Vylepšeny parametry řešení konfliktů databáze (`ON CONFLICT(key) DO UPDATE`) pro explicitní přehodnocování a přepisování relačního atributu `channel_type`, umožňující plynulé živé přeřazování cachovaných telemetrických datových listů.

## 2026.05.004

**Souhrn:** Hybridní monitorovací evoluce, lehký Python agent daemon, bezpečné push ingest API, real-time UI streaming a automatizovaná TUI deployment suite.

### Funkce a vylepšení

* **Hybridní monitorovací architektura:** Transformován Sentinel na výkonný hybridní monitorovací systém doplněním existujícího pasivního modelu sledování logů (Pull) o aktivní distribuovaný agentní (Push) framework umožňující přímé reportování infrastruktury.
* **Bezpečný Ingest API Endpoint:** Navržena vysokopropustná autentizační trasa (`/api/v1/agent/ingest`) v `chat_service.py` zabezpečena kryptografickými Bearer Tokeny. Endpoint dynamicky autentizuje připojující se daemony, validuje identity přidružených uzlů a okamžitě vkládá příchozí event streamy do jádra stavového enginu se standardizovanými úrovněmi závažnosti (`CRITICAL`, `WARNING`, `OK`).
* **Lehký multifunkční agent (`sentinel_agent.py`):** Vyvinut Python daemon s nulovou závislostí a nízkým footprintem běžící jako izolovaná systemd service na spravovaných serverových uzlech. Agent obsahuje přizpůsobitelné ověřovací podrutiny:
    * **Stavový systém delta reportování:** Integrováno interní schéma sledování paměti (`self.last_reported_states`) vyhodnocující operační proměnné lokálně. Agent nyní potlačuje identické persistentní alert spamy a exkluzivně odesílá stavové pakety, kdykoli profil infrastrukturních metrik projde skutečným přechodem stavu.
    * **Profilovač baseline síťových socketů:** Autorun engine zachytí izolovaný snímek baseline všech lokálních naslouchajících rozhraní a bindingů procesů (`ss -tulpn`) při inicializaci. Okamžitá varovná telemetrie je spuštěna při detekci neautorizovaného driftu síťových socketů nebo nasazení nepovolených portů za firewallem systému po nastavení.
    * **Watchdog služeb:** Interfacuje přímo se `systemctl` pro vyhodnocení runtime zdraví definovaných klíčových služeb.
    * **Engine mountpointů blokového úložiště:** Validuje přístupnost cílových cest pro okamžité hlášení zastaralých nebo odpojených souborových systémů.
    * **Real-time Security Profiler:** Sleduje aktivní root shell přístupy (`who`), dotazuje lokální balíčkové správce (`apt`/`dnf`) pro hlášení čekajících bezpečnostních aktualizací a veřejných CVE zranitelností a agreguje statistiky brute-force z lokálních firewallů (`fail2ban`).
* **Asynchronní Agent Watchdog (Reaper):** Implementována neblokující background thread smyčka (`agent_watchdog_loop`) v `state.py`. Watchdog kontinuálně skenuje relační databázové struktury a automaticky přepíná chybějící uzly do stavu `OFFLINE`, pokud jejich živý heartbeat signál překročí striktní 3-minutové okno.
* **Plynulá synchronizace živého UI:** Připojen datový pipeline agenta přímo k frontendovým layout událostem. Záznamy s vysokou závažností jsou okamžitě přenášeny přes WebSockets (`self.socketio.emit`) pro vynucení real-time úprav stavu UI a zobrazení červeně pulzujících alert indikátorů na dashboardu bez nutnosti manuálního refetche klientem.
* **Zrcadlení stavu do Home Assistant:** Rozšířena smyčka endpointu pro automatické zrcadlení příchozích dat agentních záznamů do aktivního frameworku Home Assistant (`utils.send_ha_alert`), umožňující okamžité odesílání notifikací při kritických hardwarových nebo bezpečnostních anomáliích vzdálených uzlů.
* **Interaktivní TUI Inicializační průvodce** (`sentinel_agent_init.py`): Injektován barevný ANSI-řízený command-line nástroj pro automatizaci vzdálených nasazení agentů. Průvodce parsuje existující konfigurační parametry jako výchozí hodnoty, umožňuje granulární menu-řízené modifikace rozsahů monitorování služeb, mountpaths a síťových portů, automaticky generuje validní `systemd` unit soubory a poskytuje rychlé příkazy (`start`, `restart`, `enable`) podložené okamžitou zpětnou vazbou z logů.
* **Diagnostický test pipeline:** Vybaven agent daemon on-demand CLI argumentem `--test`. Trigger vloží umělý high-priority diagnostický záznam do aktivního pipeline a pozastaví jeho životní cyklus, umožňující operátorům vizuálně sledovat routování dat a ověřovací workflow napříč celým aplikačním stackem před odesláním auto-resolution cleanup paketu.

### Opravy chyb a refaktorování

* **Case-Insensitive mapování stavu databáze:** Refaktorovány handlery injekce stavu v ingest routě pro striktní kompilaci příznaků záznamů jako malá písmena (`"active"`), úspěšně řeší strukturální misalignment databáze, kde case-sensitive SQLite dotazy filtrovaly nebo chybně interpretovaly aktivní agentní záznamy.
* **Optimalizace payloadu UI šablony:** Přepracován slovníkový payload generovaný agentními událostmi pro explicitní poskytování starších kontextových polí (`"host"`, `"plugin_name"`, `"last_line"`), zajišťující plnou kompatibilitu s existujícími frontendovými renderery a datovými listy příkazu `stav`.

## 2026.05.003

**Souhrn:** Implementace mobilní responzivity, zpevnění viewportu a stabilizace UI/UX layoutu.

### Funkce a vylepšení

* **Off-Canvas mobilní drawer layout:** Transformováno rigidní dvousloupcové desktop flexbox rozhraní do dynamického mobilního layoutu. Při poklesu šířky obrazovky na `850px` nebo méně je panel nástrojů (`#tools-panel`) automaticky skryt mimo obrazovku (`left: -320px`) a může být plynule přepínán přes animovaný off-canvas sliding mechanismus.
* **Poloprůhledný mobilní backdrop:** Zaveden tmavý overlay element (`#mobile-backdrop`) dynamicky vykreslovaný za aktivním off-canvas panelem. Klepnutím kdekoliv na tento backdrop se okamžitě sbalí postranní menu pro zlepšení mobilní navigace a UX.
* **Zpevnění dynamické výšky viewportu:** Migrována hlavní omezení layoutu ze standardního `100vh` na moderní dynamickou jednotku výšky viewportu (`100dvh`). Efektivně obchází závažné problémy mobilního prohlížeče, kde nasazení virtuální klávesnice nebo panely adresního řádku tlačily vstupní sekci chatu mimo obrazovku.
* **Obrany layoutu proti flex-shrinkage:** Zpevněn chat input layout (`#input-area` a `#file-name-display`) explicitním definováním `flex-shrink: 0`. Přísně zaručuje, že kontejner uživatelského vstupu si zachová rozměry a viditelnost i při plnění wrapper kontextu chatu těžkými systémovými logy.
* **Refaktorování víceřádkového záhlaví:** Refaktorován core blok `<header>` pro zrušení jeho striktního omezení `55px` na mobilních obrazovkách. Nyní automaticky zabalí do dvou odlišných, vertikálně naskládaných řádků při omezeném prostoru, udržujíc podstatné elementy, odznáčky a ikony rychlých akcí dokonale zarovnané.
* **Automatický kontext zachycení menu:** Injektován globální event handler mapper do frontendového životního cyklu. Klepnutí na libovolné akční tlačítko, rozbalení stromu log adresáře nebo připojení konkrétního bloku souboru okamžitě vynutí zavření mobilního postranního draweru, vrátí fokus zpět na živou terminálovou konzoli.

## 2026.05.002

**Souhrn:** Pokročilá vlákna diagnostika, kompatibilita Vector DB pro přísná prostředí a OS Watchdog Heartbeats.

### Funkce a vylepšení

* **Patchování ChromaDB pro enterprise prostředí:** Vyřešen kritický problém blokování spouštění, kde standardním systémovým prostředím chyběla moderní databázová rozšíření vyžadovaná vektorovým znalostním enginem. Sentinel nyní zachycuje inicializační cestu v `__main__.py` a `rag.py` pro dynamickou substituci výchozího platformního modulu za `pysqlite3`.
* **Asynchronní pool vektorové indexace:** Přesunuty těžké kroky načítání textových chunků a kompilace indexu uvnitř `rag.py` do oddělené asynchronní background smyčky (`_ingest_worker`). Zajišťuje, že živé webové rozhraní může okamžitě přijímat dotazy uživatelů na portu `5050` i při aktivním zpracovávání obrovských vícemagabajtových administrátorských dokumentačních složek do vektorů.
* **Synchronizace stavu Systemd Service:** Vylepšena viditelnost runtime na pozadí navázáním přímé socket integrace s OS init systémem. Proces nyní odesílá operační telemetrické příznaky (`READY=1`) po dokončení fáze self-check a udržuje pravidelné heartbeat kontroly (`WATCHDOG=1`) pro zabránění vynuceným killům supervisora systemd service.

### Opravy chyb a refaktorování

* **Diagnostický dump před zabitím:** Upgradován interní webový UI supervisor skript pro monitorování zdraví připojení. Při vícenásobném výpadku komunikace po sobě watchdog systém automaticky zachytí plný volatilní footprint přes `get_ram_usage()` a spustí snapshot stack-trace threadu (`dump_stack_traces()`) před bezpečným restartem service instance.

## 2026.05.001

**Souhrn:** Dekuplování core do plugin architektury, ekosystém externích pluginů, unifikovaná podpora OS a telemetrický engine.

### Funkce a vylepšení

* **Transformace do oddělené architektury:** Provedena major systémová refaktorizace eliminující veškerou pevně zakódovanou logiku monitorování infrastruktury a operačního systému z core binárního distribučního stromu. Engine byl kompletně převeden na čistý, rozšiřitelný framework řízený výhradně standardními konfiguracemi a dynamickými hooky.
* **Repozitáře externího ekosystému:** Zřízen samostatný distribuční repozitář `sentinel-plugins`. Předdefinované systémové detektory (jako správci Slurm, watchdogy teploty a monitorování autentizace) nyní sídlí externě, umožňujíc systémovým administrátorům konstruovat, distribuovat a aktualizovat vlastní pluginy nezávisle.
* **Automatizovaný deployment a onboarding toolchain:** Navržen specializovaný inicializační nástroj (`sentinel_init.py`). Skript kompletně automatizuje vyhodnocení cílového serveru, nastavení oprávnění adresářů, generování konfiguračního skeletonu a synchronizaci standardních pluginů, minimalizujíc manuální chyby nasazení.
* **Unifikovaný cross-OS kompatibilní pipeline:** Standardizovány kódové cesty prostředí napříč enterprise a open-source Linux ekosystémy. Systémové hooky, vazby řízení procesů, memory-mapped logovací pipeline a background watchery byly důkladně zpevněny a ověřeny pro out-of-the-box provoz na RHEL, Debian a Ubuntu.
* **Prediktivní telemetrie a trend engine:** Implementován backend data science tracking framework podložený strukturovaným `telemetry` databázovým schématem uvnitř `state.py` a zpracovávaný přes `analytics.py`.
    * Nasazeny time-series vyhlazovací pipeline pomocí specializovaných klouzavých průměrů pro filtrování erratické telemetrické šumu.
    * Integrovány pokročilé modely trendové analýzy vyžadující těsnou matematickou spolehlivost (`MIN_R_SQUARED = 0.90`) pro mapování trajektorií a alert při persistentním driftu.
    * Umožněny přesné výpočty Time-To-Critical (TTC) pro upozornění operátorů dny předem před saturací souborových systémů nebo driftem hardwarových metrik mimo zdravé hranice.
* **Izolace životnosti akčních bloků:** Zaveden dedikovaný garbage collection cyklus (`action_cleanup_loop`) běžící paralelně s core službami uvnitř `state.py`. Daemon kontinuálně skenuje relační databázové struktury a automaticky expiruje čekající nápravné návrhy překračující striktní 15-minutové okno, zachovávajíc integritu databáze.

## 2026.01.16

**Souhrn:** Představení Sentinel Commander V2 webového GUI, kontextově-uvědomělé znalostní báze a algoritmů Sniper Search.

### Funkce a vylepšení

* **Pokročilý engine znalostní báze:** Nasazen automatizovaný kompilační pipeline skript (`build_kb.py`) navržený pro systematické parsování raw technických administrátorských souborů ve složce `admindocs/`. Skript odstraňuje non-textové vizuální obálky, optimalizuje bílé mezery a sestavuje konsolidovaný čistý referenční blok (`knowledge_base.txt`).
* **Logika Sniper Hierarchy Search:** Přepracovány backendové vrstvy routování dotazů v `chat_service.py` pro použití víceúrovňové architektury data hunting. Metriky váhy shody jsou posilovány, když výrazy protínají standardní Markdown záhlaví, zatímco přísné filtry mapování infrastruktury odstraňují volatilní log stopy pro zamezení kontaminace LLM kontextu.
* **Sentinel Commander V2 Frontend architektura:** Vypracován komplexní blueprint webového rozhraní operující přes Socket.IO připojení na portu `5050`. Responzivní tmavý/světlý operační dashboard exposuje real-time statistiky stavu a konzole pro okamžitou interakci.
* **Překlad přirozeného jazyka příkazů:** Injektovány střední překladové vrstvy schopné mapovat vícejazyčný operační vstup přímo na předvídatelné systémové příkazové čipy (`STAV`, `LOG`, `INFO`), zjednodušující zpracování dotazů na více clusterech.
* **Vylepšení MS Teams zpráv:** Upgradovány systémové background notifikace pro mapování přímo na bohaté HTML struktury, vylepšujíc rozvržení zpráv explicitními záhlavími a sledovacími kontexty.

### Opravy chyb a refaktorování

* **Detekce chlazení case-insensitive s debouncingem:** Zpevněny handlery alertů chladicího systému uvnitř `detectors.py` pro zpracování nestrukturovaného vstupu case-insensitivně, podpíraje kontroly přechodů stavu interním čítačem pro zamezení alert flappingu.
* **Prompty pro zabránění halucinacím:** Přepracovány interní systémové prompt omezení pro nucení integrovaných LLM modelů k přísným odpovědím na základě vložených vektorových segmentů, zamítajíce nepodložené kontextové předpoklady.

## 2026.01.02

**Souhrn:** Standardizace bohatých Teams notifikací, granulární klasifikátory zneužití výpočetních zdrojů a cluster-aware Slurm tracking.

### Funkce a vylepšení

* **Strategie bohatých vizuálních notifikací:** Kompletně refaktorovány background komunikační vrstvy uvnitř `utils.py` pro použití rozšiřitelného slovníkového mapovacího modulu. Odchozí alerty nyní automaticky bundlují relevantní kontextové operační symboly (🚨, ⚠️, ✅) a specifická barevná schémata.
* **Granulární trackery zneužití výpočetních uzlů:** Upgradovány výpočetní monitorovací pipeline pro aktivní sledování log stop emitovaných z `cluster-login-compute.py`. Aktualizovaný parser čistě extrahuje klasifikační rozsahy, měří hranice zdrojů a označuje prioritní události explicitním příznakem `CRITICAL LOGIN ABUSE`.
* **Host-aware Slurm Reboot Reporting:** Refaktorována interní mechanika sledování restartu clusteru (`detect_slurm_reboot`) pro extrakci strukturálních topologických kontextů z hostname serverů. Změna umožňuje jemné sledování přechodů strojů napříč regiony infrastruktury (např. Karolina, Barbora) a přímé hlášení zaseknutých stavů.
* **Potlačení šumu administrátorských alertů:** Aktualizován modul správce stavu (`state.py`) pro udržování distribučních smyček notifikací prázných od "Resolved" status zpráv napříč root administrátorskými cestami.

## 2025.12.10

**Souhrn:** Integrace monitorování konektivity HPC, dynamická náprava služeb a sledování Git verzí.

### Funkce a vylepšení

* **Monitorování failoveru infrastruktury HPC:** Integrovány automatizované monitorovací vrstvy (`detect_hpc_connectivity`) navržené pro parsování SNMP selhání. Modul sleduje výpadky připojení napříč explicitními seznamy cílů infrastruktury a označuje záznamy jako vyřešené pouze při návratu stabilních datových bloků.
* **Dynamická extrakce nápravy:** Upgradován modul nápravy systému pro obejití rigidních statických řetězců při identifikaci chyb služby. Systém využívá automatizované regulární výrazy pro zachycení přesného selhávajícího cíle daemona (např. `netcfg.service`) a předání přímo do logiky nápravy.
* **Automatizované sledování Git verzování:** Injektovány kódové cesty do `config.py` dotazující lokální repozitářový strom při spuštění aplikace. Funkce automaticky načítá krátký Git SHA identifikátor (`SUBVERSION`), tiskne ho do systémových logovacích pipeline a webových zápatí pro audit tracking.
* **Dvoúrovňová logika environmentálního varování:** Rozšířeny bezpečnostní wrappery hardwarových senzorů vytvořením odlišného dvoúrovňového pipeline vyhodnocování prahů. Stavy deplece kyslíku pod `14.2%` spouštějí prioritní varování nebezpečnosti, zatímco standardní high-boundary variance jsou vyhodnocovány nezávisle.

## 2025.12.08

**Souhrn:** Spuštění autonomních AI nápravných návrhů a kontextového sledování stavu clusteru.

### Funkce a vylepšení

* **Engine nápravných návrhů (`actions.py`):** Vytvořen zcela nový automatizovaný operační modul. Místo generování prostých textových chybových alertů Sentinel nyní odesílá raw telemetrii záznamů přímo do interních Ollama worker pipeline pro konstrukci explicitních nápravných provozních návrhů.
* **Izolované sandbox autorizační smyčky:** Nakonfigurovány nápravné řídící toky pro směrování všech navrhovaných terminálových spouštěcích skriptů do izolovaných evaluačních kanálů, zajišťujíc inspekci a ověření kódových sekvencí systémovými administrátory před spuštěním.
* **Kontextové sledování log segmentů:** Přepracovány stavové stroje parsování `detect_cluster` pro dynamické sledování aktivních blokových rozsahů (jako Mounts, SSSD nebo IB kontroly), zajišťujíc hlášení chyb spolu s jejich technickým sub-komponentním kontextem.

## 2025.12.05

**Souhrn:** Refaktorizace sledování záznamů, kontroly ECC chyb s debouncingem a ochrana před rotací logů.

### Funkce a vylepšení

* **Granulární životní cyklus sledování záznamů:** Přepracováno systémové sledování stavu pro izolaci problémů na konkrétní hostitele, služby nebo deskriptory procesů místo seskupování varování na úrovni broad log souboru.
* **ECC Error Flapping Debounce:** Zpevněny validační rutiny paměťových chyb (`detect_ecc_errors`) zavedením mechanismu debouncingu (`missing_count`). Záznamy jsou nyní bezpečně mazány z aktivního sledování teprve po zmizení ze systémových streamů po 3 po sobě jdoucích spouštěcích smyčkách.
* **State-Aware Log Rotation Handlers:** Přepsány file watchdogy monitorování logů pro čisté přizpůsobení se platformním `logrotate` nasazením. Pozorovatelé sledování souborů zachycují události mazání nebo přealokace, automaticky resetujíc ukazatele pro zamezení mezer ve sledování.

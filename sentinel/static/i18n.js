// Sentinel Commander – i18n (Czech default, English optional)
// Language stored in localStorage key 'sentinel_lang'

const TRANSLATIONS = {
  cs: {
    // ── Sidebar ────────────────────────────────────────────────────────────────
    quick_actions: 'Rychlé akce',
    log_records: 'Záznamy z Logů',
    agent_records: 'Záznamy z Agentů',
    security_records: 'Security záznamy',
    root_records: 'Root záznamy',
    server_info: 'Info o serveru',
    actions_ai: 'Akce & AI Návrhy',
    predictions_trends: 'Predikce & Trendy',
    ignored: 'Ignorované',
    manage_agents: 'Správa Agentů',
    log_groups: 'Skupiny Logů',
    analyze_all_related: 'Analyzovat vše (Souvislosti)',
    analyze_all_separate: 'Analyzovat vše - samostatně',
    active_context: 'Aktivní kontext:',

    // ── Header tooltips ────────────────────────────────────────────────────────
    manage_clients_title: 'Správa připojených klientů',
    manage_agents_title: 'Správa agentů',
    satellites_title: 'Sentinel Satellites: HW zařízení & alert nodes',
    queue_title: 'Počet dotazů čekajících na zpracování',
    rag_title: 'Stav znalostní báze (RAG)',
    log_records_title: 'Záznamy z LOG souborů',
    agent_reports_title: 'Hlášení z agentů',
    root_sessions_title: 'Aktivní root shell relace',
    security_title: 'Bezpečnostní incidenty (Fail2ban, CVE, Porty)',
    toggle_theme: 'Přepnout režim',
    enable_notifications: 'Zapnout upozornění',
    disable_notifications: 'Vypnout upozornění',
    logout: 'Odhlásit',
    attach_to_chat: 'Připojit k chatu',
    analyze: 'Analyzovat',
    upload_file: 'Nahrát vlastní soubor',
    mqtt_loading: 'MQTT Broker: Načítám status...',
    teams_active: 'MS Teams Integration: Aktivní',
    teams_disabled: 'MS Teams Integration: Vypnuto',
    ha_active: 'Home Assistant Integration: Aktivní',
    ha_disabled: 'Home Assistant Integration: Vypnuto',

    // ── Input ──────────────────────────────────────────────────────────────────
    input_placeholder: 'Zadejte dotaz nebo příkaz...',

    // ── Confirm modal ──────────────────────────────────────────────────────────
    confirm_action: 'Potvrzení akce',
    confirm_question: 'Opravdu chcete provést tento příkaz?',
    cluster_label: 'Cluster:',
    cancel: 'Zrušit',
    execute_btn: 'Provést',
    close: 'Zavřít',
    close_window: 'Zavřít okno',
    back: 'Zpět',

    // ── Log modal ─────────────────────────────────────────────────────────────
    select_log: 'Vyberte log...',

    // ── Predictions modal ─────────────────────────────────────────────────────
    predictions_title: 'Predikce & Trendy (posledních 24h)',

    // ── Graph modal ───────────────────────────────────────────────────────────
    metric_detail: 'Detail metriky',

    // ── Agent modal ───────────────────────────────────────────────────────────
    register_new_agent: 'Registrace nového agenta',
    agent_hostname_placeholder: 'Zadejte hostname cílového serveru (např. kcn-01)...',
    generate_token: 'Generovat Token',
    registered_daemons: 'Registrovaní démoni',
    last_heartbeat: 'Poslední odezva (Heartbeat)',
    reporting_col: 'Hlášení',
    actions_col: 'Akce',

    // ── SA / Satellites modal ──────────────────────────────────────────────────
    register_alert_node: 'Registrace nového Alert Node',
    alert_node_placeholder: 'Např. sentinel-alert-lab, sentinel-alert-customer-a...',
    register_btn: 'Registrovat',
    last_heartbeat_sa: 'Poslední heartbeat',
    alerts_col: 'Alerty',
    no_agents_registered: 'Žádní agenti registrováni.',
    agents_modal_title: 'Správa sítě',
    agents_tab: 'Agenti',
    alert_nodes_tab: 'Alert Nodes',
    hw_tab: 'Spolupracovníci',
    other_collaborator_tab: 'Spolupracovníci',
    register_hw_device: 'Registrace nového spolupracovníka',
    hostname_no_prefix: 'Hostname (libovolný)',
    hw_hostname_placeholder: 'Např. parking-cam-01, bedroom-sensor...',
    webui_url_optional: 'Web UI URL (volitelné)',
    no_hw_registered: 'Žádný spolupracovník registrován.',

    // ── Device detail / generic ────────────────────────────────────────────────
    device_detail: 'Detail zařízení',
    loading: 'Načítám…',
    loading_dots: 'Načítám...',

    // ── SA Credentials modal ───────────────────────────────────────────────────
    connection_credentials: 'Připojovací údaje',
    copy_url: 'Kopírovat URL',
    copy_token: 'Kopírovat Token',
    token_warning: '⚠️ Pozor: Token se zobrazí pouze teď. Ulož si jej bezpečně.',

    // ── About modal ───────────────────────────────────────────────────────────
    about_sentinel: 'O systému Sentinel',
    author_label: 'Autor:',
    contact_label: 'Kontakt:',
    source_repo_sentinel: 'Zdrojový repozitář - Sentinel:',
    source_repo_plugins: 'Zdrojový repozitář - Plugins:',

    // ── Pending actions modal ──────────────────────────────────────────────────
    no_pending_actions: 'Žádné čekající akce.',
    command_col: 'Příkaz',
    reason_col: 'Důvod',

    // ── Client modal ──────────────────────────────────────────────────────────
    connected_clients: 'Připojení Klienti',
    user_col: 'Uživatel',
    ip_isp_col: 'IP Adresa / ISP',
    connected_since_col: 'Připojen od',

    // ── Direct chat ───────────────────────────────────────────────────────────
    write_message: 'Napište zprávu...',

    // ── Dashboard ─────────────────────────────────────────────────────────────
    dashboard: 'Dashboard',
    dash_total_alerts: 'Aktivní alerty',
    dash_snoozed: 'Odloženo',
    dash_agents: 'Agenti',
    dash_pending: 'Čekající akce',
    dash_ai_queue: 'AI fronta',
    dash_ai_latency: 'AI latence',
    dash_ai_requests: 'AI dotazů',
    dash_uptime: 'Uptime',
    dash_cpu: 'CPU',
    dash_ram: 'RAM',
    dash_disk: 'Disk',
    dash_top_plugins: 'Nejaktivnější pluginy (dnes)',
    dash_recent: 'Nedávné alerty',
    dash_trend: 'Trend alertů (7 dní)',
    dash_channel_dist: 'Distribuce kanálů',
    dash_no_issues: 'Žádné aktivní alerty',
    dash_no_plugins: 'Žádná data',
    dash_online: 'online',
    dash_offline: 'offline',
    dash_version: 'Verze',

    // ── Issue comments ─────────────────────────────────────────────────────────
    comments_title: 'Komentáře',
    comments_no_comments: 'Zatím žádné komentáře. Buďte první!',
    comments_add_ph: 'Napište komentář...',
    comments_add_btn: 'Přidat',
    comments_delete_confirm: 'Smazat tento komentář?',
    comments_load_error: 'Chyba při načítání komentářů.',
    comments_add_error: 'Chyba při přidávání komentáře.',
    comments_empty_error: 'Komentář nemůže být prázdný.',

    // ── Root audit modal ───────────────────────────────────────────────────────
    root_audit_title: 'Root Audit — Historie relací',
    no_root_sessions: 'Žádné root relace v historii.',
    from_ip: 'Z IP',
    connected_col: 'Připojen',
    state_col: 'Stav',
    disconnected_col: 'Odpojen',
    duration_col: 'Délka',
    showing_max_100: 'Zobrazeno max. 100 posledních záznamů.',
    root_active_badge: 'AKTIVNÍ',
    root_audit_export_csv: 'Export CSV',
    root_audit_active_only: 'Jen aktivní',
    root_audit_stats: '{active} aktivních / {total} celkem',

    // ── JS dynamic messages ────────────────────────────────────────────────────
    comm_error: '⚠️ Chyba komunikace nebo vypršel časový limit.',
    analyze_error: '⚠️ Chyba při analýze.',
    group_analyze_error: '⚠️ Chyba při komplexní analýze skupiny {group}.',
    starting_analysis: 'Spouštím AI analýzu: <b>{filename}</b>',
    starting_complex_analysis: '🧠 Spouštím <b>komplexní analýzu souvislostí</b> pro skupinu <b>{group}</b>...',
    starting_seq_analysis: '🚀 Spouštím postupnou analýzu skupiny <b>{group}</b> ({count} souborů)...',
    context_set: '📎 Kontext nastaven: <b>{filename}</b>',
    connection_error: 'Chyba spojení',
    load_error: 'Chyba načítání dat.',
    alert_title_warn: '⚠️ ({count}) POZOR!',
    new_error_title: '🔴 Nová chyba!',
    mqtt_connected: 'MQTT Broker: Připojeno',
    mqtt_disconnected: 'MQTT Broker: Odpojeno / Chyba',
    mqtt_disabled_cfg: 'MQTT Broker: Vypnuto v konfiguraci',
    delete_agent_title: 'Smazat agenta',
    api_comm_error: 'Chyba komunikace s API.',
    api_write_error: 'Chyba komunikace při zápisu na API.',
    confirm_remove_agent: 'Opravdu chcete odebrat agenta ze serveru {hostname}? Uzel ztratí oprávnění pushovat data.',
    remove_failed: 'Odebrání selhalo.',
    api_error: 'Chyba API.',
    enter_valid_hostname: 'Zadejte platný hostname cílového uzlu.',
    token_generated: '<strong>Klíč vygenerován úspěšně!</strong><br><br>Token: <u>{token}</u><br><br><span style="color:#888;">Zkopírujte si tento token do konfigurace agenta. Později již nebude zobrazen!</span>',
    register_failed: 'Registrace selhala: {msg}',
    modal_not_found: 'Chyba: Modal element nenalezen. Obnovte stránku.',
    load_error_console: 'Chyba načítání — kontroluj prohlížeč console (F12).',
    load_error_detail: 'Chyba načítání: {msg}',
    registration_error: 'Chyba registrace: {msg}',
    confirm_delete_agent: "Smazat agenta '{hostname}' ze záznamu? Bude muset znovu zaregistrován.",
    issues_title_agent: 'Incident Matrix: Vzdálení Agenti',
    issues_title_root: 'Audit Relací: Aktivní ROOT terminály',
    issues_title_security: 'Security Center: Zranitelnosti a Hrozby',
    issues_title_infra: 'Incident Matrix: Záznamy z Log souborů',
    loading_db: 'Načítám data z databáze...',
    api_sentinel_error: 'Chyba komunikace s API Sentinelu.',
    no_clients: 'Nejsou připojeni žádní externí klienti.',
    local_network: 'Lokální / Interní síť',
    finding_isp: 'Hledám ISP...',
    unknown_isp: 'Neznámý ISP',
    isp_unavailable: 'ISP nedostupné',
    direct_chat_device: 'Přímý chat na toto zařízení',
    last_ping: 'Poslední ping: {time}',
    p2p_chat_notice: 'Nová relace chatu P2P. Zprávy nejsou ukládány na server.',
    disconnected: 'Odpojen',
    root_audit_load_error: 'Chyba při načítání Root Auditu:',
    delete_btn: 'Smazat',
    confirm_delete_hw: "Smazat HW zařízení '{hostname}'?",
    active_incidents: 'Aktivní incidenty',
    sensors_live: 'Senzory (live)',
    no_active_incidents: 'Žádné aktivní incidenty.',
    load_incidents_error: 'Nepodařilo se načíst incidenty: {msg}',
    webui_unavailable: 'Web UI nedostupné: {msg}',
    api_connection: 'API připojení',
    connected_status: '✓ Připojeno',
    not_connected_status: '✗ Nepřipojeno',
    light_label: 'Světlo',
    presence_label: 'Přítomnost',
    presence_detected: '● Detekováno',
    presence_none: '○ Nic',
    incidents_label: 'Incidenty',
    state_label: 'Stav',
    name_label: 'Název',
    notifications_label: 'Notifikace',
    active_status: '⚠ Aktivní',
    model_switch_error: 'Chyba přepnutí modelu: {msg}',
    checking_clients: 'Zjišťuji stav klientů...',
    confirm_reject_proposal: 'Zamítnout AI návrh #{id}?',
    mobile_device: 'Mobilní zařízení',
    desktop_device: 'Stolní počítač',
    operation_in_progress: 'Probíhá jiná operace.',

    // ── Status / loading states ────────────────────────────────────────────────
    timeout_label: 'Vypršel čas!',
    online_status: 'Online',
    offline_status: 'Offline',
    lines_count: 'řádků',
    reading_file: 'Čtu soubor...',
    file_empty: 'Soubor je prázdný.',
    loading_telemetry: 'Načítám telemetrii...',
    no_data_yet: 'Zatím nejsou nasbírána data (systém čeká na první 5min snapshot).',
    expired: 'EXPIROVÁNO',
    expires_in: 'Vyprší za: {time}',
    system_snapshot: 'SYSTÉMOVÝ SNÍMEK',
    loading_agents: 'Načítám registrované agenty...',
    no_agents_registered_table: 'Zatím nebyli zaregistrováni žádní vzdálení agenti.',
    api_load_error: 'Selhalo načítání dat API endpointu.',
    token_shown_once: '(token se zobrazuje pouze při generování)',
    no_rules_yet: 'Zatím nejsou definována žádná pravidla.',
    rules_load_error: 'Chyba načítání: {msg}',
    data_load_failed: 'Nepodařilo se načíst data',

    // ── Bulk select / export ───────────────────────────────────────────────────
    selected_count: '{count} vybráno',
    bulk_select: 'Výběr',
    bulk_select_all: 'Vše',
    bulk_ignore_btn: 'Ignorovat',
    export_markdown: 'Export Markdown',
    export_csv: 'Export CSV',
    print_report: 'Report',
    report_filter_title: 'Report — Filtr',
    report_select_all: 'Vše',
    report_select_none: 'Žádné',
    report_generate: 'Otevřít report',

    // ── KB Reindex ─────────────────────────────────────────────────────────────
    kb_reindexing: 'Reindexuji...',
    kb_reindex_started: 'Spuštěno',
    kb_reindex_label: 'KB Reindex',
    kb_choose_file: 'Vybrat soubor',
    kb_drop_hint: 'Přetáhněte soubory nebo klikněte pro výběr',
    kb_indexed_files: 'Indexované soubory',
    no_active_plugins_issues: 'Žádné aktivní pluginy s incidenty',

    // ── Settings modal ─────────────────────────────────────────────────────────
    settings_load_failed: 'Nepodařilo se načíst konfiguraci',
    settings_saved: '✓ Uloženo a aplikováno.',
    settings_applied_memory: '⚠ Aplikováno v paměti. {msg}',
    settings_save_error: 'Chyba ukládání.',
    settings_network_error: 'Chyba sítě.',

    // ── Pending actions ────────────────────────────────────────────────────────
    confirm_execute_action: 'Spustit akci #{id} nyní na cílovém systému?',
    executed_ok: '✅ Spuštěno.',
    confirm_delete_action: 'Smazat čekající akci #{id}?',
    delete_failed: 'Smazání selhalo.',
    confirm_delete_rule: 'Smazat toto pravidlo?',
    execute_title: 'Spustit nyní',
    edit_command_title: 'Upravit příkaz',
    reanalyze_title: 'Znovu analyzovat s AI',
    mark_reviewed_title: 'Označit jako zkontrolované',
    rule_delete_btn: 'Smazat',
    fail_add_rule: 'Nepodařilo se přidat pravidlo.',

    // ── Notifications ──────────────────────────────────────────────────────────
    notifications_on_title: 'Vypnout upozornění',
    notifications_off_title: 'Zapnout upozornění',

    // ── Welcome message ────────────────────────────────────────────────────────
    welcome_commands_header: 'Dostupné příkazy:',
    welcome_cmd_status: '<b>stav</b> — přehled aktivních a ověřovaných problémů',
    welcome_cmd_pending: '<b>pending</b> — seznam akcí čekajících na váš souhlas',
    welcome_cmd_sys: '<b>sys</b> — stav systémových prostředků a AI modelu',
    welcome_cmd_analyze: '<b>analyzovat [název]</b> — hloubkový AI rozbor logu',
    welcome_cmd_live: '<b>LIVE [dotaz]</b> — dotaz nad aktuálními issues (přidá kontext živého stavu infrastruktury)',

    // ── Maintenance windows (snooze scheduler) ────────────────────────────────
    maint_windows: 'Plánovaná údržba',
    maint_no_rules: 'Žádná pravidla. Přidejte první maintenance window.',
    maint_add_rule: 'Přidat pravidlo',
    maint_name_ph: 'Název (např. Noční údržba)',
    maint_channels_ph: '* nebo INFRA,AGENT',
    maint_hosts_label: 'Hosts (volitelné)',
    maint_start_label: 'Od (h)',
    maint_end_label: 'Do (h)',
    maint_days_ph: '* nebo 0,1,2,3,4 (Po-Pá)',
    maint_active_badge: 'AKTIVNÍ',
    maint_rule_delete_confirm: 'Smazat toto pravidlo?',
    maint_rule_added: 'Pravidlo přidáno.',
    maint_rule_error: 'Chyba při přidávání pravidla.',
    channel: 'Kanál',
    days_label: 'Dny',

    // ── Agent health dashboard ────────────────────────────────────────────────
    agent_health: 'Stav agentů',
    agent_health_online: 'Online',
    agent_health_offline: 'Offline',
    agent_health_24h: '24h',
    agent_health_7d: '7 dní',
    agent_health_total_alerts: 'Celkem alertů',
    agent_health_last_seen: 'Poslední odezva',
    agent_health_last_alert: 'Poslední alert',
    agent_health_no_agents: 'Žádní agenti nejsou registrováni.',
    agent_health_registered: 'Registrován',

    // ── Agent detail ──────────────────────────────────────────────────────────
    agent_detail_title: 'Agent detail',
    agent_detail_info: 'Info',
    agent_detail_alerts: 'Statistiky alertů',
    agent_detail_active_issues: 'Aktivní issues',
    agent_detail_no_issues: 'Žádné aktivní issues',
    agent_detail_lag: 'Data lag',
    agent_detail_version: 'Verze',

    // ── Issue severity ────────────────────────────────────────────────────────
    severity_critical: 'Kritická',
    severity_high: 'Vysoká',
    severity_medium: 'Střední',
    severity_low: 'Nízká',
    severity_set: 'Nastavit prioritu',
    severity_clear: 'Zrušit prioritu',

    // ── Auto-remediation ──────────────────────────────────────────────────────
    autofail_badge: 'AUTO-OPRAVA SELHALA',
    autofail_desc: 'Automatická oprava selhala',
    autofix_validating: 'Auto-oprava probíhá — ověřování',

    // ── Tags ─────────────────────────────────────────────────────────────────
    tag_cloud_title: 'Tag Cloud',
    tag_add: 'Přidat tag',
    tag_no_tags: 'Žádné tagy',
    tag_filter_hint: 'Klikni pro filtrování',

    // ── Batch AI ─────────────────────────────────────────────────────────────
    batch_ai_btn: 'AI Souhrn',
    batch_ai_analyzing: 'Analyzuji…',
    batch_ai_header: 'Batch analýza aktivních alertů',

    // ── Comment templates ─────────────────────────────────────────────────────
    tpl_use: 'Použít šablonu',
    tpl_no_templates: 'Žádné šablony',
    tpl_add: 'Přidat šablonu',

    // ── System errors ─────────────────────────────────────────────────────────
    sys_errors_title: 'Chyby systému',
    sys_errors_none: 'Žádné chyby',

    // ── Host heatmap ──────────────────────────────────────────────────────────
    heatmap_title: 'Heatmap hostů',

    // ── SLA ───────────────────────────────────────────────────────────────────
    sla_breach: 'SLA porušeno',
    sla_warning: 'SLA blíží',

    // ── Config diff ───────────────────────────────────────────────────────────
    config_diff_title: 'Config diff',
    config_diff_ok: 'Config je aktuální',

    // ── SSH modal ─────────────────────────────────────────────────────────────
    ssh_modal_title: 'SSH Akce',
    ssh_run: 'Spustit',
    ssh_allowlist_hint: 'Pouze příkazy z allowlistu',

    // ── Topology ─────────────────────────────────────────────────────────────
    topology_title: 'Síťová mapa agentů',

    // ── Changelog ────────────────────────────────────────────────────────────
    changelog_title: 'Changelog',

    // ── Pattern editor ───────────────────────────────────────────────────────
    patterns_title: 'Pattern Editor',
    patterns_add: 'Přidat pattern',
    patterns_test: 'Testovat',

    // ── Health history ───────────────────────────────────────────────────────
    health_history_title: 'Health Score — Historie',

    // ── Recurring ────────────────────────────────────────────────────────────
    recurring_tag: 'Opakující se issue (3×/24h)',

    // ── Dashboard layout ─────────────────────────────────────────────────────
    dash_layout: 'Rozložení widgetů',

    // ── Alert timeline ────────────────────────────────────────────────────────
    alert_timeline: 'Časová osa alertů',
    timeline_heatmap_title: 'Rozložení alertů (hodiny × dny)',
    timeline_daily_title: 'Denní přehled alertů',
    timeline_busiest_day: 'Nejaktivnější den',
    timeline_busiest_hour: 'Nejaktivnější hodina',
    timeline_total: 'Celkem alertů',
    timeline_days_7: '7 dní',
    timeline_days_14: '14 dní',
    timeline_days_30: '30 dní',

    // ── Plugin stats ──────────────────────────────────────────────────────────
    plugin_stats: 'Plugin Statistiky',
    plugin_col: 'Plugin',
    today_col: 'Dnes',
    week_col: '7 dní',
    total_col: 'Celkem',
    last_seen_col: 'Naposledy',

    // ── Live log tail ─────────────────────────────────────────────────────────
    live_tail: 'Živý přenos logu',
    live_tail_btn: 'Živý přenos',
    live_tail_connecting: 'Připojuji...',
    live_tail_connected: 'Připojeno',
    live_tail_live: 'Živě',
    live_tail_reconnecting: 'Odpojeno, znovu připojuji...',
    live_tail_autoscroll: 'Auto-scroll',

    // ── Language button ────────────────────────────────────────────────────────
    lang_switch_label: 'EN',

    // ── New modals & features ──────────────────────────────────────────────────
    tools_modal_btn: 'Monitoring & Nástroje',
    tools_modal_title: 'Monitoring & Nástroje',
    rag_info_title: 'Znalostní báze (RAG)',
    rag_provider: 'Provider',
    rag_model: 'Model',
    rag_docs: 'Dokumenty',
    rag_chunks: 'Fragmenty',
    queue_details_title: 'Fronta požadavků',
    queue_pending: 'Čeká ve frontě',
    queue_workers: 'Pracovní vlákna',
    queue_latency: 'AI latence',
    queue_total_req: 'Celkem požadavků',
    history_title: 'Historie změn',
    role_mgmt_title: 'Správa rolí uživatelů',
    role_badge_title: 'Správa rolí',
    role_contact_admin: 'Pro změnu role kontaktujte hlavního správce (superadmin).',
    role_add_user: 'Přidat uživatele / změnit roli',
    role_username_ph: 'Uživatelské jméno...',
    role_username_required: 'Zadejte uživatelské jméno.',
    role_saved: '✓ Role uložena.',
    integration_title: 'Integrace',
    integration_toggle_desc: 'Správa integrace {name}. Klikněte pro přepnutí stavu.',
    integration_toggle_btn: 'Přepnout stav',
    integration_toggled: 'Integrace {state}.',
    enabled: 'aktivována',
    disabled: 'deaktivována',
    yes: 'Ano',
    no: 'Ne',
    int_status: 'Stav',
    int_connected: 'Připojeno',
    int_disconnected: 'Odpojeno',
    int_user: 'Uživatel',
    int_topic_prefix: 'Topic prefix',
    int_notify_service: 'Notify service',
    int_token: 'Token nastaven',
    int_channels: 'Počet kanálů',
    int_channel_names: 'Kanály',
    int_secret: 'Secret nastaven',
    ignored_empty: 'Žádné ignorované záznamy.',
    unignore_btn: 'Sledovat',
    no_data: 'Žádná data.',
    error_generic: 'Nastala chyba. Zkuste znovu.',
    kb_reindex_desc: 'Přeindexuje znalostní bázi z ./docs a ./admindocs.',
    refresh: 'Obnovit',
    clear_console: 'Vymazat konzoli',
    welcome_intro: 'Jsem váš autonomní asistent pro správu systémů. Monitoruji infrastrukturu v reálném čase a pomáhám diagnostikovat incidenty.',
    // ── Token modal ──────────────────────────────────────────────────────────
    token_modal_title: 'Token agenta',
    token_modal_copy: 'Kopírovat',
    token_modal_copied: 'Zkopírováno!',
    token_modal_note: 'Uložte token nyní – nezobrazí se znovu.',
    // ── Viewer role ───────────────────────────────────────────────────────────
    viewer_readonly_note: 'Režim prohlížeče — jen čtení',
    viewer_chat_disabled: 'Chat v režimu prohlížeče není dostupný',
    // ── Connection modal ──────────────────────────────────────────────────────
    conn_modal_title: 'Stav spojení',
    conn_section_server: 'Server',
    conn_section_ai: 'AI Engine',
    conn_section_integrations: 'Integrace',
    conn_hostname: 'Hostname',
    conn_listen: 'Naslouchá',
    conn_version: 'Verze',
    conn_uptime: 'Uptime',
    conn_ws_clients: 'WS klienti',
    conn_db_size: 'Velikost DB',
    conn_ai_backend: 'Backend',
    conn_ai_url: 'URL',
    conn_ai_model: 'Model',
    conn_ai_requests: 'Celkem požadavků',
    conn_ai_latency: 'Průměrná latence',
    conn_ai_errors: 'Chyby',
    disabled_status: '— Vypnuto',
    close_btn: 'Zavřít',
    refresh_btn: 'Obnovit',
  },

  en: {
    // ── Sidebar ────────────────────────────────────────────────────────────────
    quick_actions: 'Quick Actions',
    log_records: 'Log Records',
    agent_records: 'Agent Records',
    security_records: 'Security Records',
    root_records: 'Root Records',
    server_info: 'Server Info',
    actions_ai: 'Actions & AI Proposals',
    predictions_trends: 'Predictions & Trends',
    ignored: 'Ignored',
    manage_agents: 'Manage Agents',
    clear_console: 'Clear Console',
    log_groups: 'Log Groups',
    analyze_all_related: 'Analyze All (Related)',
    analyze_all_separate: 'Analyze All - Separately',
    active_context: 'Active context:',

    // ── Header tooltips ────────────────────────────────────────────────────────
    manage_clients_title: 'Manage connected clients',
    manage_agents_title: 'Manage agents',
    satellites_title: 'Sentinel Satellites: HW devices & alert nodes',
    queue_title: 'Number of queries waiting to be processed',
    rag_title: 'Knowledge base status (RAG)',
    log_records_title: 'Records from LOG files',
    agent_reports_title: 'Reports from agents',
    root_sessions_title: 'Active root shell sessions',
    security_title: 'Security incidents (Fail2ban, CVE, Ports)',
    toggle_theme: 'Toggle theme',
    enable_notifications: 'Enable notifications',
    disable_notifications: 'Disable notifications',
    logout: 'Logout',
    attach_to_chat: 'Attach to chat',
    analyze: 'Analyze',
    upload_file: 'Upload custom file',
    mqtt_loading: 'MQTT Broker: Loading status...',
    teams_active: 'MS Teams Integration: Active',
    teams_disabled: 'MS Teams Integration: Disabled',
    ha_active: 'Home Assistant Integration: Active',
    ha_disabled: 'Home Assistant Integration: Disabled',

    // ── Input ──────────────────────────────────────────────────────────────────
    input_placeholder: 'Enter query or command...',

    // ── Confirm modal ──────────────────────────────────────────────────────────
    confirm_action: 'Confirm action',
    confirm_question: 'Are you sure you want to execute this command?',
    cluster_label: 'Cluster:',
    cancel: 'Cancel',
    execute_btn: 'Execute',
    close: 'Close',
    close_window: 'Close window',
    back: 'Back',

    // ── Log modal ─────────────────────────────────────────────────────────────
    select_log: 'Select log...',

    // ── Predictions modal ─────────────────────────────────────────────────────
    predictions_title: 'Predictions & Trends (last 24h)',

    // ── Graph modal ───────────────────────────────────────────────────────────
    metric_detail: 'Metric detail',

    // ── Agent modal ───────────────────────────────────────────────────────────
    register_new_agent: 'Register new agent',
    agent_hostname_placeholder: 'Enter target server hostname (e.g. kcn-01)...',
    generate_token: 'Generate Token',
    registered_daemons: 'Registered daemons',
    last_heartbeat: 'Last response (Heartbeat)',
    reporting_col: 'Reporting',
    actions_col: 'Actions',

    // ── SA / Satellites modal ──────────────────────────────────────────────────
    register_alert_node: 'Register new Alert Node',
    alert_node_placeholder: 'E.g. sentinel-alert-lab, sentinel-alert-customer-a...',
    register_btn: 'Register',
    last_heartbeat_sa: 'Last heartbeat',
    alerts_col: 'Alerts',
    no_agents_registered: 'No agents registered.',
    agents_modal_title: 'Network Management',
    agents_tab: 'Agents',
    alert_nodes_tab: 'Alert Nodes',
    hw_tab: 'Collaborators',
    other_collaborator_tab: 'Collaborators',
    register_hw_device: 'Register new collaborator',
    hostname_no_prefix: 'Hostname (any)',
    hw_hostname_placeholder: 'E.g. parking-cam-01, bedroom-sensor...',
    webui_url_optional: 'Web UI URL (optional)',
    no_hw_registered: 'No collaborator registered.',

    // ── Device detail / generic ────────────────────────────────────────────────
    device_detail: 'Device detail',
    loading: 'Loading…',
    loading_dots: 'Loading...',

    // ── SA Credentials modal ───────────────────────────────────────────────────
    connection_credentials: 'Connection credentials',
    copy_url: 'Copy URL',
    copy_token: 'Copy Token',
    token_warning: '⚠️ Warning: Token is shown only once. Store it securely.',

    // ── About modal ───────────────────────────────────────────────────────────
    about_sentinel: 'About Sentinel',
    author_label: 'Author:',
    contact_label: 'Contact:',
    source_repo_sentinel: 'Source repository - Sentinel:',
    source_repo_plugins: 'Source repository - Plugins:',

    // ── Pending actions modal ──────────────────────────────────────────────────
    no_pending_actions: 'No pending actions.',
    command_col: 'Command',
    reason_col: 'Reason',

    // ── Client modal ──────────────────────────────────────────────────────────
    connected_clients: 'Connected Clients',
    user_col: 'User',
    ip_isp_col: 'IP Address / ISP',
    connected_since_col: 'Connected since',

    // ── Direct chat ───────────────────────────────────────────────────────────
    write_message: 'Type a message...',

    // ── Dashboard ─────────────────────────────────────────────────────────────
    dashboard: 'Dashboard',
    dash_total_alerts: 'Active Alerts',
    dash_snoozed: 'Snoozed',
    dash_agents: 'Agents',
    dash_pending: 'Pending Actions',
    dash_ai_queue: 'AI Queue',
    dash_ai_latency: 'AI Latency',
    dash_ai_requests: 'AI Requests',
    dash_uptime: 'Uptime',
    dash_cpu: 'CPU',
    dash_ram: 'RAM',
    dash_disk: 'Disk',
    dash_top_plugins: 'Most Active Plugins (today)',
    dash_recent: 'Recent Alerts',
    dash_trend: 'Alert Trend (7 days)',
    dash_channel_dist: 'Channel Distribution',
    dash_no_issues: 'No active alerts',
    dash_no_plugins: 'No data',
    dash_online: 'online',
    dash_offline: 'offline',
    dash_version: 'Version',

    // ── Issue comments ─────────────────────────────────────────────────────────
    comments_title: 'Comments',
    comments_no_comments: 'No comments yet. Be the first!',
    comments_add_ph: 'Write a comment...',
    comments_add_btn: 'Add',
    comments_delete_confirm: 'Delete this comment?',
    comments_load_error: 'Error loading comments.',
    comments_add_error: 'Error adding comment.',
    comments_empty_error: 'Comment cannot be empty.',

    // ── Root audit modal ───────────────────────────────────────────────────────
    root_audit_title: 'Root Audit — Session History',
    no_root_sessions: 'No root sessions in history.',
    from_ip: 'From IP',
    connected_col: 'Connected',
    state_col: 'State',
    disconnected_col: 'Disconnected',
    duration_col: 'Duration',
    showing_max_100: 'Showing max. 100 most recent records.',
    root_active_badge: 'ACTIVE',
    root_audit_export_csv: 'Export CSV',
    root_audit_active_only: 'Active only',
    root_audit_stats: '{active} active / {total} total',

    // ── JS dynamic messages ────────────────────────────────────────────────────
    comm_error: '⚠️ Communication error or request timed out.',
    analyze_error: '⚠️ Error during analysis.',
    group_analyze_error: '⚠️ Error during group analysis of {group}.',
    starting_analysis: 'Starting AI analysis: <b>{filename}</b>',
    starting_complex_analysis: '🧠 Starting <b>complex related-log analysis</b> for group <b>{group}</b>...',
    starting_seq_analysis: '🚀 Starting sequential analysis of group <b>{group}</b> ({count} files)...',
    context_set: '📎 Context set: <b>{filename}</b>',
    connection_error: 'Connection error',
    load_error: 'Data load error.',
    alert_title_warn: '⚠️ ({count}) ALERT!',
    new_error_title: '🔴 New error!',
    mqtt_connected: 'MQTT Broker: Connected',
    mqtt_disconnected: 'MQTT Broker: Disconnected / Error',
    mqtt_disabled_cfg: 'MQTT Broker: Disabled in config',
    delete_agent_title: 'Delete agent',
    api_comm_error: 'API communication error.',
    api_write_error: 'API communication error on write.',
    confirm_remove_agent: 'Remove agent from server {hostname}? The node will lose permission to push data.',
    remove_failed: 'Removal failed.',
    api_error: 'API error.',
    enter_valid_hostname: 'Enter a valid target node hostname.',
    token_generated: '<strong>Key generated successfully!</strong><br><br>Token: <u>{token}</u><br><br><span style="color:#888;">Copy this token into the agent config. It will not be shown again!</span>',
    register_failed: 'Registration failed: {msg}',
    modal_not_found: 'Error: Modal element not found. Refresh the page.',
    load_error_console: 'Load error — check browser console (F12).',
    load_error_detail: 'Load error: {msg}',
    registration_error: 'Registration error: {msg}',
    confirm_delete_agent: "Delete agent '{hostname}' from records? It will need to be re-registered.",
    issues_title_agent: 'Incident Matrix: Remote Agents',
    issues_title_root: 'Session Audit: Active ROOT terminals',
    issues_title_security: 'Security Center: Vulnerabilities and Threats',
    issues_title_infra: 'Incident Matrix: Log file records',
    loading_db: 'Loading data from database...',
    api_sentinel_error: 'Sentinel API communication error.',
    no_clients: 'No external clients connected.',
    local_network: 'Local / Internal network',
    finding_isp: 'Looking up ISP...',
    unknown_isp: 'Unknown ISP',
    isp_unavailable: 'ISP unavailable',
    direct_chat_device: 'Direct chat with this device',
    last_ping: 'Last ping: {time}',
    p2p_chat_notice: 'New P2P chat session. Messages are not stored on the server.',
    disconnected: 'Disconnected',
    root_audit_load_error: 'Error loading Root Audit:',
    delete_btn: 'Delete',
    confirm_delete_hw: "Delete HW device '{hostname}'?",
    active_incidents: 'Active incidents',
    sensors_live: 'Sensors (live)',
    no_active_incidents: 'No active incidents.',
    load_incidents_error: 'Failed to load incidents: {msg}',
    webui_unavailable: 'Web UI unavailable: {msg}',
    api_connection: 'API connection',
    connected_status: '✓ Connected',
    not_connected_status: '✗ Not connected',
    light_label: 'Light',
    presence_label: 'Presence',
    presence_detected: '● Detected',
    presence_none: '○ None',
    incidents_label: 'Incidents',
    state_label: 'State',
    name_label: 'Name',
    notifications_label: 'Notifications',
    active_status: '⚠ Active',
    model_switch_error: 'Model switch error: {msg}',
    checking_clients: 'Checking client status...',
    confirm_reject_proposal: 'Reject AI proposal #{id}?',
    mobile_device: 'Mobile device',
    desktop_device: 'Desktop computer',
    operation_in_progress: 'Another operation is in progress.',

    // ── Status / loading states ────────────────────────────────────────────────
    timeout_label: 'Timeout!',
    online_status: 'Online',
    offline_status: 'Offline',
    lines_count: 'lines',
    reading_file: 'Reading file...',
    file_empty: 'File is empty.',
    loading_telemetry: 'Loading telemetry...',
    no_data_yet: 'No data collected yet (waiting for first 5-min snapshot).',
    expired: 'EXPIRED',
    expires_in: 'Expires in: {time}',
    system_snapshot: 'SYSTEM SNAPSHOT',
    loading_agents: 'Loading registered agents...',
    no_agents_registered_table: 'No remote agents registered yet.',
    api_load_error: 'Failed to load API data.',
    token_shown_once: '(token is shown only during generation)',
    no_rules_yet: 'No rules defined yet.',
    rules_load_error: 'Load error: {msg}',
    data_load_failed: 'Could not load data',

    // ── Bulk select / export ───────────────────────────────────────────────────
    selected_count: '{count} selected',
    bulk_select: 'Select',
    bulk_select_all: 'All',
    bulk_ignore_btn: 'Ignore',
    export_markdown: 'Export Markdown',
    export_csv: 'Export CSV',
    print_report: 'Report',
    report_filter_title: 'Report — Filter',
    report_select_all: 'All',
    report_select_none: 'None',
    report_generate: 'Open Report',

    // ── KB Reindex ─────────────────────────────────────────────────────────────
    kb_reindexing: 'Reindexing...',
    kb_reindex_started: 'Started',
    kb_reindex_label: 'KB Reindex',
    kb_choose_file: 'Choose file',
    kb_drop_hint: 'Drag files here or click to select',
    kb_indexed_files: 'Indexed files',
    no_active_plugins_issues: 'No active plugins with issues',

    // ── Settings modal ─────────────────────────────────────────────────────────
    settings_load_failed: 'Failed to load config',
    settings_saved: '✓ Saved and applied.',
    settings_applied_memory: '⚠ Applied in memory. {msg}',
    settings_save_error: 'Error saving.',
    settings_network_error: 'Network error.',

    // ── Pending actions ────────────────────────────────────────────────────────
    confirm_execute_action: 'Execute action #{id} now on the target system?',
    executed_ok: '✅ Executed.',
    confirm_delete_action: 'Delete pending action #{id}?',
    delete_failed: 'Delete failed.',
    confirm_delete_rule: 'Delete this rule?',
    execute_title: 'Execute now',
    edit_command_title: 'Edit command',
    reanalyze_title: 'Re-analyze with AI',
    mark_reviewed_title: 'Mark reviewed',
    rule_delete_btn: 'Delete',
    fail_add_rule: 'Failed to add rule.',

    // ── Notifications ──────────────────────────────────────────────────────────
    notifications_on_title: 'Disable notifications',
    notifications_off_title: 'Enable notifications',

    // ── Welcome message ────────────────────────────────────────────────────────
    welcome_intro: 'I am your autonomous system management assistant. I monitor infrastructure in real time and help diagnose incidents.',
    welcome_commands_header: 'Available commands:',
    welcome_cmd_status: '<b>status</b> — overview of active and validating issues',
    welcome_cmd_pending: '<b>pending</b> — list of actions awaiting your approval',
    welcome_cmd_sys: '<b>sys</b> — system resource and AI model status',
    welcome_cmd_analyze: '<b>analyze [name]</b> — deep AI analysis of a log',
    welcome_cmd_live: '<b>LIVE [query]</b> — query over current issues (adds live infrastructure context)',

    // ── Maintenance windows (snooze scheduler) ────────────────────────────────
    maint_windows: 'Maintenance Windows',
    maint_no_rules: 'No rules yet. Add your first maintenance window.',
    maint_add_rule: 'Add rule',
    maint_name_ph: 'Name (e.g. Nightly maintenance)',
    maint_channels_ph: '* or INFRA,AGENT',
    maint_hosts_label: 'Hosts (optional)',
    maint_start_label: 'From (h)',
    maint_end_label: 'To (h)',
    maint_days_ph: '* or 0,1,2,3,4 (Mon-Fri)',
    maint_active_badge: 'ACTIVE',
    maint_rule_delete_confirm: 'Delete this rule?',
    maint_rule_added: 'Rule added.',
    maint_rule_error: 'Error adding rule.',
    channel: 'Channel',
    days_label: 'Days',

    // ── Agent health dashboard ────────────────────────────────────────────────
    agent_health: 'Agent Health',
    agent_health_online: 'Online',
    agent_health_offline: 'Offline',
    agent_health_24h: '24h',
    agent_health_7d: '7 days',
    agent_health_total_alerts: 'Total alerts',
    agent_health_last_seen: 'Last heartbeat',
    agent_health_last_alert: 'Last alert',
    agent_health_no_agents: 'No agents registered.',
    agent_health_registered: 'Registered',

    // ── Agent detail ──────────────────────────────────────────────────────────
    agent_detail_title: 'Agent detail',
    agent_detail_info: 'Info',
    agent_detail_alerts: 'Alert statistics',
    agent_detail_active_issues: 'Active issues',
    agent_detail_no_issues: 'No active issues',
    agent_detail_lag: 'Data lag',
    agent_detail_version: 'Version',

    // ── Issue severity ────────────────────────────────────────────────────────
    severity_critical: 'Critical',
    severity_high: 'High',
    severity_medium: 'Medium',
    severity_low: 'Low',
    severity_set: 'Set priority',
    severity_clear: 'Clear priority',

    // ── Auto-remediation ──────────────────────────────────────────────────────
    autofail_badge: 'AUTO-REMEDIATION FAILED',
    autofail_desc: 'Automatic remediation failed',
    autofix_validating: 'Auto-remediation running — validating',

    // ── Tags ─────────────────────────────────────────────────────────────────
    tag_cloud_title: 'Tag Cloud',
    tag_add: 'Add tag',
    tag_no_tags: 'No tags yet',
    tag_filter_hint: 'Click to filter',

    // ── Batch AI ─────────────────────────────────────────────────────────────
    batch_ai_btn: 'AI Summary',
    batch_ai_analyzing: 'Analyzing…',
    batch_ai_header: 'Batch analysis of active alerts',

    // ── Comment templates ─────────────────────────────────────────────────────
    tpl_use: 'Use template',
    tpl_no_templates: 'No templates',
    tpl_add: 'Add template',

    // ── System errors ─────────────────────────────────────────────────────────
    sys_errors_title: 'System errors',
    sys_errors_none: 'No errors',

    // ── Host heatmap ──────────────────────────────────────────────────────────
    heatmap_title: 'Host heatmap',

    // ── SLA ───────────────────────────────────────────────────────────────────
    sla_breach: 'SLA breach',
    sla_warning: 'SLA warning',

    // ── Config diff ───────────────────────────────────────────────────────────
    config_diff_title: 'Config diff',
    config_diff_ok: 'Config is up to date',

    // ── SSH modal ─────────────────────────────────────────────────────────────
    ssh_modal_title: 'SSH Action',
    ssh_run: 'Run',
    ssh_allowlist_hint: 'Only allowlisted commands',

    // ── Topology ─────────────────────────────────────────────────────────────
    topology_title: 'Agent Network Map',

    // ── Changelog ────────────────────────────────────────────────────────────
    changelog_title: 'Changelog',

    // ── Pattern editor ───────────────────────────────────────────────────────
    patterns_title: 'Pattern Editor',
    patterns_add: 'Add pattern',
    patterns_test: 'Test',

    // ── Health history ───────────────────────────────────────────────────────
    health_history_title: 'Health Score — History',

    // ── Recurring ────────────────────────────────────────────────────────────
    recurring_tag: 'Recurring issue (3×/24h)',

    // ── Dashboard layout ─────────────────────────────────────────────────────
    dash_layout: 'Widget layout',

    // ── Alert timeline ────────────────────────────────────────────────────────
    alert_timeline: 'Alert Timeline',
    timeline_heatmap_title: 'Alert distribution (hours × days)',
    timeline_daily_title: 'Daily alert overview',
    timeline_busiest_day: 'Busiest day',
    timeline_busiest_hour: 'Busiest hour',
    timeline_total: 'Total alerts',
    timeline_days_7: '7 days',
    timeline_days_14: '14 days',
    timeline_days_30: '30 days',

    // ── Plugin stats ──────────────────────────────────────────────────────────
    plugin_stats: 'Plugin Statistics',
    plugin_col: 'Plugin',
    today_col: 'Today',
    week_col: '7 days',
    total_col: 'Total',
    last_seen_col: 'Last seen',

    // ── Live log tail ─────────────────────────────────────────────────────────
    live_tail: 'Live Log Tail',
    live_tail_btn: 'Live stream',
    live_tail_connecting: 'Connecting...',
    live_tail_connected: 'Connected',
    live_tail_live: 'Live',
    live_tail_reconnecting: 'Disconnected, reconnecting...',
    live_tail_autoscroll: 'Auto-scroll',

    // ── Language button ────────────────────────────────────────────────────────
    lang_switch_label: 'CS',

    // ── New modals & features ──────────────────────────────────────────────────
    tools_modal_btn: 'Monitoring & Tools',
    tools_modal_title: 'Monitoring & Tools',
    rag_info_title: 'Knowledge Base (RAG)',
    rag_provider: 'Provider',
    rag_model: 'Model',
    rag_docs: 'Documents',
    rag_chunks: 'Chunks',
    queue_details_title: 'Request Queue',
    queue_pending: 'Pending in queue',
    queue_workers: 'Worker threads',
    queue_latency: 'AI latency',
    queue_total_req: 'Total requests',
    history_title: 'Changelog',
    role_mgmt_title: 'User Role Management',
    role_badge_title: 'Role management',
    role_contact_admin: 'To change your role please contact the main administrator (superadmin).',
    role_add_user: 'Add user / change role',
    role_username_ph: 'Username...',
    role_username_required: 'Please enter a username.',
    role_saved: '✓ Role saved.',
    integration_title: 'Integration',
    integration_toggle_desc: 'Manage {name} integration. Click to toggle.',
    integration_toggle_btn: 'Toggle state',
    integration_toggled: 'Integration {state}.',
    enabled: 'enabled',
    disabled: 'disabled',
    yes: 'Yes',
    no: 'No',
    int_status: 'Status',
    int_connected: 'Connected',
    int_disconnected: 'Disconnected',
    int_user: 'User',
    int_topic_prefix: 'Topic prefix',
    int_notify_service: 'Notify service',
    int_token: 'Token configured',
    int_channels: 'Channels count',
    int_channel_names: 'Channels',
    int_secret: 'Secret configured',
    ignored_empty: 'No ignored records.',
    unignore_btn: 'Watch',
    no_data: 'No data.',
    error_generic: 'An error occurred. Please try again.',
    kb_reindex_desc: 'Re-index the knowledge base from ./docs and ./admindocs.',
    refresh: 'Refresh',
    // ── Token modal ──────────────────────────────────────────────────────────
    token_modal_title: 'Agent Token',
    token_modal_copy: 'Copy',
    token_modal_copied: 'Copied!',
    token_modal_note: 'Save this token now — it will not be shown again.',
    // ── Viewer role ───────────────────────────────────────────────────────────
    viewer_readonly_note: 'View-only mode — read only',
    viewer_chat_disabled: 'Chat is not available in viewer mode',
    // ── Connection modal ──────────────────────────────────────────────────────
    conn_modal_title: 'Connection Status',
    conn_section_server: 'Server',
    conn_section_ai: 'AI Engine',
    conn_section_integrations: 'Integrations',
    conn_hostname: 'Hostname',
    conn_listen: 'Listening on',
    conn_version: 'Version',
    conn_uptime: 'Uptime',
    conn_ws_clients: 'WS clients',
    conn_db_size: 'DB size',
    conn_ai_backend: 'Backend',
    conn_ai_url: 'URL',
    conn_ai_model: 'Model',
    conn_ai_requests: 'Total requests',
    conn_ai_latency: 'Avg latency',
    conn_ai_errors: 'Errors',
    disabled_status: '— Disabled',
    close_btn: 'Close',
    refresh_btn: 'Refresh',
  },
};

// ── Core API ──────────────────────────────────────────────────────────────────

let currentLang = localStorage.getItem('sentinel_lang') || 'cs';

function t(key, vars) {
  const dict = TRANSLATIONS[currentLang] || TRANSLATIONS.cs;
  let str = (key in dict) ? dict[key] : (TRANSLATIONS.cs[key] ?? key);
  if (vars) {
    str = str.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{${k}}`));
  }
  return str;
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.documentElement.lang = currentLang;
  _updateLangBtn();
}

function toggleLang() {
  currentLang = currentLang === 'cs' ? 'en' : 'cs';
  localStorage.setItem('sentinel_lang', currentLang);
  applyI18n();
}

function _updateLangBtn() {
  const btn = document.getElementById('lang-btn');
  if (btn) btn.textContent = t('lang_switch_label');
}

document.addEventListener('DOMContentLoaded', applyI18n);

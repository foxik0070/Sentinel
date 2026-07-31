"""
462: Diagnostický plán — AI si sama dojde pro data místo hádání.

BEZPEČNOSTNÍ NÁVRH: model NEGENERUJE shell. Vybírá pouze ID z pevného
katalogu read-only příkazů níže. Tím odpadá celá plocha pro injection
i pro „kreativní" destruktivní příkazy — cokoli mimo katalog se zahodí.

Tok:
  1. plan_prompt()      → AI dostane issue + katalog, vrátí seznam ID
  2. resolve_steps()    → ID se přeloží na skutečné příkazy (neznámé se zahodí)
  3. (volající spustí)  → přes actions.run_ssh_command_real(internal=True)
  4. interpret_prompt() → výstupy se vrátí modelu k vyhodnocení
"""

# Katalog — VÝHRADNĚ read-only. Nic, co zapisuje, restartuje nebo maže.
# Klíč je stabilní ID, na které se odkazuje AI; hodnota se nikdy nebere
# z uživatelského ani modelového vstupu.
DIAG_CATALOG: dict[str, dict] = {
    "disk_usage":      {"cmd": "df -h",
                        "desc": "Zaplnění disků"},
    "disk_inodes":     {"cmd": "df -i",
                        "desc": "Vyčerpání inodů (disk hlásí plno i s volným místem)"},
    "big_dirs":        {"cmd": "du -sh /var/* /home/* /tmp/* 2>/dev/null | sort -rh | head -20",
                        "desc": "Největší adresáře — co disk zabírá"},
    "memory":          {"cmd": "free -m",
                        "desc": "Volná paměť a swap"},
    "load":            {"cmd": "uptime",
                        "desc": "Load average a doba běhu"},
    "top_cpu":         {"cmd": "ps -eo pcpu,pmem,pid,comm --sort=-pcpu | head -12",
                        "desc": "Procesy podle CPU"},
    "top_mem":         {"cmd": "ps -eo pmem,pcpu,pid,comm --sort=-pmem | head -12",
                        "desc": "Procesy podle paměti"},
    "failed_units":    {"cmd": "systemctl --failed --no-pager",
                        "desc": "Selhané systemd jednotky"},
    "service_status":  {"cmd": "systemctl status {service} --no-pager -n 20",
                        "desc": "Stav konkrétní služby", "param": "service"},
    "journal_errors":  {"cmd": "journalctl -p err -n 40 --no-pager",
                        "desc": "Poslední chyby v journalu"},
    "journal_service": {"cmd": "journalctl -u {service} -n 40 --no-pager",
                        "desc": "Log konkrétní služby", "param": "service"},
    "listening_ports": {"cmd": "ss -tlnp",
                        "desc": "Naslouchající porty a procesy"},
    "network_ifaces":  {"cmd": "ip -brief addr",
                        "desc": "Stav síťových rozhraní"},
    "dmesg_tail":      {"cmd": "dmesg | tail -40",
                        "desc": "Kernel hlášky (OOM, I/O chyby, hardware)"},
    "mounts":          {"cmd": "mount | grep -vE '^(proc|sysfs|cgroup|tmpfs|devpts)'",
                        "desc": "Připojené souborové systémy"},
    "uptime_reboot":   {"cmd": "who -b",
                        "desc": "Čas posledního startu (nečekaný reboot?)"},
}

# Povolené znaky v parametru — jméno systemd jednotky. Bez mezer a metaznaků,
# takže se do příkazu nedá nic propašovat ani při halucinaci modelu.
_PARAM_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._@-")

MAX_STEPS = 5


def _safe_param(value: str) -> str | None:
    """Ověří parametr (jméno služby). None = nepoužitelný."""
    v = str(value or "").strip()
    if not v or len(v) > 64:
        return None
    return v if set(v) <= _PARAM_OK else None


def catalog_for_prompt() -> str:
    """Katalog v podobě, kterou dostane model.

    ID je v uvozovkách, aby bylo zřejmé, co má model vrátit — bez toho malé
    modely vracely pořadové číslo řádku (ověřeno na qwen2.5-coder:1.5b).
    """
    lines = []
    for cid, item in DIAG_CATALOG.items():
        suffix = "  (vyžaduje parametr 'service')" if item.get("param") else ""
        lines.append(f'- id="{cid}" — {item["desc"]}{suffix}')
    return "\n".join(lines)


def plan_prompt(host: str, plugin: str, message: str, telemetry_note: str = "") -> str:
    """Prompt, kterým AI vybere diagnostické kroky.

    543: `message` pochází z logu, tedy z nedůvěryhodného zdroje — jde do
    promptu ohraničený jako data. Hlavní pojistkou zůstává, že model vybírá
    jen ID z katalogu, ale spoléhat se na jedinou vrstvu je málo.
    """
    from .ai_guard import wrap_untrusted
    safe_message, _ = wrap_untrusted(message, "hláška z logu")
    return (
        "Jsi zkušený SRE. K následujícímu problému vyber diagnostické příkazy, "
        "které pomohou potvrdit nebo vyvrátit příčinu.\n\n"
        f"PROBLÉM:\n[{plugin}] {host}:\n{safe_message}\n"
        f"{telemetry_note}\n"
        f"DOSTUPNÉ PŘÍKAZY (vybírej POUZE z tohoto seznamu, podle ID):\n"
        f"{catalog_for_prompt()}\n\n"
        f"Vyber maximálně {MAX_STEPS} nejrelevantnějších. Nevymýšlej vlastní příkazy.\n"
        'Odpověz POUZE JSON: {"hypothesis": "<příčina, 1 krátká věta>", '
        '"steps": [{"id": "<id z katalogu>", "service": "<jen u příkazů s parametrem>", '
        '"why": "<max 8 slov>"}]}\n'
        "Pole \"why\" musí být VELMI krátké, jinak se odpověď nevejde."
    )


def resolve_steps(raw_steps) -> list[dict]:
    """Přeloží ID od modelu na spustitelné příkazy.

    Neznámá ID, chybějící či nebezpečné parametry a duplicity se ZAHODÍ —
    spustit se může jen to, co je v katalogu.
    """
    out, seen = [], set()
    for step in (raw_steps or [])[:MAX_STEPS * 2]:
        if not isinstance(step, dict):
            continue
        # Tolerantní k formátu ID (mezery, velikost písmen) — modely je rády
        # „hezky" naformátují. Malé modely navíc často vrátí POŘADOVÉ ČÍSLO
        # položky místo jejího ID, tak přijmeme i to. Pořád platí, že projde
        # výhradně položka z katalogu — nic jiného se spustit nedá.
        cid = str(step.get("id") or "").strip().lower()
        item = DIAG_CATALOG.get(cid)
        if not item and cid.isdigit():
            ids = list(DIAG_CATALOG)
            pos = int(cid) - 1                    # katalog číslujeme od 1
            item = DIAG_CATALOG[ids[pos]] if 0 <= pos < len(ids) else None
            if item:
                cid = ids[pos]
        if not item:
            continue
        cmd = item["cmd"]
        param_name = item.get("param")
        param_value = None
        if param_name:
            param_value = _safe_param(step.get(param_name))
            if not param_value:
                continue           # bez platného parametru krok nedává smysl
            cmd = cmd.replace("{" + param_name + "}", param_value)
        if cmd in seen:
            continue
        seen.add(cmd)
        out.append({
            "id": cid,
            "command": cmd,
            "desc": item["desc"],
            "param": param_value,
            "why": str(step.get("why") or "")[:200],
        })
        if len(out) >= MAX_STEPS:
            break
    return out


def interpret_prompt(host: str, message: str, hypothesis: str, results: list) -> str:
    """Prompt, kterým AI vyhodnotí výstupy diagnostiky."""
    from .ai_guard import wrap_untrusted
    blocks = []
    for r in results:
        output = (r.get("output") or "").strip()
        if len(output) > 1500:                       # ať se vejdeme do kontextu
            output = output[:1500] + "\n…(zkráceno)"
        status = "" if r.get("ok") else "  [PŘÍKAZ SELHAL]"
        # 543: výstup příkazu je obsah cizího stroje — do promptu jen jako data.
        safe_out, _ = wrap_untrusted(output or '(prázdný výstup)', "výstup příkazu")
        blocks.append(f"$ {r.get('command')}{status}\n{safe_out}")
    return (
        "Jsi zkušený SRE. Níže je problém, tvá původní hypotéza a skutečné "
        "výstupy diagnostických příkazů z daného stroje.\n\n"
        f"PROBLÉM: {host}: {message}\n"
        f"PŮVODNÍ HYPOTÉZA: {hypothesis or '(žádná)'}\n\n"
        f"VÝSTUPY:\n" + "\n\n".join(blocks) + "\n\n"
        "Vyhodnoť, co data ukazují. Pokud hypotézu vyvracejí, řekni to.\n"
        'Odpověz POUZE JSON: {"confirmed": <true/false/null>, '
        '"finding": "<co data ukázala, 1-3 věty česky>", '
        '"next_step": "<co udělat dál, 1 věta>", "confidence": <0-100>}'
    )

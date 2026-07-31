"""
488: Postupná remediace — nejdřív nejmenší zásah, teprve při neúspěchu větší.

Dosud AI navrhla rovnou to, co ji napadlo — často restart nebo reboot, i když
by stačilo znovu načíst konfiguraci. Tady je pořadí dané pevně: začíná se
pozorováním, pak nejmenší možný zásah, a teprve když se prokáže, že nezabral,
se jde o stupeň výš.

NA ČEM TO STOJÍ:

1. Žebříky jsou PEVNÝ KATALOG. Model vybírá jen situaci, ne příkazy —
   stejně jako u diagnostiky (462). Nemůže tedy „přeskočit" na reboot.

2. Vyšší stupeň se nabídne až když je předchozí OVĚŘENĚ neúspěšný (486).
   Ne „příkaz proběhl", ale „problém se pořád vrací" — jinak by se
   eskalovalo kvůli zásahu, který ještě neměl čas zabrat.

3. Destruktivní stupně mají `requires_human` a nesmí se spustit samy,
   bez ohledu na to, kolikrát selhaly ty nižší.
"""
import logging

logger = logging.getLogger(__name__)

# Stupeň 1 je vždy pozorování — kolikrát „problém" zmizí sám a jediné, co
# by restart způsobil, je výpadek navíc.
LADDERS: dict[str, dict] = {
    "service_failed": {
        "desc": "Služba neběží nebo spadla",
        "param": "service",
        "steps": [
            {"level": 1, "cmd": "systemctl status {service} --no-pager -n 30",
             "desc": "Zjistit stav a důvod selhání", "readonly": True},
            {"level": 2, "cmd": "journalctl -u {service} -n 100 --no-pager",
             "desc": "Přečíst log služby", "readonly": True},
            {"level": 3, "cmd": "systemctl reload {service}",
             "desc": "Znovu načíst konfiguraci bez výpadku"},
            {"level": 4, "cmd": "systemctl restart {service}",
             "desc": "Restartovat službu (krátký výpadek)"},
            {"level": 5, "cmd": "reboot",
             "desc": "Restart celého stroje", "requires_human": True},
        ],
    },
    "disk_full": {
        "desc": "Došlo místo na disku",
        "steps": [
            {"level": 1, "cmd": "df -h", "desc": "Kde přesně došlo místo", "readonly": True},
            {"level": 2, "cmd": "du -sh /var/* /tmp/* 2>/dev/null | sort -rh | head -20",
             "desc": "Co místo zabírá", "readonly": True},
            {"level": 3, "cmd": "journalctl --disk-usage",
             "desc": "Kolik zabírá journal", "readonly": True},
            {"level": 4, "cmd": "journalctl --vacuum-time=7d",
             "desc": "Zkrátit journal na 7 dní"},
            {"level": 5, "cmd": "systemctl restart rsyslog",
             "desc": "Uvolnit smazané soubory držené logovací službou"},
        ],
    },
    "high_memory": {
        "desc": "Dochází paměť",
        "steps": [
            {"level": 1, "cmd": "free -m", "desc": "Stav paměti a swapu", "readonly": True},
            {"level": 2, "cmd": "ps -eo pmem,pcpu,pid,comm --sort=-pmem | head -12",
             "desc": "Kdo paměť drží", "readonly": True},
            {"level": 3, "cmd": "dmesg | grep -i -m5 'out of memory'",
             "desc": "Zabíjel už kernel procesy?", "readonly": True},
            {"level": 4, "cmd": "systemctl restart {service}",
             "desc": "Restartovat službu, která paměť drží", "param": "service"},
            {"level": 5, "cmd": "reboot", "desc": "Restart stroje", "requires_human": True},
        ],
    },
    "host_unreachable": {
        "desc": "Stroj neodpovídá",
        "steps": [
            {"level": 1, "cmd": "ping -c3 {host}", "desc": "Odpovídá na ICMP?",
             "readonly": True, "param": "host", "run_locally": True},
            {"level": 2, "cmd": "ip -brief addr", "desc": "Stav síťových rozhraní",
             "readonly": True},
            {"level": 3, "cmd": "systemctl restart networking",
             "desc": "Restart síťování (riskuje ztrátu spojení)", "requires_human": True},
            {"level": 4, "cmd": "reboot", "desc": "Restart stroje", "requires_human": True},
        ],
    },
}

_PARAM_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._@-")


def normalize_situation(value) -> str:
    """Uklidí ID kategorie od modelu.

    Malé modely opisují formát z promptu a vracejí `id="host_unreachable"`
    místo holého `host_unreachable` (ověřeno na llama3.2) — stejná past jako
    u pořadových čísel v diagnostice (462). Pořád platí, že projde jen
    položka z katalogu; tohle jen srovná zápis.
    """
    v = str(value or '').strip().lower()
    if v.startswith('id='):
        v = v[3:]
    return v.strip('\'"` \t')


def _safe_param(value) -> str | None:
    v = str(value or "").strip()
    if not v or len(v) > 64:
        return None
    return v if set(v) <= _PARAM_OK else None


def catalog_for_prompt() -> str:
    """Situace, ze kterých model vybírá. Příkazy nevidí — nemá je vybírat."""
    return "\n".join(f'- id="{k}" — {v["desc"]}' for k, v in LADDERS.items())


def plan_prompt(host: str, plugin: str, message: str) -> str:
    return (
        "Jsi zkušený SRE. Zařaď následující problém do jedné z kategorií.\n\n"
        f"PROBLÉM:\n[{plugin}] {host}: {message}\n\n"
        f"KATEGORIE:\n{catalog_for_prompt()}\n\n"
        'Odpověz POUZE JSON: {"situation": "<id>", "service": "<jméno služby, '
        'pokud je z problému zřejmé, jinak prázdné>"}'
    )


def next_step(situation: str, attempts: list, params: dict | None = None) -> dict | None:
    """488: Jaký je další stupeň žebříku.

    `attempts` jsou dosavadní pokusy na tomhle issue (486) — podle nich se
    pozná, co už bylo zkoušeno a jestli to ověřeně selhalo.

    Vrací None, když žebřík došel nebo se čeká na ověření běžícího pokusu.
    """
    ladder = LADDERS.get(normalize_situation(situation))
    if not ladder:
        return None

    tried, pending = set(), False
    for a in attempts or []:
        if not isinstance(a, dict):
            continue
        cmd = a.get('command') or ''
        status = a.get('status')
        if status == 'pending':
            # Nevíme, jestli poslední zásah zabral — eskalovat teď by
            # znamenalo restartovat něco, co se možná právě spravuje.
            pending = True
        if status in ('failed', 'worked', 'uncertain', 'pending'):
            tried.add(cmd)
        if status == 'worked':
            return None            # zabralo, není proč jít výš
    if pending:
        return None

    for step in ladder['steps']:
        cmd = step['cmd']
        need = step.get('param') or (ladder.get('param') if '{' in cmd else None)
        if need:
            val = _safe_param((params or {}).get(need))
            if not val:
                # ZASTAVIT, ne přeskočit. Přeskakování by propadlo na vyšší
                # stupně — a protože `reboot` žádný parametr nemá, chybějící
                # jméno služby by vedlo rovnou k restartu stroje. Přesně to,
                # čemu má žebřík bránit.
                return None
            cmd = cmd.replace('{' + need + '}', val)
        if cmd in tried:
            continue
        return {
            "situation": situation,
            "level": step['level'],
            "command": cmd,
            "desc": step['desc'],
            "readonly": bool(step.get('readonly')),
            "requires_human": bool(step.get('requires_human')),
            "run_locally": bool(step.get('run_locally')),
            "is_last": step is ladder['steps'][-1],
        }
    return None


def plan(situation: str, params: dict | None = None) -> list:
    """Celý žebřík pro přehled v UI — co se stane, když nic nezabere."""
    ladder = LADDERS.get(normalize_situation(situation))
    if not ladder:
        return []
    out = []
    for step in ladder['steps']:
        cmd = step['cmd']
        need = step.get('param') or (ladder.get('param') if '{' in cmd else None)
        if need:
            val = _safe_param((params or {}).get(need))
            if not val:
                continue
            cmd = cmd.replace('{' + need + '}', val)
        out.append({"level": step['level'], "command": cmd, "desc": step['desc'],
                    "readonly": bool(step.get('readonly')),
                    "requires_human": bool(step.get('requires_human'))})
    return out

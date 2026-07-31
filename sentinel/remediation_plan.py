"""
489: Rollback plán — jak změnu vrátit, když nepomůže.
491: Odhad rizika v kontextu — restart databáze není totéž co restart cache.
492: Dry-run diff — u příkazů, co to umí, ukázat co by se stalo.
495: Odhad doby řešení z historie podobných problémů.
497: Batch remediace — stejný problém na N hostech jedním schváleným plánem.
498: Kontrola maintenance okna — nenavrhovat restart produkce v pracovní době.
500: Rozpoznání neřešitelného — co potřebuje fyzický zásah.
502: Prioritizace fronty — podle dopadu × jistoty.
503: Detekce protichůdných akcí — nová akce ruší předchozí.

Co je tu společné: zásah se neposuzuje sám o sobě, ale v kontextu. Tentýž
příkaz je jindy neškodný a jindy výpadek — a rozdíl je v tom, CO restartuje,
KDY a CO se dělo předtím.
"""
import logging
import re
from datetime import datetime, time, timedelta, timezone

logger = logging.getLogger(__name__)


def _parse(value):
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# --- 489 -------------------------------------------------------------------

# Ke každému zásahu opačný krok. Kde opak neexistuje, řekneme to nahlas —
# „nedá se vrátit" je pro rozhodování důležitější informace než mlčení.
_ROLLBACK = [
    (re.compile(r'^systemctl\s+stop\s+(\S+)'), lambda m: f"systemctl start {m.group(1)}",
     "Službu lze znovu spustit."),
    (re.compile(r'^systemctl\s+start\s+(\S+)'), lambda m: f"systemctl stop {m.group(1)}",
     "Službu lze zase zastavit."),
    (re.compile(r'^systemctl\s+disable\s+(\S+)'), lambda m: f"systemctl enable {m.group(1)}",
     "Autostart lze vrátit."),
    (re.compile(r'^systemctl\s+enable\s+(\S+)'), lambda m: f"systemctl disable {m.group(1)}",
     "Autostart lze zase vypnout."),
    (re.compile(r'^systemctl\s+mask\s+(\S+)'), lambda m: f"systemctl unmask {m.group(1)}",
     "Masku lze sejmout."),
    (re.compile(r'^ip\s+link\s+set\s+(\S+)\s+down'), lambda m: f"ip link set {m.group(1)} up",
     "Rozhraní lze zvednout."),
    (re.compile(r'^iptables\s+-A\s+(\S+)(.*)'),
     lambda m: f"iptables -D {m.group(1)}{m.group(2)}", "Pravidlo lze smazat."),
]

# Zásahy, které vrátit NELZE. Tady je upozornění důležitější než návod.
_IRREVERSIBLE = (
    (re.compile(r'\brm\b|\bshred\b|\bwipefs\b'), "Smazaná data se nevrátí."),
    (re.compile(r'\bmkfs|\bfdisk|\bparted'), "Přepsaný souborový systém se nevrátí."),
    (re.compile(r'\bvacuum|--vacuum-time|--vacuum-size'), "Smazané logy se nevrátí."),
    (re.compile(r'\btruncate\b'), "Oříznutý soubor se nevrátí."),
    (re.compile(r'\bdd\b'), "Přepsaná data se nevrátí."),
    (re.compile(r'\bapt-get\s+(remove|purge)|\bapt\s+remove'), "Odinstalovaný balíček je nutné nainstalovat znovu."),
)


def rollback_for(command: str) -> dict:
    """489: Jak zásah vrátit."""
    cmd = str(command or '').strip()
    if not cmd:
        return {"reversible": None, "rollback": None, "note": "Prázdný příkaz."}

    for rx, why in _IRREVERSIBLE:
        if rx.search(cmd):
            return {"reversible": False, "rollback": None,
                    "note": f"NEVRATNÉ: {why} Před spuštěním si ověř, že to je opravdu chtěné."}

    for rx, build, note in _ROLLBACK:
        m = rx.match(cmd)
        if m:
            return {"reversible": True, "rollback": build(m), "note": note}

    if re.match(r'^systemctl\s+(restart|reload)\s+', cmd):
        return {"reversible": True, "rollback": None,
                "note": ("Restart nemá opačný krok — služba už jednou spadla. "
                         "Pokud nepomůže, další krok je diagnostika, ne opakování.")}
    if re.match(r'^reboot|^shutdown', cmd):
        return {"reversible": False, "rollback": None,
                "note": "Restart stroje vrátit nelze; výpadek proběhne tak jako tak."}
    return {"reversible": None, "rollback": None,
            "note": "Opačný krok neznáme — posuď ručně, než to spustíš."}


# --- 491 -------------------------------------------------------------------

# Role služby mění dopad téhož příkazu. Restart cache je nepříjemnost,
# restart databáze je výpadek všeho, co na ní stojí.
_CRITICAL_HINTS = ('mariadb', 'mysql', 'postgres', 'postgresql', 'sshd', 'ssh',
                   'network', 'systemd-networkd', 'nginx', 'haproxy', 'pve',
                   'proxmox', 'lldap', 'ldap', 'docker', 'containerd')
_LOW_IMPACT_HINTS = ('redis', 'memcached', 'cache', 'promtail', 'node-exporter',
                     'telegraf', 'cron', 'logrotate', 'motioneye', 'jellyfin',
                     'navidrome', 'komga', 'audiobookshelf')


def contextual_risk(command: str, base_score: int = 0, dependents: int = 0) -> dict:
    """491: Riziko podle toho, CO se restartuje a kdo na tom závisí.

    Klasifikátor (safety.py) hodnotí tvar příkazu. Tady se přidává význam
    cíle — `systemctl restart` má bodově nula, ale u databáze je to výpadek.
    """
    cmd = str(command or '').lower()
    score = int(base_score or 0)
    reasons = []

    target = ''
    m = re.search(r'systemctl\s+\w+\s+(\S+)', cmd)
    if m:
        target = m.group(1).replace('.service', '')

    if any(h in cmd for h in _CRITICAL_HINTS):
        # Restart databáze nebo síťové služby JE výpadek všeho, co na ní
        # stojí — musí spadnout rovnou do 'high', ne doprostřed škály.
        score += 60
        reasons.append(f"cíl je kritická služba ({target or '?'})")
    elif any(h in cmd for h in _LOW_IMPACT_HINTS):
        reasons.append(f"cíl má omezený dopad ({target or '?'})")
    else:
        score += 10
        reasons.append("význam cíle neznáme")

    if 'ssh' in cmd or 'network' in cmd:
        score += 20
        reasons.append("zásah může přerušit vlastní spojení")

    if dependents:
        score += min(30, dependents * 5)
        reasons.append(f"závisí na tom {dependents} dalších služeb")

    score = max(0, min(100, score))
    return {
        "score": score,
        "level": 'high' if score >= 60 else ('medium' if score >= 30 else 'low'),
        "reasons": reasons,
        "target": target,
    }


# --- 492 -------------------------------------------------------------------

# Příkazy, které umí ukázat dopad, aniž by ho způsobily.
_DRY_RUN = [
    (re.compile(r'^apt-get\s+(install|upgrade|remove|dist-upgrade)(.*)', re.I),
     lambda m: f"apt-get -s {m.group(1)}{m.group(2)}"),
    (re.compile(r'^apt\s+(install|upgrade|remove|full-upgrade)(.*)', re.I),
     lambda m: f"apt-get -s {m.group(1)}{m.group(2)}"),
    (re.compile(r'^rsync\s+(.*)', re.I), lambda m: f"rsync --dry-run {m.group(1)}"),
    (re.compile(r'^mount\s+(.*)', re.I), lambda m: f"mount --fake -v {m.group(1)}"),
    (re.compile(r'^iptables\s+(-[AID].*)', re.I), lambda m: "iptables -L -n --line-numbers"),
    (re.compile(r'^systemctl\s+(restart|reload|stop)\s+(\S+)', re.I),
     lambda m: f"systemctl status {m.group(2)} --no-pager -n 20"),
]


def dry_run_for(command: str) -> dict:
    """492: Náhled dopadu bez dopadu."""
    cmd = str(command or '').strip()
    for rx, build in _DRY_RUN:
        m = rx.match(cmd)
        if m:
            return {"available": True, "command": build(m),
                    "note": "Ukáže, co by se stalo, aniž by to udělalo."}
    return {"available": False, "command": None,
            "note": "Tenhle příkaz náhled neumí — dopad odhadni z rollback plánu."}


# --- 498 -------------------------------------------------------------------

WORK_START = time(8, 0)
WORK_END = time(18, 0)


def in_maintenance_window(now=None, severity: str = '') -> dict:
    """498: Je vhodná doba na rušivý zásah?

    Kritický problém se řeší hned — výpadek už stejně běží. U ostatních
    nemá smysl kvůli tomu shazovat produkci uprostřed pracovního dne.
    """
    now = now or datetime.now(timezone.utc)
    sev = str(severity or '').lower()
    is_weekend = now.weekday() >= 5
    in_hours = WORK_START <= now.time() <= WORK_END and not is_weekend

    if sev in ('critical', 'high'):
        return {"allowed": True, "in_work_hours": in_hours,
                "note": "Závažný problém — výpadek už běží, čekat nemá smysl."}
    if in_hours:
        return {"allowed": False, "in_work_hours": True,
                "note": ("Pracovní doba. Odlož rušivý zásah na večer, nebo si "
                         "vyžádej výslovné schválení.")}
    return {"allowed": True, "in_work_hours": False,
            "note": "Mimo pracovní dobu — zásah je v pořádku."}


# --- 500 -------------------------------------------------------------------

_PHYSICAL = [
    (re.compile(r'\bsmart\b.*\b(fail|bad|pending|reallocat)', re.I), "výměna disku"),
    # Bez `(?<!\w)` se `Current_Pending_Sector` (skutečný název SMART atributu)
    # nechytí — `\b` před „pending" neplatí, protože je před ním podtržítko.
    (re.compile(r'(?<![a-z])(reallocated|pending)[_ ]sector', re.I), "výměna disku"),
    (re.compile(r'\bmedium error|\bI/O error.*\bsd[a-z]', re.I), "výměna disku"),
    (re.compile(r'\bECC\b.*\berror|\bmemory\b.*\buncorrectable', re.I), "výměna paměti"),
    (re.compile(r'\bfan\b.*\b(fail|stopped)|\bthermal.*shutdown', re.I), "servis chlazení"),
    (re.compile(r'\bpower supply|\bPSU\b.*\bfail', re.I), "výměna zdroje"),
    (re.compile(r'\blink down\b|\bcable\b.*\b(unplug|disconnect)', re.I), "kontrola kabeláže"),
    (re.compile(r'\bunreachable via ICMP|\bhost is down', re.I), "možná fyzická nedostupnost"),
]


def needs_physical_intervention(message: str) -> dict:
    """500: Je to problém, který software nevyřeší?

    Nabízet restart u vadného disku je ztráta času a falešná naděje —
    a hlavně to odkládá objednávku náhradního dílu.
    """
    text = str(message or '')
    for rx, what in _PHYSICAL:
        if rx.search(text):
            return {"physical": True, "action": what,
                    "note": (f"Tohle software nevyřeší — potřeba {what}. "
                             f"Automatické zásahy problém jen odloží.")}
    return {"physical": False, "action": None, "note": ""}


# --- 503 -------------------------------------------------------------------

_OPPOSITES = [
    ('start', 'stop'), ('enable', 'disable'), ('mask', 'unmask'),
    ('up', 'down'), ('mount', 'umount'),
]


def conflicts_with(new_command: str, recent_commands, window_min: int = 30,
                   now=None) -> list:
    """503: Ruší nová akce něco, co se právě udělalo?

    Bez tohohle se stane, že jeden zásah službu vypne a druhý ji za minutu
    zapne — a nikdo neví proč.
    """
    now = now or datetime.now(timezone.utc)
    new = str(new_command or '').lower()
    new_target = _target_of(new)
    out = []
    for rec in recent_commands or []:
        if not isinstance(rec, dict):
            continue
        at = _parse(rec.get('at') or rec.get('executed_at') or rec.get('applied_at'))
        if at and (now - at).total_seconds() / 60.0 > window_min:
            continue
        old = str(rec.get('command') or '').lower()
        if not old or _target_of(old) != new_target or not new_target:
            continue
        for a, b in _OPPOSITES:
            if (f' {a} ' in f' {old} ' and f' {b} ' in f' {new} ') or \
               (f' {b} ' in f' {old} ' and f' {a} ' in f' {new} '):
                out.append({"previous": rec.get('command'), "at": rec.get('at'),
                            "note": (f"Tahle akce ruší předchozí ({a}/{b}) na "
                                     f"stejném cíli. Ověř, jestli to je záměr.")})
                break
    return out


def _target_of(command: str) -> str:
    m = re.search(r'(?:systemctl|service)\s+\w+\s+(\S+)', str(command or ''))
    if m:
        return m.group(1).replace('.service', '')
    m = re.search(r'ip\s+link\s+set\s+(\S+)', str(command or ''))
    return m.group(1) if m else ''


# --- 495 -------------------------------------------------------------------

def estimate_resolution_time(issue, history) -> dict:
    """495: Jak dlouho to nejspíš potrvá, podle podobných případů."""
    from .alert_quality import normalize_message
    sig = (issue or {}).get('plugin_name') or ''
    pattern = normalize_message((issue or {}).get('last_line'))
    durations = []
    for h in history or []:
        if not isinstance(h, dict) or h.get('plugin_name') != sig:
            continue
        if normalize_message(h.get('last_line')) != pattern:
            continue
        a, b = _parse(h.get('first_seen')), _parse(h.get('resolved_at'))
        if a and b and b >= a:
            durations.append((b - a).total_seconds() / 60.0)
    if len(durations) < 3:
        return {"known": False, "samples": len(durations),
                "note": "Málo podobných případů na odhad."}
    durations.sort()
    n = len(durations)
    median = durations[n // 2] if n % 2 else (durations[n // 2 - 1] + durations[n // 2]) / 2
    return {"known": True, "samples": n,
            "median_min": round(median, 1),
            "fastest_min": round(durations[0], 1),
            "slowest_min": round(durations[-1], 1),
            "note": (f"Podobný problém se {n}× vyřešil za {median:.0f} min "
                     f"(rozptyl {durations[0]:.0f}–{durations[-1]:.0f}).")}


# --- 502 -------------------------------------------------------------------

_SEV_WEIGHT = {'critical': 100, 'high': 70, 'medium': 40, 'low': 15, '': 20}


def prioritize(issues, playbooks=None, now=None) -> list:
    """502: Seřadí frontu podle dopadu × jistoty řešení.

    Nejvýš patří to, co hodně bolí A víme, jak to spravit — na tom je
    odpracovaná hodina nejlépe využitá.
    """
    now = now or datetime.now(timezone.utc)
    from .playbooks import signature
    known = {p.get('signature') for p in (playbooks or []) if isinstance(p, dict)}

    out = []
    for i in issues or []:
        if not isinstance(i, dict):
            continue
        impact = _SEV_WEIGHT.get(str(i.get('severity') or '').lower(), 20)
        born = _parse(i.get('first_seen'))
        age_h = (now - born).total_seconds() / 3600.0 if born else 0
        impact += min(30, age_h)                    # co visí dlouho, tlačí víc
        if (i.get('recurring_count') or 0) > 1:
            impact += 15                            # opakování = trvalá bolest

        sig = signature(i.get('plugin_name'), i.get('last_line'))
        confidence = 80 if sig in known else 30
        if needs_physical_intervention(i.get('last_line'))['physical']:
            confidence = 5                          # softwarem to nespravíme

        out.append({
            "key": i.get('key'), "host": i.get('host'),
            "plugin_name": i.get('plugin_name'),
            "message": (i.get('last_line') or '')[:120],
            "impact": round(min(150, impact), 1),
            "confidence": confidence,
            "score": round(min(150, impact) * confidence / 100.0, 1),
            "has_playbook": sig in known,
        })
    return sorted(out, key=lambda x: -x['score'])


# --- 497 -------------------------------------------------------------------

def group_for_batch(issues, min_hosts: int = 2) -> list:
    """497: Stejný problém na N hostech — jeden plán místo N schvalování."""
    from .alert_quality import normalize_message
    groups: dict = {}
    for i in issues or []:
        if not isinstance(i, dict):
            continue
        key = (i.get('plugin_name') or '', normalize_message(i.get('last_line')))
        groups.setdefault(key, []).append(i)

    out = []
    for (plugin, pattern), items in groups.items():
        hosts = sorted({i.get('host') for i in items if i.get('host')})
        if len(hosts) < min_hosts:
            continue
        out.append({
            "plugin_name": plugin, "pattern": pattern,
            "hosts": hosts, "host_count": len(hosts),
            "keys": [i.get('key') for i in items if i.get('key')],
            "sample": (items[0].get('last_line') or '')[:160],
            "note": (f"Stejný problém na {len(hosts)} hostech — schval jeden "
                     f"plán a spusť ho na všech, ne {len(hosts)}× zvlášť."),
        })
    return sorted(out, key=lambda x: -x['host_count'])

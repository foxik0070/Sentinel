"""
472: Detekce konfiguračního driftu — stroje, které se rozešly.
477: Detekce zombie zdrojů — běží a nikdo je nepoužívá.
479: Certifikáty v kontextu — nejen kdy vyprší, ale co spadne.
482: Analýza po restartu — naběhlo všechno jako předtím?
485: Kontrola dokumentace vs. realita.

Sběr dat jde přes PEVNÝ KATALOG read-only příkazů, stejně jako diagnostika
(462). Analýza je čistá funkce nad tím, co se sebralo — jde testovat bez
SSH a bez modelu.

Proč to má smysl: tyhle věci nikdo nehlásí. Drift se projeví až tím, že se
jeden stroj chová jinak; zombie služba se pozná až podle účtu za elektřinu;
certifikát až výpadkem. Všechno jsou to problémy, které mlčí do poslední
chvíle.
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Read-only příkazy pro sběr. Model si je nevybírá — volá je kód podle
# toho, co se audituje.
AUDIT_COMMANDS = {
    "kernel":     "uname -r",
    "os":         "grep -m1 PRETTY_NAME /etc/os-release",
    "uptime":     "uptime -s",
    "timezone":   "timedatectl show -p Timezone --value",
    "enabled_units": "systemctl list-unit-files --state=enabled --no-pager --no-legend | awk '{print $1}' | sort",
    "listening":  "ss -tlnH | awk '{print $4}' | sort -u",
    "pkg_count":  "dpkg -l 2>/dev/null | grep -c '^ii' || rpm -qa 2>/dev/null | wc -l",
}


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


# --- 472 -------------------------------------------------------------------

# Kolik strojů musí mít shodnou hodnotu, aby se dala považovat za normu.
DRIFT_MIN_HOSTS = 3


def detect_drift(facts, min_hosts: int = DRIFT_MIN_HOSTS) -> list:
    """472: Stroje, které se odchýlily od většiny.

    `facts` = {"host": {"kernel": "...", "os": "...", ...}}

    Většina není totéž co správnost — proto se to hlásí jako „liší se",
    ne „je špatně". Odchylka může být záměr (jeden stroj se testuje na
    novém jádru) a jen člověk pozná rozdíl.
    """
    if len(facts or {}) < min_hosts:
        return []

    out = []
    keys = {k for v in facts.values() if isinstance(v, dict) for k in v}
    for key in sorted(keys):
        # Seznamy (jednotky, porty) se porovnávají zvlášť níž
        values = {h: v.get(key) for h, v in facts.items()
                  if isinstance(v, dict) and isinstance(v.get(key), str) and v.get(key)}
        if len(values) < min_hosts:
            continue
        counts = Counter(values.values())
        norm, n_norm = counts.most_common(1)[0]
        if n_norm == len(values):
            continue                       # všichni stejní, žádný drift
        outliers = [{"host": h, "value": v[:120]} for h, v in values.items() if v != norm]
        # Když se „většina" skládá z poloviny, není to norma, ale rozpad.
        if n_norm < len(values) * 0.6:
            out.append({"attribute": key, "kind": "fragmented",
                        "distinct_values": len(counts), "hosts": len(values),
                        "note": (f"{key}: {len(counts)} různých hodnot napříč "
                                 f"{len(values)} stroji — žádná není převažující.")})
            continue
        out.append({
            "attribute": key, "kind": "outlier",
            "expected": norm[:120], "expected_hosts": n_norm,
            "outliers": outliers,
            "note": (f"{key}: {len(outliers)} z {len(values)} strojů se liší od "
                     f"většiny. Ověř, jestli je to záměr."),
        })
    return sorted(out, key=lambda x: -len(x.get('outliers', []) or [0]))


def diff_unit_lists(facts, min_hosts: int = DRIFT_MIN_HOSTS) -> list:
    """472: Služby, které běží jen někde.

    Užitečné hlavně opačně: jednotka zapnutá všude kromě jednoho stroje
    je obvykle chyba nasazení, ne úmysl.
    """
    per_host = {}
    for host, f in (facts or {}).items():
        raw = (f or {}).get('enabled_units') if isinstance(f, dict) else None
        if isinstance(raw, str) and raw.strip():
            per_host[host] = {u.strip() for u in raw.splitlines() if u.strip()}
    if len(per_host) < min_hosts:
        return []

    counts = Counter(u for units in per_host.values() for u in units)
    total = len(per_host)
    out = []
    for unit, n in counts.items():
        if n == total or n < 2:
            continue
        missing = sorted(h for h, units in per_host.items() if unit not in units)
        if len(missing) <= max(1, total // 4):
            out.append({"unit": unit, "present_on": n, "total": total,
                        "missing_on": missing,
                        "note": (f"`{unit}` je zapnutá na {n} z {total} strojů — "
                                 f"chybí na {', '.join(missing)}. Chyba nasazení?")})
    return sorted(out, key=lambda x: -x['present_on'])


# --- 477 -------------------------------------------------------------------

def find_zombies(services, idle_days: int = 30, now=None) -> list:
    """477: Běží a nikdo to nepoužívá.

    `services` = [{"host", "unit", "active_since", "last_activity", "connections"}]

    Nepoužívaná služba není jen plýtvání — je to i plocha k útoku, kterou
    nikdo nesleduje, protože o ní všichni zapomněli.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(idle_days)))
    out = []
    for s in services or []:
        if not isinstance(s, dict) or not s.get('unit'):
            continue
        conns = s.get('connections')
        if isinstance(conns, int) and conns > 0:
            continue                       # někdo je připojený → používá se
        last = _parse(s.get('last_activity'))
        if last and last > cutoff:
            continue                       # nedávná aktivita → používá se
        since = _parse(s.get('active_since'))
        if since and since > cutoff:
            continue                       # běží krátce → na závěr je brzy
        if last is None and conns is None:
            continue                       # nemáme čím podložit, nehádáme
        out.append({
            "host": s.get('host'), "unit": s['unit'],
            "last_activity": s.get('last_activity'),
            "connections": conns,
            "idle_days": int((now - last).days) if last else None,
            "note": ("Běží, ale nic ji nepoužívá. Kromě plýtvání je to plocha "
                     "k útoku, kterou nikdo nesleduje."),
        })
    return out


# --- 479 -------------------------------------------------------------------

def cert_impact(certs, listening=None, warn_days: int = 30, now=None) -> list:
    """479: Nejen kdy vyprší, ale co spadne.

    Samotné datum nestačí k rozhodnutí, co řešit dřív. Certifikát na portu,
    kde nikdo neposlouchá, počká; ten pod hlavní službou ne.
    """
    now = now or datetime.now(timezone.utc)
    ports_by_host = defaultdict(set)
    for entry in listening or []:
        if isinstance(entry, dict) and entry.get('host'):
            for p in (entry.get('ports') or []):
                ports_by_host[entry['host']].add(str(p))

    out = []
    for c in certs or []:
        if not isinstance(c, dict):
            continue
        exp = _parse(c.get('expires'))
        if not exp:
            continue
        days = (exp - now).days
        if days > warn_days:
            continue
        host, port = c.get('host'), str(c.get('port') or '')
        # Rozlišit „nikdo neposlouchá" od „nemáme data". Bez toho by chybějící
        # sběr vypadal jako důkaz, že certifikát nic nedrží — a někdo by kvůli
        # tomu odložil expiraci, která shodí produkci.
        known_ports = ports_by_host.get(host)
        if not port or known_ports is None or not known_ports:
            in_use = None
        else:
            in_use = port in known_ports
        severity = ('critical' if days <= 7 else 'high') if in_use is not False else 'low'
        out.append({
            "host": host, "port": port, "subject": c.get('subject'),
            "expires": c.get('expires'), "days_left": days,
            "in_use": in_use, "severity": severity,
            "note": (f"Vyprší za {days} dní. "
                     + ("Port je aktivní — výpadek se projeví hned."
                        if in_use else
                        "Na tomhle portu nikdo neposlouchá — nejspíš nikoho neshodí."
                        if in_use is False else
                        "Nevíme, jestli se používá.")),
        })
    return sorted(out, key=lambda x: x['days_left'])


# --- 482 -------------------------------------------------------------------

def compare_after_reboot(before, after) -> dict:
    """482: Naběhlo po restartu všechno jako předtím?

    Restart je nejčastější chvíle, kdy něco tiše nenaběhne — a přijde se
    na to až za týdny, protože chybějící služba nic nehlásí.
    """
    b = {u.strip() for u in str((before or {}).get('enabled_units') or '').splitlines() if u.strip()}
    a = {u.strip() for u in str((after or {}).get('enabled_units') or '').splitlines() if u.strip()}
    bp = {p.strip() for p in str((before or {}).get('listening') or '').splitlines() if p.strip()}
    ap = {p.strip() for p in str((after or {}).get('listening') or '').splitlines() if p.strip()}

    missing_units = sorted(b - a)
    missing_ports = sorted(bp - ap)
    return {
        "comparable": bool(b or bp),
        "missing_units": missing_units,
        "new_units": sorted(a - b),
        "missing_ports": missing_ports,
        "new_ports": sorted(ap - bp),
        "clean": not missing_units and not missing_ports,
        "note": ("Po restartu naběhlo vše jako předtím."
                 if not missing_units and not missing_ports else
                 f"Po restartu chybí {len(missing_units)} jednotek a "
                 f"{len(missing_ports)} portů — ověř, jestli je to záměr."),
    }


# --- 485 -------------------------------------------------------------------

_DOC_HOST = re.compile(r'\b([a-z][a-z0-9-]*\d[a-z0-9-]*|[a-z][a-z0-9-]{3,})\b\.?', re.I)
_DOC_PORT = re.compile(r'\bport\s+(\d{2,5})\b', re.I)
_DOC_UNIT = re.compile(r'\b([a-z0-9_.-]+\.service)\b', re.I)


def check_docs_against_reality(doc_text, known_hosts, known_units=None,
                               known_ports=None) -> list:
    """485: Co dokumentace tvrdí a co už neplatí.

    Zastaralý runbook je nebezpečnější než žádný — člověk podle něj jedná
    v krizi, kdy nemá čas ověřovat.
    """
    hosts = {str(h).lower() for h in (known_hosts or []) if h}
    units = {str(u).lower() for u in (known_units or []) if u}
    ports = {str(p) for p in (known_ports or []) if p}
    findings = []

    for m in _DOC_UNIT.finditer(str(doc_text or '')):
        unit = m.group(1).lower()
        if units and unit not in units:
            findings.append({"kind": "unit", "value": m.group(1),
                             "note": f"`{m.group(1)}` v dokumentaci, ale nikde neběží."})
    for m in _DOC_PORT.finditer(str(doc_text or '')):
        port = m.group(1)
        if ports and port not in ports:
            findings.append({"kind": "port", "value": port,
                             "note": f"Port {port} v dokumentaci, ale nikdo na něm neposlouchá."})

    # Hostnames hlídáme jen tam, kde je dokumentace uvádí jako stroj —
    # jinak by se hlásilo každé běžné slovo.
    for m in re.finditer(r'(?:stroj|host|server|node)\s+([a-z][a-z0-9._-]{2,})',
                         str(doc_text or ''), re.I):
        h = m.group(1).lower().rstrip('.')
        if hosts and h not in hosts and h.split('.')[0] not in hosts:
            findings.append({"kind": "host", "value": m.group(1),
                             "note": f"Stroj `{m.group(1)}` v dokumentaci neexistuje."})

    seen, unique = set(), []
    for f in findings:
        k = (f['kind'], f['value'].lower())
        if k not in seen:
            seen.add(k)
            unique.append(f)
    return unique

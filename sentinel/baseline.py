"""
469: Baseline profil hosta — jak vypadá „normální den" a co se z něj vymyká.
470: Sezónnost nad rámec 397 — denní doba, konec měsíce, zálohovací okna.
473: Audit bezpečnostních logů — vzory, které jednotlivě neprojdou prahem.
475: Flapping s příčinou — `/api/analytics/flapping` říká CO, tohle PROČ.
476: Anomálie ve vztazích metrik — CPU roste, ale požadavky ne.
481: Chybějící monitoring — které stroje nikdo nesleduje.

Společné je, že hledají problém tam, kde jednotlivá hodnota práh nepřekročí.
Práh je binární: buď hodnota přeteče, nebo ne. Realita je jiná — deset
neúspěšných přihlášení za hodinu je normální, deset za minutu z deseti IP
adres je útok, a žádné z nich prahem neprojde.

Vše deterministické. AI může výsledek popsat, ne rozhodnout, jestli platí.
"""
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

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


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def _stdev(vals):
    if len(vals) < 2:
        return None
    m = _mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


# --- 469 -------------------------------------------------------------------

# Kolik vzorků potřebujeme, aby „normál" něco znamenal.
MIN_BASELINE_SAMPLES = 20

# Kolik směrodatných odchylek už je odchylka. 3σ je konzervativní —
# u normálního rozdělení to je zhruba 1 z 370 měření.
BASELINE_SIGMA = 3.0


def build_host_profile(host: str, series) -> dict:
    """469: Popis normálního stavu hosta z jeho vlastní historie.

    Absolutní práh („teplota nad 70") nutně sedí jen na část strojů. Profil
    z vlastní historie pozná, že tenhle konkrétní stroj jede běžně na 45 —
    a 60 je u něj problém, i když je pod obecným prahem.
    """
    profile = {"host": host, "metrics": {}, "samples": 0}
    for name, points in (series or {}).items():
        vals = []
        for _, v in points or []:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if len(vals) < MIN_BASELINE_SAMPLES:
            continue
        m, sd = _mean(vals), _stdev(vals)
        if m is None or sd is None:
            continue
        profile["metrics"][name] = {
            "mean": round(m, 2), "stdev": round(sd, 2),
            "min": round(min(vals), 2), "max": round(max(vals), 2),
            "samples": len(vals),
        }
        profile["samples"] += len(vals)
    return profile


def deviations_from_profile(profile, current: dict, sigma: float = BASELINE_SIGMA) -> list:
    """469: Co se z normálu vymyká."""
    out = []
    for name, value in (current or {}).items():
        stats = (profile or {}).get('metrics', {}).get(name)
        if not stats:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        sd = stats['stdev']
        if not sd:
            continue                       # bez rozptylu nelze určit odchylku
        z = (v - stats['mean']) / sd
        if abs(z) < sigma:
            continue
        out.append({
            "metric": name, "value": round(v, 2), "usual": stats['mean'],
            "sigma": round(z, 1),
            "note": (f"{name}: {v:.1f} proti obvyklým {stats['mean']:.1f} "
                     f"(±{sd:.1f}) — {abs(z):.1f}× mimo normál."),
        })
    return sorted(out, key=lambda x: -abs(x['sigma']))


# --- 470 -------------------------------------------------------------------

def seasonal_profile(events) -> dict:
    """470: Kdy se problémy dějí — hodina, den v týdnu, den v měsíci.

    Bez tohohle vypadá „záloha vytíží disk každou noc" jako opakovaná
    porucha. Se sezónností je vidět, že to je rozvrh, ne problém.
    """
    by_hour = defaultdict(int)
    by_dow = defaultdict(int)
    by_dom = defaultdict(int)
    total = 0
    stamps = []
    for e in events or []:
        at = _parse(e.get('at') or e.get('first_seen') or e.get('timestamp')
                    if isinstance(e, dict) else e)
        if not at:
            continue
        total += 1
        stamps.append(at)
        by_hour[at.hour] += 1
        by_dow[at.weekday()] += 1
        by_dom[at.day] += 1
    if not total:
        return {"total": 0, "peaks": []}

    # Dimenzi lze posuzovat jen tehdy, když ji data pokrývají. Ze tří dnů
    # historie vyjde „den v měsíci" jako silný vzorec, i když je to jen
    # artefakt krátkého okna — každý přítomný den nutně vypadá jako špička.
    span_h = (max(stamps) - min(stamps)).total_seconds() / 3600.0
    dims = []
    if span_h >= 24:
        dims.append(("hodina", by_hour, 24))
    if span_h >= 24 * 7:
        dims.append(("den_v_tydnu", by_dow, 7))
    if span_h >= 24 * 14:
        dims.append(("den_v_mesici", by_dom, 31))

    peaks = []
    for label, data, size in dims:
        expected = total / size
        for key, count in data.items():
            # Trojnásobek očekávaného je vzorec, ne náhoda — u malých počtů
            # ale žádáme i absolutní minimum, ať to nehlásí náhodné shluky.
            if count >= max(3, expected * 3):
                peaks.append({"dimension": label, "value": key, "count": count,
                              "expected": round(expected, 1),
                              "ratio": round(count / expected, 1) if expected else None})
    peaks.sort(key=lambda p: -(p['ratio'] or 0))
    return {"total": total, "peaks": peaks,
            "by_hour": dict(by_hour), "by_dow": dict(by_dow)}


def is_scheduled_pattern(peaks) -> dict:
    """470: Vypadá to jako rozvrh (záloha, cron), ne jako porucha?"""
    hourly = [p for p in (peaks or []) if p['dimension'] == 'hodina']
    if not hourly:
        return {"scheduled": False, "note": ""}
    top = max(hourly, key=lambda p: p['count'])
    if top['value'] in range(0, 6) or (top['ratio'] or 0) >= 5:
        return {"scheduled": True, "hour": top['value'],
                "note": (f"Většina výskytů v {top['value']}:00 — vypadá to na "
                         f"pravidelnou úlohu (záloha, cron), ne na poruchu.")}
    return {"scheduled": False, "note": ""}


# --- 473 -------------------------------------------------------------------

_AUTH_FAIL = re.compile(r'failed password|authentication failure|invalid user', re.I)
_AUTH_OK = re.compile(r'accepted (password|publickey)', re.I)
_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_USER_RE = re.compile(r'for(?:\s+invalid\s+user)?\s+(\S+)\s+from', re.I)

# Vzory, které jednotlivě prahem neprojdou, ale dohromady dávají obrázek.
DISTRIBUTED_MIN_IPS = 5
SPRAY_MIN_USERS = 5
SUCCESS_AFTER_FAILS = 10


def audit_auth_log(lines, window_min: int = 60) -> list:
    """473: Vzory v auth logu, které jednotlivě neprojdou prahem.

    Deset neúspěšných přihlášení za hodinu je normál. Deset z deseti různých
    adres na jeden účet je rozprostřený útok — a žádné z nich samo o sobě
    práh nepřekročí.
    """
    fails_by_ip = defaultdict(int)
    fails_by_user = defaultdict(set)
    ips_by_user = defaultdict(set)
    users_by_ip = defaultdict(set)
    success_after = []
    fail_count = 0

    for line in lines or []:
        text = str(line or '')
        ip_m = _IP_RE.search(text)
        ip = ip_m.group(0) if ip_m else ''
        user_m = _USER_RE.search(text)
        user = user_m.group(1) if user_m else ''

        if _AUTH_FAIL.search(text):
            fail_count += 1
            if ip:
                fails_by_ip[ip] += 1
                if user:
                    users_by_ip[ip].add(user)
            if user:
                fails_by_user[user].add(ip)
                if ip:
                    ips_by_user[user].add(ip)
        elif _AUTH_OK.search(text) and fail_count >= SUCCESS_AFTER_FAILS:
            success_after.append({"ip": ip, "user": user, "after_fails": fail_count})

    findings = []
    for user, ips in ips_by_user.items():
        if len(ips) >= DISTRIBUTED_MIN_IPS:
            findings.append({
                "kind": "distributed_bruteforce", "target": user,
                "sources": len(ips), "severity": "high",
                "note": (f"Účet '{user}' napadán z {len(ips)} různých adres — "
                         f"jednotlivě žádná práh nepřekročí."),
            })
    for ip, users in users_by_ip.items():
        if len(users) >= SPRAY_MIN_USERS:
            findings.append({
                "kind": "user_spray", "source": ip,
                "targets": len(users), "severity": "high",
                "note": (f"Adresa {ip} zkouší {len(users)} různých účtů — "
                         f"hledá, který existuje."),
            })
    for s in success_after:
        findings.append({
            "kind": "success_after_bruteforce", "source": s['ip'], "target": s['user'],
            "severity": "critical",
            "note": (f"ÚSPĚŠNÉ přihlášení po {s['after_fails']} neúspěších — "
                     f"ověř, jestli je legitimní."),
        })
    return findings


# --- 475 -------------------------------------------------------------------

def flapping_cause(history, window_min: int = 60) -> dict:
    """475: Proč to flapuje — pravidelně, nebo nahodile?

    Pravidelný interval ukazuje na časovač nebo watchdog; nahodilý spíš na
    přetížení nebo hardware. Je to rozdíl v tom, kde hledat.
    """
    stamps = sorted(t for t in (_parse((h or {}).get('first_seen')) for h in history or []) if t)
    if len(stamps) < 4:
        return {"known": False, "note": "Málo výskytů na posouzení."}
    gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(stamps, stamps[1:])]
    m, sd = _mean(gaps), _stdev(gaps)
    if not m:
        return {"known": False, "note": "Nulové odstupy."}
    cv = (sd / m) if sd is not None and m else None      # variační koeficient

    if cv is not None and cv < 0.25:
        return {"known": True, "pattern": "regular", "interval_min": round(m, 1),
                "note": (f"Opakuje se pravidelně po {m:.0f} min — hledej "
                         f"časovač, cron nebo watchdog, ne náhodné selhání.")}
    return {"known": True, "pattern": "irregular", "interval_min": round(m, 1),
            "note": (f"Nepravidelně (průměr {m:.0f} min, velký rozptyl) — "
                     f"spíš přetížení nebo hardware než rozvrh.")}


# --- 476 -------------------------------------------------------------------

def relation_anomalies(series, pairs=None) -> list:
    """476: Metriky, které spolu obvykle chodí, se rozešly.

    „CPU roste, ale požadavků neubývá ani nepřibývá" znamená, že práci dělá
    něco jiného než provoz — smyčka, retry bouře, nebo cizí proces.
    """
    default_pairs = [
        ('cpu', 'requests'), ('cpu', 'load'), ('disk_io', 'disk_used'),
        ('memory', 'connections'), ('net_in', 'net_out'),
    ]
    out = []
    for a_hint, b_hint in (pairs or default_pairs):
        a_name = _find_metric(series, a_hint)
        b_name = _find_metric(series, b_hint)
        if not a_name or not b_name:
            continue
        a_vals = _values(series[a_name])
        b_vals = _values(series[b_name])
        n = min(len(a_vals), len(b_vals))
        if n < MIN_BASELINE_SAMPLES:
            continue
        corr = _correlation(a_vals[-n:], b_vals[-n:])
        if corr is None:
            continue
        a_trend = _slope(a_vals[-n:])
        b_trend = _slope(b_vals[-n:])
        # Zajímá nás případ, kdy jedna roste a druhá ne A zároveň spolu
        # přestaly souviset.
        if a_trend > 0 and abs(b_trend) < abs(a_trend) * 0.2 and corr < 0.3:
            out.append({
                "metric_a": a_name, "metric_b": b_name,
                "correlation": round(corr, 2),
                "note": (f"{a_name} roste, ale {b_name} ne (korelace {corr:.2f}) "
                         f"— práci dělá něco jiného než běžný provoz."),
            })
    return out


def _find_metric(series, hint):
    for name in (series or {}):
        if hint in name.lower():
            return name
    return None


def _values(points):
    out = []
    for _, v in points or []:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _slope(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = _mean(xs), _mean(vals)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, vals)) / sxx if sxx else 0.0


def _correlation(a, b):
    n = min(len(a), len(b))
    if n < 2:
        return None
    ma, mb = _mean(a), _mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else None


# --- 481 -------------------------------------------------------------------

def missing_monitoring(known_hosts, agents, issues, telemetry_hosts=None) -> list:
    """481: Stroje, o kterých nic nevíme.

    Nula alertů z hosta vypadá stejně jako klid — ale může znamenat, že ho
    nikdo nesleduje. Tichý stroj je horší než hlučný, protože o jeho
    problému se nedozvíme vůbec.
    """
    seen_agent = {str(a.get('hostname') or '').lower()
                  for a in (agents or []) if isinstance(a, dict)}
    seen_issue = {str(i.get('host') or '').lower()
                  for i in (issues or []) if isinstance(i, dict)}
    seen_tele = {str(h or '').lower() for h in (telemetry_hosts or [])}

    out = []
    for host in (known_hosts or []):
        h = str(host or '').strip()
        if not h:
            continue
        low = h.lower()
        sources = []
        if low in seen_agent:
            sources.append('agent')
        if low in seen_tele:
            sources.append('telemetrie')
        if low in seen_issue:
            sources.append('issue')
        if sources:
            continue
        out.append({
            "host": h, "sources": sources,
            "note": ("Žádný agent, telemetrie ani issue — o tomhle stroji "
                     "nevíme nic. Nula alertů tady neznamená klid."),
        })
    return out

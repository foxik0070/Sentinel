"""
453: Detekce společného jmenovatele — co mají alerty společného.
454: Časová osa incidentu — chronologie ze všech zdrojů.
455: „Co se změnilo od posledně" — diff proti minulému výskytu.
456: Cross-host pattern — stejný alert na >30 % hostů = systémový problém.
459: Detekce kaskád — lavina alertů z jedné příčiny → JEDNA notifikace.
461: Hypotézy s pravděpodobností — místo jedné odpovědi 2-3 s jistotou.
465: Zpětná korelace při vyřešení — zmizely i navázané problémy?

Všechno se počítá z dat, ne modelem. Model umí napsat, PROČ spolu věci
souvisí, ale jestli spolu souvisí, je otázka na počty a časy — a tam se
plete. Hypotézy (461) jsou jediné místo, kde má model prostor, a i tam
dostane spočítaná fakta jako podklad.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Nad tímhle podílem zasažených hostů už nejde o lokální problém.
CROSS_HOST_RATIO = 0.30

# Okno, ve kterém se alerty považují za jednu lavinu.
CASCADE_WINDOW_SEC = 60
CASCADE_MIN_SIZE = 5


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


# --- 453 -------------------------------------------------------------------

def common_denominator(issues) -> dict:
    """453: Co mají alerty společného.

    Když deset problémů sdílí jeden atribut, je to obvykle ta příčina —
    a hledat ji zvlášť u každého je zbytečná práce.
    """
    if not issues:
        return {"shared": [], "count": 0}
    fields = ('host', 'plugin_name', 'channel_type', 'severity')
    counts = {f: {} for f in fields}
    n = 0
    for i in issues:
        if not isinstance(i, dict):
            continue
        n += 1
        for f in fields:
            v = i.get(f)
            if v:
                counts[f][v] = counts[f].get(v, 0) + 1
    if not n:
        return {"shared": [], "count": 0}

    shared = []
    for f, vals in counts.items():
        for val, c in vals.items():
            ratio = c / n
            # Atribut sdílený všemi je zajímavý; sdílený polovinou taky,
            # pokud jich je dost.
            if ratio >= 0.8 or (ratio >= 0.5 and c >= 3):
                shared.append({"field": f, "value": val, "count": c,
                               "ratio": round(ratio, 2)})
    shared.sort(key=lambda x: (-x['ratio'], -x['count']))
    return {"shared": shared, "count": n}


# --- 456 -------------------------------------------------------------------

def cross_host_pattern(issues, known_hosts=None, ratio: float = CROSS_HOST_RATIO) -> list:
    """456: Stejný alert na velké části hostů = systémový problém.

    Deset hlášek „služba spadla" na deseti strojích není deset problémů,
    ale jeden — a řešit je po jednom znamená deset zbytečných zásahů.
    """
    from .alert_quality import normalize_message
    total_hosts = len({h for h in (known_hosts or []) if h})
    groups: dict = {}
    for i in issues or []:
        if not isinstance(i, dict):
            continue
        key = (i.get('plugin_name') or '', normalize_message(i.get('last_line')))
        groups.setdefault(key, set()).add(i.get('host') or '')

    if not total_hosts:
        total_hosts = len({i.get('host') for i in issues or []
                           if isinstance(i, dict) and i.get('host')})
    if not total_hosts:
        return []

    out = []
    for (plugin, pattern), hosts in groups.items():
        hosts = {h for h in hosts if h}
        share = len(hosts) / total_hosts
        if share < ratio or len(hosts) < 2:
            continue
        out.append({
            "plugin_name": plugin, "pattern": pattern,
            "hosts": sorted(hosts), "host_count": len(hosts),
            "total_hosts": total_hosts, "share": round(share, 2),
            "verdict": ("Systémový problém — postihuje "
                        f"{len(hosts)} z {total_hosts} hostů. Řeš příčinu, "
                        "ne jednotlivé stroje."),
        })
    return sorted(out, key=lambda x: -x['share'])


# --- 459 -------------------------------------------------------------------

def detect_cascade(issues, window_sec: int = CASCADE_WINDOW_SEC,
                   min_size: int = CASCADE_MIN_SIZE) -> list:
    """459: Lavina alertů z jedné příčiny.

    Dvacet notifikací během minuty nikdo nepřečte — a to podstatné (co bylo
    PRVNÍ) v nich zanikne. Vrací skupiny; volající pošle jednu zprávu.
    """
    stamped = []
    for i in issues or []:
        if not isinstance(i, dict):
            continue
        t = _parse(i.get('first_seen') or i.get('last_seen'))
        if t:
            stamped.append((t, i))
    if len(stamped) < min_size:
        return []
    stamped.sort(key=lambda x: x[0])

    groups, current = [], [stamped[0]]
    for t, i in stamped[1:]:
        # Řetězí se podle mezery mezi SOUSEDNÍMI alerty — kaskáda přichází
        # postupně, ne najednou.
        if (t - current[-1][0]).total_seconds() <= window_sec:
            current.append((t, i))
        else:
            groups.append(current)
            current = [(t, i)]
    groups.append(current)

    out = []
    for g in groups:
        if len(g) < min_size:
            continue
        items = [i for _, i in g]
        first = items[0]
        out.append({
            "size": len(items),
            "started_at": g[0][0].isoformat(),
            "span_sec": int((g[-1][0] - g[0][0]).total_seconds()),
            "trigger": {"host": first.get('host'), "plugin_name": first.get('plugin_name'),
                        "message": (first.get('last_line') or '')[:160]},
            "hosts": sorted({i.get('host') for i in items if i.get('host')}),
            "keys": [i.get('key') for i in items if i.get('key')],
            "common": common_denominator(items)['shared'][:3],
            "note": (f"{len(items)} alertů za {int((g[-1][0] - g[0][0]).total_seconds())} s "
                     f"— pošli JEDNU notifikaci a řeš první z nich."),
        })
    return sorted(out, key=lambda x: -x['size'])


# --- 454 -------------------------------------------------------------------

def build_timeline(issue, changes=None, attempts=None, notifications=None,
                   max_items: int = 40) -> list:
    """454: Chronologie ze všech zdrojů.

    Při postmortemu je otázka „co se dělo v jakém pořadí" první, na kterou
    člověk potřebuje odpověď — a dnes ji skládá ručně ze čtyř obrazovek.
    """
    events = []

    born = _parse((issue or {}).get('first_seen'))
    if born:
        events.append({"at": born, "kind": "issue_start",
                       "text": f"Problém vznikl: {((issue or {}).get('last_line') or '')[:120]}"})
    seen = _parse((issue or {}).get('last_seen'))
    if seen and born and seen != born:
        events.append({"at": seen, "kind": "issue_last_seen",
                       "text": "Naposledy detekován"})
    done = _parse((issue or {}).get('resolved_at'))
    if done:
        events.append({"at": done, "kind": "issue_resolved",
                       "text": f"Vyřešeno ({(issue or {}).get('resolve_reason') or '?'})"})

    for c in changes or []:
        at = _parse((c or {}).get('at'))
        if at:
            events.append({"at": at, "kind": c.get('kind') or 'change',
                           "text": f"{c.get('what')}: {str(c.get('detail'))[:100]}"})

    for a in attempts or []:
        at = _parse((a or {}).get('applied_at'))
        if at:
            events.append({"at": at, "kind": "fix_attempt",
                           "text": f"Zásah: {(a.get('command') or '')[:100]}"})
        ver = _parse((a or {}).get('verified_at'))
        if ver:
            events.append({"at": ver, "kind": "fix_verified",
                           "text": f"Ověření: {a.get('status')} — {(a.get('verdict_detail') or '')[:80]}"})

    for n in notifications or []:
        at = _parse((n or {}).get('at') or (n or {}).get('created_at'))
        if at:
            events.append({"at": at, "kind": "notification",
                           "text": f"Notifikace → {n.get('channel') or '?'}"})

    events.sort(key=lambda e: e['at'])
    out = []
    start = events[0]['at'] if events else None
    for e in events[:max_items]:
        out.append({"at": e['at'].isoformat(), "kind": e['kind'], "text": e['text'],
                    "offset_sec": int((e['at'] - start).total_seconds()) if start else 0})
    return out


# --- 455 -------------------------------------------------------------------

def diff_against_previous(current, previous) -> dict:
    """455: Čím se tenhle výskyt liší od minulého.

    Opakující se problém se řeší rychleji, když je vidět, co je jinak —
    jiná hláška znamená jinou příčinu, i když je alert stejný.
    """
    if not current or not previous:
        return {"has_previous": False, "changes": []}
    changes = []
    for field, label in (('last_line', 'hláška'), ('severity', 'závažnost'),
                         ('host', 'stroj'), ('channel_type', 'kanál')):
        a, b = (previous.get(field) or ''), (current.get(field) or '')
        if a != b:
            changes.append({"field": field, "label": label,
                            "before": str(a)[:120], "after": str(b)[:120]})

    prev_dur = _duration_min(previous)
    cur_dur = _duration_min(current)
    if prev_dur is not None and cur_dur is not None:
        delta = cur_dur - prev_dur
        if abs(delta) >= max(1.0, prev_dur * 0.5):
            changes.append({"field": "duration", "label": "doba trvání",
                            "before": f"{prev_dur:.0f} min", "after": f"{cur_dur:.0f} min"})
    return {
        "has_previous": True,
        "previous_at": previous.get('resolved_at') or previous.get('last_seen'),
        "changes": changes,
        "identical": not changes,
    }


def _duration_min(issue):
    a = _parse((issue or {}).get('first_seen'))
    b = _parse((issue or {}).get('resolved_at') or (issue or {}).get('last_seen'))
    if not a or not b or b < a:
        return None
    return (b - a).total_seconds() / 60.0


# --- 465 -------------------------------------------------------------------

def verify_related_resolved(resolved_issue, active_issues, changes=None) -> dict:
    """465: Když problém zmizí, zmizely i ty navázané?

    Zůstane-li po vyřešení hlavní příčiny viset následek, je to buď
    zapomenutý alert, nebo znamení, že příčina byla jiná. Obojí stojí za
    pozornost.
    """
    host = (resolved_issue or {}).get('host') or ''
    resolved_at = _parse((resolved_issue or {}).get('resolved_at'))
    still = []
    for i in active_issues or []:
        if not isinstance(i, dict) or i.get('key') == (resolved_issue or {}).get('key'):
            continue
        if host and i.get('host') != host:
            continue
        born = _parse(i.get('first_seen'))
        # Zajímá nás jen to, co vzniklo PŘED vyřešením — pozdější problém
        # s tímhle incidentem nesouvisí.
        if resolved_at and born and born > resolved_at:
            continue
        still.append({"key": i.get('key'), "plugin_name": i.get('plugin_name'),
                      "message": (i.get('last_line') or '')[:120]})
    return {
        "host": host,
        "still_active": still,
        "count": len(still),
        "verdict": ("Vše na stroji je čisté." if not still else
                    f"Na {host} zůstává {len(still)} problémů — buď je to "
                    f"zapomenutý alert, nebo příčina byla jiná."),
    }


# --- 461 -------------------------------------------------------------------

def hypotheses_prompt(issue, facts: str = "") -> str:
    """461: Vynutí VÍC hypotéz s odhadem jistoty.

    Jedna odpověď vypadá jistě, i když jistá není. Několik hypotéz s čísly
    ukáže, že model tipuje — a člověk ví, že má ověřovat.
    """
    from .ai_guard import wrap_untrusted
    safe, _ = wrap_untrusted((issue or {}).get('last_line') or '', "hláška z logu")
    return (
        "Jsi zkušený SRE. Navrhni VÍCE možných příčin, ne jednu.\n\n"
        f"PROBLÉM: [{(issue or {}).get('plugin_name', '?')}] "
        f"{(issue or {}).get('host', '?')}:\n{safe}\n"
        f"{facts}\n"
        "Uveď 2 až 3 hypotézy seřazené od nejpravděpodobnější. U každé odhadni "
        "pravděpodobnost v procentech (součet nemusí být 100) a napiš, ČÍM ji "
        "ověřit. Pokud si nejsi jistý, dej nižší čísla.\n"
        'Odpověz POUZE JSON: {"hypotheses": [{"cause": "<příčina>", '
        '"probability": <0-100>, "verify_by": "<jak ověřit>"}]}'
    )


def normalize_hypotheses(data, max_items: int = 3) -> list:
    """461: Uklidí hypotézy od modelu a seřadí podle jistoty."""
    raw = (data or {}).get('hypotheses') if isinstance(data, dict) else data
    out = []
    for h in (raw or []):
        if not isinstance(h, dict):
            continue
        cause = str(h.get('cause') or '').strip()
        if not cause:
            continue
        try:
            prob = max(0, min(100, int(float(h.get('probability')))))
        except (TypeError, ValueError):
            prob = None
        out.append({"cause": cause[:250], "probability": prob,
                    "verify_by": str(h.get('verify_by') or '')[:250]})
    out.sort(key=lambda x: -(x['probability'] if x['probability'] is not None else -1))
    return out[:max_items]

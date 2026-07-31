"""
471: Prediktivní kapacita s kontextem — nejen KDY dojde místo, ale PROČ.
474: Proaktivní kontrola zdraví — co se pravděpodobně pokazí příště.

Lineární regrese řekne „za 12 dní bude disk plný". Sama o sobě je ale k málo
platná: neřekne, co ten růst žene, ani jestli to vůbec dává smysl (růst po
jednorázovém importu není trend). Tady se k číslu přidává kontext z toho,
co systém ví — a teprve nad tím se ptáme modelu.

Předpověď je vždy podmíněná: „pokud růst pokračuje". Bez té podmínky by
z odhadu vznikl slib.
"""
import logging

logger = logging.getLogger(__name__)

# Pod touhle spolehlivostí regrese je předpověď věštění z kávy.
MIN_R2_FOR_FORECAST = 0.5

# Dál než takhle dopředu nemá smysl počítat.
MAX_FORECAST_DAYS = 365


def forecast_days_to_limit(current: float, slope_per_hour: float, limit: float = 100.0):
    """Za kolik dní se dosáhne meze. None, když k tomu nesměřuje."""
    try:
        cur, sl, lim = float(current), float(slope_per_hour), float(limit)
    except (TypeError, ValueError):
        return None
    if sl <= 0 or cur >= lim:
        return None
    days = (lim - cur) / sl / 24.0
    return round(days, 1) if 0 < days <= MAX_FORECAST_DAYS else None


def build_capacity_items(degrading, limit: float = 100.0) -> list:
    """471: K trendům z 467 přidá odhad, kdy narazí na mez."""
    out = []
    for d in degrading or []:
        if not isinstance(d, dict):
            continue
        if (d.get('r2') or 0) < MIN_R2_FOR_FORECAST:
            continue
        days = forecast_days_to_limit(d.get('last'), d.get('slope_per_hour'), limit)
        out.append({
            "metric": d.get('metric'),
            "current": d.get('last'),
            "growth_pct": d.get('growth_pct'),
            "slope_per_hour": d.get('slope_per_hour'),
            "r2": d.get('r2'),
            "days_to_limit": days,
            "limit": limit,
            "note": ("Platí, pokud růst pokračuje stejným tempem."
                     if days else "Nesměřuje k mezi v dohledné době."),
        })
    return sorted(out, key=lambda x: (x['days_to_limit'] is None,
                                      x['days_to_limit'] if x['days_to_limit'] is not None else 1e9))


def capacity_prompt(items, changes_note: str = "") -> str:
    """471: Prompt, který se ptá na PŘÍČINU růstu, ne na jeho zopakování."""
    block = "\n".join(
        f"- {i['metric']}: nyní {i['current']}, {i['slope_per_hour']:+.3f}/h, "
        f"mez za {i['days_to_limit']} dní" if i.get('days_to_limit') else
        f"- {i['metric']}: nyní {i['current']}, roste pomalu"
        for i in (items or [])[:6])
    return (
        "Jsi kapacitní plánovač. Níže jsou metriky s prokázaným růstem "
        "(už spočítaným, nepočítej ho znovu).\n\n"
        f"METRIKY:\n{block}\n"
        f"{changes_note}\n"
        "Řekni, co růst nejspíš žene a co s tím udělat DŘÍV, než se mez naplní. "
        "Nepřepisuj čísla z tabulky.\n"
        'Odpověz POUZE JSON: {"likely_cause": "<1 věta>", '
        '"recommendation": "<1-2 věty>", "urgency": "low|medium|high"}'
    )


def health_prompt(snapshot) -> str:
    """474: Týdenní otázka „co se pravděpodobně pokazí příště"."""
    s = snapshot or {}
    lines = [
        f"AKTIVNÍ PROBLÉMY: {s.get('active_issues', 0)}",
        f"OPAKUJÍCÍ SE: {s.get('recurring', 0)}",
        f"ROSTOUCÍ METRIKY: {s.get('degrading', 0)}",
        f"METRIKY, KTERÉ PŘESTALY CHODIT: {s.get('missing', 0)}",
        f"NEÚSPĚŠNÉ OPRAVY: {s.get('failed_fixes', 0)}",
    ]
    if s.get('top_issues'):
        lines.append("NEJČASTĚJŠÍ: " + "; ".join(str(t)[:80] for t in s['top_issues'][:5]))
    if s.get('near_limit'):
        lines.append("BLÍZKO MEZE: " + "; ".join(str(t)[:80] for t in s['near_limit'][:3]))
    return (
        "Jsi zkušený SRE a děláš týdenní přehled infrastruktury.\n\n"
        + "\n".join(lines) +
        "\n\nOdpověz, co se v příštím týdnu nejspíš pokazí a čemu věnovat "
        "pozornost. Vycházej JEN z čísel výše, nic si nedomýšlej.\n"
        'Odpověz POUZE JSON: {"risks": ["<riziko 1>", "<riziko 2>"], '
        '"focus": "<na co se zaměřit, 1 věta>", "overall": "good|watch|bad"}'
    )


def build_snapshot(state, trend_detect) -> dict:
    """474: Čísla pro týdenní přehled. Každý zdroj izolovaný."""
    snap = {"active_issues": 0, "recurring": 0, "degrading": 0, "missing": 0,
            "failed_fixes": 0, "top_issues": [], "near_limit": []}
    try:
        issues = state.get_active_issues() or []
        snap["active_issues"] = len(issues)
        snap["recurring"] = sum(1 for i in issues if (i.get('recurring_count') or 0) > 1)
        snap["top_issues"] = [f"[{i.get('plugin_name')}] {i.get('host')}: "
                              f"{(i.get('last_line') or '')[:60]}" for i in issues[:5]]
    except Exception as e:
        logger.debug(f"474: issue nedostupné: {e}")
    try:
        series = state.get_metric_series(hours=168)
        deg = trend_detect.detect_degradation(series)
        snap["degrading"] = len(deg)
        snap["near_limit"] = [f"{c['metric']} za {c['days_to_limit']} dní"
                              for c in build_capacity_items(deg) if c.get('days_to_limit')][:3]
        snap["missing"] = len(trend_detect.detect_missing(series))
    except Exception as e:
        logger.debug(f"474: telemetrie nedostupná: {e}")
    try:
        snap["failed_fixes"] = sum(1 for a in (state.get_fix_attempts(limit=500) or [])
                                   if a.get('status') == 'failed')
    except Exception as e:
        logger.debug(f"474: pokusy o opravu nedostupné: {e}")
    return snap

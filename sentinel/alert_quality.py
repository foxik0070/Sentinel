"""
480: Rozpoznání falešných poplachů.

Alert, který se stokrát vyřešil sám během minuty, nikoho neinformuje —
jen otupí pozornost, takže si příště nikdo nevšimne ani toho pravého.

Vyhodnocení je DETERMINISTICKÉ, počítá se z historie issue. AI se sem
neplete: „kolikrát se to vyřešilo samo" je otázka pro SQL, ne pro model.

CO SE NIKDY NENAVRHNE K UTIŠENÍ:
  - co někdy řešil člověk (resolved_by vyplněné) — pak to poplach nebyl
  - co vedlo k zásahu (fix_attempts) — někdo to považoval za skutečné
  - co má málo výskytů — na závěr je brzy

Návrh je vždy ZDRŽENÍ, ne vypnutí: když se problém sám vyřeší do minuty,
stačí hlásit až po pěti a zmizí jen šum, ne signál.
"""
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Kolik výskytů musí být, než z toho něco vyvozujeme.
MIN_OCCURRENCES = 10

# Do téhle délky trvání považujeme problém za pomíjivý.
TRANSIENT_MAX_MIN = 10

# Pod touhle hranicí jde nejspíš o jednorázovou událost, ne o stav —
# u té zdržení hlášení nepomůže (viz poznámka v _suggestion).
ONESHOT_MAX_MIN = 2

# Kolik procent výskytů se musí vyřešit samo, aby šlo o kandidáta.
SELF_RESOLVED_MIN_PCT = 95.0

# Řešeno člověkem = nebyl to planý poplach. Stačí jeden takový výskyt.
_HUMAN_REASONS = {'recheck_forced', 'manual', 'resolved_manually'}

# Části hlášky, které se mění výskyt od výskytu a bránily by seskupení.
_NUM_RE = re.compile(r'\d+([.,]\d+)?')
_TIME_RE = re.compile(r'\b\d{1,2}:\d{2}(:\d{2})?\b')
_DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b[A-Z][a-z]{2}\s+\d{1,2}\b')
_HEX_RE = re.compile(r'\b[0-9a-f]{8,}\b', re.I)


def normalize_message(line: str) -> str:
    """Setře proměnlivé části hlášky, aby šly výskyty seskupit.

    Bez toho by každý výskyt s jiným číslem vypadal jako jedinečný problém
    a nic by se nikdy nenasčítalo.
    """
    s = str(line or '').strip()
    s = _DATE_RE.sub('<d>', s)
    s = _TIME_RE.sub('<t>', s)
    s = _HEX_RE.sub('<h>', s)
    s = _NUM_RE.sub('<n>', s)
    return ' '.join(s.split())[:200]


def _parse(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _duration_min(row):
    a, b = _parse(row.get('first_seen')), _parse(row.get('resolved_at'))
    if not a or not b:
        return None
    d = (b - a).total_seconds() / 60.0
    return d if d >= 0 else None


def _median(values):
    if not values:
        return None
    v = sorted(values)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def analyze(history_rows, touched_keys=None, min_occurrences: int = MIN_OCCURRENCES) -> list:
    """Najde skupiny alertů, které se opakovaně řeší samy.

    `touched_keys` jsou klíče issue, na kterých někdo zasahoval (486) —
    ty se z návrhů vylučují, i kdyby statistika vypadala jakkoli.
    """
    touched = set(touched_keys or ())
    groups: dict = {}

    for row in history_rows or []:
        if not isinstance(row, dict):
            continue
        gid = (row.get('plugin_name') or '', row.get('host') or '',
               normalize_message(row.get('last_line')))
        g = groups.setdefault(gid, {
            "count": 0, "self_resolved": 0, "human": 0,
            "durations": [], "keys": set(), "sample": row.get('last_line') or '',
        })
        g["count"] += 1
        g["keys"].add(row.get('key') or '')
        by = (row.get('resolved_by') or '').strip()
        reason = (row.get('resolve_reason') or '').strip().lower()
        if by or reason in _HUMAN_REASONS:
            g["human"] += 1
        else:
            g["self_resolved"] += 1
        d = _duration_min(row)
        if d is not None:
            g["durations"].append(d)

    out = []
    for (plugin, host, pattern), g in groups.items():
        if g["count"] < min_occurrences:
            continue
        if g["human"]:
            continue                       # někdy to řešil člověk → nebyl to šum
        if g["keys"] & touched:
            continue                       # někdo na tom zasahoval
        pct = g["self_resolved"] / g["count"] * 100.0
        if pct < SELF_RESOLVED_MIN_PCT:
            continue
        med = _median(g["durations"])
        if med is None:
            continue
        out.append({
            "plugin_name": plugin,
            "host": host,
            "pattern": pattern,
            "sample": g["sample"][:200],
            "occurrences": g["count"],
            "self_resolved_pct": round(pct, 1),
            "median_duration_min": round(med, 1),
            "transient": med <= TRANSIENT_MAX_MIN,
            "suggestion": _suggestion(med, g["count"]),
        })
    return sorted(out, key=lambda x: -x["occurrences"])


def _suggestion(median_min: float, count: int) -> dict:
    """Konkrétní, ověřitelný návrh — ne „zvaž úpravu prahu".

    U pomíjivých problémů navrhujeme ZDRŽENÍ hlášení. Vypnutí by zahodilo
    i případ, kdy problém jednou nepomine — a to je právě ten, na kterém
    záleží.
    """
    if median_min <= TRANSIENT_MAX_MIN:
        # S rezervou nad medián, ať se neutiší i o něco delší výskyty.
        delay = max(5, int(median_min * 3) + 2)
        s = {
            "kind": "delay",
            "delay_min": delay,
            "text": (f"Hlásit až když problém trvá déle než {delay} min. "
                     f"Polovina z {count} výskytů zmizela do "
                     f"{median_min:.0f} min sama."),
        }
        if median_min <= ONESHOT_MAX_MIN:
            # Rozlišit STAV od UDÁLOSTI podle dat nejde: „služba je mimo"
            # i „někdo klepl na honeypot" trvají minutu. U události je ale
            # zdržení nesmysl — ta nemá jak trvat déle, takže by se utišila
            # úplně. Na to musí upozornit člověk, ne odhad.
            s["note"] = ("Ověř, jestli nejde o jednorázovou událost (např. "
                         "záznam z honeypotu nebo přihlášení). U těch zdržení "
                         "nepomůže — patří spíš mezi informace než mezi issue.")
        return s
    return {
        "kind": "review_threshold",
        "delay_min": None,
        "text": (f"Problém trvá dlouho (medián {median_min:.0f} min), ale vždy "
                 f"skončí sám. Spíš než utišit stojí za to ověřit, jestli je "
                 f"práh detektoru nastavený správně."),
    }


def summarize(candidates) -> dict:
    """Kolik šumu by se dalo ubrat."""
    cands = candidates or []
    noise = sum(c["occurrences"] for c in cands if c.get("transient"))
    return {
        "candidates": len(cands),
        "transient": sum(1 for c in cands if c.get("transient")),
        "suppressible_alerts": noise,
    }

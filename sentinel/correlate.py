"""
450: Korelace se změnami — co se stalo TĚSNĚ PŘED tím, než problém vznikl.
447: Kauzální řetěz — struktura {příčina → následek}, ne odstavec textu.

450 je nejlevnější diagnostika, jakou máme: většina problémů nevznikne sama
od sebe, ale po zásahu. Přesto se to dohledávalo ručně.

Souvislost v čase NENÍ důkaz příčiny. Modul proto nikde netvrdí „tohle to
způsobilo" — vrací „tohle se stalo předtím" a nechává závěr na člověku,
případně na AI, která to musí označit za hypotézu.

447 vrací STROM, ne text. Odstavec od modelu si člověk musí přečíst celý,
aby zjistil, co z čeho plyne; strom to ukáže na první pohled a jde ho
vykreslit.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Jak daleko před vznikem problému hledat změny. Delší okno přinese hlavně
# nesouvisející šum — po hodinách už časová blízkost nic nenaznačuje.
DEFAULT_WINDOW_MIN = 120

MAX_CHAIN_DEPTH = 6


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


def _within(ts, start, end):
    dt = _parse(ts)
    return dt is not None and start <= dt <= end


def collect_changes(state, issue, window_min: int = DEFAULT_WINDOW_MIN) -> list:
    """450: Co se změnilo v okně před vznikem problému.

    Každý zdroj je izolovaný — výpadek jednoho nesmí zatajit ostatní.
    """
    born = _parse((issue or {}).get('first_seen') or (issue or {}).get('last_seen'))
    if not born:
        return []
    start = born - timedelta(minutes=max(1, int(window_min)))
    host = (issue or {}).get('host') or ''
    out = []

    # Změna konfigurace Sentinelu samotného
    try:
        for row in state.get_config_history(limit=50) or []:
            if _within(row.get('timestamp'), start, born):
                out.append({"kind": "config_change", "at": row.get('timestamp'),
                            "what": "Změna konfigurace Sentinelu",
                            "detail": f"hash {str(row.get('content_hash'))[:12]}"})
    except Exception as e:
        logger.debug(f"correlate: config_history nedostupná: {e}")

    # Příkazy vykonané na strojích
    try:
        for a in state.list_actions(limit=200) or []:
            if not _within(a.get('executed_at') or a.get('created_at'), start, born):
                continue
            if host and a.get('node') and a['node'] != host:
                continue
            out.append({"kind": "action", "at": a.get('executed_at') or a.get('created_at'),
                        "what": f"Vykonán příkaz na {a.get('node') or '?'}",
                        "detail": (a.get('command') or '')[:160]})
    except Exception as e:
        logger.debug(f"correlate: akce nedostupné: {e}")

    # Naše vlastní zásahy (486)
    try:
        for f in state.get_fix_attempts(limit=200) or []:
            if not _within(f.get('applied_at'), start, born):
                continue
            if host and f.get('host') and f['host'] != host:
                continue
            out.append({"kind": "fix_attempt", "at": f.get('applied_at'),
                        "what": f"Pokus o opravu na {f.get('host') or '?'}",
                        "detail": (f.get('command') or '')[:160]})
    except Exception as e:
        logger.debug(f"correlate: pokusy o opravu nedostupné: {e}")

    # Jiné problémy, které vypukly těsně předtím — často je to tentýž
    # kořen, jen se projevil dřív jinde.
    try:
        for other in state.get_active_issues() or []:
            if other.get('key') == (issue or {}).get('key'):
                continue
            if not _within(other.get('first_seen'), start, born):
                continue
            out.append({"kind": "prior_issue", "at": other.get('first_seen'),
                        "what": f"Jiný problém na {other.get('host') or '?'}",
                        "detail": f"[{other.get('plugin_name')}] "
                                  f"{(other.get('last_line') or '')[:120]}"})
    except Exception as e:
        logger.debug(f"correlate: souběžné issue nedostupné: {e}")

    for item in out:
        dt = _parse(item['at'])
        item['minutes_before'] = round((born - dt).total_seconds() / 60.0, 1) if dt else None
    return sorted(out, key=lambda x: x.get('minutes_before') if x.get('minutes_before') is not None else 1e9)


def changes_note(changes, limit: int = 5) -> str:
    """Shrnutí změn do promptu. Formulace nesmí naznačovat příčinnost."""
    if not changes:
        return "PŘEDCHOZÍ ZMĚNY: žádné nenalezeny.\n"
    lines = ["PŘEDCHOZÍ ZMĚNY (časová souvislost, ne důkaz příčiny):"]
    for c in changes[:limit]:
        mb = c.get('minutes_before')
        when = f"{mb:.0f} min před" if isinstance(mb, (int, float)) else "?"
        lines.append(f"- {when}: {c['what']} — {c['detail']}")
    return "\n".join(lines) + "\n"


def chain_prompt(issue, changes=None, telemetry_note: str = "") -> str:
    """447: Prompt, který vynutí STROM místo odstavce."""
    return (
        "Jsi zkušený SRE. Sestav řetěz příčin a následků pro tento problém.\n\n"
        f"PROBLÉM: [{(issue or {}).get('plugin_name', '?')}] "
        f"{(issue or {}).get('host', '?')}: "
        f"{((issue or {}).get('last_line') or '')[:250]}\n"
        f"{telemetry_note}"
        f"{changes_note(changes)}\n"
        "Vrať řetěz od kořenové příčiny k pozorovanému projevu. Každý článek "
        "je jedna krátká věta. Pokud si nejsi jistý, uveď nižší confidence.\n"
        'Odpověz POUZE JSON: {"root_cause": "<kořenová příčina>", '
        '"chain": ["<následek 1>", "<následek 2>"], '
        '"observed": "<co uživatel vidí>", "confidence": <0-100>}'
    )


def normalize_chain(data) -> dict | None:
    """447: Ověří a uklidí strukturu od modelu.

    Model rád vrátí řetěz jako jeden slepený řetězec nebo vnořené objekty;
    UI ale potřebuje plochý seznam kroků. Co se nedá srovnat, zahodíme —
    rozbitý strom je horší než žádný.
    """
    if not isinstance(data, dict):
        return None
    root = str(data.get('root_cause') or '').strip()
    observed = str(data.get('observed') or '').strip()
    if not root:
        return None

    raw = data.get('chain')
    steps = []
    if isinstance(raw, str):
        # „a -> b -> c", „a → b" i „a; b; c". Šipku sjednotit PŘED testem,
        # jinak se unicode varianta nerozdělí (podmínka by běžela na
        # původním textu, kde „->" není).
        text = raw.replace('→', '->')
        parts = text.split('->') if '->' in text else text.split(';')
        steps = [p.strip() for p in parts if p.strip()]
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str) and item.strip():
                steps.append(item.strip())
            elif isinstance(item, dict):
                val = item.get('effect') or item.get('step') or item.get('text')
                if val and str(val).strip():
                    steps.append(str(val).strip())

    try:
        conf = max(0, min(100, int(data.get('confidence'))))
    except (TypeError, ValueError):
        conf = None

    return {
        "root_cause": root[:300],
        "chain": [s[:300] for s in steps[:MAX_CHAIN_DEPTH]],
        "observed": observed[:300],
        "confidence": conf,
        # Celý řetěz včetně krajních článků — UI ho vykreslí jako strom.
        "nodes": [root[:300]] + [s[:300] for s in steps[:MAX_CHAIN_DEPTH]] +
                 ([observed[:300]] if observed else []),
    }

"""
486: Ověření, že oprava fungovala.

Dosud skončil zásah tím, že příkaz proběhl bez chyby — což ale neznamená,
že problém zmizel. Tenhle modul si pokus o opravu zapamatuje a po prodlevě
ověří, jestli se issue vrátil.

Verdikt je ZÁMĚRNĚ deterministický (porovnání časů), ne AI. AI se ptáme až
na interpretaci, pokud si o ni volající řekne — u otázky „vrátil se problém?"
je časové razítko spolehlivější než model.

Výsledek se propisuje do zpětné vazby (527): oprava, která prokazatelně
nezabrala, se zaznamená jako odmítnutá, takže ji autofix příště označí.
Tím se systém učí z reálných výsledků, ne jen z klikání uživatele.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Jak dlouho po zásahu čekáme, než vyhodnotíme. Kratší okno by označilo za
# úspěch i opravy, které jen na chvíli utišily symptom.
DEFAULT_WAIT_MIN = 15

# Horní mez — po ní má porovnání malou vypovídací hodnotu, protože se mezitím
# mohlo stát cokoli jiného.
MAX_WAIT_MIN = 240

VERDICT_WORKED = 'worked'
VERDICT_FAILED = 'failed'
VERDICT_UNCERTAIN = 'uncertain'
VERDICT_PENDING = 'pending'


def _parse_iso(value):
    """Tolerantní parsování času z DB. Vrací aware datetime v UTC, nebo None.

    Časy v DB jsou historicky psané dvěma způsoby (naive z SQLite
    `datetime('now')` a ISO s offsetem) — naive se považuje za UTC, jinak
    by rozdíl vyšel o hodiny vedle.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def is_due(attempt, now=None) -> bool:
    """Je pokus zralý na vyhodnocení?"""
    if (attempt or {}).get('status') != VERDICT_PENDING:
        return False
    due = _parse_iso(attempt.get('verify_after'))
    if not due:
        return False
    return (now or datetime.now(timezone.utc)) >= due


def evaluate(attempt, problem, now=None) -> tuple:
    """Vyhodnotí jeden pokus o opravu. Vrací (verdikt, vysvětlení).

    `problem` je aktuální stav issue z DB (None = issue už neexistuje).
    """
    now = now or datetime.now(timezone.utc)
    applied = _parse_iso((attempt or {}).get('applied_at'))
    if not applied:
        return VERDICT_UNCERTAIN, "Neznámý čas zásahu — nelze porovnat."

    waited_min = (now - applied).total_seconds() / 60.0
    if waited_min > MAX_WAIT_MIN:
        return (VERDICT_UNCERTAIN,
                f"Od zásahu uplynulo {int(waited_min)} min — na závěr příliš dlouho.")

    # Issue zmizel úplně (vyřešen, smazán) → oprava zabrala.
    if not problem:
        return VERDICT_WORKED, f"Issue po zásahu zmizel (po {int(waited_min)} min)."

    if problem.get('resolved') or problem.get('status') == 'resolved':
        return VERDICT_WORKED, f"Issue byl vyřešen {int(waited_min)} min po zásahu."

    last_seen = _parse_iso(problem.get('last_seen'))
    if not last_seen:
        return VERDICT_UNCERTAIN, "Issue nemá čas poslední detekce — nelze porovnat."

    # Jádro rozhodnutí: byl problém detekován ZNOVU až PO zásahu?
    if last_seen > applied:
        mins = (now - last_seen).total_seconds() / 60.0
        return (VERDICT_FAILED,
                f"Problém byl znovu detekován {int((last_seen - applied).total_seconds() / 60)} min "
                f"po zásahu (naposledy před {int(mins)} min) — oprava nezabrala.")

    return (VERDICT_WORKED,
            f"Od zásahu ({int(waited_min)} min) se problém znovu neobjevil.")


def summarize(attempts) -> dict:
    """Statistika úspěšnosti oprav — kolik zásahů reálně zabralo."""
    counts = {}
    for a in attempts or []:
        counts[a.get('status') or VERDICT_PENDING] = counts.get(a.get('status') or VERDICT_PENDING, 0) + 1
    worked = counts.get(VERDICT_WORKED, 0)
    failed = counts.get(VERDICT_FAILED, 0)
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "success_pct": round(worked / (worked + failed) * 100, 1) if (worked + failed) else None,
    }


def run_due_verifications(state, notify=None, now=None) -> dict:
    """Vyhodnotí všechny zralé pokusy. Vrací souhrn pro log.

    `state` a `notify` se předávají zvenčí, aby šel modul testovat bez DB
    a bez odesílání notifikací.
    """
    now = now or datetime.now(timezone.utc)
    done = {VERDICT_WORKED: 0, VERDICT_FAILED: 0, VERDICT_UNCERTAIN: 0}

    for attempt in state.get_pending_fix_attempts():
        if not is_due(attempt, now):
            continue
        try:
            problem = state.get_problem(attempt.get('problem_key'))
        except Exception as e:
            logger.error(f"fix_verify: get_problem selhalo: {e}")
            continue

        verdict, detail = evaluate(attempt, problem, now)
        if verdict == VERDICT_PENDING:
            continue
        state.close_fix_attempt(attempt['id'], verdict, detail)
        done[verdict] = done.get(verdict, 0) + 1

        # Propojení 486 → 527: co prokazatelně nezabralo, ať se příště
        # nenabízí jako hotové řešení. Uncertain se nezapisuje — u nejistého
        # výsledku by to jen zaneslo paměť falešnými odmítnutími.
        if verdict in (VERDICT_WORKED, VERDICT_FAILED) and attempt.get('command'):
            try:
                state.record_ai_feedback(
                    kind='autofix',
                    rating='applied' if verdict == VERDICT_WORKED else 'down',
                    suggestion=attempt['command'],
                    problem_key=attempt.get('problem_key') or '',
                    plugin_name=attempt.get('plugin_name') or '',
                    host=attempt.get('host') or '',
                    reason='' if verdict == VERDICT_WORKED else f"Ověřeno automaticky: {detail}",
                    username='auto-verify')
            except Exception as e:
                logger.error(f"fix_verify: zápis zpětné vazby selhal: {e}")

        if verdict == VERDICT_FAILED and notify:
            try:
                notify(attempt, detail)
            except Exception as e:
                logger.error(f"fix_verify: notifikace selhala: {e}")

    return done


def wait_until(minutes=None, now=None) -> str:
    """Čas, kdy se má pokus vyhodnotit (ISO, UTC)."""
    try:
        m = int(minutes) if minutes is not None else DEFAULT_WAIT_MIN
    except (TypeError, ValueError):
        m = DEFAULT_WAIT_MIN
    m = max(1, min(m, MAX_WAIT_MIN))
    return ((now or datetime.now(timezone.utc)) + timedelta(minutes=m)).isoformat()

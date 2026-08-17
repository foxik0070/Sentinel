"""Sdílená recheck pravidla — „platí ten issue ještě?"

Logika sem byla vytažena z routes/issues.py, kde žila uvnitř view funkce a šla
tedy spustit jen ručním kliknutím na stetoskop v UI. Kvůli tomu se issues, které
zdroj přestal hlásit, uzavíraly jen když si toho někdo všiml. Teď na stejná
pravidla sahá i periodický auto-recheck v scheduleru.

Pravidla jsou deterministická (žádná AI): rozhodují podle toho, jak dlouho zdroj
mlčí a jestli je zdroj vůbec schopen se ozvat.
"""
import logging
from datetime import datetime, timezone

from . import config, state

logger = logging.getLogger(__name__)

# Verdikty
STILL_ACTIVE = 'still_active'
RESOLVED = 'resolved'
UNCERTAIN = 'uncertain'


def issue_age_minutes(prob: dict) -> float:
    """Kolik minut uplynulo od poslední detekce. Nečitelný last_seen → 0.0."""
    try:
        seen = datetime.fromisoformat(prob.get('last_seen'))
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - seen).total_seconds() / 60.0
    except (TypeError, ValueError):
        return 0.0


def evaluate(prob: dict, key: str = '') -> tuple[str, str, float]:
    """Posoudí, jestli issue ještě platí.

    Vrací (verdict, detail, age_min). Verdict je STILL_ACTIVE / RESOLVED /
    UNCERTAIN — volající rozhodne, co s tím (UI nabídne force, scheduler
    UNCERTAIN nechá být).
    """
    key = key or prob.get('key') or ''
    age_min = issue_age_minutes(prob)

    fresh = int(getattr(config, 'RECHECK_FRESH_MIN', 10))
    agent_silence = int(getattr(config, 'RECHECK_AGENT_SILENCE_MIN', 15))
    source_silence = int(getattr(config, 'RECHECK_SOURCE_SILENCE_MIN', 45))

    if age_min < fresh:
        return (STILL_ACTIVE,
                f"Issue byl znovu detekován před {int(age_min)} min — stále platí.",
                age_min)

    if key.startswith('AGENT|'):
        hostname = key.split('|')[1] if '|' in key else ''
        try:
            agent = next((a for a in state.get_all_agents()
                          if a.get('hostname') == hostname), None)
        except Exception as e:
            logger.debug(f"evaluate: agenty se nepodařilo načíst: {e}")
            agent = None
        if agent and agent.get('status') == 'ONLINE' and age_min > agent_silence:
            return (RESOLVED,
                    f"Agent {hostname} je online a issue nehlásil {int(age_min)} min "
                    f"— problém pominul.",
                    age_min)
        if agent and agent.get('status') != 'ONLINE':
            return (UNCERTAIN,
                    f"Agent {hostname} je offline — nelze ověřit, ponecháno aktivní.",
                    age_min)
        return (UNCERTAIN,
                "Issue je čerstvý nebo agent neznámý — ponecháno aktivní.",
                age_min)

    if age_min > source_silence:
        # Interní detektory (telemetrie, HA, heartbeat, watcher) běží v řádu minut
        return (RESOLVED,
                f"Zdroj issue nere-detekoval {int(age_min)} min — problém pominul.",
                age_min)

    return (UNCERTAIN,
            f"Poslední detekce před {int(age_min)} min — příliš čerstvé "
            f"na automatické vyřešení.",
            age_min)


def auto_recheck_pass(min_age_hours: int | None = None) -> list:
    """Projede dlouho otevřené issues a uzavře ty, které podle pravidel pominuly.

    Záměrně řeší jen verdikt RESOLVED — UNCERTAIN se nechává člověku. Vrací
    seznam (key, detail) uzavřených issues.
    """
    if not getattr(config, 'AUTO_RECHECK_ENABLED', True):
        return []
    # None = vzít z configu; explicitní 0 znamená "bez minimálního stáří"
    min_age = int(min_age_hours if min_age_hours is not None
                  else getattr(config, 'AUTO_RECHECK_MIN_AGE_HOURS', 6))
    min_age_min = max(0, min_age) * 60.0

    closed = []
    try:
        issues = state.get_active_issues(include_snoozed=False)
    except Exception as e:
        logger.error(f"auto_recheck_pass: nelze načíst issues: {e}")
        return []

    for prob in issues:
        key = prob.get('key') or ''
        if not key:
            continue
        # Acknowledged necháváme být — někdo o nich ví a řeší je.
        if (prob.get('status') or '') == 'acknowledged':
            continue
        try:
            verdict, detail, age_min = evaluate(prob, key)
        except Exception as e:
            logger.debug(f"auto_recheck_pass: {key}: {e}")
            continue
        if verdict != RESOLVED or age_min < min_age_min:
            continue
        try:
            state.mark_resolved(key, reason='recheck_auto', resolved_by='system')
            closed.append((key, detail))
        except Exception as e:
            logger.error(f"auto_recheck_pass: mark_resolved({key}) selhalo: {e}")

    if closed:
        logger.info(f"auto_recheck_pass: uzavřeno {len(closed)} issues")
    return closed

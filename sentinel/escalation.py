"""
499: Eskalace s kontextem.

Dosud eskalace řekla jen „issue je aktivní 26 h → priorita HIGH". Kdo se tím
budí ve tři ráno, z toho nepozná nic — hlavně ne, co už se zkoušelo.

Kontext skládáme z toho, co systém opravdu ví:
  - co se už zkusilo opravit a jak to dopadlo (486)
  - jestli se problém opakuje a jak často
  - co ukazuje telemetrie proti běžnému stavu (449)
  - co se děje na stejném stroji souběžně (446)

Fakta jsou deterministická. AI se ptáme až na shrnutí, a když není po ruce,
zpráva se pošle i bez něj — eskalace nesmí padnout kvůli nedostupnému modelu.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_ATTEMPTS_SHOWN = 3
MAX_SIBLINGS_SHOWN = 4
MAX_METRICS_SHOWN = 3


def _age_hours(iso_value, now=None) -> float | None:
    if not iso_value:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - dt).total_seconds() / 3600.0


def collect(state, issue, now=None) -> dict:
    """Posbírá fakta k issue. Každý zdroj je izolovaný — výpadek jednoho
    nesmí připravit příjemce o zbytek kontextu."""
    ctx = {"attempts": [], "siblings": [], "metrics": [], "recurring": None}
    key = (issue or {}).get('key') or ''
    host = (issue or {}).get('host') or ''

    try:
        attempts = state.get_fix_attempts(key, limit=10) or []
        ctx["attempts"] = attempts[:MAX_ATTEMPTS_SHOWN]
        ctx["attempts_total"] = len(attempts)
        ctx["attempts_failed"] = sum(1 for a in attempts if a.get('status') == 'failed')
    except Exception as e:
        logger.debug(f"escalation: pokusy o opravu nedostupné: {e}")

    try:
        ctx["recurring"] = issue.get('recurring_count') or issue.get('occurrences')
    except Exception:
        pass

    try:
        tele = state.get_telemetry_context(host, issue.get('last_seen'))
        ctx["metrics"] = (tele or {}).get('metrics', [])[:MAX_METRICS_SHOWN]
    except Exception as e:
        logger.debug(f"escalation: telemetrie nedostupná: {e}")

    try:
        others = [i for i in (state.get_active_issues() or [])
                  if i.get('host') == host and i.get('key') != key]
        ctx["siblings"] = others[:MAX_SIBLINGS_SHOWN]
        ctx["siblings_total"] = len(others)
    except Exception as e:
        logger.debug(f"escalation: souběžné issue nedostupné: {e}")

    return ctx


def format_message(issue, ctx, age_hours, target_sev, ai_summary=None) -> str:
    """Sestaví HTML zprávu. Vstupy jsou z DB, ne od uživatele, ale escapujeme
    stejně — obsah logu je cizí text a nemá co ovlivňovat rozvržení zprávy."""
    import html as _html

    def esc(v, limit=120):
        return _html.escape(str(v or '')[:limit])

    lines = [
        f"⚠️ <b>Eskalace → {esc(target_sev).upper()}</b>",
        f"<b>{esc(issue.get('host'), 60)}</b> [{esc(issue.get('plugin_name'), 40)}]",
        f"<code>{esc(issue.get('last_line'), 160)}</code>",
        f"Aktivní <b>{age_hours:.1f} h</b>",
    ]

    if ctx.get("recurring"):
        lines.append(f"Opakuje se: <b>{esc(ctx['recurring'], 10)}×</b>")

    attempts = ctx.get("attempts") or []
    if attempts:
        # Nejdůležitější část: ať příjemce nezkouší podruhé to, co nezabralo.
        lines.append(f"<b>Už se zkoušelo ({ctx.get('attempts_total', len(attempts))}×):</b>")
        icon = {'worked': '✅', 'failed': '❌', 'pending': '⏳', 'uncertain': '❔'}
        for a in attempts:
            lines.append(f"&nbsp;&nbsp;{icon.get(a.get('status'), '•')} "
                         f"<code>{esc(a.get('command'), 80)}</code>")
    else:
        lines.append("<b>Zatím se nic nezkusilo.</b>")

    metrics = ctx.get("metrics") or []
    if metrics:
        parts = []
        for m in metrics:
            d = m.get('delta_pct')
            parts.append(f"{esc(m.get('metric'), 30)} {d:+.0f}%" if isinstance(d, (int, float))
                         else esc(m.get('metric'), 30))
        lines.append("<b>Telemetrie:</b> " + ", ".join(parts))

    siblings = ctx.get("siblings") or []
    if siblings:
        total = ctx.get('siblings_total', len(siblings))
        names = ", ".join(esc(s.get('plugin_name'), 30) for s in siblings)
        lines.append(f"<b>Souběžně na stroji ({total}):</b> {names}")

    if ai_summary:
        lines.append(f"<b>AI:</b> {esc(ai_summary, 400)}")

    return "<br>".join(lines)


def ai_prompt(issue, ctx, age_hours) -> str:
    """Prompt pro shrnutí. Zdůrazňuje neúspěšné pokusy — právě ty odlišují
    eskalaci od původního alertu."""
    tried = "\n".join(
        f"- {a.get('command')} → {a.get('status')}" for a in (ctx.get("attempts") or [])
    ) or "- nic"
    metrics = ", ".join(
        f"{m.get('metric')} {m.get('delta_pct'):+.0f}%"
        for m in (ctx.get("metrics") or [])
        if isinstance(m.get('delta_pct'), (int, float))
    ) or "beze změny"
    return (
        "Jsi SRE. Problém se nedaří vyřešit a eskaluje se. Napiš 1-2 věty česky "
        "pro kolegu, který ho přebírá: co je nejpravděpodobnější příčina a co "
        "zkusit dál. Neopakuj, co už selhalo.\n\n"
        f"PROBLÉM: [{issue.get('plugin_name', '?')}] {issue.get('host', '?')}: "
        f"{(issue.get('last_line') or '')[:200]}\n"
        f"AKTIVNÍ: {age_hours:.1f} h\n"
        f"UŽ SE ZKOUŠELO:\n{tried}\n"
        f"TELEMETRIE: {metrics}\n\n"
        # Bez tohohle malé modely papouškují znění otázky („Co je příčina: …"),
        # což ve zprávě zabírá místo a nic nepřidá (ověřeno na llama3.2).
        "Piš rovnou souvislý text. Neopakuj zadání ani nadpisy jako "
        "„Příčina:\" nebo „Co zkusit dál:\"."
    )


def build(state, issue, age_hours, target_sev, ask_ai=None, now=None) -> str:
    """Kompletní eskalační zpráva. `ask_ai` je volitelná funkce prompt→text."""
    ctx = collect(state, issue, now)
    summary = None
    if ask_ai:
        try:
            summary = (ask_ai(ai_prompt(issue, ctx, age_hours)) or '').strip() or None
        except Exception as e:
            logger.warning(f"escalation: AI shrnutí selhalo, posílám bez něj: {e}")
    return format_message(issue, ctx, age_hours, target_sev, summary)

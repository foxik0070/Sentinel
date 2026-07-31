"""
493: Učení z ručních zásahů.

Když admin problém vyřeší sám přes SSH, ta znalost dnes zmizí — příště
stejný problém řeší znovu od nuly a AI navrhuje něco jiného.

Odvozujeme postup z toho, co se opravdu stalo: ruční příkaz, po kterém
problém zmizel. Klíčem je PODPIS problému (plugin + otisk hlášky), aby se
postup našel i u dalšího výskytu s jinými čísly.

ČEHO SE DRŽET:

1. Souvislost v čase není důkaz. „Problém zmizel po příkazu" neznamená, že
   ho vyřešil ten příkaz — mohl pominout sám. Proto se vyžaduje VÍCE
   nezávislých potvrzení a výsledek je návrh, ne pravidlo.

2. Postup se nikdy nespouští sám. Je to nabídka pro člověka; k automatice
   vede jen cesta přes allowlist a 505.

3. Neúspěšné příkazy se nesbírají. Co selhalo, není postup.
"""
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Do jaké doby po příkazu musí problém zmizet, aby se to počítalo.
# Delší okno by spojovalo nesouvisející věci.
RESOLVE_WINDOW_MIN = 30

# Kolik nezávislých potvrzení chceme, než postup nabídneme.
MIN_EVIDENCE = 2

# Účty, které nejsou člověk — jejich zásahy už řeší 486/505.
_NON_HUMAN = {'ai_auto', 'system', 'auto-verify', 'action', ''}


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


def signature(plugin: str, message: str) -> str:
    """Podpis problému — plugin + otisk hlášky bez proměnlivých částí."""
    from .alert_quality import normalize_message
    return f"{(plugin or '?').strip()}|{normalize_message(message)}"


def _human_commands(ssh_log, actions):
    """Ruční, úspěšné příkazy z obou zdrojů, sjednocené do jednoho tvaru."""
    out = []
    for row in ssh_log or []:
        if not isinstance(row, dict) or not row.get('success'):
            continue
        actor = str(row.get('actor') or '').strip().lower()
        if actor in _NON_HUMAN:
            continue
        out.append({"host": row.get('hostname') or '', "command": row.get('command') or '',
                    "at": row.get('executed_at'), "actor": row.get('actor') or '',
                    "source": "ssh_console"})
    for a in actions or []:
        if not isinstance(a, dict) or a.get('status') != 'executed':
            continue
        actor = str(a.get('executed_by') or '').strip().lower()
        if actor in _NON_HUMAN:
            continue
        out.append({"host": a.get('node') or '', "command": a.get('command') or '',
                    "at": a.get('executed_at') or a.get('created_at'),
                    "actor": a.get('executed_by') or '', "source": "action",
                    "problem_key": a.get('problem_key') or ''})
    return [c for c in out if c['command'] and _parse(c['at'])]


def derive(resolved_issues, ssh_log=None, actions=None,
           min_evidence: int = MIN_EVIDENCE, window_min: int = RESOLVE_WINDOW_MIN) -> list:
    """493: Odvodí postupy z ručních zásahů, po kterých problém zmizel.

    `resolved_issues` = záznamy z issue_history (mají resolved_at).
    """
    cmds = _human_commands(ssh_log, actions)
    if not cmds:
        return []

    book: dict = {}
    for iss in resolved_issues or []:
        if not isinstance(iss, dict):
            continue
        resolved = _parse(iss.get('resolved_at'))
        if not resolved:
            continue
        host = iss.get('host') or ''
        sig = signature(iss.get('plugin_name'), iss.get('last_line'))

        for c in cmds:
            at = _parse(c['at'])
            # Příkaz musí PŘEDCHÁZET vyřešení a být blízko.
            if not at or at > resolved:
                continue
            if (resolved - at).total_seconds() / 60.0 > window_min:
                continue
            # Buď byl navázaný přímo na tenhle problém, nebo aspoň na týž stroj.
            same_key = c.get('problem_key') and c['problem_key'] == iss.get('key')
            if not same_key and (not host or c['host'] != host):
                continue
            entry = book.setdefault((sig, c['command']), {
                "signature": sig, "command": c['command'],
                "plugin_name": iss.get('plugin_name') or '', "hosts": set(),
                "actors": set(), "issues": set(), "direct_links": 0,
                "sample_message": (iss.get('last_line') or '')[:200],
            })
            # Důkazem je POČET RŮZNÝCH INCIDENTŮ, ne počet dvojic. Kdyby se
            # počítaly dvojice, tři incidenty a tři příkazy v okně by daly
            # devět „důkazů" a jistota by vyletěla z ničeho.
            entry["issues"].add(iss.get('key') or id(iss))
            entry["hosts"].add(host)
            entry["actors"].add(c['actor'])
            if same_key:
                entry["direct_links"] += 1

    out = []
    for e in book.values():
        e["evidence"] = len(e["issues"])
        if e["evidence"] < min_evidence:
            continue
        out.append({
            "signature": e["signature"],
            "plugin_name": e["plugin_name"],
            "command": e["command"],
            "evidence": e["evidence"],
            "direct_links": e["direct_links"],
            "hosts": sorted(h for h in e["hosts"] if h),
            "actors": sorted(a for a in e["actors"] if a),
            "sample_message": e["sample_message"],
            "confidence": _confidence(e),
            "caveat": ("Odvozeno z časové souvislosti — problém mohl pominout "
                       "i sám. Ověř, než to použiješ."),
        })
    return sorted(out, key=lambda x: (-x["confidence"], -x["evidence"]))


def _confidence(entry) -> int:
    """Hrubá jistota 0-100. Přímá vazba na issue váží víc než shoda stroje."""
    # Postupně, ne skokem — dva incidenty jsou náznak, pět už vzorec.
    score = min(60, 12 + entry["evidence"] * 10)
    score += min(30, entry["direct_links"] * 15)
    if len(entry["actors"]) > 1:
        score += 10                     # nezávisle potvrzeno víc lidmi
    return min(100, score)


def find_for_issue(playbooks, issue) -> list:
    """Postupy použitelné na konkrétní problém."""
    sig = signature((issue or {}).get('plugin_name'), (issue or {}).get('last_line'))
    return [p for p in playbooks or [] if p.get('signature') == sig]

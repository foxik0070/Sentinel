"""
463: Iterativní vyšetřování — hypotéza → diagnostika → vyhodnocení → další krok.
494: Runbook generátor z vyřešeného incidentu.
496: Návrh preventivního opatření — aby se to nestalo znovu.
520: Verzování promptů a měření dopadu změny.
534: Anotace pro fine-tuning — dvojice (incident → správné řešení).
542: Sdílení znalostí mezi instancemi (export/import naučené KB).

Společné téma: **z vyřešeného incidentu vytěžit něco trvalého.** Dnes se
znalost rozplyne — příště ji někdo objevuje znovu. Runbook, prevence
i trénovací data jsou tři různé způsoby, jak ji udržet.

Co se sem NEDOSTANE: incident bez ověřeného řešení. Runbook opsaný ze
špatné opravy je horší než žádný, protože ho někdo příště poslechne.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Kolik kol smí vyšetřování udělat, než to předá člověku.
MAX_INVESTIGATION_ROUNDS = 3


# --- 463 -------------------------------------------------------------------

def next_investigation_step(rounds, max_rounds: int = MAX_INVESTIGATION_ROUNDS) -> dict:
    """463: Pokračovat ve vyšetřování, nebo to předat?

    `rounds` = [{"hypothesis": ..., "confirmed": bool|None, "confidence": int}, ...]

    Smyčka se zastaví, když je hypotéza potvrzená (máme odpověď), když se
    přestane hýbat (další kolo by jen spálilo čas), nebo po `max_rounds`.
    Nekonečné vyšetřování je horší než přiznat, že na to nestačíme.
    """
    done = [r for r in (rounds or []) if isinstance(r, dict)]
    if not done:
        return {"action": "investigate", "round": 1,
                "note": "První kolo — ověřit nejpravděpodobnější hypotézu."}

    last = done[-1]
    if last.get('confirmed') is True:
        return {"action": "conclude", "round": len(done),
                "hypothesis": last.get('hypothesis'),
                "note": "Hypotéza potvrzená — dál není co zjišťovat."}

    if len(done) >= max_rounds:
        return {"action": "escalate", "round": len(done),
                "note": (f"Po {len(done)} kolech se příčinu určit nepodařilo. "
                         f"Další kolo by jen spálilo čas — předej člověku.")}

    # Nezlepšuje-li se jistota, další kolo nemá smysl: model jen opisuje
    # totéž jinými slovy.
    if len(done) >= 2:
        prev, cur = done[-2].get('confidence'), last.get('confidence')
        if isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and cur <= prev:
            return {"action": "escalate", "round": len(done),
                    "note": ("Jistota se mezi koly nezvýšila — další diagnostika "
                             "nepomáhá, předej člověku.")}

    tried = [r.get('hypothesis') for r in done if r.get('hypothesis')]
    return {"action": "investigate", "round": len(done) + 1,
            "exclude": tried,
            "note": f"Kolo {len(done) + 1} — vyloučeno: {', '.join(t[:40] for t in tried[:3])}"}


def investigation_prompt(issue, rounds, evidence: str = "") -> str:
    """463: Prompt pro další kolo — s tím, co už bylo vyloučeno."""
    from .ai_guard import wrap_untrusted
    safe, _ = wrap_untrusted((issue or {}).get('last_line') or '', "hláška z logu")
    excluded = "\n".join(
        f"- {r.get('hypothesis')} → {'potvrzeno' if r.get('confirmed') else 'VYVRÁCENO'}"
        for r in (rounds or []) if isinstance(r, dict) and r.get('hypothesis')) or "- nic"
    return (
        "Jsi zkušený SRE uprostřed vyšetřování. Níže je problém, co už bylo "
        "vyloučeno a nová data.\n\n"
        f"PROBLÉM: {(issue or {}).get('host', '?')}:\n{safe}\n\n"
        f"UŽ VYLOUČENO (neopakuj to):\n{excluded}\n\n"
        f"NOVÁ DATA:\n{evidence or '(žádná)'}\n\n"
        "Navrhni JINOU hypotézu než ty vyloučené a řekni, čím ji ověřit.\n"
        'Odpověz POUZE JSON: {"hypothesis": "<nová hypotéza>", '
        '"verify_by": "<čím ověřit>", "confidence": <0-100>}'
    )


# --- 494 -------------------------------------------------------------------

def build_runbook(issue, attempts, timeline=None, changes=None) -> dict | None:
    """494: Runbook z incidentu, který má OVĚŘENÉ řešení.

    Bez ověřeného řešení se runbook negeneruje. Návod opsaný ze špatné
    opravy je horší než žádný — někdo ho příště poslechne.
    """
    worked = [a for a in (attempts or [])
              if isinstance(a, dict) and a.get('status') == 'worked' and a.get('command')]
    if not worked:
        return None

    failed = [a.get('command') for a in (attempts or [])
              if isinstance(a, dict) and a.get('status') == 'failed' and a.get('command')]

    from .alert_quality import normalize_message
    return {
        "title": (f"[{(issue or {}).get('plugin_name', '?')}] "
                  f"{(issue or {}).get('last_line') or ''}")[:120],
        "signature": normalize_message((issue or {}).get('last_line')),
        "plugin_name": (issue or {}).get('plugin_name'),
        "symptom": ((issue or {}).get('last_line') or '')[:300],
        "solution": worked[-1]['command'],
        "solution_verified": True,
        # Co NEfungovalo je stejně cenné jako co fungovalo — ušetří to
        # příštímu člověku slepé uličky.
        "tried_and_failed": failed[:5],
        "diagnostics": [e.get('text') for e in (timeline or [])
                        if isinstance(e, dict) and e.get('kind') in
                        ('fix_attempt', 'fix_verified')][:8],
        "preceding_changes": [c.get('what') for c in (changes or []) if isinstance(c, dict)][:3],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def runbook_markdown(rb) -> str:
    """494: Runbook v podobě, kterou jde vložit do wiki."""
    if not rb:
        return ""
    lines = [f"# {rb['title']}", "",
             "## Příznak", rb['symptom'], "",
             "## Řešení", f"```\n{rb['solution']}\n```",
             "*Ověřeno: problém se po tomto zásahu nevrátil.*", ""]
    if rb.get('tried_and_failed'):
        lines += ["## Co nepomohlo", ""]
        lines += [f"- `{c}`" for c in rb['tried_and_failed']]
        lines.append("")
    if rb.get('preceding_changes'):
        lines += ["## Co předcházelo", ""]
        lines += [f"- {c}" for c in rb['preceding_changes']]
    return "\n".join(lines)


# --- 496 -------------------------------------------------------------------

# Opakující se problém se neřeší zásahem, ale změnou nastavení. Návrh se
# odvíjí od toho, CO se opakuje — u disku má smysl rotace logů, u služby
# restart policy.
_PREVENTION = [
    (('disk', 'space', 'místo', 'full'), 'logrotate / journald limit',
     'Nastavit `SystemMaxUse` v journald a rotaci logů, ať se to nenaplní znovu.'),
    (('memory', 'oom', 'paměť'), 'limit paměti v unitu',
     'Přidat `MemoryMax=` do systemd unitu, ať proces nesebere stroj celý.'),
    (('service', 'failed', 'služba'), 'restart policy',
     'Přidat `Restart=on-failure` a `RestartSec=` do unitu — systemd to zvedne sám.'),
    (('cert', 'expir', 'tls', 'ssl'), 'automatická obnova',
     'Nastavit certbot/acme timer, ať obnova neleží na člověku.'),
    (('backup', 'záloh'), 'monitoring zálohy',
     'Hlídat stáří poslední úspěšné zálohy, ne jen výsledek posledního běhu.'),
    (('temp', 'thermal', 'teplot'), 'chlazení nebo limit',
     'Ověřit chlazení; případně snížit zátěž přes `CPUQuota=`.'),
    (('connection', 'refused', 'timeout'), 'health check a závislosti',
     'Doplnit `After=`/`Requires=` a health check, ať pořadí startu sedí.'),
]


def suggest_prevention(issue, occurrences: int = 1) -> dict:
    """496: Co udělat, aby se to nestalo znovu.

    U jednorázového problému se prevence nenavrhuje — ne všechno, co se
    jednou pokazí, potřebuje trvalé opatření.
    """
    if occurrences < 2:
        return {"suggest": False, "note": "Zatím jednorázové — prevence není potřeba."}

    text = f"{(issue or {}).get('plugin_name', '')} {(issue or {}).get('last_line', '')}".lower()
    for keys, what, how in _PREVENTION:
        if any(k in text for k in keys):
            return {"suggest": True, "measure": what, "how": how,
                    "occurrences": occurrences,
                    "note": (f"Opakuje se {occurrences}× — zásah problém řeší "
                             f"dočasně, tohle trvale.")}
    return {"suggest": True, "measure": "neurčeno", "how": "",
            "occurrences": occurrences,
            "note": (f"Opakuje se {occurrences}×, ale typ problému neznáme — "
                     f"posuď ručně, co by to trvale vyřešilo.")}


# --- 520 -------------------------------------------------------------------

def prompt_version(text: str) -> str:
    """520: Otisk promptu. Změna promptu = jiná verze = jiná měřitelná sada."""
    norm = ' '.join(str(text or '').split())
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def compare_prompt_scores(runs) -> dict:
    """520: Zlepšila změna promptu výsledky, nebo zhoršila?

    `runs` = [{"prompt_version": ..., "score": 0-100, "at": iso}, ...]
    Bez tohohle se prompty ladí podle dojmu.
    """
    by_ver: dict = {}
    for r in runs or []:
        if not isinstance(r, dict):
            continue
        v, s = r.get('prompt_version'), r.get('score')
        if not v or not isinstance(s, (int, float)):
            continue
        by_ver.setdefault(v, []).append(float(s))

    stats = {v: {"runs": len(xs), "avg": round(sum(xs) / len(xs), 1)}
             for v, xs in by_ver.items()}
    if len(stats) < 2:
        return {"comparable": False, "versions": stats,
                "note": "Na porovnání je potřeba aspoň dvě verze promptu."}

    ordered = sorted(stats.items(), key=lambda kv: -kv[1]['avg'])
    best, worst = ordered[0], ordered[-1]
    return {"comparable": True, "versions": stats,
            "best": best[0], "best_avg": best[1]['avg'],
            "worst": worst[0], "worst_avg": worst[1]['avg'],
            "delta": round(best[1]['avg'] - worst[1]['avg'], 1)}


# --- 534 -------------------------------------------------------------------

def export_training_pairs(history, attempts, min_confidence: str = 'worked') -> list:
    """534: Dvojice (incident → ověřené řešení) pro případný fine-tuning.

    Bere se jen to, co prokazatelně zabralo. Trénovat na neověřených
    odpovědích znamená naučit model dnešní chyby.
    """
    by_key = {h.get('key'): h for h in (history or [])
              if isinstance(h, dict) and h.get('key')}
    out, seen = [], set()
    for a in attempts or []:
        if not isinstance(a, dict) or a.get('status') != min_confidence:
            continue
        iss = by_key.get(a.get('problem_key'))
        cmd = (a.get('command') or '').strip()
        if not iss or not cmd:
            continue
        prompt = (f"[{iss.get('plugin_name')}] {iss.get('host')}: "
                  f"{(iss.get('last_line') or '')[:200]}")
        key = (prompt, cmd)
        if key in seen:
            continue
        seen.add(key)
        out.append({"messages": [
            {"role": "user", "content": f"Systémový alert:\n{prompt}\nJak to vyřešit?"},
            {"role": "assistant", "content": cmd},
        ], "verified": True, "host": iss.get('host')})
    return out


def training_jsonl(pairs) -> str:
    """534: JSONL, jak ho čekají trénovací nástroje."""
    return "\n".join(json.dumps({"messages": p["messages"]}, ensure_ascii=False)
                     for p in (pairs or []))


# --- 542 -------------------------------------------------------------------

KB_EXPORT_VERSION = 1


def export_kb(chunks, source: str = 'sentinel') -> dict:
    """542: Naučená KB pro přenos na jinou instanci."""
    from .rag_utils import dedupe_chunks
    clean = dedupe_chunks(chunks)
    return {
        "version": KB_EXPORT_VERSION,
        "source": str(source)[:64],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(clean),
        "checksum": hashlib.sha256("".join(clean).encode()).hexdigest()[:16],
        "chunks": clean,
    }


def import_kb(payload, existing=None) -> dict:
    """542: Import cizí KB — jen to, co ještě nemáme.

    Ověřuje se kontrolní součet i formát. Cizí KB je cizí vstup: poškozený
    nebo podvržený soubor by otrávil znalostní bázi, ze které pak model
    odpovídá.
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "očekáván objekt", "imported": 0}
    if payload.get('version') != KB_EXPORT_VERSION:
        return {"ok": False, "imported": 0,
                "error": f"nepodporovaná verze {payload.get('version')!r}"}
    chunks = payload.get('chunks')
    if not isinstance(chunks, list):
        return {"ok": False, "error": "chybí seznam chunků", "imported": 0}

    clean = [str(c).strip() for c in chunks if str(c or '').strip()]
    expected = payload.get('checksum')
    actual = hashlib.sha256("".join(clean).encode()).hexdigest()[:16]
    if expected and expected != actual:
        return {"ok": False, "imported": 0,
                "error": "kontrolní součet nesedí — soubor je poškozený nebo upravený"}

    have = {' '.join(str(c).lower().split()) for c in (existing or [])}
    new = [c for c in clean if ' '.join(c.lower().split()) not in have]
    return {"ok": True, "imported": len(new), "skipped": len(clean) - len(new),
            "chunks": new, "source": payload.get('source')}

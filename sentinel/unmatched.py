"""
466: AI čte nezachycené logy.

Detektory hlásí jen to, na co má někdo pattern. Řádek, který vypadá jako
chyba, ale žádný plugin ho nezpracoval, propadne — a nikdo se o něm nedozví,
protože chybějící alert není vidět.

Sbíráme VZOREK takových řádků a necháme model navrhnout pattern. Návrh se
nikdy neaktivuje sám: špatný pattern buď zaplaví systém šumem, nebo tiše
překryje detektor, který fungoval.

VÝKON: běží to v cestě watcheru nad každým řádkem logu, takže se drží
levné operace — jeden test na klíčové slovo a zápis do ohraničené paměti.
Žádné regexy, žádná DB, žádné volání AI.
"""
import logging
import threading

logger = logging.getLogger(__name__)

# Slova, po kterých řádek vypadá jako problém. Levný test podřetězcem;
# regex by na téhle cestě stál znatelně víc.
_SIGNALS = ('error', 'fail', 'critical', 'fatal', 'denied', 'refused',
            'timeout', 'panic', 'exception', 'unable to', 'cannot ',
            'chyba', 'selhal', 'odmít')

# Kolik vzorků držíme. Strop, ne fronta — po naplnění se přestává sbírat,
# aby zaplavený log nesnědl paměť.
MAX_SAMPLES = 500

# Delší řádky ořezat, ať stack trace nezabere celý strop.
MAX_LINE_LEN = 400

_samples: dict = {}
_lock = threading.Lock()
_stats = {"seen": 0, "captured": 0, "dropped_full": 0}


def looks_interesting(line: str) -> bool:
    """Vypadá řádek jako problém?"""
    low = str(line or '').lower()
    return any(s in low for s in _SIGNALS)


def record(file_path: str, lines) -> int:
    """Zapamatuje si vzorek nezachycených řádků. Vrací počet nových.

    Seskupuje se podle otisku hlášky, takže tisíc stejných chyb zabere
    jedno místo a v přehledu je vidět, jak často se to děje.
    """
    from .alert_quality import normalize_message
    added = 0
    for line in lines or []:
        text = str(line or '').strip()
        if not text:
            continue
        _stats["seen"] += 1
        if not looks_interesting(text):
            continue
        key = (file_path or '?', normalize_message(text))
        with _lock:
            if key in _samples:
                _samples[key]["count"] += 1
                continue
            if len(_samples) >= MAX_SAMPLES:
                _stats["dropped_full"] += 1
                continue
            _samples[key] = {"file": file_path or '?', "sample": text[:MAX_LINE_LEN],
                             "pattern": key[1], "count": 1}
            _stats["captured"] += 1
            added += 1
    return added


def top(limit: int = 20) -> list:
    """Nejčastější nezachycené hlášky."""
    with _lock:
        items = sorted(_samples.values(), key=lambda x: -x["count"])
    return items[:max(1, int(limit))]


def stats() -> dict:
    with _lock:
        return dict(_stats, groups=len(_samples))


def clear():
    with _lock:
        _samples.clear()
        for k in _stats:
            _stats[k] = 0


def suggest_prompt(items) -> str:
    """Prompt pro návrh patternů z nezachycených řádků."""
    block = "\n".join(f"[{i['file']}] (×{i['count']}) {i['sample'][:200]}"
                      for i in (items or [])[:15])
    return (
        "Jsi expert na monitoring logů. Následující řádky vypadají jako problém, "
        "ale žádný detektor je nezachytil.\n\n"
        f"ŘÁDKY:\n{block}\n\n"
        "Navrhni nejvýše 3 regexy, které by tyhle případy detekovaly. Regex musí "
        "být konkrétní — příliš obecný by hlásil i běžný provoz.\n"
        'Odpověz POUZE JSON pole: [{"name":"...", "pattern":"...", '
        '"reason":"...", "example":"..."}]'
    )


def validate_suggestions(suggestions, samples=None) -> list:
    """Ověří, že navržené regexy jsou platné a nejsou nebezpečně obecné.

    Pattern typu `.*` nebo `error` chytne skoro každý řádek a zaplaví systém
    — nemá smysl ho nabízet.
    """
    import re
    out = []
    for s in suggestions or []:
        if not isinstance(s, dict):
            continue
        pat = str(s.get('pattern') or '').strip()
        if not pat:
            continue
        try:
            rx = re.compile(pat)
        except re.error as e:
            logger.debug(f"466: neplatný regex {pat!r}: {e}")
            continue
        # Test na obecnost PŘED délkou: `.*` je krátké i nebezpečné zároveň
        # a je užitečnější ho vrátit označené než ho tiše zahodit — admin
        # jinak neví, že model navrhl něco, co by zaplavilo systém.
        if _too_broad(rx, pat):
            out.append(dict(s, pattern=pat,
                            rejected="příliš obecný — chytal by běžný provoz"))
            continue
        if len(pat) < 4:
            continue                    # příliš krátký na smysluplný detektor
        matched = sum(1 for it in (samples or []) if rx.search(it.get('sample', '')))
        out.append(dict(s, pattern=pat, matches_samples=matched, rejected=None))
    return out


def _too_broad(rx, pattern: str) -> bool:
    """Chytá pattern i text, který s problémem nesouvisí?"""
    if pattern.strip('^$') in ('.*', '.+', '.', '\\w+', '\\S+'):
        return True
    benign = [
        "Started Session 12345 of user root.",
        "Accepted publickey for sentinel from 192.168.2.1 port 22 ssh2",
        "GET /api/status HTTP/1.1 200 512",
        "systemd[1]: Reached target Multi-User System.",
    ]
    return sum(1 for b in benign if rx.search(b)) >= 2

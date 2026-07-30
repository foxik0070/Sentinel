"""
516: Detekce halucinací v AI odpovědích.

Model si běžně vymyslí hostname nebo službu, která v infrastruktuře není —
zní to věrohodně a člověk podle toho začne hledat neexistující stroj.

ZÁMĚRNĚ OPATRNÉ: neoznačujeme „nepravda", ale „tohle neznám, ověř si to".
Falešné obvinění správné odpovědi je horší než přehlédnutá halucinace,
protože podkope důvěru v celé upozornění.

Co se dá ověřit a co ne:
  - hostnames  → tvrdá pravda (agenti, infra mapa, issue) — hlásíme spolehlivě
  - služby     → jen „už jsme ji někdy viděli"; nová služba být legitimní může,
                 proto nižší závažnost
  - cesty      → NEOVĚŘUJEME, na to bychom museli na stroj; hlásit je jako
                 podezřelé by generovalo samý šum
"""
import logging
import re

logger = logging.getLogger(__name__)

# Hostname: alfanumerické skupiny oddělené tečkou/pomlčkou. Uvnitř kódu
# a URL se nechytá, to řešíme níž.
_HOST_RE = re.compile(r'\b([a-z][a-z0-9]*(?:[-.][a-z0-9]+)+)\b', re.I)
_SERVICE_RE = re.compile(r'\b([a-z][a-z0-9_-]{2,40}\.service)\b', re.I)

# Jednoslovný název (bez tečky a pomlčky) se od běžného podstatného jména
# odlišit nedá — chytáme ho jen tam, kde ho model uvedl slovem „stroj/host/…".
_INTRODUCED_RE = re.compile(
    r'\b(?:stroj[iíe]?|hostitel[ie]?|host|node|nodu|server(?:u|y)?|uzl[uy]|uzel)\s+'
    r'([a-z][a-z0-9._-]{2,40})\b', re.I)

# Slova, která po „stroj/server" následují běžně a strojem nejsou.
_STOPWORDS = {
    'je', 'není', 'neni', 'byl', 'byla', 'bylo', 'má', 'ma', 'nemá', 'nema',
    'se', 'si', 'na', 'do', 'od', 'ale', 'a', 'i', 'v', 've', 'za', 'po',
    'pro', 'jako', 'kde', 'který', 'ktery', 'která', 'ktera', 'jsou', 'byly',
    'nefunguje', 'funguje', 'běží', 'bezi', 'spadl', 'spadla', 'restart',
    'restartu', 'této', 'teto', 'tohoto', 'toho', 'tom', 'tomto', 'jeho',
    'nebo', 'takže', 'takze', 'protože', 'protoze', 'zřejmě', 'zrejme',
}

# Slova, která vypadají jako hostname, ale nejsou — bez tohohle by se hlásily
# domény z odkazů, přípony souborů a běžné technické pojmy.
_NOT_HOSTS = {
    'e.g', 'i.e', 'atd.tak', 'apod.a',
    'localhost', 'example.com', 'foo.bar',
}
_COMMON_SUFFIX = (
    '.service', '.socket', '.timer', '.target', '.mount', '.conf', '.log',
    '.json', '.yaml', '.yml', '.txt', '.sh', '.py', '.db', '.gz', '.md',
    '.io', '.com', '.org', '.net', '.cz', '.local', '.sh', '.tar',
)
# Technické výrazy s tečkou/pomlčkou, které nejsou stroje
_TECH_WORDS = {
    'read-only', 'auto-execute', 'dry-run', 'root-cause', 'self-signed',
    'open-webui', 'systemd-journal', 'out-of-memory', 'disk-full',
    'timeout-s', 'non-free', 'log-rotate', 'e-mail', 'on-line', 'off-line',
}


def _looks_like_host(token: str) -> bool:
    """Odfiltruje to, co jen připomíná hostname."""
    t = token.lower().strip('.')
    if t in _NOT_HOSTS or t in _TECH_WORDS:
        return False
    if t.endswith(_COMMON_SUFFIX):
        return False
    if t.replace('.', '').replace('-', '').isdigit():   # verze, IP fragmenty
        return False
    if len(t) < 4 or len(t) > 63:
        return False
    return True


def known_entities(state) -> dict:
    """Posbírá, co v infrastruktuře opravdu existuje.

    Selhání jednoho zdroje nesmí prohlásit celý svět za neznámý — to by
    označilo za halucinaci i správné odpovědi, proto se chyby polykají
    jednotlivě a výsledek se skládá z toho, co se povedlo.
    """
    hosts, services = set(), set()
    try:
        for a in state.get_all_agents() or []:
            if a.get('hostname'):
                hosts.add(str(a['hostname']).lower())
    except Exception as e:
        logger.debug(f"ai_verify: agenti nedostupní: {e}")
    try:
        from . import config
        for m in getattr(config, 'INFRASTRUCTURE_MAPPING', []) or []:
            for field in ('name', 'mgmt_node'):
                if m.get(field):
                    hosts.add(str(m[field]).lower())
    except Exception as e:
        logger.debug(f"ai_verify: infra mapa nedostupná: {e}")
    try:
        for i in state.get_active_issues() or []:
            if i.get('host'):
                hosts.add(str(i['host']).lower())
            line = str(i.get('last_line') or '')
            for m in _SERVICE_RE.finditer(line):
                services.add(m.group(1).lower())
    except Exception as e:
        logger.debug(f"ai_verify: issue nedostupné: {e}")
    return {"hosts": hosts, "services": services}


def _strip_noise(text: str) -> str:
    """Odstraní části, kde se hostname-like tokeny vyskytují legitimně —
    URL a bloky kódu. Bez toho by se hlásila každá doména z odkazu."""
    text = re.sub(r'```.*?```', ' ', text or '', flags=re.S)
    text = re.sub(r'`[^`]*`', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    return text


def check(text: str, known: dict) -> dict:
    """Najde v odpovědi entity, které systém nezná.

    Vrací {"unknown_hosts": [...], "unknown_services": [...], "suspicious": bool}.
    """
    clean = _strip_noise(text)
    kh = {h.lower() for h in (known or {}).get('hosts', set())}
    ks = {s.lower() for s in (known or {}).get('services', set())}

    unknown_hosts, unknown_services = [], []

    def _consider(tok: str, require_separator: bool):
        if require_separator and not _looks_like_host(tok):
            return
        low = tok.lower().strip('.')
        if not require_separator:
            if low in _STOPWORDS or low.endswith(_COMMON_SUFFIX) or len(low) < 3:
                return
        # Krátký název stroje uvnitř FQDN bereme jako shodu (rpi vs rpi.local)
        if low in kh or low.split('.')[0] in kh:
            return
        if low not in [u.lower() for u in unknown_hosts]:
            unknown_hosts.append(tok)

    for m in _HOST_RE.finditer(clean):
        _consider(m.group(1), require_separator=True)
    # Jednoslovné názvy jen tam, kde je model výslovně označil za stroj
    for m in _INTRODUCED_RE.finditer(clean):
        _consider(m.group(1), require_separator=False)

    for m in _SERVICE_RE.finditer(clean):
        low = m.group(1).lower()
        if low in ks or low.replace('.service', '') in kh:
            continue
        if low not in [u.lower() for u in unknown_services]:
            unknown_services.append(m.group(1))

    return {
        "unknown_hosts": unknown_hosts,
        "unknown_services": unknown_services,
        # Za podezřelou považujeme jen neznámý STROJ. Neznámá služba je
        # běžná (model navrhne nainstalovat něco nového) a hlásit ji jako
        # halucinaci by bylo zavádějící.
        "suspicious": bool(unknown_hosts),
    }


def verify(state, text: str) -> dict:
    """Ověří odpověď proti stavu infrastruktury."""
    return check(text, known_entities(state))


def warning_html(result: dict) -> str:
    """Upozornění pro UI. Formulace záměrně nesoudí — model může mít pravdu
    a jen jsme o tom stroji zatím neslyšeli."""
    import html as _html
    if not (result or {}).get("unknown_hosts"):
        return ""
    names = ", ".join(_html.escape(h) for h in result["unknown_hosts"][:5])
    return (
        "<div style='background:rgba(255,193,7,0.12);border:1px solid #ffc107;"
        "border-radius:4px;padding:7px 10px;margin-top:8px;font-size:0.8em;color:#ffc107;'>"
        f"⚠️ V odpovědi jsou stroje, které Sentinel nezná: <b>{names}</b> — ověř si je."
        "</div>"
    )

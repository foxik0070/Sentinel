"""
509: Komprese kontextu — opakující se řádky sbalit před odesláním modelu.
511: Hybridní vyhledávání — vektory + klíčová slova.
512: Citace zdroje — z čeho odpověď čerpá.
513: RAG čistota — deduplikace a expirace naučených chunků.
514: Chunking podle struktury — dělit podle sekcí, ne po pevných blocích.
515: Reranking — druhý průchod nad kandidáty pro lepší pořadí.

Všechno jsou to čisté funkce bez stavu, aby šly testovat bez vektorové DB
a bez modelu. Napojení je v rag.py.

Proč to dohromady dává smysl: model dostane omezené okno. Každý zbytečný
token v něm (opakovaný řádek, duplicitní chunk, nesouvisející text) vytlačí
něco užitečného. Tyhle funkce dělají jedno: aby se do okna vešlo to podstatné.
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# --- 509 -------------------------------------------------------------------

# Části řádku, které se mění a bránily by rozpoznání opakování.
_VAR_RE = [
    (re.compile(r'\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*'), '<ts>'),
    (re.compile(r'\b\d{1,2}:\d{2}:\d{2}\b'), '<t>'),
    (re.compile(r'\b[A-Z][a-z]{2}\s+\d{1,2}\b'), '<d>'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '<ip>'),
    (re.compile(r'\b[0-9a-f]{12,}\b', re.I), '<hash>'),
    (re.compile(r'\[\d+\]'), '[<pid>]'),
    (re.compile(r'\b\d+\b'), '<n>'),
]

MIN_REPEATS_TO_COLLAPSE = 3


def _shape(line: str) -> str:
    s = str(line or '')
    for rx, repl in _VAR_RE:
        s = rx.sub(repl, s)
    return ' '.join(s.split())


def compress_lines(lines, min_repeats: int = MIN_REPEATS_TO_COLLAPSE) -> str:
    """509: Sbalí opakující se řádky.

    Padesát stejných řádků nese stejnou informaci jako jeden — jen sní okno,
    do kterého se pak nevejde to zajímavé. Zachovává se POŘADÍ a první výskyt
    v původním znění, aby zůstala konkrétní čísla.
    """
    out, run_shape, run_count, run_first = [], None, 0, None

    def flush():
        if run_first is None:
            return
        if run_count >= min_repeats:
            out.append(f"{run_first}    … ({run_count}× podobný řádek)")
        else:
            out.extend([run_first] * run_count)

    for line in lines or []:
        text = str(line or '').rstrip('\n')
        sh = _shape(text)
        if sh == run_shape:
            run_count += 1
            continue
        flush()
        run_shape, run_count, run_first = sh, 1, text
    flush()
    return "\n".join(out)


def compression_ratio(original, compressed: str) -> float:
    """Kolik se ušetřilo (0-1). Pro měření, jestli to vůbec pomáhá."""
    orig = "\n".join(str(x) for x in (original or []))
    if not orig:
        return 0.0
    return round(1.0 - len(compressed) / len(orig), 3)


# --- 511 -------------------------------------------------------------------

# Výrazy, které musí sedět doslova: hostname, kód chyby, cesta, jednotka.
# Sémantická podobnost je na ně slabá — „chyba 502" a „chyba 404" jsou si
# vektorově blízké, ale jde o úplně jiný problém.
# Cesty se hledají zvlášť: `\b` před lomítkem neplatí tak, jak by člověk
# čekal, a `/var/log/syslog` se kvůli tomu ořízlo na `/log/syslog`.
_PATH_RE = re.compile(r'(?<![\w/])(/[\w.-]+(?:/[\w.-]+)*)')
_TOKEN_RE = re.compile(
    r'\b(?:[a-z0-9-]+\.(?:service|socket|timer|target)|[A-Z]{2,}-?\d{2,}|'
    r'\d{3}|[a-z][a-z0-9-]*\d[a-z0-9-]*)\b', re.I)


def exact_terms(query: str) -> list:
    """Výrazy z dotazu, které se musí shodovat doslova."""
    q = str(query or '')
    found = [m.group(1).lower() for m in _PATH_RE.finditer(q)]
    found += [m.group(0).lower() for m in _TOKEN_RE.finditer(q)]
    return list(dict.fromkeys(t for t in found if len(t) >= 3))[:8]


def hybrid_rank(query: str, candidates, keyword_weight: float = 0.35) -> list:
    """511: Přerovná kandidáty podle vektorové vzdálenosti I doslovné shody.

    `candidates` = [{"doc": text, "distance": float}, ...]
    Vrací tytéž položky se skóre, seřazené (nižší = lepší).
    """
    terms = exact_terms(query)
    out = []
    for c in candidates or []:
        if not isinstance(c, dict) or not c.get('doc'):
            continue
        dist = c.get('distance')
        dist = 0.5 if not isinstance(dist, (int, float)) else float(dist)
        doc_low = str(c['doc']).lower()
        hits = sum(1 for t in terms if t in doc_low)
        # Doslovná shoda vzdálenost snižuje, ale nepřebije ji úplně —
        # jinak by chunk se shodným číslem vyhrál i bez souvislosti.
        bonus = (hits / len(terms)) * keyword_weight if terms else 0.0
        out.append(dict(c, keyword_hits=hits, score=round(max(0.0, dist - bonus), 4)))
    return sorted(out, key=lambda x: x['score'])


# --- 515 -------------------------------------------------------------------

def rerank(query: str, candidates, top_n: int = 3) -> list:
    """515: Druhý průchod nad širším výběrem.

    Vektorové hledání vrátí hrubé pořadí; tady se přidá překryv slov, který
    zachytí i to, co embedding minul (zkratky, kódy). Levné — žádný model.
    """
    q_terms = {t for t in re.findall(r'\w{3,}', str(query or '').lower())}
    ranked = hybrid_rank(query, candidates)
    for c in ranked:
        doc_terms = {t for t in re.findall(r'\w{3,}', str(c['doc']).lower())}
        overlap = len(q_terms & doc_terms) / len(q_terms) if q_terms else 0.0
        c['overlap'] = round(overlap, 3)
        c['final_score'] = round(c['score'] - overlap * 0.2, 4)
    return sorted(ranked, key=lambda x: x['final_score'])[:max(1, int(top_n))]


# --- 512 -------------------------------------------------------------------

def build_citations(candidates) -> list:
    """512: Z čeho odpověď čerpá.

    Bez toho nejde u odpovědi poznat, jestli stojí na znalostní bázi, nebo
    si ji model vymyslel.
    """
    cites = []
    for i, c in enumerate(candidates or [], 1):
        doc = str((c or {}).get('doc') or '')
        if not doc:
            continue
        cites.append({
            "n": i,
            "source": (c.get('source') or c.get('metadata', {}).get('source') or 'kb'),
            "excerpt": doc.strip()[:160],
            "distance": c.get('distance'),
            "id": hashlib.md5(doc.encode()).hexdigest()[:12],
        })
    return cites


def citations_note(cites) -> str:
    """Citace pod odpověď."""
    if not cites:
        return ""
    lines = ["Zdroje:"]
    for c in cites[:5]:
        lines.append(f"[{c['n']}] {c['source']}: {c['excerpt'][:110]}")
    return "\n".join(lines)


# --- 513 -------------------------------------------------------------------

DEFAULT_MAX_LEARNED = 500
DEFAULT_MAX_AGE_DAYS = 180


def dedupe_chunks(chunks) -> list:
    """513: Zahodí duplicity. Porovnává se normalizovaný text.

    Bez toho `learned_kb.txt` roste donekonečna a tentýž poznatek se do
    kontextu dostane třikrát — na úkor něčeho jiného.
    """
    seen, out = set(), []
    for ch in chunks or []:
        text = str(ch or '').strip()
        if not text:
            continue
        key = ' '.join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def expire_learned(entries, max_entries: int = DEFAULT_MAX_LEARNED,
                   max_age_days: int = DEFAULT_MAX_AGE_DAYS, now=None) -> tuple:
    """513: Vyhodí staré a přebytečné naučené chunky.

    `entries` = [{"text": ..., "at": iso}, ...]. Vrací (ponechané, zahozené).
    Starý poznatek není jen neužitečný — může být přímo zavádějící, protože
    infrastruktura se mezitím změnila.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(max_age_days)))
    kept, dropped = [], []

    parsed = []
    for e in entries or []:
        if not isinstance(e, dict) or not str(e.get('text') or '').strip():
            continue
        parsed.append(e)

    for e in parsed:
        at = _parse_iso(e.get('at'))
        if at and at < cutoff:
            dropped.append(dict(e, reason='příliš staré'))
        else:
            kept.append(e)

    # Nejstarší nad limit pryč — novější poznatek odráží současný stav.
    if len(kept) > max_entries:
        kept.sort(key=lambda e: _parse_iso(e.get('at')) or datetime.min.replace(tzinfo=timezone.utc))
        overflow = len(kept) - max_entries
        dropped.extend(dict(e, reason='nad limit') for e in kept[:overflow])
        kept = kept[overflow:]
    return kept, dropped


def _parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# --- 514 -------------------------------------------------------------------

_HEADING_RE = re.compile(r'^(#{1,6}\s+\S|[A-Z][A-Z0-9 _-]{4,}:?\s*$|FILE:|CONTEXT:)')

MIN_CHUNK_LEN = 40
MAX_CHUNK_LEN = 2000


def split_by_structure(text: str) -> list:
    """514: Dělí podle nadpisů, ne po pevných blocích.

    Pevná délka rozsekne postup uprostřed a model pak dostane půlku návodu.
    Sekce drží myšlenku pohromadě.
    """
    lines = str(text or '').splitlines()
    chunks, current = [], []

    def flush():
        block = "\n".join(current).strip()
        if len(block) >= MIN_CHUNK_LEN:
            # Příliš dlouhou sekci rozdělit po odstavcích, ať se vejde do okna.
            if len(block) > MAX_CHUNK_LEN:
                for part in _split_long(block):
                    chunks.append(part)
            else:
                chunks.append(block)
        elif block and chunks:
            chunks[-1] = chunks[-1] + "\n" + block     # krátký zbytek přilepit

    for line in lines:
        if _HEADING_RE.match(line.strip()) and current:
            flush()
            current = [line]
        else:
            current.append(line)
    flush()
    return chunks


def _split_long(block: str) -> list:
    parts, buf = [], []
    size = 0
    for para in block.split("\n\n"):
        if size + len(para) > MAX_CHUNK_LEN and buf:
            parts.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(para)
        size += len(para)
    if buf:
        parts.append("\n\n".join(buf))
    return parts

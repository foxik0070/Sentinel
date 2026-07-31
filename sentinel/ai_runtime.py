"""
517: Odmítnutí bez dat — „nevím, chybí mi X" místo pravděpodobné smyšlenky.
518: Konzistence napříč dotazy — stejná otázka nemá dávat protichůdné odpovědi.
519: Jazyk odpovědi podle uživatele — prompty dnes míchají češtinu a angličtinu.
521: Few-shot z reálných incidentů — příklady ze stejné domény.
522: Routing podle složitosti — triviální úloha na malý model, korelace na velký.
523: Rozpočet tokenů per úloha — 435 sbírá data, chyběl strop.
525: Cache odpovědí — stejný alert do X minut neanalyzovat znovu.

Co mají společné: netýkají se toho, CO se modelu ptáme, ale JAK. Dohromady
šetří čas na NPU a hlavně dělají odpovědi předvídatelnějšími — model, který
na stejnou otázku odpoví pokaždé jinak, se nedá použít k rozhodování.
"""
import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# --- 517 -------------------------------------------------------------------

# Fráze, kterými model přiznává, že na odpověď nemá podklady. Pozná se podle
# nich, že odpověď NENÍ tvrzení — a nemá se s ní zacházet jako s faktem.
_REFUSAL_MARKERS = (
    'nevím', 'nevim', 'nemám dost', 'nemam dost', 'chybí mi', 'chybi mi',
    'nelze určit', 'nelze urcit', 'nedostatek dat', 'není jasné',
    "i don't know", 'insufficient data', 'cannot determine', 'not enough',
)


def refusal_instruction() -> str:
    """517: Věta do promptu, která model opravňuje říct „nevím".

    Bez ní model vždycky něco napíše — a pravděpodobně znějící smyšlenka je
    horší než přiznaná mezera, protože podle ní někdo začne jednat.
    """
    return ("Pokud na odpověď nemáš dost podkladů, NEHÁDEJ. Napiš 'NEVÍM' "
            "a uveď, jaký konkrétní údaj ti chybí.")


def is_refusal(text: str) -> bool:
    """Přiznal model, že neví?"""
    low = str(text or '').lower()
    return any(m in low for m in _REFUSAL_MARKERS)


def missing_data_note(available: dict) -> str:
    """517: Řekne modelu, co k dispozici NENÍ.

    Bez toho model mlčky předpokládá, že chybějící údaj je v pořádku —
    „žádné chyby v logu" a „log jsem nedostal" pak splynou.
    """
    missing = [k for k, v in (available or {}).items() if not v]
    if not missing:
        return ""
    return ("NEDOSTUPNÉ ÚDAJE (nepředpokládej, že jsou v pořádku — prostě "
            "je nemáme): " + ", ".join(missing) + "\n")


# --- 519 -------------------------------------------------------------------

def language_instruction(lang: str = 'cs') -> str:
    """519: Jednotný jazyk odpovědi.

    Prompty v projektu jsou psané česky i anglicky podle toho, kdy vznikly,
    a model pak míchá jazyky v jedné odpovědi.
    """
    return ("Odpověz česky." if str(lang or 'cs').lower().startswith('cs')
            else "Answer in English.")


# --- 521 -------------------------------------------------------------------

MAX_FEWSHOT = 3


def build_fewshot(resolved_incidents, plugin: str = '', max_examples: int = MAX_FEWSHOT) -> str:
    """521: Příklady vyřešených incidentů ze stejné domény.

    Malý model se z jednoho konkrétního příkladu naučí formát i obsah líp
    než z odstavce instrukcí. Berou se jen incidenty s OVĚŘENÝM řešením —
    příklad se špatnou odpovědí by model naučil dělat tutéž chybu.
    """
    picked = []
    for inc in resolved_incidents or []:
        if not isinstance(inc, dict):
            continue
        problem = str(inc.get('problem') or inc.get('last_line') or '').strip()
        solution = str(inc.get('solution') or inc.get('command') or '').strip()
        if not problem or not solution:
            continue
        if plugin and inc.get('plugin_name') and inc['plugin_name'] != plugin:
            continue
        picked.append((problem[:150], solution[:150]))
        if len(picked) >= max_examples:
            break
    if not picked:
        return ""
    lines = ["PŘÍKLADY Z TÉHLE INFRASTRUKTURY (skutečné, ověřené):"]
    for p, s in picked:
        lines.append(f"- Problém: {p}\n  Řešení: {s}")
    return "\n".join(lines) + "\n"


# --- 522 -------------------------------------------------------------------

# Úlohy, u kterých se vyplatí rychlost před hloubkou. Klasifikace severity
# na velkém modelu je plýtvání — odpověď je stejně jedno slovo.
_SIMPLE_TASKS = {'classify', 'severity', 'category', 'yes_no', 'extract'}
_COMPLEX_TASKS = {'correlate', 'analyze', 'postmortem', 'causal_chain', 'diagnose'}


def route(task: str, prompt_len: int = 0) -> str:
    """522: Který model na tuhle úlohu — 'fast' nebo 'strong'.

    Rozhoduje povaha úlohy, ne délka; dlouhý vstup u klasifikace pořád
    znamená krátkou odpověď. Výjimkou je opravdu velký vstup, kde malý
    model kontext neudrží.
    """
    t = str(task or '').strip().lower()
    if t in _COMPLEX_TASKS:
        return 'strong'
    if t in _SIMPLE_TASKS:
        return 'strong' if prompt_len > 6000 else 'fast'
    return 'strong'


# --- 523 -------------------------------------------------------------------

# Strop tokenů na úlohu za hodinu. Bez něj může jedna zacyklená smyčka
# vyčerpat celý rozpočet a zastavit i to podstatné.
DEFAULT_TOKEN_BUDGET = {
    'classify': 20000, 'extract': 40000, 'summarize': 60000,
    'correlate': 80000, 'analyze': 120000,
}

_token_usage: dict = {}
_token_lock = threading.Lock()


def record_tokens(task: str, tokens: int, now=None) -> None:
    now = now or datetime.now(timezone.utc)
    with _token_lock:
        _token_usage.setdefault(str(task or 'other'), []).append((now, int(tokens or 0)))


def token_budget_left(task: str, now=None, budget: int = None) -> tuple:
    """523: Kolik tokenů na tuhle úlohu ještě zbývá (klouzavá hodina)."""
    now = now or datetime.now(timezone.utc)
    t = str(task or 'other')
    cap = budget if budget is not None else DEFAULT_TOKEN_BUDGET.get(t, 60000)
    cutoff = now - timedelta(hours=1)
    with _token_lock:
        used_list = [(ts, n) for ts, n in _token_usage.get(t, []) if ts > cutoff]
        _token_usage[t] = used_list
        used = sum(n for _, n in used_list)
    return max(0, cap - used), used, cap


def token_budget_ok(task: str, now=None, budget: int = None) -> bool:
    left, _, _ = token_budget_left(task, now, budget)
    return left > 0


def reset_token_budget():
    with _token_lock:
        _token_usage.clear()


# --- 525 + 518 -------------------------------------------------------------

# Jak dlouho je odpověď platná. Delší cache by u měnícího se systému vracela
# zastaralé závěry.
DEFAULT_CACHE_TTL_MIN = 15
MAX_CACHE_ENTRIES = 200

_cache: dict = {}
_cache_lock = threading.Lock()
_cache_stats = {"hits": 0, "misses": 0, "conflicts": 0}


def cache_key(task: str, prompt: str) -> str:
    """Otisk úlohy a dotazu. Normalizuje mezery, aby drobný rozdíl ve
    formátování nezpůsobil zbytečné přepočítání."""
    norm = ' '.join(str(prompt or '').lower().split())
    return hashlib.sha256(f"{task}|{norm}".encode()).hexdigest()[:32]


def cache_get(task: str, prompt: str, now=None, ttl_min: int = DEFAULT_CACHE_TTL_MIN):
    """525: Odpověď z cache, pokud je čerstvá."""
    now = now or datetime.now(timezone.utc)
    key = cache_key(task, prompt)
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            _cache_stats["misses"] += 1
            return None
        if (now - entry['at']).total_seconds() / 60.0 > ttl_min:
            _cache.pop(key, None)
            _cache_stats["misses"] += 1
            return None
        _cache_stats["hits"] += 1
        return entry['answer']


def cache_put(task: str, prompt: str, answer: str, now=None) -> dict | None:
    """525 + 518: Uloží odpověď a ohlásí, když si model protiřečí.

    Konflikt se NEPŘEPISUJE tiše: když na tutéž otázku přijde jiná odpověď,
    je to signál, že se na model v téhle věci nedá spolehnout — a to má
    uživatel vidět.
    """
    now = now or datetime.now(timezone.utc)
    key = cache_key(task, prompt)
    ans = str(answer or '')
    conflict = None
    with _cache_lock:
        prev = _cache.get(key)
        if prev and _materially_different(prev['answer'], ans):
            _cache_stats["conflicts"] += 1
            conflict = {"previous": prev['answer'][:200], "current": ans[:200],
                        "note": "Model na stejnou otázku odpověděl jinak."}
        if len(_cache) >= MAX_CACHE_ENTRIES:
            oldest = min(_cache.items(), key=lambda kv: kv[1]['at'])[0]
            _cache.pop(oldest, None)
        _cache[key] = {"answer": ans, "at": now}
    return conflict


def _materially_different(a: str, b: str) -> bool:
    """Liší se odpovědi obsahem, ne jen formulací?

    Drobná odchylka ve slovosledu není rozpor; hodnotíme překryv slov.
    """
    import re as _re
    # Interpunkci pryč: „plný," a „plný" je totéž slovo a bez očištění by
    # jiný slovosled vypadal jako rozpor.
    def words(s):
        return {w for w in _re.findall(r'\w+', str(s or '').lower()) if len(w) > 3}

    wa, wb = words(a), words(b)
    if not wa or not wb:
        return bool(wa) != bool(wb)
    return len(wa & wb) / len(wa | wb) < 0.5


def cache_stats() -> dict:
    with _cache_lock:
        total = _cache_stats["hits"] + _cache_stats["misses"]
        return dict(_cache_stats, entries=len(_cache),
                    hit_rate=round(_cache_stats["hits"] / total * 100, 1) if total else None)


def cache_clear():
    with _cache_lock:
        _cache.clear()
        for k in _cache_stats:
            _cache_stats[k] = 0

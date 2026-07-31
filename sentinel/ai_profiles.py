"""
508: Kontextové okno podle úlohy.

Dosud se `num_ctx` volilo od oka a v kódu bylo roztroušených pět různých
hodnot bez zjevného klíče. Velké okno u jednoduché úlohy stojí čas —
na NPU i na CPU roste latence s velikostí kontextu, aniž by to odpovědi
pomohlo.

Profily jsou pojmenované podle TOHO, CO SE DĚLÁ, ne podle velikosti:
volající pak nemusí hádat čísla a při změně modelu se ladí na jednom místě.
"""
import logging

logger = logging.getLogger(__name__)

# num_ctx  … kolik kontextu model dostane
# max_tokens … jak dlouhá smí být odpověď
# temperature … u strojově zpracovávaných odpovědí co nejníž
PROFILES: dict[str, dict] = {
    # Zařazení do kategorie, severity, ano/ne. Vstup i výstup jsou krátké;
    # velké okno by tu jen zdržovalo.
    "classify": {"num_ctx": 512, "max_tokens": 80, "temperature": 0.0},

    # Strukturovaný výstup z krátkého zadání (autofix, výběr kroku).
    # Odpověď musí být celá, jinak se JSON usekne — viz 462.
    "extract": {"num_ctx": 1024, "max_tokens": 400, "temperature": 0.1},

    # Text pro člověka — shrnutí, eskalace, vysvětlení.
    "summarize": {"num_ctx": 2048, "max_tokens": 400, "temperature": 0.2},

    # Souvislosti mezi více zdroji: telemetrie, sousední issue, změny.
    "correlate": {"num_ctx": 4096, "max_tokens": 600, "temperature": 0.1},

    # Rozbor delšího vstupu (logy, výstupy diagnostiky).
    "analyze": {"num_ctx": 8192, "max_tokens": 800, "temperature": 0.1},
}

DEFAULT_PROFILE = "summarize"


def for_task(task: str, **overrides) -> dict:
    """Parametry pro danou úlohu. Neznámé jméno spadne na výchozí profil —
    horší odpověď je pořád lepší než výjimka v cestě k AI."""
    prof = PROFILES.get(str(task or '').strip().lower())
    if prof is None:
        logger.debug(f"ai_profiles: neznámý profil {task!r}, beru {DEFAULT_PROFILE}")
        prof = PROFILES[DEFAULT_PROFILE]
    out = dict(prof)
    out.update({k: v for k, v in overrides.items() if v is not None})
    return out


def fits(task: str, prompt: str, chars_per_token: int = 4) -> bool:
    """Vejde se prompt do okna profilu?

    Hrubý odhad (znaky/4) — přesné počítání tokenů by vyžadovalo tokenizér
    modelu. Slouží k varování, ne k tvrdému rozhodnutí.
    """
    prof = for_task(task)
    return len(str(prompt or '')) / max(1, chars_per_token) <= prof['num_ctx']


def pick_for_prompt(prompt: str, preferred: str = None) -> str:
    """Profil, do kterého se prompt ještě vejde.

    Když se do preferovaného nevejde, posune se na větší — usekaný kontext
    dá horší odpověď než pomalejší běh.
    """
    order = ["classify", "extract", "summarize", "correlate", "analyze"]
    start = order.index(preferred) if preferred in order else 0
    for name in order[start:]:
        if fits(name, prompt):
            return name
    return "analyze"

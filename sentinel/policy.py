"""
487: Vysvětlení, proč byl příkaz zablokován + povolená alternativa.
490: Návrh pravidla do allowlistu u opakovaně navrhovaných příkazů.

Dosud uživatel dostal jen „BLOCKED" a nevěděl, co s tím — tak si to buď
udělal ručně mimo Sentinel (ztráta auditu), nebo si otevřel allowlist
šířeji, než bylo potřeba.

DVĚ ZÁSADY, na kterých tu stojí bezpečnost:

1. Alternativu NEGENERUJE model. Bere se z allowlistu a z read-only
   simulace v safety.py. Model by jinak „pomohl" tím, že navrhne obejití.

2. Pravidlo do allowlistu je vždy jen NÁVRH pro admina. Rozšíření
   allowlistu je změna oprávnění a nesmí vzniknout automaticky. Navrhuje
   se přesný příkaz, ne glob — glob rozšiřuje povolení na věci, které
   nikdo neposoudil.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Kolikrát musí AI stejný příkaz navrhnout, než ho nabídneme do allowlistu.
MIN_SUGGESTIONS_FOR_RULE = 3

# Pravidlo v allowlistu znamená „spouštěj bez ptaní", takže laťka je
# READ-ONLY, ne jen „nízké skóre". Nízké skóre je pro tohle rozhodnutí
# příliš měkké: `rm -rf /var` dostane od klasifikátoru 25, což by při
# prahu 30 stačilo — a to je přesně ten příkaz, který se bez ptaní
# spouštět nemá.
MAX_RISK_FOR_RULE = 0


def _binary(command: str) -> str:
    """První slovo příkazu bez sudo — podle něj hledáme příbuzné povolené."""
    for tok in str(command or '').strip().split():
        if tok in ('sudo', '-n', 'nohup', 'time'):
            continue
        return tok.split('/')[-1]
    return ''


def explain_block(command: str, safety, allowlist: list | None = None) -> dict:
    """487: Proč to neprošlo a co jde místo toho.

    Vrací {blocked, risk_score, reasons, in_allowlist, alternatives, hint}.
    """
    cmd = str(command or '').strip()
    if not cmd:
        return {"blocked": True, "risk_score": 100, "reasons": ["prázdný příkaz"],
                "in_allowlist": False, "alternatives": [], "hint": ""}

    score, reasons = safety.classify(cmd)
    rules = allowlist or []
    matched = _match_allowlist(cmd, rules)

    blocked_by_risk = score >= safety.THRESHOLD_BLOCK
    blocked = blocked_by_risk or matched is None

    alternatives = []
    # 1) Read-only náhled téhož zásahu — nejlepší první krok: ukáže stav,
    #    aniž by cokoli změnil.
    try:
        preview_cmd, preview_desc = safety.simulate(cmd)
        if preview_cmd:
            alternatives.append({"command": preview_cmd, "why": preview_desc,
                                 "kind": "read_only_preview"})
    except Exception as e:
        logger.debug(f"policy: simulate selhalo: {e}")

    # 2) Povolená pravidla nad stejným nástrojem — co s tímhle programem smí
    b = _binary(cmd)
    if b:
        for r in rules:
            pat = (r.get('pattern') or '').strip()
            if pat and _binary(pat) == b and pat != cmd:
                alternatives.append({"command": pat,
                                     "why": r.get('description') or 'povolené pravidlo',
                                     "kind": "allowlisted"})
            if len(alternatives) >= 6:
                break

    if blocked_by_risk:
        hint = ("Příkaz je vyhodnocen jako rizikový, takže ho nespustí ani "
                "schválení člověkem. Použij read-only náhled, nebo zásah rozděl "
                "na menší kroky.")
    elif matched is None:
        hint = ("Příkaz není v allowlistu. Buď použij některou z povolených "
                "variant níže, nebo si nech pravidlo schválit adminem.")
    else:
        hint = "Příkaz je povolen."

    return {
        "blocked": blocked,
        "risk_score": score,
        "reasons": reasons,
        "in_allowlist": matched is not None,
        "matched_pattern": (matched or {}).get('pattern', ''),
        "alternatives": alternatives[:6],
        "hint": hint,
    }


def _match_allowlist(cmd: str, rules: list):
    """Shoda s allowlistem — stejná pravidla jako state.check_command_allowed.

    Nevoláme ji přímo, aby šel modul testovat bez DB; chování musí zůstat
    shodné, jinak by vysvětlení tvrdilo něco jiného, než co se opravdu stane.
    """
    import fnmatch
    from .state_agents import _adds_shell_meta
    for rule in rules or []:
        pattern = (rule.get('pattern') or '').strip()
        if not pattern:
            continue
        if cmd == pattern:
            return rule
        try:
            if fnmatch.fnmatch(cmd, pattern) and not _adds_shell_meta(cmd, pattern):
                return rule
        except Exception:
            continue
    return None


def suggest_allowlist_rules(audit_entries: list, allowlist: list, safety,
                            min_count: int = MIN_SUGGESTIONS_FOR_RULE) -> list:
    """490: Příkazy, které AI navrhuje opakovaně a jsou bezpečné.

    Vrací kandidáty k ručnímu schválení, seřazené podle četnosti.
    """
    counts: dict = {}
    for e in audit_entries or []:
        cmd = _extract_command(e)
        if not cmd:
            continue
        counts[cmd] = counts.get(cmd, 0) + 1

    out = []
    for cmd, n in counts.items():
        if n < min_count:
            continue
        if _match_allowlist(cmd, allowlist):
            continue                      # už povoleno, není co navrhovat
        try:
            score, reasons = safety.classify(cmd)
        except Exception:
            continue
        if score > MAX_RISK_FOR_RULE:
            continue                      # cokoli nad read-only řeší admin ručně
        # Druhá, nezávislá podmínka: klasifikátor musí příkaz sám označit za
        # read-only. Skóre 0 může vzniknout i tím, že na příkaz žádné pravidlo
        # nesedí — což u neznámého nástroje neznamená, že je neškodný.
        try:
            if not safety._looks_readonly(cmd):
                continue
        except Exception:
            continue
        out.append({
            "command": cmd,
            "times_suggested": n,
            "risk_score": score,
            "risk_reasons": reasons,
            # Přesný příkaz, ne glob: glob by povolil i varianty, které
            # nikdo neposoudil.
            "proposed_pattern": cmd,
            "impact": _impact_note(cmd),
        })
    return sorted(out, key=lambda x: -x['times_suggested'])


def _extract_command(entry) -> str:
    """Vytáhne příkaz z auditního záznamu (odpověď modelu je JSON nebo text)."""
    if isinstance(entry, str):
        raw = entry
    elif isinstance(entry, dict):
        raw = entry.get('response') or ''
        if not raw:
            return ''
    else:
        return ''
    raw = str(raw)
    m = re.search(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if m:
        cmd = m.group(1).replace('\\"', '"').replace('\\\\', '\\').strip()
        return '' if cmd.upper() in ('N/A', '') else cmd
    return ''


def _impact_note(command: str) -> str:
    """Co povolení pravidla znamená v praxi.

    Sentinel se na cizí stroje hlásí neprivilegovaným uživatelem a root-příkazy
    prefixuje `sudo -n`, takže povolení tady může znamenat i běh pod sudo.
    Admin to musí vidět dřív, než pravidlo schválí.
    """
    b = _binary(command)
    needs_root = b in ('systemctl', 'journalctl', 'iptables', 'nft', 'mount',
                       'umount', 'apt', 'apt-get', 'dpkg', 'docker', 'podman')
    parts = [f"Povolí spouštění `{command}` bez ručního schválení."]
    if needs_root:
        parts.append("Na vzdálených strojích poběží přes `sudo -n` — "
                     "musí to dovolit i sudoers.")
    return " ".join(parts)

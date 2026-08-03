"""
451: Topologická korelace — souvisí výpadky spolu?
458: Blast radius — koho ještě problém zasáhne.
504: Simulace dopadu — co se stane, když tenhle stroj vypnu.

POCTIVĚ O DATECH: CDP/LLDP sousednost v téhle instalaci není (topologie je
prázdná, agenti nemají skupiny, `depends_on` nikdo nenastavil). Stavět na
ní by znamenalo psát kód proti neexistujícím datům.

Závislosti se proto ODVOZUJÍ z toho, co opravdu máme, a ke každé se hlásí,
odkud pochází a jak silná je:

  jádro     — LXC kontejnery sdílejí jádro hypervizoru, takže shodná verze
              znamená „běží na témže stroji". Silný, ověřitelný signál.
  souběh    — hosty, které opakovaně padají ve stejnou minutu, spolu
              nejspíš něco sdílejí. Statistika, ne důkaz.
  podsíť    — společný segment. Slabý signál, snadno náhodný.

Odvozená závislost NENÍ fakt. Proto se všude vrací `confidence` a
formulace „pravděpodobně", ne „určitě".
"""
import logging
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)

# Kolikrát musí dva hosty spadnout společně, než to bereme jako signál.
MIN_COFAILURES = 5

# Granularita souběhu. Minuta je kompromis: kratší okno mine kaskádu, která
# se šíří pár vteřin, delší slepí náhodné shody.
COFAIL_GRANULARITY = 16      # délka ISO řetězce po minuty


def infer_from_kernel(facts) -> list:
    """451: Kontejnery na společném hypervizoru.

    LXC sdílí jádro hostitele, takže shodná verze jádra u strojů s různou
    distribucí je spolehlivý příznak, že běží na jednom železe. Když ten
    stroj spadne, spadnou všechny naráz.
    """
    by_kernel = defaultdict(list)
    for host, f in (facts or {}).items():
        if not isinstance(f, dict):
            continue
        k = str(f.get('kernel') or '').strip()
        if k:
            by_kernel[k].append(host)

    out = []
    for kernel, hosts in by_kernel.items():
        if len(hosts) < 2:
            continue
        # Hypervizor poznáme podle toho, že má jinou distribuci než zbytek —
        # kontejnery bývají stejné, hostitel ne. Když to nejde určit,
        # neurčujeme; skupina samotná je užitečná i bez pojmenovaného rodiče.
        distros = {h: str((facts[h] or {}).get('os') or '') for h in hosts}
        counts = Counter(distros.values())
        parent = None
        if len(counts) > 1:
            rare = counts.most_common()[-1][0]
            candidates = [h for h, d in distros.items() if d == rare]
            if len(candidates) == 1:
                parent = candidates[0]
        out.append({
            "kind": "shared_kernel", "kernel": kernel,
            "hosts": sorted(hosts), "parent": parent,
            "confidence": 85 if parent else 70,
            "note": (f"{len(hosts)} strojů sdílí jádro {kernel}"
                     + (f" — pravděpodobně kontejnery na {parent}."
                        if parent else " — pravděpodobně běží na jednom hostiteli.")),
        })
    return out


def infer_from_cofailure(history, min_events: int = MIN_COFAILURES) -> list:
    """451: Hosty, které opakovaně padají zároveň.

    Souběh není důkaz závislosti — může jít o společnou příčinu jinde
    (výpadek proudu, síť). Ale právě to je informace, kterou chceme.
    """
    by_slot = defaultdict(set)
    total_by_host = Counter()
    for h in history or []:
        if not isinstance(h, dict):
            continue
        host, fs = h.get('host'), str(h.get('first_seen') or '')
        if host and fs:
            by_slot[fs[:COFAIL_GRANULARITY]].add(host)
            total_by_host[host] += 1

    pairs = Counter()
    for hosts in by_slot.values():
        hs = sorted(hosts)
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                pairs[(hs[i], hs[j])] += 1

    out = []
    for (a, b), n in pairs.items():
        if n < min_events:
            continue
        # Podíl vůči tomu, jak často padá ten méně častý — jinak by hlučný
        # host vypadal jako závislý na všem.
        base = min(total_by_host[a], total_by_host[b]) or 1
        ratio = n / base
        out.append({
            "kind": "co_failure", "hosts": [a, b], "events": n,
            "ratio": round(ratio, 2),
            "confidence": min(80, int(ratio * 100)),
            "note": (f"{a} a {b} spadly společně {n}× "
                     f"({ratio:.0%} výskytů toho méně častého) — pravděpodobně "
                     f"sdílejí příčinu, ne že by jeden závisel na druhém."),
        })
    return sorted(out, key=lambda x: -x['confidence'])


def build_graph(kernel_links=None, cofailure_links=None) -> dict:
    """Sloučí odvozené vazby do jednoho grafu se zdrojem a jistotou."""
    neighbors = defaultdict(dict)

    for link in kernel_links or []:
        hosts = link.get('hosts') or []
        for a in hosts:
            for b in hosts:
                if a == b:
                    continue
                prev = neighbors[a].get(b)
                if not prev or prev['confidence'] < link['confidence']:
                    neighbors[a][b] = {"via": "shared_kernel",
                                       "confidence": link['confidence'],
                                       "parent": link.get('parent')}

    for link in cofailure_links or []:
        a, b = (link.get('hosts') or [None, None])[:2]
        if not a or not b:
            continue
        for x, y in ((a, b), (b, a)):
            prev = neighbors[x].get(y)
            if not prev or prev['confidence'] < link['confidence']:
                neighbors[x][y] = {"via": "co_failure",
                                   "confidence": link['confidence']}
    return {h: dict(v) for h, v in neighbors.items()}


def blast_radius(host: str, graph, min_confidence: int = 50) -> dict:
    """458: Koho ještě problém pravděpodobně zasáhne.

    Vrací jen vazby nad prahem jistoty — seznam „možná souvisí se vším"
    by byl k ničemu.
    """
    linked = (graph or {}).get(host, {})
    affected = [{"host": h, **info} for h, info in linked.items()
                if info.get('confidence', 0) >= min_confidence]
    affected.sort(key=lambda x: -x['confidence'])

    parents = {i.get('parent') for i in affected if i.get('parent')}
    return {
        "host": host,
        "affected": affected,
        "count": len(affected),
        "runs_on": sorted(p for p in parents if p and p != host) or None,
        "note": (f"Problém na {host} se pravděpodobně dotkne {len(affected)} "
                 f"dalších strojů." if affected else
                 f"Podle dostupných dat nemá {host} známé vazby — ale to "
                 f"neznamená, že žádné nemá."),
    }


def simulate_shutdown(host: str, graph, agents=None, min_confidence: int = 50) -> dict:
    """504: Co se stane, když tenhle stroj vypnu.

    Rozlišuje dva různé dopady:
      - stroje, které na něm BĚŽÍ (sdílené jádro) → spadnou určitě
      - stroje, které s ním jen souvisejí          → nejistý dopad
    """
    linked = (graph or {}).get(host, {})
    certain, likely = [], []
    for h, info in linked.items():
        if info.get('confidence', 0) < min_confidence:
            continue
        # Kontejner na tomhle hostiteli spadne s ním. Opačný směr neplatí —
        # vypnutí kontejneru hypervizor neshodí.
        if info.get('via') == 'shared_kernel' and info.get('parent') == host:
            certain.append(h)
        else:
            likely.append({"host": h, "confidence": info['confidence'],
                           "via": info.get('via')})

    online = {a.get('hostname') for a in (agents or [])
              if isinstance(a, dict) and a.get('status') == 'ONLINE'}
    return {
        "host": host,
        "will_go_down": sorted(certain),
        "may_be_affected": sorted(likely, key=lambda x: -x['confidence']),
        "online_now": sorted(h for h in certain if h in online),
        "severity": ('high' if certain else ('medium' if likely else 'low')),
        "note": (f"Vypnutím {host} spadne {len(certain)} strojů, které na něm "
                 f"běží." if certain else
                 (f"Vypnutí {host} se může dotknout {len(likely)} strojů, "
                  f"ale jistotu nemáme." if likely else
                  f"Podle dostupných dat vypnutí {host} nic dalšího neshodí.")),
    }

"""
467: Detekce tiché degradace — pomalý růst, který ještě nepřekročil práh.
468: Chybějící signál — alert na to, co PŘESTALO chodit.

Dnešní detektory umí jen „hodnota překročila mez". Tím propadnou dvě věci:

  467 — metrika, která roste týden a přes práh se dostane až v neděli
        v noci. Trend je přitom jasný o dost dřív.

  468 — metrika, která PŘESTALA chodit. Nula alertů může znamenat klid
        stejně jako to, že spadl sběr dat. Bez tohohle je ticho po
        výpadku agenta k nerozeznání od ticha po vyřešení problému.

Obojí se počítá DETERMINISTICKY (regrese, mezery v čase). AI může výsledek
vysvětlit, ale nesmí rozhodovat, jestli trend existuje.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Aspoň tolik bodů, jinak je „trend" jen šum.
MIN_POINTS = 8

# Jak dobře musí přímka sedět, aby se dalo mluvit o trendu (0-1).
# Níž by se hlásilo i kolísání kolem stálé hodnoty.
MIN_R2 = 0.6

# O kolik procent výchozí hodnoty musí metrika za okno vyrůst.
MIN_GROWTH_PCT = 15.0

# Kolikanásobek obvyklého odstupu znamená „přestalo chodit".
# Trojnásobek přežije jedno vynechané měření i mírné zpoždění.
MISSING_GAP_FACTOR = 3.0

# Pod tímhle počtem vzorků neumíme určit obvyklý odstup.
MIN_SAMPLES_FOR_CADENCE = 5


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


def linear_trend(points):
    """Regrese přes (čas, hodnota). Vrací (směrnice_za_hodinu, r2) nebo None.

    Směrnice sama nestačí — bez r² by se za trend označilo i náhodné
    kolísání, které přímku protíná pod úhlem.
    """
    clean = []
    for t, v in points or []:
        dt = _parse(t)
        if dt is None:
            continue
        try:
            clean.append((dt.timestamp(), float(v)))
        except (TypeError, ValueError):
            continue
    if len(clean) < MIN_POINTS:
        return None

    n = len(clean)
    t0 = clean[0][0]
    xs = [(t - t0) / 3600.0 for t, _ in clean]     # hodiny od začátku
    ys = [v for _, v in clean]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx

    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, r2


def detect_degradation(series, min_growth_pct: float = MIN_GROWTH_PCT):
    """467: Metriky s prokazatelným růstem, které ještě nikoho netrápí.

    `series` = {"jméno metriky": [(čas, hodnota), ...]}
    """
    out = []
    for name, points in (series or {}).items():
        res = linear_trend(points)
        if not res:
            continue
        slope, r2 = res
        if slope <= 0 or r2 < MIN_R2:
            continue
        vals = [float(v) for _, v in points if _is_num(v)]
        if not vals:
            continue
        first, last = vals[0], vals[-1]
        if first <= 0:
            continue
        growth_pct = (last - first) / abs(first) * 100.0
        if growth_pct < min_growth_pct:
            continue
        out.append({
            "metric": name,
            "slope_per_hour": round(slope, 4),
            "r2": round(r2, 3),
            "first": round(first, 2),
            "last": round(last, 2),
            "growth_pct": round(growth_pct, 1),
            "samples": len(vals),
        })
    return sorted(out, key=lambda x: -x["growth_pct"])


def _is_num(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def median_interval_sec(timestamps):
    """Obvyklý odstup mezi vzorky. None, když se nedá určit.

    Medián, ne průměr — jedna dlouhá mezera po restartu by průměr vytáhla
    a maskovala tím další výpadky.
    """
    ts = sorted(t for t in (_parse(x) for x in timestamps or []) if t)
    if len(ts) < MIN_SAMPLES_FOR_CADENCE:
        return None
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:]) if (b - a).total_seconds() > 0]
    if not gaps:
        return None
    gaps.sort()
    n = len(gaps)
    return gaps[n // 2] if n % 2 else (gaps[n // 2 - 1] + gaps[n // 2]) / 2.0


def detect_missing(series, now=None, factor: float = MISSING_GAP_FACTOR):
    """468: Metriky, které přestaly chodit.

    Očekávaný odstup se odvozuje z historie samotné metriky — pevná hodnota
    by u minutových i denních metrik nutně jednu z nich hlásila špatně.
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for name, points in (series or {}).items():
        stamps = [t for t, _ in points or []]
        cadence = median_interval_sec(stamps)
        if not cadence:
            continue
        last = max((t for t in (_parse(s) for s in stamps) if t), default=None)
        if not last:
            continue
        silent = (now - last).total_seconds()
        if silent <= cadence * factor:
            continue
        out.append({
            "metric": name,
            "last_seen": last.isoformat(),
            "silent_sec": int(silent),
            "silent_min": round(silent / 60.0, 1),
            "expected_every_sec": int(cadence),
            "missed_samples": int(silent / cadence),
        })
    return sorted(out, key=lambda x: -x["silent_sec"])


def describe_degradation(item) -> str:
    """Věta pro člověka — kdy to dojde k problému, ne jen že to roste."""
    slope = item.get('slope_per_hour') or 0
    return (f"{item['metric']}: {item['first']} → {item['last']} "
            f"(+{item['growth_pct']} % za {item['samples']} měření, "
            f"{slope:+.3f}/h, spolehlivost {item['r2']}).")


def describe_missing(item) -> str:
    return (f"{item['metric']}: nic {item['silent_min']} min, "
            f"obvykle každých {item['expected_every_sec']} s "
            f"— chybí ~{item['missed_samples']} měření.")

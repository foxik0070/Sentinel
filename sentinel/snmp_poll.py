"""
327: Aktivní SNMP polling — dotazování OID hodnot a ukládání do telemetrie.

Doplněk k pasivnímu SNMP trap receiveru (snmp_trap.py). Hodnoty se ukládají
přes save_telemetry_snapshot(), takže projdou anomaly detekcí (397) i
threshold alerty (telemetry_alerts) stejně jako ostatní telemetrie.

Config (config.yaml):

    snmp_poll:
      enabled: true
      interval: 300            # sekundy mezi cykly
      targets:
        - host: 192.168.2.1
          name: gateway        # prefix metriky (default = host)
          community: public    # v1/v2c
          version: "2c"        # 1 | 2c | 3
          category: SNMP       # telemetry kategorie
          oids:
            - { oid: 1.3.6.1.4.1.2021.10.1.3.1, metric: load1 }
            - { oid: 1.3.6.1.2.1.2.2.1.10.1, metric: if1_in_bytes, delta: true }

`delta: true` → místo surové hodnoty counteru se uloží přírůstek za sekundu
(Counter32/64 samy o sobě jen rostou a pro alerty jsou nepoužitelné).

SNMPv3: version: "3" + secname/auth_protocol/auth_pass/priv_protocol/priv_pass
(hesla lze načíst z prostředí přes {SECRET:ENV_VAR}).

Vyžaduje net-snmp klienta (`apt install snmp`). Bez něj se polling tiše vypne.
"""
import logging
import re
import subprocess
import threading
import time

from . import state

logger = logging.getLogger("sentinel.snmp_poll")

_MISSING_BINARY_LOGGED = False
# (host, metric) → (timestamp, raw_value) pro výpočet delta u counterů
_last_counter: dict = {}
_counter_lock = threading.Lock()


def _build_auth_args(target: dict) -> list:
    """Vrátí SNMP autentizační argumenty dle verze (v1/v2c community, v3 USM)."""
    version = str(target.get("version", "2c"))
    if version == "3":
        args = ["-v3", "-u", str(target.get("secname", ""))]
        auth_p = target.get("auth_protocol")
        priv_p = target.get("priv_protocol")
        if auth_p and priv_p:
            args += ["-l", "authPriv"]
        elif auth_p:
            args += ["-l", "authNoPriv"]
        else:
            args += ["-l", "noAuthNoPriv"]
        if auth_p:
            args += ["-a", str(auth_p), "-A", str(target.get("auth_pass", ""))]
        if priv_p:
            args += ["-x", str(priv_p), "-X", str(target.get("priv_pass", ""))]
        return args
    return [f"-v{version}", "-c", str(target.get("community", "public"))]


def _snmpget(target: dict, oid: str, timeout: int = 5) -> str | None:
    """Načte jedno OID přes snmpget. Vrací surovou hodnotu nebo None."""
    global _MISSING_BINARY_LOGGED
    host = target.get("host", "")
    if not host or not oid:
        return None
    try:
        # -Oqv: jen hodnota bez OID; -t timeout; -r 0: bez retry (cyklus se opakuje)
        result = subprocess.run(
            ["snmpget", "-Oqv", *_build_auth_args(target),
             "-t", str(timeout), "-r", "0", host, oid],
            capture_output=True, text=True, timeout=timeout + 3
        )
        out = (result.stdout or "").strip()
        if result.returncode != 0 or not out:
            logger.debug(f"snmpget {host} {oid}: rc={result.returncode} {(result.stderr or out)[:120]}")
            return None
        return out
    except FileNotFoundError:
        if not _MISSING_BINARY_LOGGED:
            logger.warning("snmp_poll: snmpget nenalezen — nainstaluj net-snmp (apt install snmp). Polling vypnut.")
            _MISSING_BINARY_LOGGED = True
        return None
    except subprocess.TimeoutExpired:
        logger.debug(f"snmpget {host} {oid}: timeout")
        return None
    except Exception as e:
        logger.debug(f"snmpget {host} {oid}: {e}")
        return None


_TIMETICKS_RE = re.compile(r'\((\d+)\)')
_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?')


def _parse_snmp_value(raw: str) -> float | None:
    """Vytáhne číslo z SNMP výstupu. Zvládá i formáty bez -Oqv.

    '42' → 42.0 | '"1.23"' → 1.23 | 'INTEGER: 42' → 42.0
    'Timeticks: (123456) 0:20:34' → 123456.0 | '23.5 C' → 23.5
    """
    if raw is None:
        return None
    s = str(raw).strip().strip('"').strip()
    if not s:
        return None
    # Timeticks — surové ticky v závorce mají přednost před formátovaným časem
    if "Timeticks" in s or (s.startswith("(") and ")" in s):
        m = _TIMETICKS_RE.search(s)
        if m:
            return float(m.group(1))
    # 'INTEGER: 42', 'Gauge32: 42', 'Counter64: 42', 'STRING: 1.23'
    if ":" in s:
        s = s.split(":", 1)[1].strip().strip('"').strip()
    try:
        return float(s)
    except ValueError:
        pass
    m = _NUM_RE.search(s)          # '23.5 C', '42 %'
    return float(m.group(0)) if m else None


def _apply_delta(key: str, value: float, now: float) -> float | None:
    """Pro counter OID vrátí přírůstek za sekundu. První vzorek → None."""
    with _counter_lock:
        prev = _last_counter.get(key)
        _last_counter[key] = (now, value)
    if not prev:
        return None
    prev_ts, prev_val = prev
    elapsed = now - prev_ts
    if elapsed <= 0:
        return None
    diff = value - prev_val
    if diff < 0:
        return None               # přetečení counteru / restart zařízení
    return round(diff / elapsed, 3)


def poll_target(target: dict) -> dict:
    """Načte všechna OID jednoho cíle. Vrací {metric: value} pro telemetrii."""
    host = target.get("host", "")
    prefix = str(target.get("name") or host).strip()
    timeout = int(target.get("timeout", 5))
    out: dict = {}
    now = time.time()

    for entry in target.get("oids") or []:
        if isinstance(entry, str):
            entry = {"oid": entry, "metric": entry.replace(".", "_")}
        oid = str(entry.get("oid", "")).strip()
        metric = str(entry.get("metric") or oid.replace(".", "_")).strip()
        if not oid or not metric:
            continue
        value = _parse_snmp_value(_snmpget(target, oid, timeout))
        if value is None:
            continue
        full_metric = f"{prefix}.{metric}" if prefix else metric
        if entry.get("delta"):
            value = _apply_delta(f"{prefix}|{metric}", value, now)
            if value is None:
                continue          # první vzorek counteru — nemáme s čím porovnat
        out[full_metric] = value
    return out


def poll_once(cfg: dict) -> int:
    """Jeden cyklus přes všechny cíle. Vrací počet uložených metrik."""
    saved = 0
    for target in cfg.get("targets") or []:
        if not isinstance(target, dict) or not target.get("host"):
            continue
        try:
            values = poll_target(target)
            if values:
                category = str(target.get("category", "SNMP"))
                state.save_telemetry_snapshot(category, values)
                saved += len(values)
        except Exception as e:
            logger.error(f"snmp_poll target {target.get('host')}: {e}")
    return saved


def _poll_loop(cfg: dict):
    interval = max(30, int(cfg.get("interval", 300)))
    logger.info(f"SNMP poller spuštěn: {len(cfg.get('targets') or [])} cílů, interval {interval}s")
    while not state.shutdown_event.is_set():
        try:
            n = poll_once(cfg)
            if n:
                logger.debug(f"snmp_poll: uloženo {n} metrik")
        except Exception as e:
            logger.error(f"snmp_poll loop: {e}")
        # přerušitelné čekání — shutdown nečeká celý interval
        for _ in range(interval):
            if state.shutdown_event.is_set():
                return
            time.sleep(1)


def start_snmp_poll(cfg: dict):
    """Spustí polling na pozadí, pokud je povolen a má cíle."""
    if not cfg or not cfg.get("enabled"):
        return None
    if not (cfg.get("targets") or []):
        logger.info("snmp_poll: enabled, ale žádné targets — přeskočeno")
        return None
    t = threading.Thread(target=_poll_loop, args=(cfg,), daemon=True, name="SNMPPoller")
    t.start()
    return t

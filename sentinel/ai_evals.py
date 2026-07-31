"""
434: AI eval suite — regresní testy kvality AI odpovědí.

Sada deterministických testů: prompt + očekávaná klíčová slova.
Skóre = podíl testů, kde odpověď obsahuje aspoň `min_hits` z `expect_any`
a žádné slovo z `forbid`. Běží na pozadí (každý dotaz na RPi5 ~30 s),
výsledky se ukládají do kv_settings 'ai_eval_results' (posledních 10 běhů).

Vlastní testy lze přidat do /var/lib/sentinel/ai_evals.json (stejný formát).
"""
import json
import os
import threading
import time
import logging
from datetime import datetime

from . import config, state

logger = logging.getLogger("sentinel.ai_evals")

# Výchozí sada — doménové dotazy, na které musí odpovědět i malý model
DEFAULT_EVALS = [
    {
        "id": "oom_kill",
        "prompt": "Log entry: 'kernel: Out of memory: Kill process 1234 (java) score 900'. "
                  "What happened and what is the immediate remediation? Answer in 3 sentences.",
        "expect_any": ["memory", "oom", "killed", "ram"],
        "min_hits": 2,
        "forbid": [],
    },
    {
        "id": "disk_full",
        "prompt": "Server reports: 'No space left on device' on /var. "
                  "Name three commands to diagnose which files consume the space.",
        "expect_any": ["du", "df", "ncdu", "find", "ls -"],
        "min_hits": 2,
        "forbid": [],
    },
    {
        "id": "ssh_bruteforce",
        "prompt": "auth.log shows 500 lines of 'Failed password for root from 203.0.113.7'. "
                  "What is happening and name two mitigations.",
        "expect_any": ["brute", "fail2ban", "firewall", "block", "attack", "key", "disable root"],
        "min_hits": 2,
        "forbid": [],
    },
    {
        "id": "systemd_restart",
        "prompt": "How do I restart a failed systemd service called nginx and check why it failed? "
                  "Give exact commands.",
        "expect_any": ["systemctl restart", "systemctl status", "journalctl"],
        "min_hits": 2,
        "forbid": [],
    },
    {
        "id": "cert_expiry",
        "prompt": "TLS certificate on port 443 expires in 5 days. "
                  "Name the command to verify the expiry date and one way to renew it.",
        "expect_any": ["openssl", "certbot", "renew", "x509", "acme"],
        "min_hits": 2,
        "forbid": [],
    },
    {
        "id": "no_hallucinated_ok",
        "prompt": "Log entry: 'CRITICAL: RAID array /dev/md0 degraded, disk /dev/sdb failed'. "
                  "Is this system healthy? Answer yes or no with a one-sentence reason.",
        "expect_any": ["no", "not healthy", "degraded", "failed"],
        "min_hits": 1,
        "forbid": ["yes, the system is healthy", "everything is fine"],
    },
]

_CUSTOM_EVALS_PATH = "/var/lib/sentinel/ai_evals.json"
_run_lock = threading.Lock()
_running = {"active": False, "progress": 0, "total": 0}


def generate_from_incidents(fix_attempts, history, max_cases: int = 20) -> list:
    """529: Testy z reálných incidentů místo šesti ručně napsaných.

    Ručně psaná sada testuje, co nás napadlo — ne to, co se v téhle
    infrastruktuře opravdu děje. Z incidentu s OVĚŘENOU opravou (486) víme
    obojí: zadání i to, co ho skutečně vyřešilo.

    Bez ověřených oprav nevznikne nic. To je záměr: test, u kterého neznáme
    správnou odpověď, měří jen mnohomluvnost modelu.
    """
    by_key = {}
    for h in history or []:
        if isinstance(h, dict) and h.get('key'):
            by_key.setdefault(h['key'], h)

    seen, cases = set(), []
    for a in fix_attempts or []:
        if not isinstance(a, dict) or a.get('status') != 'worked':
            continue
        cmd = (a.get('command') or '').strip()
        issue = by_key.get(a.get('problem_key'))
        if not cmd or not issue:
            continue
        message = (issue.get('last_line') or '').strip()
        if not message:
            continue

        keywords = _command_keywords(cmd)
        if not keywords:
            continue
        sig = (issue.get('plugin_name') or '', ' '.join(sorted(keywords)))
        if sig in seen:
            continue                     # tentýž typ incidentu netestovat 10×
        seen.add(sig)

        cases.append({
            "id": f"incident_{issue.get('plugin_name') or 'x'}_{len(cases)}",
            "prompt": (f"Systémový alert: [{issue.get('plugin_name')}] "
                       f"{issue.get('host')}: {message[:200]}\n"
                       f"Jaký příkaz problém vyřeší? Odpověz stručně."),
            "expect_any": sorted(keywords),
            "min_hits": 1,
            "forbid": [],
            "source": "incident",
            "evidence_command": cmd,
        })
        if len(cases) >= max_cases:
            break
    return cases


def _command_keywords(command: str) -> list:
    """Významové části příkazu, které od modelu čekáme.

    Přeskakuje přepínače a příliš obecná slova — kdyby se očekávalo „-n"
    nebo „a", prošlo by skoro cokoli a test by neměřil nic.
    """
    skip = {'sudo', 'the', 'and', 'run', '&&', '||'}
    out = []
    for tok in str(command or '').replace('|', ' ').split():
        t = tok.strip().lower()
        if not t or t.startswith('-') or t in skip or len(t) < 3:
            continue
        out.append(t.split('/')[-1])
    return list(dict.fromkeys(out))[:6]


def load_evals() -> list:
    evals = list(DEFAULT_EVALS)
    try:
        if os.path.exists(_CUSTOM_EVALS_PATH):
            with open(_CUSTOM_EVALS_PATH, 'r', encoding='utf-8') as f:
                custom = json.load(f)
            if isinstance(custom, list):
                evals.extend(e for e in custom if isinstance(e, dict) and e.get('prompt'))
    except Exception as e:
        logger.warning(f"ai_evals: custom file load failed: {e}")
    return evals


def _score_reply(ev: dict, reply: str) -> dict:
    r = (reply or "").lower()
    hits = [kw for kw in ev.get("expect_any", []) if kw.lower() in r]
    violations = [kw for kw in ev.get("forbid", []) if kw.lower() in r]
    ok = len(hits) >= int(ev.get("min_hits", 1)) and not violations
    # AI chybové odpovědi = fail bez ohledu na keywords
    if r.startswith("chyba spojení s ai") or r.startswith("ai error"):
        ok = False
    return {"id": ev.get("id", "?"), "ok": ok, "hits": hits,
            "violations": violations, "reply_len": len(reply or "")}


def run_evals(service) -> dict:
    """Spustí celou sadu synchronně (volat z background vlákna). Vrací výsledek."""
    evals = load_evals()
    results = []
    t0 = time.time()
    with _run_lock:
        _running.update(active=True, progress=0, total=len(evals))
    try:
        for i, ev in enumerate(evals):
            q0 = time.time()
            try:
                reply = service.execute_ollama(ev["prompt"], num_ctx=1024, max_tokens=250)
            except Exception as e:
                reply = f"AI Error: {e}"
            res = _score_reply(ev, reply)
            res["latency_s"] = round(time.time() - q0, 1)
            results.append(res)
            with _run_lock:
                _running["progress"] = i + 1
    finally:
        with _run_lock:
            _running["active"] = False

    passed = sum(1 for r in results if r["ok"])
    run = {
        "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "model": getattr(config, 'HAILO_OLLAMA_MODEL', '') if getattr(config, 'HAILO_OLLAMA_ENABLED', False) else getattr(config, 'OLLAMA_MODEL', '?'),
        "backend": "hailo" if getattr(config, 'HAILO_OLLAMA_ENABLED', False) else "ollama",
        "passed": passed,
        "total": len(results),
        "score_pct": round(passed / len(results) * 100) if results else 0,
        "duration_s": round(time.time() - t0, 1),
        "results": results,
    }
    try:
        raw = state.get_setting('ai_eval_results')
        history = json.loads(raw) if raw else []
        history.append(run)
        state.set_setting('ai_eval_results', json.dumps(history[-10:], ensure_ascii=False))
    except Exception as e:
        logger.error(f"ai_evals: save failed: {e}")
    logger.info(f"AI eval run: {passed}/{len(results)} passed ({run['score_pct']} %) in {run['duration_s']}s")
    return run


def start_background_run(service) -> bool:
    """Spustí evaly na pozadí; False pokud už běží."""
    with _run_lock:
        if _running["active"]:
            return False
        _running["active"] = True
    def _worker():
        try:
            run_evals(service)
        except Exception as e:
            logger.error(f"ai_evals background: {e}")
            with _run_lock:
                _running["active"] = False
    threading.Thread(target=_worker, daemon=True, name="AI-Evals").start()
    return True


def status() -> dict:
    with _run_lock:
        return dict(_running)

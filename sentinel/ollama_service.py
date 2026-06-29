import os
import sys
import time
import asyncio
import subprocess
import requests
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from . import config
from . import state
from . import utils
from . import actions

# Prevent concurrent LLM calls that exhaust VRAM (CLAUDE.md sec. 3)
_llm_semaphore = threading.Semaphore(1)

def get_ollama_location():
    return config.OLLAMA_URL if config.ARGS.get("EXTERNAL_OLLAMA") else "local binary"

def get_ollama_type():
    return "external URL" if config.ARGS.get("EXTERNAL_OLLAMA") else "local binary"

def ollama_monitor(interval: int = 300):
    fail_count = 0
    max_retries_before_alert = 3

    if config.HAILO_OLLAMA_ENABLED:
        check_url = config.HAILO_OLLAMA_URL.replace("/v1/chat/completions", "/api/tags").replace("/chat/completions", "/api/tags")
    elif config.ARGS.get("EXTERNAL_OLLAMA") and config.OLLAMA_URL:
        check_url = config.OLLAMA_URL.replace("/chat/completions", "/models")
    else:
        check_url = None

    utils.log_message(f"Starting AI Monitor (Interval: {interval}s)")

    while not state.shutdown_event.is_set():
        try:
            if config.HAILO_OLLAMA_ENABLED:
                resp = requests.get(check_url, timeout=10)
                if resp.status_code not in [200, 404]:
                    raise ConnectionError(f"hailo-ollama HTTP {resp.status_code}")
            elif config.ARGS.get("EXTERNAL_OLLAMA"):
                headers = {"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else {}
                resp = requests.get(check_url, headers=headers, timeout=10)
                if resp.status_code not in [200, 404]:
                    raise ConnectionError(f"HTTP Status {resp.status_code}")
            else:
                res = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=10)
                if res.returncode != 0: raise RuntimeError("Binary check failed")

            if fail_count > 0:
                utils.log_message("AI service recovered.")
                fail_count = 0
        except Exception as e:
            fail_count += 1
            if fail_count == max_retries_before_alert:
                utils.send_to_teams(f"⚠️ <b>CRITICAL:</b> AI Engine unreachable: {e}", "general")
        finally:
            for _ in range(interval):
                if state.shutdown_event.is_set(): break
                time.sleep(1)

# --- WORKER LOGIC ---

def process_single_task(item):
    """Agnostic Task Processor. Does not care what it processes, only relies on channel config."""
    if isinstance(item, dict):
        line = item.get("text", "")
        target_channel = item.get("channel", "general")
        line_type = item.get("type", "info")
        context = item.get("context")
    else:
        # Fallback for old tuples
        line = item[0]
        line_type = item[1] if len(item) > 1 else "problem"
        context = item[2] if len(item) > 2 else None
        target_channel = "general"

    if line_type in ["ai_request", "tests"]:
        prompt_text = line
    else:
        # Load from dynamic PROMPTS config
        raw_prompt = config.PROMPTS.get(target_channel, config.PROMPTS.get("default", "Analyze: {line}"))
        prompt_text = raw_prompt.replace("{line}", line)

    try:
        text = ""
        with _llm_semaphore:
            if config.HAILO_OLLAMA_ENABLED:
                # Hailo AI HAT 2+ — hailo-ollama OpenAI-compatible API
                # hailo-ollama bug: LF v message content způsobí parse_error.101 při vnitřním rendering
                safe_text = prompt_text.replace('\n', ' ').replace('\r', ' ')
                payload = {
                    "model": config.HAILO_OLLAMA_MODEL,
                    "messages": [
                        {"role": "user", "content": safe_text}
                    ],
                    "stream": False,
                    "temperature": 0.2,
                    "max_tokens": 200 if line_type == "ai_request" else 512,
                }
                resp = requests.post(config.HAILO_OLLAMA_URL, json=payload,
                                     headers={"Content-Type": "application/json"}, timeout=300)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            elif config.ARGS.get("EXTERNAL_OLLAMA"):
                payload = {
                    "model": config.OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a pragmatic system analysis engine."},
                        {"role": "user", "content": prompt_text}
                    ],
                    "stream": False,
                    "temperature": 0.2
                }
                headers = {"Content-Type": "application/json"}
                if config.OLLAMA_API_KEY:
                    headers["Authorization"] = f"Bearer {config.OLLAMA_API_KEY}"

                resp = requests.post(config.OLLAMA_URL, json=payload, headers=headers, timeout=300)
                resp.raise_for_status()

                data = resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    text = data["choices"][0].get("message", {}).get("content", "")
                else:
                    text = data.get("message", {}).get("content", "")
            else:
                # Fallback to local subprocess
                res = subprocess.run(["ollama", "run", config.OLLAMA_MODEL], input=prompt_text, capture_output=True, text=True, timeout=300)
                if res.returncode != 0: raise RuntimeError(res.stderr)
                text = res.stdout

        text = text.strip()
        if text:
            utils.ollama_logger.info(f"CH: {target_channel} | RESP: {len(text)} chars")
            if context and context.get("source") == "remediation_request":
                actions.process_ai_proposal(context, text)
            elif context and context.get("source") == "severity_classify":
                _apply_auto_severity(context, text)
            else:
                utils.send_to_teams(text, target_channel)
        return True

    except Exception as e:
        utils.ollama_logger.error(f"Task Failed: {e}")
        return False

def _apply_auto_severity(context, text):
    """Parse LLM severity response and update the issue in DB (only if severity still unset)."""
    import re as _re
    words = _re.findall(r'\b(critical|high|medium|low)\b', text.lower())
    if not words:
        return
    sev = words[0]
    key = context.get('problem_key')
    if not key:
        return
    try:
        conn = state._get_conn()
        conn.execute("UPDATE problems SET severity=? WHERE key=? AND (severity IS NULL OR severity='')", (sev, key))
        conn.commit(); conn.close()
        utils.ollama_logger.info(f"Auto-severity: {key} → {sev}")
    except Exception as e:
        utils.ollama_logger.error(f"Auto-severity update failed: {e}")

def worker_thread_loop(worker_id):
    utils.ollama_logger.info(f"Worker {worker_id} started.")
    
    while not state.shutdown_event.is_set():
        try:
            task = state.fetch_next_task(worker_id)
            
            if task:
                task_id = task['id']
                payload = task['payload']
                process_single_task(payload)
                state.complete_task(task_id)
            else:
                for _ in range(2): 
                    if state.shutdown_event.is_set(): break
                    time.sleep(1)
                
        except Exception as e:
            utils.ollama_logger.error(f"Worker {worker_id} error: {e}")
            time.sleep(5)
            
    utils.ollama_logger.info(f"Worker {worker_id} stopping.")

def _log_hailo_status():
    """Zaloguje stav Hailo hardware při startu. Pouze informativní."""
    # Hailo-8/8L vytvoří /dev/hailo0; Hailo-10H používá hailo1x_pci bez /dev node
    active = (os.path.exists('/dev/hailo0') or
              os.path.exists('/sys/module/hailo1x_pci'))

    if config.HAILO_OLLAMA_ENABLED:
        status = "AKTIVNÍ" if active else "OFFLINE (driver nenalezen)"
        utils.log_message(
            f"Hailo AI HAT 2+ (hailo-ollama): model={config.HAILO_OLLAMA_MODEL} | "
            f"url={config.HAILO_OLLAMA_URL} | NPU: {status}"
        )

    if config.AI_HAT_ENABLED:
        device = config.AI_HAT_DEVICE or 'hailo8l'
        tops = config.AI_HAT_TOPS
        use_emb = config.AI_HAT_USE_EMBEDDINGS
        status = "AKTIVNÍ (/dev/hailo0)" if active else "OFFLINE (nutný reboot / driver nenačten)"
        utils.log_message(
            f"AI HAT+ (embeddingy): {device} ({tops} TOPS) | Stav: {status} | "
            f"NPU embeddingy: {'ano' if use_emb else 'ne (Ollama fallback)'}"
        )

async def _async_worker_loop(worker_id: str, loop_semaphore: asyncio.Semaphore):
    """Async coroutine worker — fetches and processes tasks via executor for blocking calls.
    Uses loop_semaphore to limit concurrent AI calls (critical for Hailo card)."""
    loop = asyncio.get_event_loop()
    utils.ollama_logger.info(f"AsyncWorker {worker_id} started.")
    while not state.shutdown_event.is_set():
        task = await loop.run_in_executor(None, state.fetch_next_task, worker_id)
        if task:
            async with loop_semaphore:
                await loop.run_in_executor(None, process_single_task, task['payload'])
            await loop.run_in_executor(None, state.complete_task, task['id'])
        else:
            await asyncio.sleep(1)
    utils.ollama_logger.info(f"AsyncWorker {worker_id} stopping.")


def start_threads():
    utils.log_message(f"Starting AI Pool ({config.WORKER_THREADS} workers, asyncio)...")
    _log_hailo_status()

    monitor_thread = threading.Thread(target=ollama_monitor, daemon=True, name="Sentinel-Monitor")
    monitor_thread.start()

    # For Hailo: only 1 concurrent AI inference; for CPU: up to WORKER_THREADS
    max_concurrent = 1 if config.HAILO_OLLAMA_ENABLED else config.WORKER_THREADS

    def _run_async_workers():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        semaphore = asyncio.Semaphore(max_concurrent)
        workers = [_async_worker_loop(f"W-{i}", semaphore) for i in range(config.WORKER_THREADS)]
        try:
            loop.run_until_complete(asyncio.gather(*workers))
        except Exception as e:
            utils.log_message(f"AsyncWorker loop error: {e}")
        finally:
            loop.close()
        utils.log_message("AsyncWorker Pool stopped.")

    supervisor_thread = threading.Thread(target=_run_async_workers, daemon=True, name="Sentinel-Supervisor")
    supervisor_thread.start()

    return supervisor_thread, monitor_thread

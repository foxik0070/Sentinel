import os
import html
import json
import time
import base64
import re
import subprocess
import requests
from flask import Blueprint, request, jsonify, g, Response
from ..auth import requires_auth, get_real_ip, int_param
from .. import state, config, utils
from werkzeug.utils import secure_filename
import logging
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.chat")


def create_blueprint(service):
    bp = Blueprint('chat', __name__)

    @bp.route('/api/analyze_single_file', methods=['POST'])
    @requires_auth
    def analyze_single_file():
        data = request.get_json(silent=True) or {}
        filename = data.get('file', '')
        path = service._safe_log_path(filename)
        if path and os.path.exists(path):
            content = utils.read_file_mmap(path)
            _max_c = 8192
            content_trimmed = content[-_max_c:] + (f"\n[...zkráceno na posledních {_max_c} znaků...]" if len(content) > _max_c else "")
            default_prompt = "IT Admin. Log '{filename}':\n\n{content}\n\nBriefly (max 4 sentences) summarize the errors. Answer in ENGLISH."
            prompt = config.PROMPTS.get("chat_analyze_single", default_prompt).replace("{filename}", filename).replace("{content}", content_trimmed)
            ai_reply = service.execute_ollama(prompt, num_ctx=2048, max_tokens=400)
            return jsonify({"reply": html.escape(ai_reply).replace('\n', '<br>')})
        return jsonify({"reply": "File not found."}), 404

    @bp.route('/api/analyze_group_complex', methods=['POST'])
    @requires_auth
    def analyze_group_complex():
        data = request.get_json(silent=True) or {}
        group_name = data.get('group')
        real_key = next((k for k in config.LOG_GROUPS if k.lower() == group_name.lower()), None)
        if not real_key: return jsonify({"reply": f"Skupina '{group_name}' nebyla nalezena."})
        
        combined_content = ""
        analyzed_files = []
        
        MAX_PER_FILE = 8000
        MAX_TOTAL = 30000
        for filename in config.LOG_GROUPS[real_key]:
            path = service._safe_log_path(filename)
            if path and os.path.exists(path):
                content = utils.read_file_mmap(path)
                if content.strip():
                    combined_content += f"\n=== FILE: {filename} ===\n{content[-MAX_PER_FILE:]}\n"
                    analyzed_files.append(filename)
            if len(combined_content) >= MAX_TOTAL:
                combined_content = combined_content[-MAX_TOTAL:]
                break

        if not combined_content: return jsonify({"reply": "Žádné logy k analýze."})

        file_list_str = ", ".join(analyzed_files)
        default_complex = "IT Admin. Logs ({files_list}):\n\n{content}\n\nFind the main problems (max 5 sentences). Answer in ENGLISH."
        prompt = config.PROMPTS.get("chat_analyze_complex", default_complex).replace("{files_list}", file_list_str).replace("{content}", combined_content)
        ai_reply = service.execute_ollama(prompt, num_ctx=config.OLLAMA_NUM_CTX or 8000, max_tokens=500)
        files_html = "".join([f"<span style='background:rgba(0,120,212,0.2); padding:2px 6px; border-radius:4px; margin-right:5px; font-size:0.85em; border:1px solid rgba(0,120,212,0.4);'>{f}</span>" for f in analyzed_files])
        header = f"<div style='margin-bottom:10px; border-bottom:1px solid var(--border); padding-bottom:8px;'><small style='color:var(--text-muted); text-transform:uppercase;'>Analyzované zdroje ({len(analyzed_files)}):</small><br><div style='margin-top:4px;'>{files_html}</div></div>"
        final_reply = header + html.escape(ai_reply).replace('\n', '<br>')
        return jsonify({"reply": final_reply})

    @bp.route('/api/set_active_log', methods=['POST'])
    @requires_auth
    def set_active_log():
        data = request.get_json(silent=True) or {}
        filename = data.get('filename')
        path = service._safe_log_path(filename)
        if path and os.path.exists(path):
            content, lines = service.read_file_content(path)
            safe_name = os.path.basename(path)
            service.get_session_data()['active_file'] = {'name': safe_name, 'content': content}
            service.log_event("context_set", f"User set context file: {safe_name}", user=g.username)
            return jsonify({"status": "ok", "filename": safe_name, "lines": lines})
        return jsonify({"error": "File not found"}), 404

    @bp.route('/api/upload_file', methods=['POST'])
    @requires_auth
    def upload_file():
        ip = get_real_ip()
        if not utils.security.check_rate_limit(ip, 'upload'): return jsonify({"status":"error", "message":"Rate limit exceeded"}), 429
        if 'file' not in request.files: return jsonify({"status": "error"})
        file = request.files['file']
        if not file.filename:
            return jsonify({"status": "error", "message": "No filename"}), 400
        safe_name = secure_filename(file.filename)
        if not safe_name:
            return jsonify({"status": "error", "message": "Invalid filename"}), 400
        allowed_ext = {'.log', '.txt', '.conf', '.cfg', '.yaml', '.yml', '.json', '.py', '.sh', '.csv', '.md'}
        file_ext = os.path.splitext(safe_name)[1].lower()
        if file_ext not in allowed_ext:
            return jsonify({"status": "error", "message": f"Extension '{file_ext}' not allowed"}), 400
        raw = file.read(service._MAX_UPLOAD_BYTES + 1)
        if len(raw) > service._MAX_UPLOAD_BYTES:
            return jsonify({"status": "error", "message": "File too large (max 5 MB)"}), 413
        content = raw.decode('utf-8', errors='replace')
        service.get_session_data()['active_file'] = {'name': safe_name, 'content': content}
        service.log_event("file_upload", f"User uploaded: {safe_name}", user=g.username)
        return jsonify({"status":"ok"})

    @bp.route('/api/logs/list', methods=['GET'])
    @requires_auth
    def list_logs():
        try:
            files = []
            for f in os.listdir(config.LOG_DIR):
                if f.endswith(('.log', '.txt')):
                    fp = os.path.join(config.LOG_DIR, f)
                    st = os.stat(fp)
                    files.append({"name": f, "size": f"{round(st.st_size/(1024*1024), 2)} MB", "mtime": datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')})
            files.sort(key=lambda x: x['mtime'], reverse=True)
            return jsonify({"files": files})
        except Exception as e: return jsonify({"error": str(e)}), 500

    @bp.route('/api/logs/view', methods=['POST'])
    @requires_auth
    def view_log():
        fname = (request.get_json(silent=True) or {}).get('filename')
        path = service._safe_log_path(fname)
        if path and os.path.exists(path):
            return jsonify({"content": html.escape(utils.read_file_mmap(path))})
        return jsonify({"error": "Not found"}), 404

    @bp.route('/api/logs/tail/<path:filename>', methods=['GET'])
    @requires_auth
    def tail_log(filename):
        path = service._safe_log_path(filename)
        if not path or not os.path.exists(path):
            return jsonify({"error": "Not found"}), 404
        lines_back = int_param(request.args.get('lines', 50), 50, 1, 200)

        def generate():
            try:
                with open(path, 'rb') as f:
                    f.seek(0, 2)
                    fsize = f.tell()
                    buf, pos, found = [], fsize, 0
                    while pos > 0 and found < lines_back:
                        read_sz = min(4096, pos)
                        pos -= read_sz
                        f.seek(pos)
                        chunk = f.read(read_sz)
                        buf.insert(0, chunk)
                        found += chunk.count(b'\n')
                    raw = b''.join(buf).decode('utf-8', errors='replace')
                    for line in raw.split('\n')[-lines_back:]:
                        yield f"data: {json.dumps({'line': line, 'init': True})}\n\n"
                    last_pos = fsize
                while True:
                    time.sleep(1)
                    try:
                        cur_size = os.path.getsize(path)
                    except OSError:
                        break
                    if cur_size > last_pos:
                        with open(path, 'rb') as f2:
                            f2.seek(last_pos)
                            new_data = f2.read(cur_size - last_pos)
                        last_pos = cur_size
                        for line in new_data.decode('utf-8', errors='replace').split('\n'):
                            if line:
                                yield f"data: {json.dumps({'line': line, 'init': False})}\n\n"
                    elif cur_size < last_pos:
                        last_pos = cur_size
                        yield f"data: {json.dumps({'line': '--- log rotated ---', 'init': False})}\n\n"
            except GeneratorExit:
                pass
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @bp.route('/api/chat/stream', methods=['POST'])
    @requires_auth
    def chat_stream():
        """SSE streaming endpoint for real AI queries (non-command messages)."""
        data = request.json or {}
        msg = data.get('message', '').strip()
        if not msg:
            return jsonify({"error": "empty"}), 400

        ip = get_real_ip()
        if not utils.security.check_rate_limit(ip, 'chat'):
            return jsonify({"error": "Rate limit exceeded"}), 429

        role = getattr(g, 'user_role', 'user')
        service.log_event("chat_stream", f"[{g.username}] {msg}", user=g.username)
        service.conversation_history.append(f"{g.username}: {msg}")
        if len(service.conversation_history) > getattr(service, "_conv_history_limit", 100):
            service.conversation_history.pop(0)

        start_ts = time.time()

        # Build messages/prompt (same logic as chat_api AI path)
        session_data = service.get_session_data()
        if session_data.get('active_file'):
            af = session_data['active_file']
            fname = af['name']
            _MAX_FILE_CHARS = 8192
            content = af['content'][:_MAX_FILE_CHARS]
            if len(af['content']) > _MAX_FILE_CHARS:
                content += "\n\n[...zkráceno na 2048 tokenů...]"
            history_str = "\n".join(service.conversation_history[-4:])
            system_msg = (f"You are Sentinel, a Linux infrastructure support assistant. "
                          f"The user is examining file '{fname}'. Answer concisely in ENGLISH.")
            user_msg = (f"{f'Conversation history:{chr(10)}{history_str}{chr(10)}{chr(10)}' if history_str else ''}"
                        f"File content:\n{content}\n\nQuestion: {msg}")
            if config.HAILO_OLLAMA_ENABLED:
                messages = [{"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg}]
                prompt = None
            else:
                messages = None
                prompt = f"{system_msg}\n\n{user_msg}\n\nAnswer:"
        else:
            from .. import rag
            context = rag.rag_system.search(msg)
            status_note = "(KB indexing) " if not rag.rag_system.is_ready else ""
            has_ctx = bool(context and context.strip() not in ("", "KB Empty.", "No text match found."))
            history_str = "\n".join(service.conversation_history[-5:-1])
            system_msg = (f"You are Sentinel, an AI assistant for Linux infrastructure administration. "
                          f"{status_note}Answer in ENGLISH. Be concise. "
                          "If the context is irrelevant, answer from general expertise.")
            user_parts = []
            if history_str:
                user_parts.append(f"Conversation history:\n{history_str}")
            if has_ctx:
                user_parts.append(f"Knowledge base context:\n{context}")
            user_parts.append(f"Question: {msg}")
            user_msg = "\n\n".join(user_parts)
            if config.HAILO_OLLAMA_ENABLED:
                messages = [{"role": "system", "content": system_msg},
                            {"role": "user", "content": user_msg}]
                prompt = None
            else:
                messages = None
                prompt = f"{system_msg}\n\n{user_msg}\n\nAnswer:"

        def _stream_generator():
            service.chat_queue_depth += 1
            _stream_start = time.time()
            try:
                service.llm_semaphore.acquire()
                service.chat_queue_depth -= 1
                service.metrics["ai_requests"] += 1

                def _stream_hailo_or_fallback():
                    """Stream from hailo-ollama /api/chat (native Ollama format);
                    fall back to CPU ollama only on connect/protocol error."""
                    # hailo-ollama: /v1/chat/completions rejects stream=True;
                    # streaming only works on /api/chat (native Ollama wire format).
                    base = config.HAILO_OLLAMA_URL.split('/v1/')[0].split('/api/')[0].rstrip('/')
                    hailo_chat_url = f"{base}/api/chat"
                    hailo_msgs = [{"role": m["role"],
                                   "content": m["content"].replace('\n', ' ').replace('\r', ' ')}
                                  for m in messages]
                    payload = {"model": config.HAILO_OLLAMA_MODEL,
                               "messages": hailo_msgs, "stream": True, "options": {"temperature": 0.1}}
                    hailo_done = False
                    try:
                        with requests.post(hailo_chat_url, json=payload,
                                           headers={"Content-Type": "application/json"},
                                           timeout=(8, 120), stream=True) as resp:
                            resp.raise_for_status()
                            for line in resp.iter_lines():
                                if not line:
                                    continue
                                try:
                                    chunk = json.loads(line.decode('utf-8', errors='replace'))
                                    token = chunk.get('message', {}).get('content', '')
                                    if token:
                                        yield f"data: {json.dumps({'token': token})}\n\n"
                                    if chunk.get('done'):
                                        hailo_done = True
                                        break
                                except Exception:
                                    pass
                    except Exception as hailo_err:
                        if hailo_done:
                            # Response was complete — exception is from connection teardown, ignore
                            return
                        logger.warning(f"hailo-ollama unavailable ({hailo_err}), falling back to CPU ollama for chat")
                        yield f"data: {json.dumps({'token': '[NPU nedostupný — CPU] '})}\n\n"
                        # CPU ollama fallback
                        cpu_url = config.OLLAMA_URL
                        cpu_payload = {"model": config.OLLAMA_MODEL,
                                       "messages": [{"role": "user", "content": user_msg}],
                                       "stream": True, "options": {"temperature": 0.1}}
                        headers_cpu = {"Content-Type": "application/json"}
                        if config.OLLAMA_API_KEY:
                            headers_cpu["Authorization"] = f"Bearer {config.OLLAMA_API_KEY}"
                        try:
                            with requests.post(cpu_url, json=cpu_payload,
                                               headers=headers_cpu, timeout=(10, 120), stream=True) as resp:
                                resp.raise_for_status()
                                for line in resp.iter_lines():
                                    if not line:
                                        continue
                                    try:
                                        chunk = json.loads(line.decode('utf-8', errors='replace'))
                                        token = (chunk.get('message', {}).get('content', '')
                                                 or chunk.get('choices', [{}])[0].get('delta', {}).get('content', ''))
                                        if token:
                                            yield f"data: {json.dumps({'token': token})}\n\n"
                                        if chunk.get('done'):
                                            break
                                    except Exception:
                                        pass
                        except Exception as cpu_err:
                            yield f"data: {json.dumps({'token': f'⚠️ AI nedostupné: {cpu_err}'})}\n\n"
                        return
                    if not hailo_done:
                        # Stream ended without done:true — treat as error
                        yield f"data: {json.dumps({'token': '⚠️ Neúplná odpověď NPU'})}\n\n"

                if config.HAILO_OLLAMA_ENABLED:
                    yield from _stream_hailo_or_fallback()

                elif config.ARGS.get("EXTERNAL_OLLAMA"):
                    is_v1 = "/v1/" in config.OLLAMA_URL
                    if is_v1:
                        payload = {"model": config.OLLAMA_MODEL,
                                   "messages": [{"role": "user", "content": prompt or user_msg}],
                                   "stream": True, "temperature": 0.1}
                    else:
                        payload = {"model": config.OLLAMA_MODEL,
                                   "prompt": prompt or user_msg,
                                   "stream": True,
                                   "options": {"temperature": 0.1, "num_ctx": 2048}}
                    headers = {"Authorization": f"Bearer {config.OLLAMA_API_KEY}"} if config.OLLAMA_API_KEY else {}
                    try:
                        with requests.post(config.OLLAMA_URL, json=payload,
                                           headers=headers, timeout=600, stream=True) as resp:
                            for line in resp.iter_lines():
                                if not line:
                                    continue
                                raw = line.decode('utf-8', errors='replace')
                                if raw.startswith('data:'):
                                    raw = raw[5:].strip()
                                if raw in ('[DONE]', ''):
                                    continue
                                try:
                                    chunk = json.loads(raw)
                                    # v1 OpenAI format
                                    token = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                    # legacy /api/generate format
                                    if not token:
                                        token = chunk.get('response', '')
                                    if token:
                                        yield f"data: {json.dumps({'token': token})}\n\n"
                                    if chunk.get('done'):
                                        break
                                except Exception:
                                    pass
                    except Exception as e:
                        yield f"data: {json.dumps({'token': f'Chyba AI: {str(e)}'})}\n\n"
                else:
                    # subprocess fallback — not streamable, send as single chunk
                    try:
                        result = subprocess.run(
                            [getattr(config, 'OLLAMA_BIN', 'ollama'), "run", config.OLLAMA_MODEL],
                            input=prompt or user_msg, capture_output=True, text=True, timeout=600
                        )
                        for token in result.stdout.split(' '):
                            if token:
                                yield f"data: {json.dumps({'token': token + ' '})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'token': f'Chyba AI: {str(e)}'})}\n\n"

                duration = round(time.time() - _stream_start, 2)
                service.metrics["ai_latency_history"].append(duration)
                yield f"data: {json.dumps({'done': True, 'duration': duration})}\n\n"
                service.log_event("rag_chat_stream", "Streaming response sent",
                               user=g.username, duration_ms=duration*1000)
            except GeneratorExit:
                duration = round(time.time() - _stream_start, 2)
                if duration > 0.1:
                    service.metrics["ai_latency_history"].append(duration)
                raise
            finally:
                service.llm_semaphore.release()

        return Response(_stream_generator(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @bp.route('/api/chat', methods=['POST'])
    @requires_auth
    def chat_api():
        start_ts = time.time()
        ip = get_real_ip()
        if not utils.security.check_rate_limit(ip, 'chat'): 
            return jsonify({"reply": "Rate limit exceeded."}), 429
        
        data = request.get_json(silent=True) or {}
        msg = data.get('message', '').strip()
        
        # OPRAVA OPRÁVNĚNÍ PRO MOBILNÍ ZAŘÍZENÍ:
        role = getattr(g, 'user_role', 'user')
        
        service.log_event("chat_message", f"[{g.username}] {msg}", user=g.username)
        
        service.conversation_history.append(f"{g.username}: {msg}")
        if len(service.conversation_history) > getattr(service, "_conv_history_limit", 100): service.conversation_history.pop(0)
        
        if msg.lower() == 'clear file':
            service.get_session_data()['active_file'] = None
            return jsonify({"reply": "Soubor uvolněn.", "file_cleared": True})

        if msg == 'delete_all_issues':
            if role not in ['admin', 'superadmin']: return jsonify({"reply": "⛔ Pouze pro Admina."})
            for i in state.get_active_issues(): state.delete_problem(i['key'])
            state.delete_all_pending_actions()
            return jsonify({"reply": "🗑️ Databáze problémů a akcí vyčištěna."})
 
        if msg.startswith('delete_key '):
            if role not in ['admin', 'superadmin']: return jsonify({"reply": "⛔ Odepřeno. Právo pouze pro administrátory."})
            try:
                k = base64.b64decode(msg.split()[1]).decode()
                state.delete_problem(k)
                service.log_event("issue_delete", f"Deleted issue key: {k}", user=g.username)
                return jsonify({"reply": "", "silent": True})
            except Exception as e:
                return jsonify({"reply": f"⚠️ Chyba mazání: {str(e)}"})

        if msg.startswith('ignore_key '):
            if role not in ['admin', 'superadmin']: return jsonify({"reply": "⛔ Odepřeno. Právo pouze pro administrátory."})
            k = base64.b64decode(msg.split()[1]).decode()
            service.ignored_issues.add(k); service.save_ignored_issues(); return jsonify({"reply": "", "silent": True})

        if msg.startswith(('approve', 'reject', 'confirm_approve')):
            if role not in ['admin', 'superadmin']: return jsonify({"reply": "⛔ Admin only."})
            try:
                parts = msg.split()
                cmd_type, aid = parts[0], int(parts[1])
                act = state.get_action(aid)
                if not act or act['status'] != 'pending': return jsonify({"reply": "Neplatná akce."})
                
                if cmd_type == 'approve':
                    return jsonify({"reply": f"Potvrdit?<br><b>{html.escape(act['command'])}</b>", "confirm_required": True, "action_id": aid, "cluster": act['cluster'], "command": act['command']})
                
                elif cmd_type == 'confirm_approve':
                    state.update_action_status(aid, "executing", "Starting...", g.username)
                    service.metrics["cmd_executed"] += 1
                    from .. import actions
                    ok, out = actions.run_ssh_command_real(act['cluster'], act['command'], action_id=aid)
                    state.update_action_status(aid, "executed" if ok else "failed", out, g.username)
                    service.log_event("action_exec", f"Action {aid} executed. Success: {ok}", user=g.username)
                    
                    if ok and act.get('problem_key'):
                        try:
                            prob = state.get_problem(act['problem_key'])
                            if prob:
                                prob['status'] = 'validating'
                                prob['last_seen'] = datetime.now(timezone.utc).isoformat()
                                state.save_problem(act['problem_key'], prob)
                        except Exception as e:
                            logger.error(f"Failed to update problem status: {e}")

                    return jsonify({"reply": f"{'✅' if ok else '❌'} <b>Hotovo.</b><br><pre>{html.escape(out)}</pre>"})
                
                elif cmd_type == 'reject':
                    try:
                        state.update_action_status(aid, "rejected", "Rejected", g.username)
                        state.log_action_event(aid, "rejected", actor=g.username)
                        service.log_event("action_reject", f"Action {aid} rejected", user=g.username)
                        return jsonify({"reply": "❌ Zamítnuto."})
                    except Exception as e:
                        logger.error(f"Reject Error: {e}")
                        return jsonify({"reply": "⚠️ Chyba při zamítání."})
            except: pass

        if msg.startswith('save_action '):
            if role not in ['admin', 'superadmin']:
                return jsonify({"reply": "⛔ Admin only."})
            try:
                payload_b64 = msg.split(' ', 1)[1].strip()
                data = json.loads(base64.b64decode(payload_b64).decode())
                cmd = (data.get('command') or '').strip()
                desc = data.get('description') or 'Manual autofix'
                if not cmd or cmd == 'N/A':
                    return jsonify({"reply": "⚠️ No executable command to queue."})
                from .. import safety
                risk_score, risk_reasons = safety.classify(cmd)
                aid = state.create_pending_action(
                    problem_key=f"manual_{int(time.time())}",
                    cluster="manual", node="manual",
                    command=cmd, reason=desc, mode="dry_run",
                    risk_score=risk_score, risk_reasons=risk_reasons,
                )
                if aid:
                    return jsonify({"reply": (
                        f"✅ Action <b>#{aid}</b> queued (dry-run). "
                        f"<button onclick='openPendingActionsModal()' "
                        f"style='background:#7c3aed;color:white;border:none;padding:3px 10px;"
                        f"border-radius:4px;cursor:pointer;font-size:0.85em;margin-left:6px;'>"
                        f"📋 Open Actions</button>"
                    )})
                return jsonify({"reply": "⚠️ Already in queue or create failed."})
            except Exception as e:
                return jsonify({"reply": f"❌ Error: {html.escape(str(e))}"})

        if msg.startswith('autofix_text '):
            if role not in ['admin', 'viewer', 'superadmin']:
                return jsonify({"reply": "⛔ Přístup odepřen."})
            try:
                raw_msg = msg.split(' ', 1)[1] if ' ' in msg else msg
                # Detect b64-encoded payload (no spaces, looks like base64)
                if raw_msg and ' ' not in raw_msg and len(raw_msg) > 8:
                    try:
                        decoded = base64.b64decode(raw_msg + '==').decode('utf-8')
                        if decoded.isprintable():
                            raw_msg = decoded
                    except Exception:
                        pass
                clean_msg = re.sub(r'\[\d{4}-\d{2}-\d{2}.*?\]', '', raw_msg)
                clean_msg = re.sub(r'\[[A-Z]+\]', '', clean_msg)
                clean_msg = re.sub(r'\s+', ' ', clean_msg).strip()

                default_autofix_sys = (
                    'You are a Linux SysAdmin expert. Analyze the given issue and respond ONLY with valid JSON:\n'
                    '{"description": "one-sentence explanation of the problem and fix", "command": "exact bash command to fix or diagnose the issue"}\n'
                    'The "command" field MUST always contain a real, runnable bash command — never "N/A". '
                    'If a direct fix is not possible, provide a diagnostic command (e.g. sinfo, scontrol, systemctl status, journalctl, ps, top, pdsh).\n'
                    'No markdown, no extra text — just the JSON object.'
                )
                cfg_autofix = config.PROMPTS.get("chat_autofix", "")
                if cfg_autofix:
                    prompt = cfg_autofix.replace("{clean_msg}", clean_msg)
                    autofix_messages = None
                else:
                    autofix_messages = [
                        {"role": "system", "content": default_autofix_sys},
                        {"role": "user", "content": f"Issue: {clean_msg}"},
                    ]
                    prompt = None
                raw_response = service.execute_ollama(prompt, num_ctx=1024, messages=autofix_messages, max_tokens=200).strip()

                # JSON parsing (preferovaný formát)
                description = raw_response
                command = "N/A"
                try:
                    clean_json = raw_response.replace("```json", "").replace("```", "").strip()
                    json_match = re.search(r'\{[^{}]+\}', clean_json, re.DOTALL)
                    if json_match:
                        clean_json = json_match.group(0)
                    parsed = json.loads(clean_json)
                    description = parsed.get("description", raw_response)
                    command = parsed.get("command", "N/A")
                except (json.JSONDecodeError, Exception):
                    cmd_match = re.search(r'`([^`\n]+)`', raw_response)
                    if cmd_match:
                        command = cmd_match.group(1).strip()
                        description = raw_response.replace(f"`{command}`", "").strip()

                # Detekce vráceného vzoru místo skutečné odpovědi
                if command in ("bash command or N/A", "exact bash command, or N/A if no command applies"):
                    command = "N/A"
                if description in ("one sentence fix", "one-sentence explanation of the fix", ""):
                    description = clean_msg

                # Bezpečnostní klasifikace
                risk_html = ""
                if command and command != "N/A":
                    try:
                        from .. import safety
                        risk_score, risk_reasons = safety.classify(command)
                        risk_color = "#28a745" if risk_score < safety.THRESHOLD_REVIEW else ("#ffc107" if risk_score < safety.THRESHOLD_BLOCK else "#dc3545")
                        risk_label = "LOW" if risk_score < safety.THRESHOLD_REVIEW else ("REVIEW" if risk_score < safety.THRESHOLD_BLOCK else "HIGH RISK")
                        reasons_text = " | ".join(risk_reasons) if risk_reasons else "safe"
                        risk_html = f"<div style='font-size:0.78em;color:{risk_color};margin-top:4px;'>Risk: {risk_label} ({risk_score}/100) — {html.escape(reasons_text)}</div>"
                    except Exception:
                        pass

                ts_key = str(int(time.time() * 1000))[-7:]
                b64_payload = base64.b64encode(json.dumps({
                    "command": command,
                    "description": description,
                }).encode()).decode()
                reanalyze_b64 = base64.b64encode(clean_msg.encode()).decode()
                queue_btn = ""
                if role in ['admin', 'superadmin'] and command and command != 'N/A':
                    queue_btn = (
                        f"<button onclick='triggerAction(\"save_action {b64_payload}\")' "
                        f"style='background:#7c3aed;color:white;border:none;padding:5px 12px;"
                        f"border-radius:4px;cursor:pointer;font-size:0.82em;font-weight:600;'>➕ Queue</button>"
                    )
                html_reply = (
                    f"<div style='background:var(--card-bg);border:1px solid #7c3aed;border-radius:8px;padding:14px;max-width:100%;'>"
                    f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>"
                    f"<span>🪄</span><b style='color:#a855f7;'>AI Fix Suggestion</b></div>"
                    f"<div style='color:var(--text-main);margin-bottom:10px;line-height:1.5;font-size:0.92em;'>{html.escape(description)}</div>"
                    f"<div style='position:relative;margin-bottom:6px;'>"
                    f"<code id='afc{ts_key}' style='color:var(--code-text);background:var(--code-bg);"
                    f"padding:8px 44px 8px 10px;display:block;border-radius:4px;word-break:break-all;"
                    f"border:1px solid var(--card-border);font-family:monospace;font-size:0.9em;'>"
                    f"{html.escape(command)}</code>"
                    f"<button onclick='navigator.clipboard.writeText(document.getElementById(\"afc{ts_key}\").innerText)' "
                    f"style='position:absolute;top:5px;right:5px;background:transparent;border:1px solid var(--card-border);"
                    f"border-radius:3px;color:var(--text-muted);cursor:pointer;padding:2px 7px;font-size:0.72em;' "
                    f"title='Copy'>📋</button></div>"
                    f"{risk_html}"
                    f"<div style='display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;'>"
                    f"{queue_btn}"
                    f"<button onclick='triggerAction(\"autofix_text \"+atob(\"{reanalyze_b64}\"))' "
                    f"style='background:var(--card-bg);color:var(--text-muted);border:1px solid var(--card-border);"
                    f"padding:5px 12px;border-radius:4px;cursor:pointer;font-size:0.82em;'>🔄 Re-analyze</button>"
                    f"</div></div>"
                )
                return jsonify({"reply": html_reply})
            except Exception as e:
                return jsonify({"reply": f"❌ Chyba autofixu: {html.escape(str(e))}"})

        if msg in ['stav', 'status']:
            return jsonify({"reply": service.get_status_html(role)})

        if msg in ['agents', 'agenti']:
            agents = [a for a in state.get_all_agents() if a.get('category') not in ('hw', 'alert')]
            online = [a for a in agents if a.get('status') == 'ONLINE']
            offline = [a for a in agents if a.get('status') != 'ONLINE']
            maint = [a for a in agents if a.get('maintenance_until') and
                     __import__('datetime').datetime.fromisoformat(
                         a['maintenance_until'].replace('Z','+00:00')).replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)]
            lines = [f"<b>Agenti ({len(online)}/{len(agents)} online)</b>"]
            if maint:
                lines.append(f"<span style='color:#fa8231'>🔧 Údržba ({len(maint)}): {', '.join(a['hostname'] for a in maint)}</span>")
            if offline:
                lines.append(f"<span style='color:var(--error)'>● Offline ({len(offline)}): {', '.join(a['hostname'] for a in offline)}</span>")
            lines.append(f"<span style='color:var(--success)'>● Online ({len(online)}): {', '.join(a['hostname'] for a in online[:10])}{' +více' if len(online)>10 else ''}</span>")
            return jsonify({"reply": "<br>".join(lines)})

        if msg in ['history', 'historie']:
            try:
                conn = state._get_conn()
                rows = conn.execute(
                    "SELECT channel_type, host, plugin_name, last_line, resolved_at FROM issue_history "
                    "ORDER BY resolved_at DESC LIMIT 10"
                ).fetchall()
                conn.close()
                if not rows:
                    return jsonify({"reply": "Historie prázdná."})
                ch_colors = {'security':'#f87171','infra':'#4da6ff','agent':'#28a745','root':'#ffc107'}
                def _ih_row(r):
                    col = ch_colors.get(r[0], '#888')
                    return (f"<div style='margin-bottom:4px;'><span style='color:{col};font-size:0.8em;font-weight:700;'>{(r[0] or '?').upper()}</span> "
                            f"<b>{html.escape(r[1] or '?')}</b> [{html.escape(r[2] or '?')}] "
                            f"<span style='color:var(--text-muted);font-size:0.8em;'>{(r[4] or '')[:16]}</span></div>")
                items = "".join(_ih_row(r) for r in rows)
                return jsonify({"reply": f"<b>Posledních 10 vyřešených issues:</b><br>{items}"})
            except Exception as e:
                return jsonify({"reply": f"Chyba: {html.escape(str(e))}"})

        if msg in ['maint', 'maintenance', 'udrzba']:
            agents = state.get_all_agents()
            now_dt = datetime.now(timezone.utc)
            in_maint = []
            for a in agents:
                mu = a.get('maintenance_until')
                if mu:
                    try:
                        mu_dt = datetime.fromisoformat(mu.replace('Z','+00:00')).replace(tzinfo=timezone.utc)
                        if mu_dt > now_dt:
                            in_maint.append(f"{html.escape(a['hostname'])} (do {mu_dt.strftime('%H:%M')})")
                    except Exception:
                        pass
            if not in_maint:
                return jsonify({"reply": "Žádný agent v maintenance módu."})
            return jsonify({"reply": f"<b>🔧 Maintenance mód ({len(in_maint)}):</b><br>" + "<br>".join(in_maint)})
        
        if msg == 'show_ignored':
            h = "<h3 style='color:var(--text-main)'>Ignorované:</h3>"
            for k in service.ignored_issues:
                kb = base64.b64encode(k.encode()).decode()
                h += f"<div style='color:var(--text-main); margin-bottom:5px;'>{html.escape(k)} <button onclick=\"triggerAction('unignore_key {kb}')\">Sledovat</button></div>"
            return jsonify({"reply": h if service.ignored_issues else "Seznam prázdný."})

        if msg.startswith('unignore_key ') and role in ['admin', 'superadmin']:
            k = base64.b64decode(msg.split()[1]).decode()
            if k in service.ignored_issues: service.ignored_issues.remove(k); service.save_ignored_issues(); return jsonify({"reply": "", "silent": True})

        if msg == 'sys':
            initial_content = service.render_sys_monitor_html(g.user_role)
            html_response = f"""
            <div class='sys-monitor-container sys-monitor-live'>
                <div class='sys-header' onclick="this.nextElementSibling.classList.toggle('minimized')">
                    <span style='color:var(--text-main); font-weight:bold;'><i class='fa-solid fa-server'></i> SYSTEM MONITOR</span>
                    <span style='font-size:0.8em; color:var(--text-muted);'>▼</span>
                </div>
                <div class='sys-body'>
                    {initial_content}
                </div>
            </div>
            """
            return jsonify({"reply": html_response})
 
        if msg == 'pending':
            pending = state.get_pending_actions()
            count = len(pending)
            if not count:
                return jsonify({"reply": "✅ No pending actions."})
            return jsonify({"reply": (
                f"<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;'>"
                f"<span style='color:#ffc107;'>⏳ <b>{count}</b> pending action{'s' if count != 1 else ''}.</span>"
                f"<button onclick='openPendingActionsModal()' "
                f"style='background:#7c3aed;color:white;border:none;padding:5px 12px;"
                f"border-radius:4px;cursor:pointer;font-size:0.85em;font-weight:600;'>📋 Open Actions Panel</button>"
                f"</div>"
            )})
 
        session_data = service.get_session_data()
        if session_data.get('active_file'):
            af = session_data['active_file']
            fname = af['name']
            _MAX_FILE_CHARS = 8192  # ~2048 tokens @ ~4 chars/token
            content = af['content'][:_MAX_FILE_CHARS]
            if len(af['content']) > _MAX_FILE_CHARS:
                content += f"\n\n[... obsah zkrácen na 2048 tokenů z {len(af['content'])//4} tokenů celkem ...]"
            history_str = "\n".join(service.conversation_history[-4:])
            system_content = (
                f"You are Sentinel, a Linux infrastructure support assistant. The user is examining file '{fname}'. "
                "Answer in ENGLISH. Be concise. Base your answer on the file content when relevant; "
                "supplement with general Linux knowledge if needed."
            )
            user_content_parts = []
            if history_str:
                user_content_parts.append(f"Conversation history:\n{history_str}")
            user_content_parts.append(f"File content:\n{content}")
            user_content_parts.append(f"Question: {msg}")
            user_content = "\n\n".join(user_content_parts)
            if config.HAILO_OLLAMA_ENABLED:
                reply = service.execute_ollama(None, messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user",   "content": user_content},
                ])
            else:
                reply = service.execute_ollama(f"{system_content}\n\n{user_content}\n\nAnswer:")
            duration = time.time() - start_ts
            service.log_event("file_chat", "Answered from file context", user=g.username, duration_ms=duration*1000)
            return jsonify({
                "reply": f"<b>🤖 Sentinel ({duration:.2f}s) [File]:</b><br>{html.escape(reply).replace(chr(10), '<br>')}"
            })

        reply = service.call_ai_knowledge_base(msg)
        duration = time.time() - start_ts
        service.log_event("rag_chat", "Answered from RAG", user=g.username, duration_ms=duration*1000)
        return jsonify({
            "reply": f"<b>🤖 Sentinel ({duration:.2f}s):</b><br>{html.escape(reply).replace(chr(10), '<br>')}"
        })

    return bp

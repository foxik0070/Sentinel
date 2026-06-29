import logging
import json
import re
import subprocess
import shlex
from flask import Blueprint, request, jsonify, g, Response
from ..auth import requires_auth, int_param
from .. import state, config, actions

logger = logging.getLogger("sentinel.chat")

# 282: Validace hostname/IP před SSH voláním — brání injection přes host parametr
_HOST_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,253}$')

def _valid_host(host: str) -> bool:
    return bool(host) and bool(_HOST_RE.fullmatch(host))


def create_blueprint(service):
    bp = Blueprint('actions', __name__)

    @bp.route('/api/v1/actions', methods=['GET'])
    @requires_auth
    def api_v1_actions_list():
        """List AI-proposed actions. Defaults to pending+dry_run (the review queue).

        Query params:
          status — filter by status (default 'pending'; pass 'all' to skip)
          mode   — filter by mode   (default 'dry_run';  pass 'all' to skip)
        """
        status = request.args.get('status', 'pending')
        mode = request.args.get('mode', 'dry_run')
        actions_list = state.list_actions(
            status=None if status == 'all' else status,
            mode=None if mode == 'all' else mode,
        )
        return jsonify({"status": "ok", "actions": actions_list})

    @bp.route('/api/v1/actions/<int:aid>/audit', methods=['GET'])
    @requires_auth
    def api_v1_action_audit(aid):
        return jsonify({"status": "ok", "audit": state.get_action_audit(aid)})

    @bp.route('/api/actions/audit_log', methods=['GET'])
    @requires_auth
    def api_actions_audit_log():
        """Celkový audit log akcí (všechny záznamy, od nejnovějších)."""
        limit = int_param(request.args.get('limit', 200), 200, 1, 500)
        try:
            conn = state._get_conn()
            conn.row_factory = state.sqlite3.Row
            rows = conn.execute("""
                SELECT aa.id, aa.action_id, aa.event, aa.actor, aa.at, aa.risk_score,
                       a.command, a.node, a.cluster, a.status as action_status
                FROM action_audit aa
                LEFT JOIN actions a ON a.id = aa.action_id
                ORDER BY aa.at DESC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
            return jsonify({"status": "ok", "audit": [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"audit_log error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/v1/actions/<int:aid>/review', methods=['POST'])
    @requires_auth
    def api_v1_action_review(aid):
        """Mark a dry-run action as human-reviewed (no execution)."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "reply": "⛔ Admin only."}), 403
        ok = state.mark_action_reviewed(aid, g.username)
        if ok:
            service.log_event("action_review", f"Action {aid} marked reviewed", user=g.username)
            return jsonify({"status": "ok"})
        return jsonify({"status": "error", "reply": "Action not pending or not found."}), 404

    @bp.route('/api/v1/actions/<int:aid>/delete', methods=['POST'])
    @requires_auth
    def api_v1_action_delete(aid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "reply": "⛔ Admin only."}), 403
        ok = state.delete_action(aid)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/v1/actions/<int:aid>/execute', methods=['POST'])
    @requires_auth
    def api_v1_action_execute(aid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "reply": "⛔ Admin only."}), 403
        action = state.get_action(aid)
        if not action:
            return jsonify({"status": "error", "reply": "Action not found."}), 404
        state.approve_action_mode(aid)  # lift dry_run guard before executing
        ok, out = actions.run_ssh_command_real(action['cluster'], action['command'], action_id=aid)
        if ok:
            state.update_action_status(aid, "executed", output=out, executed_by=g.username)
            state.log_action_event(aid, "executed", actor=g.username)
            service.log_event("action_execute", f"Action {aid} executed by {g.username}")
            return jsonify({"status": "ok", "output": out})
        state.update_action_status(aid, "failed", output=out, executed_by=g.username)
        return jsonify({"status": "error", "output": out})

    @bp.route('/api/v1/actions/<int:aid>/update-command', methods=['POST'])
    @requires_auth
    def api_v1_action_update_cmd(aid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        data = request.get_json(silent=True) or {}
        new_cmd = (data.get('command') or '').strip()
        if not new_cmd:
            return jsonify({"status": "error", "reply": "Command required."}), 400
        ok = state.update_action_command(aid, new_cmd, updated_by=g.username)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/v1/allowed-commands', methods=['GET'])
    @requires_auth
    def api_v1_allowed_cmds_list():
        return jsonify({"status": "ok", "rules": state.list_allowed_commands()})

    @bp.route('/api/v1/allowed-commands', methods=['POST'])
    @requires_auth
    def api_v1_allowed_cmds_add():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        data = request.get_json(silent=True) or {}
        pattern = (data.get('pattern') or '').strip()
        if not pattern:
            return jsonify({"status": "error", "reply": "Pattern required."}), 400
        rid = state.add_allowed_command(
            pattern=pattern,
            description=data.get('description', ''),
            auto_execute=bool(data.get('auto_execute', False)),
            risk_max=int(data.get('risk_max') or 30),
            note=data.get('note', ''),
        )
        return jsonify({"status": "ok", "id": rid})

    @bp.route('/api/v1/allowed-commands/<int:rid>', methods=['PUT'])
    @requires_auth
    def api_v1_allowed_cmds_update(rid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        data = request.get_json(silent=True) or {}
        ok = state.update_allowed_command(rid, **{
            k: v for k, v in data.items()
            if k in ('pattern', 'description', 'auto_execute', 'risk_max', 'note')
        })
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/v1/allowed-commands/<int:rid>', methods=['DELETE'])
    @requires_auth
    def api_v1_allowed_cmds_del(rid):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        ok = state.delete_allowed_command(rid)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/ssh/execute', methods=['POST'])
    @requires_auth
    def api_ssh_execute():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden — jen admin a superadmin"}), 403
        d = request.json or {}
        host = (d.get('host') or '').strip()
        command = (d.get('command') or '').strip()
        if not host or not command:
            return jsonify({"error": "host a command jsou povinné"}), 400
        if not _valid_host(host):
            return jsonify({"error": "Neplatný formát hostname"}), 400
        # 045: Multi-command support — split by ';', check each sub-command
        from sentinel import safety as _safety
        sub_cmds = [c.strip() for c in command.split(';') if c.strip()]
        if not sub_cmds:
            return jsonify({"error": "Prázdný příkaz"}), 400
        for sc in sub_cmds:
            if _safety.is_blocked(sc):
                return jsonify({"error": f"Příkaz zablokován safety klasifikátorem: {sc}"}), 403
            if not state.check_command_allowed(sc):
                return jsonify({"error": f"Příkaz není v allowlistu: {sc}"}), 403
        try:
            from sentinel import actions as _actions
            ok, output = _actions.run_ssh_command_real(host, command)
            state.log_ssh_execute(host, command, g.username, ok, output)
            logger.info(f"[ssh_execute] {g.username} → {host}: {command} → {'OK' if ok else 'FAIL'}")
            return jsonify({"status": "ok" if ok else "error", "output": output, "host": host, "command": command})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/v1/allowed-commands/export', methods=['GET'])
    @requires_auth
    def api_allowed_cmds_export():
        """048: Stáhni allowed-commands jako JSON soubor."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        rules = state.list_allowed_commands()
        # Strip auto-generated fields
        export = [{"pattern": r["pattern"], "description": r.get("description", ""),
                   "auto_execute": r.get("auto_execute", False),
                   "risk_max": r.get("risk_max", 30), "note": r.get("note", "")}
                  for r in rules]
        return Response(json.dumps(export, indent=2, ensure_ascii=False),
                        mimetype='application/json',
                        headers={'Content-Disposition': 'attachment; filename=allowed_commands.json'})

    @bp.route('/api/v1/allowed-commands/import', methods=['POST'])
    @requires_auth
    def api_allowed_cmds_import():
        """048: Nahraj allowed-commands z JSON. Mode: merge (default) nebo replace."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error"}), 403
        mode = request.args.get('mode', 'merge')
        try:
            rules = request.get_json(silent=True) or []
            if not isinstance(rules, list):
                return jsonify({"status": "error", "message": "Očekáváno JSON pole"}), 400
            if mode == 'replace':
                # Smaž stávající a importuj nové
                existing = state.list_allowed_commands()
                for r in existing:
                    state.delete_allowed_command(r['id'])
            added = 0
            for r in rules:
                pattern = str(r.get('pattern', '')).strip()
                if not pattern:
                    continue
                state.add_allowed_command(
                    pattern=pattern,
                    description=str(r.get('description', ''))[:200],
                    auto_execute=bool(r.get('auto_execute', False)),
                    risk_max=int(r.get('risk_max', 30)),
                    note=str(r.get('note', ''))[:200],
                )
                added += 1
            service.log_event("allowed_cmds_import", f"Importováno {added} pravidel (mode={mode})", user=g.username)
            return jsonify({"status": "ok", "imported": added, "mode": mode})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/ssh/stream', methods=['POST'])
    @requires_auth
    def api_ssh_stream():
        """SSE streaming SSH execute — výstup přichází průběžně místo jednoho blokujícího čekání."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden — jen admin a superadmin"}), 403
        d = request.json or {}
        host = (d.get('host') or '').strip()
        command = (d.get('command') or '').strip()
        if not host or not command:
            return jsonify({"error": "host a command jsou povinné"}), 400
        if not _valid_host(host):
            return jsonify({"error": "Neplatný formát hostname"}), 400

        from sentinel import safety as _safety
        for sc in [c.strip() for c in command.split(';') if c.strip()]:
            if _safety.is_blocked(sc):
                return jsonify({"error": f"Příkaz zablokován: {sc}"}), 403
            if not state.check_command_allowed(sc):
                return jsonify({"error": f"Příkaz není v allowlistu: {sc}"}), 403

        def _generate():
            ssh_user = getattr(config, 'SSH_USER', 'root')
            ssh_key = getattr(config, 'SSH_KEY_PATH', '')
            jump = getattr(config, 'SSH_JUMP_HOST', '')

            from ..ssh_utils import build_ssh_cmd
            ssh_cmd = build_ssh_cmd(host, command, user=ssh_user, key=ssh_key, jump=jump)

            yield f"data: {json.dumps({'line': f'$ {command}', 'type': 'cmd'})}\n\n"
            try:
                proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True)
                for line in proc.stdout:
                    yield f"data: {json.dumps({'line': line.rstrip(), 'type': 'out'})}\n\n"
                proc.wait()
                rc = proc.returncode
                state.log_ssh_execute(host, command, g.username, rc == 0, f"stream (rc={rc})")
                yield f"data: {json.dumps({'done': True, 'rc': rc})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'line': str(e), 'type': 'err', 'done': True})}\n\n"

        return Response(_generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @bp.route('/api/ansible/run', methods=['POST'])
    @requires_auth
    def api_ansible_run():
        """181: Spustí ansible-playbook na vybraném hostu."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        host     = (d.get('host') or '').strip()
        playbook = (d.get('playbook') or '').strip()
        extra    = (d.get('extra_vars') or '').strip()
        if not host or not playbook:
            return jsonify({"error": "host a playbook jsou povinné"}), 400
        # Sanitize playbook path (pouze alfanumerika, /, _, -, .)
        import re as _re
        if not _re.match(r'^[\w./\-]+\.ya?ml$', playbook):
            return jsonify({"error": "Neplatná cesta k playbooku"}), 400

        ssh_user = getattr(config, 'SSH_USER', 'root')
        ssh_key  = getattr(config, 'SSH_KEY_PATH', '')
        cmd_parts = ['ansible-playbook', playbook, '-i', f'{host},', '-u', ssh_user]
        if ssh_key:
            cmd_parts += ['--private-key', ssh_key]
        if extra:
            cmd_parts += ['--extra-vars', extra]
        cmd_parts += ['--one-line']
        cmd = ' '.join(f'"{p}"' if ' ' in p else p for p in cmd_parts)
        try:
            ok, output = _actions.run_ssh_command_real('localhost', cmd)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        state.log_ssh_execute(host, f'ansible-playbook {playbook}', g.username, ok, output)
        service.log_event("ansible_run", f"host={host} playbook={playbook}", user=g.username)
        return jsonify({"status": "ok" if ok else "error", "host": host, "playbook": playbook, "output": output})

    @bp.route('/api/ssh/batch', methods=['POST'])
    @requires_auth
    def api_ssh_batch():
        """145: Spustí SSH příkaz paralelně na více hostech. Vrátí výsledky per host."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden — jen admin a superadmin"}), 403
        d = request.json or {}
        hosts   = [h.strip() for h in (d.get('hosts') or []) if str(h).strip()]
        command = (d.get('command') or '').strip()
        if not hosts or not command:
            return jsonify({"error": "hosts[] a command jsou povinné"}), 400
        if len(hosts) > 50:
            return jsonify({"error": "Max 50 hostů najednou"}), 400
        bad = [h for h in hosts if not _valid_host(h)]
        if bad:
            return jsonify({"error": f"Neplatný formát hostname: {', '.join(bad[:5])}"}), 400

        from sentinel import safety as _safety
        for sc in [c.strip() for c in command.split(';') if c.strip()]:
            if _safety.is_blocked(sc):
                return jsonify({"error": f"Příkaz zablokován: {sc}"}), 403
            if not state.check_command_allowed(sc):
                return jsonify({"error": f"Příkaz není v allowlistu: {sc}"}), 403

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from sentinel import actions as _actions

        def _run_one(host):
            # 297: Per-host timeout 15s v batch (default 30s je příliš dlouhý při 50 hostech)
            ok, out = _actions.run_ssh_command_real(host, command, timeout=15)
            state.log_ssh_execute(host, command, g.username, ok, out)
            return {"host": host, "ok": ok, "output": out}

        results = []
        with ThreadPoolExecutor(max_workers=min(len(hosts), 10)) as pool:
            futures = {pool.submit(_run_one, h): h for h in hosts}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append({"host": futures[fut], "ok": False, "output": str(e)})

        service.log_event("batch_ssh", f"hosts={len(hosts)} cmd={command}", user=g.username)
        return jsonify({"status": "ok", "results": results, "command": command})

    return bp

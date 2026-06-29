import re
import subprocess
import json
import fnmatch
from . import state
from . import utils
from . import config
from . import safety


def _pre_validate_ssh_command(command: str) -> bool:
    """244: Ověří SSH příkaz oproti DB allowlistu před odesláním. Vrátí False pokud není povolen."""
    try:
        allowed = state.list_allowed_commands()  # [{command, ...}]
        if not allowed:
            return True  # Prázdný allowlist = vše povoleno (zachová zpětnou kompatibilitu)
        cmd = command.strip()
        for entry in allowed:
            pattern = (entry.get('command') or '').strip()
            if not pattern:
                continue
            if fnmatch.fnmatch(cmd, pattern) or cmd == pattern or cmd.startswith(pattern.rstrip('*')):
                return True
        return False
    except Exception:
        return True  # Při chybě DB neblokuj (fail-open pro zachování funkce)

# Built-in type-specific remediation prompts (overridable via config.yaml `prompts:`)
_REMEDIATION_PROMPTS = {
    'systemd': (
        "Linux sysadmin. Node '{node}' reports a failed systemd service.\n"
        "Message: {raw_line}\n"
        "Identify the failed service(s) and propose a restart.\n"
        'Output ONLY valid JSON, no markdown: {"description": "Restart failed service", "command": "systemctl restart <name.service>"}'
    ),
    'zfs': (
        "Linux sysadmin. Node '{node}' reports a ZFS pool issue.\n"
        "Message: {raw_line}\n"
        "Propose a safe diagnostic command (zpool status, scrub, or clear).\n"
        'Output ONLY valid JSON, no markdown: {"description": "...", "command": "zpool status"}'
    ),
    'mount': (
        "Linux sysadmin. Node '{node}' reports a mount/filesystem issue.\n"
        "Message: {raw_line}\n"
        "Propose a safe remount or fsck command.\n"
        'Output ONLY valid JSON, no markdown: {"description": "...", "command": "mount -a"}'
    ),
    'update': (
        "Linux sysadmin. Node '{node}' has pending system updates.\n"
        "Message: {raw_line}\n"
        "Propose a safe non-interactive upgrade command.\n"
        'Output ONLY valid JSON, no markdown: {"description": "Apply pending system updates", "command": "apt-get upgrade -y"}'
    ),
}

def _classify_issue(key: str, data: dict):
    """Return issue type ('systemd', 'zfs', 'mount', 'update') or None."""
    plugin = (data.get('plugin_name') or data.get('plugin', '')).lower()
    msg = (data.get('last_line') or data.get('message', '')).lower()

    if key.startswith('SERVICE_FAILED|'):
        return 'systemd'
    if key.startswith('ZFS_ISSUE|'):
        return 'zfs'
    if 'systemd' in plugin or 'agent_systemd' in plugin:
        return 'systemd'
    if 'mount' in plugin or 'mount' in msg or 'storage' in plugin:
        return 'mount'
    if 'update' in plugin or 'upgrade' in plugin or plugin == 'ssh_update_check':
        return 'update'
    return None

def _extract_service_names(key: str, data: dict) -> list:
    """Extract service name(s) from key or message for systemd issues."""
    if key.startswith('SERVICE_FAILED|'):
        parts = key.split('|')
        if len(parts) >= 3 and parts[2].endswith('.service'):
            return [parts[2]]
    msg = data.get('last_line') or data.get('message', '')
    # Format: "Failed units detected: service1.service, service2.service"
    m = re.search(r'Failed units detected:\s*(.+)', msg)
    if m:
        raw = m.group(1)
        services = [s.strip() for s in raw.split(',') if s.strip().endswith('.service')]
        if services:
            return services
    # Fallback: bullet-separated "● service.service"
    return re.findall(r'[●○•]\s*([\w@.\-]+\.service)', msg)

def _create_action_direct(key, cluster, node, command, description, raw_line=""):
    """Create pending action without AI — for deterministic proposals."""
    risk_score, risk_reasons = safety.classify(command)
    action_id = state.create_pending_action(
        key, cluster, node, command, description,
        mode="dry_run", risk_score=risk_score, risk_reasons=risk_reasons,
        raw_line=raw_line
    )
    if action_id:
        preview_cmd, preview_desc = safety.simulate(command)
        state.set_dry_run_output(
            action_id,
            f"[SIMULATION] {preview_desc}\n$ {preview_cmd}" if preview_cmd else f"[SIMULATION] {preview_desc}"
        )
        state.frontend_queue.put_nowait({
            "type": "new_action",
            "text": f"Auto-proposed [{cluster}] {node}: {command}"
        })
        utils.send_webhook({"event": "ai_proposal", "node": node, "command": command,
                            "risk_score": risk_score, "description": description})
        utils.log_message(f"Auto-remediation proposal #{action_id}: {command} on {node}")
    return action_id

def maybe_suggest_remediation(key: str, data: dict):
    """Called on new issue — creates a pending action proposal if issue type is actionable."""
    if not getattr(config, 'AUTO_REMEDIATION_ENABLED', True):
        return

    issue_type = _classify_issue(key, data)
    if not issue_type:
        return

    if state.has_pending_action_for_key(key):
        return  # Already has a pending proposal — skip

    node = data.get('host', 'unknown')
    # Find cluster from infrastructure_mapping; fall back to hostname for direct SSH
    cluster = data.get('cluster', 'UNKNOWN')
    if cluster == 'UNKNOWN':
        cluster = _find_cluster_for_host(node) or node
    raw_line = data.get('last_line') or data.get('message', '')

    if issue_type == 'systemd':
        services = _extract_service_names(key, data)
        if services:
            cmd = 'systemctl restart ' + ' '.join(services)
            desc = f"Restart failed service{'s' if len(services) > 1 else ''}: {', '.join(services)}"
            _create_action_direct(key, cluster, node, cmd, desc, raw_line)
        # else: can't extract service name — skip; AI would just produce a placeholder
    elif issue_type in ('zfs', 'mount', 'update'):
        suggest_remediation(cluster, issue_type, node, raw_line, key)

def _find_cluster_for_host(hostname: str) -> str:
    """Look up cluster name for a hostname in infrastructure_mapping."""
    for m in getattr(config, 'INFRASTRUCTURE_MAPPING', []):
        if hostname in m.get('hosts', []) or m.get('mgmt_node') == hostname:
            return m.get('name', '')
    return ''

def suggest_remediation(cluster, issue_type, node, raw_line, problem_key):
    # Type-specific prompt: config override → built-in default → generic
    prompt_key = f"remediation_{issue_type}" if issue_type else None
    if prompt_key and prompt_key in config.PROMPTS:
        template = config.PROMPTS[prompt_key]
    elif issue_type in _REMEDIATION_PROMPTS:
        template = _REMEDIATION_PROMPTS[issue_type]
    else:
        template = config.PROMPTS.get(
            "remediation",
            "Linux sysadmin. Node '{node}' issue: {raw_line}\n"
            'Output ONLY valid JSON: {"description": "...", "command": "..."}'
        )

    prompt = template.replace("{cluster}", str(cluster)) \
                     .replace("{node}", str(node)) \
                     .replace("{raw_line}", str(raw_line))

    context = {
        "source": "remediation_request",
        "cluster": cluster,
        "node": node,
        "problem_key": problem_key,
        "raw_line": raw_line
    }

    state.enqueue_message(prompt, channel="actions", msg_type="ai_request", context=context)

def process_ai_proposal(context, ai_response):
    try:
        clean_json = ai_response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        
        command = data.get("command", "N/A")
        description = data.get("description", "AI Suggested Fix")

        cluster = context["cluster"]
        node = context["node"]
        key = context["problem_key"]
        raw_line = context.get("raw_line", "")

        # Reject unfilled template placeholders like <service_name>
        if re.search(r'<[a-zA-Z_][^>]*>', command):
            utils.log_message(f"AI returned template placeholder, skipping: {command}")
            return

        if command and command != "N/A":
            risk_score, risk_reasons = safety.classify(command)
            action_id = state.create_pending_action(
                key, cluster, node, command, description,
                mode="dry_run",
                risk_score=risk_score,
                risk_reasons=risk_reasons,
                raw_line=raw_line,
            )

            if action_id:
                preview_cmd, preview_desc = safety.simulate(command)
                if preview_cmd:
                    state.set_dry_run_output(
                        action_id,
                        f"[SIMULATION] {preview_desc}\n$ {preview_cmd}",
                    )
                else:
                    state.set_dry_run_output(action_id, f"[SIMULATION] {preview_desc}")

                risk_label = "🟢" if risk_score < safety.THRESHOLD_REVIEW else (
                    "🟡" if risk_score < safety.THRESHOLD_BLOCK else "🔴")
                reasons_html = ("<br><b>Risk:</b> " + ", ".join(risk_reasons)) if risk_reasons else ""
                msg = (
                    f"💡 <b>AI Proposal Ready (DRY RUN):</b><br>"
                    f"<b>Node:</b> {node} ({cluster})<br>"
                    f"<b>Action:</b> <code>{command}</code><br>"
                    f"<b>Reason:</b> {description}<br>"
                    f"<b>Safety:</b> {risk_label} score {risk_score}/100{reasons_html}<br>"
                    f"<i>Dry-run only in this phase — no SSH execution.</i>"
                )
                utils.send_to_teams(msg, "actions")
                utils.send_webhook({"event": "ai_proposal", "node": node, "command": command,
                                    "risk_score": risk_score, "description": description})

                state.frontend_queue.put_nowait({
                    "type": "new_action",
                    "text": f"New Action [dry_run, risk={risk_score}]: {command} ({node})"
                })

                # Auto-execute if command matches an allowlist rule with auto_execute=True
                allowed_rule = state.check_command_allowed(command)
                if (allowed_rule and allowed_rule.get('auto_execute') and
                        risk_score <= allowed_rule.get('risk_max', 30)):
                    ok, out = run_ssh_command_real(cluster, command, action_id=action_id)
                    rule_desc = allowed_rule.get('description') or allowed_rule.get('pattern', '')
                    if ok:
                        state.update_action_status(action_id, "executed", output=out, executed_by="ai_auto")
                        state.log_action_event(action_id, "auto_executed", actor="ai_auto",
                                               details={"rule_id": allowed_rule['id'],
                                                        "rule_pattern": allowed_rule['pattern']})
                        utils.send_to_teams(
                            f"⚡ <b>AUTO-EXECUTED</b> (rule: {rule_desc})<br>"
                            f"<code>{command}</code><br>Output: {out}", "actions")
                    else:
                        state.update_action_status(action_id, "failed", output=out, executed_by="ai_auto")
                        utils.log_message(f"Auto-execute failed for action {action_id}: {out}")
        else:
            utils.log_message(f"AI failed to generate valid command: {ai_response}")

    except json.JSONDecodeError:
        utils.log_message(f"Failed to parse AI JSON: {ai_response}")
    except Exception as e:
        utils.log_message(f"Error processing AI proposal: {e}")

def run_ssh_command_real(cluster, command, action_id=None, timeout: int = 30):
    mgmt_node = "localhost"
    found = False

    for mapping in getattr(config, "INFRASTRUCTURE_MAPPING", []):
        if mapping.get("name") == cluster:
            mgmt_node = mapping.get("mgmt_node", "localhost")
            found = True
            break

    # No cluster mapping — use the cluster value as a direct SSH hostname
    if not found and cluster not in ("UNKNOWN", "localhost", "manual", ""):
        mgmt_node = cluster

    # Per-action dry-run guard: if the stored action is mode='dry_run' OR the
    # safety classifier marks the command as block-worthy, never SSH-execute.
    forced_dry_run = False
    dry_run_cause = ""
    if action_id is not None:
        act = state.get_action(action_id)
        if act and act.get("mode") == "dry_run":
            forced_dry_run = True
            dry_run_cause = "action.mode=dry_run"
    if safety.is_blocked(command):
        forced_dry_run = True
        dry_run_cause = (dry_run_cause + "; " if dry_run_cause else "") + "safety.is_blocked"

    global_dry_run = bool(getattr(config, "ARGS", {}).get("DEBUG_MODE"))

    if forced_dry_run or global_dry_run:
        cause = dry_run_cause or "config.DEBUG_MODE"
        dry_run_output = f"[DRY RUN: {cause}] Would execute on {mgmt_node}: {command}"
        utils.log_message(f"[DRY RUN] ({cause}) {mgmt_node}: {command}")
        dry_run_msg = (
            f"🛡️ <b>DRY RUN EXECUTION</b><br>"
            f"<b>Mgmt Node:</b> {mgmt_node}<br>"
            f"<b>Command:</b> <code>{command}</code><br>"
            f"<b>Cause:</b> {cause}<br>"
            f"<i>Command was NOT executed (Safety Mode).</i>"
        )
        utils.send_to_teams(dry_run_msg, "actions")
        if action_id is not None:
            state.set_dry_run_output(action_id, dry_run_output)
            state.log_action_event(action_id, "dry_run_completed",
                                   details={"cause": cause, "mgmt_node": mgmt_node})
        return True, dry_run_output

    # 244: Pre-validace příkazu proti allowlistu (extra vrstva před SSH)
    if not _pre_validate_ssh_command(command):
        err = f"[BLOCKED-244] Command not in allowlist: {command[:80]}"
        utils.log_message(err)
        return False, err

    utils.log_message(f"Executing via {mgmt_node}: {command}")
    try:
        from .ssh_utils import build_ssh_cmd
        ssh_cmd = build_ssh_cmd(mgmt_node, command)
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)

        if result.returncode == 0:
            out = f"STDOUT: {result.stdout.strip()}"
            if action_id is not None:
                state.log_action_event(action_id, "executed",
                                       details={"mgmt_node": mgmt_node, "rc": 0})
            return True, out
        else:
            err = f"STDERR: {result.stderr.strip()}"
            if action_id is not None:
                state.log_action_event(action_id, "failed",
                                       details={"mgmt_node": mgmt_node, "rc": result.returncode})
            return False, err

    except subprocess.TimeoutExpired:
        if action_id is not None:
            state.log_action_event(action_id, "failed", details={"cause": "ssh_timeout"})
        return False, "SSH Timeout (30s)"
    except Exception as e:
        if action_id is not None:
            state.log_action_event(action_id, "failed", details={"cause": "ssh_exception", "err": str(e)})
        return False, f"SSH Exception: {str(e)}"

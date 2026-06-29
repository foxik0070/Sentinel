import base64
import html
import logging
import threading
import json
import time
import sqlite3
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, g, Response
from collections import deque
from ..auth import requires_auth, int_param
from .. import state, config

logger = logging.getLogger("sentinel.chat")
_joke_recent_hosts: deque = deque(maxlen=5)


def create_blueprint(service):
    bp = Blueprint('issues', __name__)

    def generate_modal_issues_html(target_channel, include_snoozed=False):
        """Generuje čiste HTML pro dedikované modální okno podle okruhu."""
        all_active = state.get_active_issues(include_snoozed=include_snoozed)
        is_super = (g.user_role == 'superadmin')
        _tag_map = state.get_tag_counts()  # {kb64: [tag, ...]}

        filtered = []
        for i in all_active:
            if i.get('key') in service.ignored_issues:
                continue

            key_str = i.get('key', '')
            is_agent = key_str.startswith('AGENT|')

            # Bezpečné zjištění kanálu z databáze nebo klíče
            ch = i.get('channel_type', '').lower()
            if not ch and is_agent:
                # Fallback parsování pokud chybí pole channel_type v kořenu objektu
                if any(x in key_str for x in ['agent_root_monitor', 'agent_security_root_monitor']): ch = 'root'
                elif any(x in key_str for x in ['agent_port_security', 'agent_vulnerability_scan', 'agent_fail2ban']): ch = 'security'
                else: ch = 'agent'

            if ch == target_channel:
                filtered.append(i)
            elif target_channel == 'infra' and not is_agent and ch not in ['security', 'root', 'agent']:
                filtered.append(i)

        # Apply user's saved drag order
        saved_order = state.get_issue_user_order(g.username, target_channel)
        if saved_order:
            order_map = {k: i for i, k in enumerate(saved_order)}
            filtered.sort(key=lambda x: order_map.get(
                base64.b64encode(x['key'].encode()).decode(), 99999))

        if target_channel == 'root' and g.user_role not in ('admin', 'superadmin'):
            return "<div style='color:var(--error); padding:15px;'>⛔ Přístup odepřen. Tuto sekci může vidět pouze Admin/Superadmin.</div>"

        if not filtered:
            return "<div style='color:var(--success); text-align:center; padding:30px; font-weight:bold;'><i class='fa-solid fa-check-circle' style='font-size:2em; display:block; margin-bottom:10px;'></i> V tomto okruhu je aktuálně čisto.</div>"

        import json as _json
        _LABEL_COLORS = ['', '#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#a855f7', '#ec4899']

        def _render_issue_card(i):
            kb64 = base64.b64encode(i['key'].encode()).decode()
            ts = (i.get('last_seen') or 'N/A').replace('T', ' ').split('.')[0]
            plugin_origin = (i.get('plugin_name') or i.get('channel_type') or '?').upper()
            safe_host = html.escape(i.get('host') or '?')
            raw_msg = i.get('last_line') or ''
            safe_msg = html.escape(raw_msg)
            safe_msg_short = html.escape(raw_msg[:120] + ('…' if len(raw_msg) > 120 else ''))
            safe_msg_title = safe_msg.replace("'", "&#39;")
            share_text = f"[{ts}] [{plugin_origin}] {safe_host}: {safe_msg}".replace("'", "\\'")
            occ = i.get('occurrence_count', 1) or 1
            occ_badge = (
                f"<span style='background:#555; color:#fff; border-radius:10px; font-size:0.7em; padding:1px 5px; margin-left:4px;'>×{occ}</span>"
            ) if occ > 1 else ""
            # Závislosti
            deps = _json.loads(i.get('depends_on') or '[]')
            dep_badge = ""
            if deps:
                dep_badge = f"<span title='Závisí na {len(deps)} issue(s)' style='background:rgba(253,126,20,.2);color:#fd7e14;border:1px solid rgba(253,126,20,.4);border-radius:10px;font-size:.7em;padding:1px 6px;margin-left:4px;cursor:pointer;' onclick=\"_openDependsModal('{kb64}')\"><i class='fa-solid fa-link'></i> {len(deps)}</span>"
            dep_btn = f"<i class='fa-solid fa-link' title='Závislosti' style='cursor:pointer;color:var(--text-muted);font-size:1.05em;margin-right:12px;transition:color .2s;' onmouseover=\"this.style.color='#fd7e14'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"_openDependsModal('{kb64}')\"></i>" if g.user_role in ['admin','superadmin'] else ""
            # Tags
            tags_html = ""
            issue_tags = _tag_map.get(kb64, [])
            if issue_tags:
                tags_html = "<div style='margin-top:4px; display:flex; flex-wrap:wrap; gap:3px;'>" + "".join(
                    f"<span onclick=\"_filterByTag('{html.escape(t)}')\" style='background:rgba(0,120,212,0.2); color:#a3cfff; border:1px solid rgba(0,120,212,0.3); border-radius:10px; font-size:0.72em; padding:1px 7px; cursor:pointer;'>#{html.escape(t)}</span>"
                    for t in issue_tags
                ) + "</div>"
            fix_btn = ""
            ssh_btn_modal = ""
            if g.user_role in ['admin', 'superadmin', 'viewer']:
                b64_payload2 = base64.b64encode(f"{i.get('host','?')}: {i.get('last_line','')}".encode()).decode()
                fix_btn = f"<i class='fa-solid fa-wand-magic-sparkles' title='Autofix' style='cursor:pointer; color:#a855f7; font-size:1.1em; margin-right:12px;' onclick=\"openAutofixModal('{b64_payload2}'); closeIssuesModal();\"></i>"
            if g.user_role in ['admin', 'superadmin']:
                _host = html.escape(i.get('host', ''))
                if _host:
                    ssh_btn_modal = f"<i class='fa-solid fa-terminal' title='SSH na {_host}' style='cursor:pointer; color:var(--text-muted); font-size:1.05em; margin-right:12px; transition:color 0.2s;' onmouseover=\"this.style.color='var(--accent)'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"closeIssuesModal(); openSshModal('{_host}')\"></i>"
            tag_btn = (
                f"<i class='fa-solid fa-tag' title='Přidat tag' style='cursor:pointer; color:var(--text-muted); font-size:1.05em; margin-right:12px; transition:color 0.2s;' "
                f"onmouseover=\"this.style.color='var(--accent)'\" onmouseout=\"this.style.color='var(--text-muted)'\" "
                f"onclick=\"_openTagModal('{kb64}')\"></i>"
            ) if g.user_role in ['admin', 'superadmin'] else ""
            ignore_btn = f"<i class='fa-solid fa-eye-slash' title='Ignorovat' style='cursor:pointer; color:var(--text-muted); font-size:1.1em; margin-right:12px;' onclick=\"triggerAction('ignore_key {kb64}');setTimeout(()=>refreshModalIssuesContent(false),300);\"></i>" if g.user_role in ['admin','superadmin'] else ""
            delete_btn = f"<i class='fa-solid fa-trash' title='Smazat' style='cursor:pointer; color:var(--error); font-size:1.1em;' onclick=\"triggerAction('delete_key {kb64}');setTimeout(()=>refreshModalIssuesContent(false),300);\"></i>" if g.user_role in ['admin','superadmin'] else ""
            fp_btn = f"<i class='fa-solid fa-ban' title='Označit jako false positive (potlačit podobné)' style='cursor:pointer; color:var(--text-muted); font-size:1.05em; margin-right:12px; transition:color .2s;' onmouseover=\"this.style.color='#fd7e14'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"_markFalsePositive('{kb64}')\"></i>" if g.user_role in ['admin','superadmin'] else ""
            similar_btn = f"<i class='fa-solid fa-magnifying-glass' title='Podobné incidenty' style='cursor:pointer; color:var(--text-muted); font-size:1.05em; margin-right:12px; transition:color .2s;' onmouseover=\"this.style.color='var(--accent)'\" onmouseout=\"this.style.color='var(--text-muted)'\" onclick=\"_openSimilarModal('{kb64}')\"></i>"
            # Rozbalovací seznam všech záznamů per technologie (f2b/security a podobné)
            records_html = ""
            _recs = i.get('records') or []
            if _recs:
                _rows = "".join(
                    f"<tr><td style='padding:2px 8px;font-family:monospace;'>{html.escape(str(r.get('ip','?')))}</td>"
                    f"<td style='padding:2px 8px;color:var(--text-muted);'>{html.escape(str(r.get('type','')))}</td>"
                    f"<td style='padding:2px 8px;text-align:right;'>×{r.get('count',1)}</td></tr>"
                    for r in _recs[:300]
                )
                _more = (f"<div style='color:var(--text-muted);font-size:.72em;padding:3px 8px;'>+{len(_recs)-300} dalších…</div>"
                         if len(_recs) > 300 else "")
                records_html = (
                    "<details style='margin-top:6px;'>"
                    f"<summary style='cursor:pointer;color:var(--accent);font-size:.8em;'>📋 {len(_recs)} záznamů — {safe_host}</summary>"
                    "<div style='max-height:320px;overflow:auto;margin-top:4px;border:1px solid var(--border);border-radius:4px;'>"
                    f"<table style='width:100%;border-collapse:collapse;font-size:.78em;'>{_rows}</table>{_more}</div></details>"
                )
            # 136: Barevný štítek
            lc = i.get('label_color') or ''
            dot_style = f"background:{lc};" if lc else "background:rgba(255,255,255,.12);"
            if g.user_role in ('admin', 'superadmin'):
                picker_swatches = "".join(
                    f"<span onclick=\"_lcSet('{kb64}','{c}')\" title='{c or 'Bez barvy'}' "
                    f"style='display:inline-block;width:16px;height:16px;border-radius:50%;cursor:pointer;"
                    f"background:{c if c else 'rgba(255,255,255,.1)'};border:2px solid {('var(--accent)' if c==lc else 'transparent')};'></span>"
                    for c in _LABEL_COLORS
                )
                label_dot = (
                    f"<span id='lc-dot-{kb64}' title='Barevný štítek' onclick=\"_lcToggle('{kb64}')\" "
                    f"style='display:inline-block;width:12px;height:12px;border-radius:50%;flex-shrink:0;cursor:pointer;margin-right:4px;{dot_style}'></span>"
                    f"<div id='lc-picker-{kb64}' style='display:none;position:absolute;z-index:50;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:6px 8px;display:none;gap:4px;align-items:center;box-shadow:0 4px 16px rgba(0,0,0,.4);'>"
                    f"{picker_swatches}</div>"
                )
            else:
                label_dot = f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;flex-shrink:0;margin-right:4px;{dot_style}'></span>" if lc else ""

            inline_comment = ""
            if g.user_role in ('admin', 'superadmin'):
                inline_comment = (
                    f"<div id='ic-{kb64}' style='display:none;margin-top:6px;'>"
                    f"<div style='display:flex;gap:6px;'>"
                    f"<input type='text' id='ic-inp-{kb64}' placeholder='Rychlý komentář…' autocomplete='off' "
                    f"style='flex:1;padding:5px 8px;background:var(--input-bg);color:var(--text-main);border:1px solid var(--border);border-radius:4px;font-size:.82em;' "
                    f"onkeydown=\"if(event.key==='Enter')_icSubmit('{kb64}');if(event.key==='Escape')_icHide('{kb64}')\">"
                    f"<button onclick=\"_icSubmit('{kb64}')\" style='padding:4px 10px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.82em;'>Přidat</button>"
                    f"<button onclick=\"_icHide('{kb64}')\" style='padding:4px 8px;background:transparent;border:1px solid var(--border);color:var(--text-muted);border-radius:4px;cursor:pointer;font-size:.82em;'>✕</button>"
                    f"</div><div id='ic-msg-{kb64}' style='font-size:.75em;min-height:14px;margin-top:3px;'></div></div>"
                )
                comment_btn = (
                    f"<i class='fa-regular fa-comment' title='Přidat komentář (inline)' style='cursor:pointer;color:var(--text-muted);font-size:1.05em;margin-right:12px;transition:color .2s;' "
                    f"onmouseover=\"this.style.color='var(--accent)'\" onmouseout=\"this.style.color='var(--text-muted)'\" "
                    f"onclick=\"_icToggle('{kb64}')\"></i>"
                )
            else:
                comment_btn = ""
            _lc_border = f"border-left:4px solid {lc};" if lc else "border-left:4px solid var(--accent);"
            return f"""<div class="modal-content" data-issue-card="1" data-issue-key="{kb64}" style='position:relative;background:rgba(255,255,255,0.02); border:1px solid var(--border); {_lc_border} padding:10px 12px; margin-bottom:6px; border-radius:4px;'>
                    <div class='issue-row-inner'>
                        <span class='issue-drag-handle' title='Přetáhnout' style='cursor:grab; color:var(--text-muted); font-size:1.1em; flex-shrink:0; padding:0 4px 0 0; user-select:none;'>⠿</span>
                        {label_dot}
                        <div class='issue-content-area'>
                            <small style='color:var(--text-muted); display:block; margin-bottom:3px;'>🕒 {ts} | <b>{plugin_origin}</b>{occ_badge} <i class='fa-solid fa-bell' title='Nastavení notifikací' style='cursor:pointer;font-size:.8em;opacity:.5;margin-left:3px;' onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=.5" onclick="openNotifySettingsModal()"></i></small>
                            <span style='color:var(--text-main); font-size:0.93em;' title='{safe_msg_title}'><b>{safe_host}</b>: {safe_msg_short}</span>
                            {tags_html}{dep_badge}{records_html}
                        </div>
                        <div class='issue-actions'>
                            {comment_btn}{dep_btn}{fix_btn}{ssh_btn_modal}{tag_btn}{fp_btn}{similar_btn}<i class='fa-solid fa-share-nodes issue-action-secondary' title='Sdílet' style='cursor:pointer; color:var(--text-muted); font-size:1.1em; margin-right:12px;' onclick="shareIssue('{share_text}', this)"></i>
                            {ignore_btn}{delete_btn}
                        </div>
                    </div>
                    {inline_comment}
                </div>"""

        # Seskupení: kanál 'infra' (Incident Matrix) -> podle TECHNOLOGIE (cluster:
        # Karolina/Barbora/CS/INFRA...), ostatní kanály -> podle pluginu.
        # Skupiny s >= 3 položkami se sbalí do <details>.
        _GROUP_AT = 3
        from collections import defaultdict as _dd
        _by_tech = (target_channel == 'infra')
        groups = _dd(list)
        for i in filtered:
            gkey = (i.get('cluster') or i.get('host') or 'OSTATNÍ') if _by_tech else i.get('plugin_name', 'unknown')
            groups[gkey].append(i)

        html_out = ""
        for gkey, items in sorted(groups.items(), key=lambda x: -len(x[1])):
            cards_html = "".join(_render_issue_card(i) for i in items)
            if len(items) >= _GROUP_AT:
                _sub = sorted({(i.get('plugin_name', '?') if _by_tech else i.get('host', '?')) for i in items})[:6]
                sub = ", ".join(_sub)
                if len(items) > 6:
                    sub += f" +{len(items)-6}"
                _icon = "fa-server" if _by_tech else "fa-layer-group"
                _unit = "záznamů" if _by_tech else "serverů"
                html_out += f"""<details style='margin-bottom:10px;'>
                        <summary style='cursor:pointer; padding:8px 12px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:4px; font-size:0.88em; color:var(--accent); font-weight:700; user-select:none; list-style:none; display:flex; justify-content:space-between; align-items:center;'>
                            <span><i class='fa-solid {_icon}'></i> {html.escape((gkey or '?').upper())} <span style='color:var(--text-muted); font-weight:400;'>({len(items)} {_unit})</span></span>
                            <span style='color:var(--text-muted); font-size:0.82em; font-weight:400;'>{html.escape(sub)}</span>
                        </summary>
                        <div style='padding:8px 0 0 8px;'>{cards_html}</div>
                    </details>"""
            else:
                html_out += cards_html

        # Přidání smazání všech záznamů
        if target_channel == 'infra' and g.user_role in ['admin', 'superadmin']:
            html_out += f"<div style='margin-top:10px; text-align:right;'><span style='color:var(--text-muted); font-size:0.8em; cursor:pointer; text-decoration:underline;' onclick=\"triggerAction('delete_all_issues'); closeIssuesModal();\">smazat vše</span></div>"

        return html_out

    @bp.route('/api/modal_issues/<channel>')
    @requires_auth
    def get_modal_issues_html(channel):
        if channel not in ['agent', 'root', 'security', 'infra']:
            return jsonify({"html": "Invalid channel"}), 400
        include_snoozed = request.args.get('snoozed', '0') == '1'
        snoozed_count = state.get_snoozed_count()
        html_content = generate_modal_issues_html(channel, include_snoozed=include_snoozed)
        return jsonify({"html": html_content, "snoozed_count": snoozed_count})

    @bp.route('/api/issues/reorder', methods=['POST'])
    @requires_auth
    def api_issues_reorder():
        data = request.json or {}
        channel = data.get('channel', '')
        keys = data.get('order', [])
        if channel not in ['agent', 'root', 'security', 'infra'] or not isinstance(keys, list):
            return jsonify({"error": "Invalid input"}), 400
        # keys are base64-encoded — store as-is (they identify issues)
        state.set_issue_user_order(g.username, channel, keys)
        return jsonify({"status": "ok"})

    @bp.route('/api/issues/delete_all/<channel>', methods=['POST'])
    @requires_auth
    def api_issues_delete_all(channel):
        """Delete all active problems in the given channel category."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 403
        if channel not in ('agent', 'root', 'security', 'infra'):
            return jsonify({"status": "error", "message": "Invalid channel"}), 400
        try:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    c = conn.execute(
                        "SELECT key FROM problems WHERE LOWER(channel_type)=? AND status='active'",
                        (channel,)
                    )
                    keys = [r[0] for r in c.fetchall()]
                    conn.execute(
                        "DELETE FROM problems WHERE LOWER(channel_type)=? AND status='active'",
                        (channel,)
                    )
                    conn.execute(
                        "UPDATE actions SET status='resolved_auto' WHERE problem_key IN ({}) AND status='pending'".format(
                            ','.join('?' * len(keys))
                        ),
                        keys
                    ) if keys else None
                    conn.commit()
                finally:
                    conn.close()
            return jsonify({"status": "ok", "deleted": len(keys)})
        except Exception as e:
            logger.error(f"delete_all error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route('/api/issues/meta')
    @requires_auth
    def api_issues_meta():
        issues = state.get_active_issues(include_snoozed=True)
        channels = sorted({i.get('channel_type', '').upper() for i in issues if i.get('channel_type')})
        plugins  = sorted({i.get('plugin_name', '') for i in issues if i.get('plugin_name')})
        statuses = sorted({i.get('status', '') for i in issues if i.get('status')})
        return jsonify({"channels": channels, "plugins": plugins, "statuses": statuses, "total": len(issues)})

    @bp.route('/api/issues/snooze', methods=['POST'])
    @requires_auth
    def api_issues_snooze():
        if g.user_role not in ['admin', 'superadmin']:
            return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        key_b64 = data.get('key')
        hours = int(data.get('hours', 4))
        if not key_b64 or hours not in (1, 4, 24, 72):
            return jsonify({"error": "Invalid params"}), 400
        try:
            key = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        ok = state.snooze_problem(key, hours)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/unsnooze', methods=['POST'])
    @requires_auth
    def api_issues_unsnooze():
        if g.user_role not in ['admin', 'superadmin']:
            return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        key_b64 = data.get('key')
        if not key_b64:
            return jsonify({"error": "Missing key"}), 400
        try:
            key = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        ok = state.unsnooze_problem(key)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/comment_counts', methods=['GET'])
    @requires_auth
    def api_comment_counts():
        return jsonify(state.get_comment_counts())

    @bp.route('/api/issues/<key_b64>/comments', methods=['GET'])
    @requires_auth
    def api_get_comments(key_b64):
        try:
            key = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        return jsonify({"comments": state.get_issue_comments(key)})

    @bp.route('/api/issues/<key_b64>/comments', methods=['POST'])
    @requires_auth
    def api_add_comment(key_b64):
        try:
            key = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        text = (request.json or {}).get('text', '').strip()
        if not text:
            return jsonify({"error": "Empty comment"}), 400
        if len(text) > 2000:
            return jsonify({"error": "Comment too long"}), 400
        ok = state.add_issue_comment(key, g.username, text)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/comments/<int:comment_id>', methods=['DELETE'])
    @requires_auth
    def api_delete_comment(comment_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_issue_comment(comment_id)
        return jsonify({"status": "ok" if ok else "error"})

    # ── Issue Tags ──────────────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/tags', methods=['GET'])
    @requires_auth
    def api_get_tags(key_b64):
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        return jsonify({"tags": state.get_issue_tags(key)})

    @bp.route('/api/issues/<key_b64>/tags', methods=['POST'])
    @requires_auth
    def api_add_tag(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        tag = (request.json or {}).get('tag', '').strip()
        if not tag:
            return jsonify({"error": "Tag nesmí být prázdný"}), 400
        ok = state.add_issue_tag(key, tag, g.username)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/tags/<int:tag_id>', methods=['DELETE'])
    @requires_auth
    def api_delete_tag(tag_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_issue_tag(tag_id)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/tags/all', methods=['GET'])
    @requires_auth
    def api_all_tags():
        return jsonify({"tags": state.get_all_tags()})

    @bp.route('/api/issues/tags/counts', methods=['GET'])
    @requires_auth
    def api_tag_counts():
        return jsonify(state.get_tag_counts())

    # ── Issue Acknowledge ───────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/acknowledge', methods=['POST'])
    @requires_auth
    def api_acknowledge_issue(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        ok = state.acknowledge_issue(key, g.username)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/<key_b64>/unacknowledge', methods=['POST'])
    @requires_auth
    def api_unacknowledge_issue(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        ok = state.unacknowledge_issue(key)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/issues/<key_b64>/label_color', methods=['POST'])
    @requires_auth
    def api_set_label_color(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        color = (request.json or {}).get('color', '')
        # Allowed: empty string (clear) or 6-char hex color
        import re as _re
        if color and not _re.match(r'^#[0-9a-fA-F]{6}$', color):
            return jsonify({"error": "invalid color"}), 400
        try:
            conn = state._get_conn()
            conn.execute("UPDATE problems SET label_color=? WHERE key=?", (color or None, key))
            conn.commit(); conn.close()
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/issues/<key_b64>/timeline', methods=['GET'])
    @requires_auth
    def api_issue_timeline(key_b64):
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        return jsonify({"timeline": state.get_issue_timeline(key)})

    # ── Issue Severity ──────────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/severity', methods=['POST'])
    @requires_auth
    def api_set_severity(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        severity = (request.json or {}).get('severity', '').strip().lower()
        if severity not in ('low', 'medium', 'high', 'critical', ''):
            return jsonify({"error": "Neplatná hodnota severity"}), 400
        ok = state.set_issue_severity(key, severity)
        return jsonify({"status": "ok" if ok else "error"})

    # ── Issue Assignee ──────────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/assign', methods=['POST'])
    @requires_auth
    def api_assign_issue(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        username = (request.json or {}).get('username', '').strip() or None
        ok = state.assign_issue(key, username)
        return jsonify({"status": "ok" if ok else "error"})

    # ── Bulk Acknowledge ────────────────────────────────────────────────────

    @bp.route('/api/issues/bulk_acknowledge', methods=['POST'])
    @requires_auth
    def api_bulk_acknowledge():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        keys_b64 = (request.json or {}).get('keys', [])
        count = 0
        for kb64 in keys_b64:
            try:
                key = base64.b64decode(kb64).decode()
                if state.acknowledge_issue(key, g.username):
                    count += 1
            except Exception:
                pass
        return jsonify({"status": "ok", "acknowledged": count})

    @bp.route('/api/issues/bulk_severity', methods=['POST'])
    @requires_auth
    def api_bulk_severity():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        keys_b64 = data.get('keys', [])
        severity = data.get('severity', '').lower()
        if severity not in ('critical', 'high', 'medium', 'low', ''):
            return jsonify({"error": "invalid severity"}), 400
        count = 0
        try:
            conn = state._get_conn()
            for kb64 in keys_b64:
                try:
                    key = base64.b64decode(kb64).decode()
                    conn.execute("UPDATE problems SET severity=? WHERE key=?", (severity or None, key))
                    count += 1
                except Exception:
                    pass
            conn.commit(); conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"status": "ok", "updated": count})

    @bp.route('/api/issues/bulk_assign', methods=['POST'])
    @requires_auth
    def api_bulk_assign():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        data = request.json or {}
        keys_b64 = data.get('keys', [])
        username = data.get('username', '').strip()
        if not username:
            return jsonify({"error": "username required"}), 400
        count = 0
        try:
            conn = state._get_conn()
            for kb64 in keys_b64:
                try:
                    key = base64.b64decode(kb64).decode()
                    conn.execute("UPDATE problems SET assigned_to=? WHERE key=?", (username, key))
                    count += 1
                except Exception:
                    pass
            conn.commit(); conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"status": "ok", "assigned": count})

    # ── Issue Triage ────────────────────────────────────────────────────────

    @bp.route('/api/issues/triage', methods=['GET'])
    @requires_auth
    def api_issues_triage():
        return jsonify({"issues": state.get_triage_issues()})

    # ── Issue Merge ─────────────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/merge', methods=['POST'])
    @requires_auth
    def api_issue_merge(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: primary_key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        target_b64 = (request.json or {}).get('target_key_b64', '')
        try: linked_key = base64.b64decode(target_b64).decode()
        except Exception: return jsonify({"error": "bad target_key"}), 400
        ok = state.merge_issues(primary_key, linked_key, g.username)
        return jsonify({"status": "ok" if ok else "error"})

    # ── Issue Re-analyze ────────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/reanalyze', methods=['POST'])
    @requires_auth
    def api_issue_reanalyze(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try: key = base64.b64decode(key_b64).decode()
        except Exception: return jsonify({"error": "bad key"}), 400
        # Načíst issue
        try:
            conn = state._get_conn()
            row = conn.execute(
                "SELECT plugin_name, host, last_line, channel_type FROM problems WHERE key=?", (key,)
            ).fetchone()
            conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        if not row:
            return jsonify({"error": "Issue nenalezena"}), 404
        plugin, host, last_line, channel = row
        context = service.call_ai_knowledge_base(last_line or '')
        prompt_template = config.PROMPTS.get(channel or 'default', config.PROMPTS.get('default', '{line}'))
        prompt = prompt_template.replace('{line}', f"[{plugin}] {host}: {last_line or ''}")
        if context:
            prompt += f"\n\nKontext z knowledge base:\n{context}"
        try:
            reply = service.execute_ollama(prompt, num_ctx=2048, max_tokens=400)
            return jsonify({"reply": html.escape(reply).replace('\n', '<br>'),
                            "host": host, "plugin": plugin})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/issues/<key_b64>/delete', methods=['DELETE'])
    @requires_auth
    def api_issue_delete(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            k = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        state.delete_problem(k)
        service.log_event("issue_delete", f"Deleted issue: {k}", user=g.username)
        return jsonify({"status": "ok"})

    @bp.route('/api/issues/<key_b64>/ignore', methods=['POST'])
    @requires_auth
    def api_issue_ignore(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            k = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        service.ignored_issues.add(k)
        service.save_ignored_issues()
        return jsonify({"status": "ok"})

    @bp.route('/api/issues/<key_b64>/ignore', methods=['DELETE'])
    @requires_auth
    def api_issue_unignore(key_b64):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            k = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "Bad key"}), 400
        service.ignored_issues.discard(k)
        service.save_ignored_issues()
        return jsonify({"status": "ok"})

    @bp.route('/api/issues/history', methods=['GET'])
    @requires_auth
    def api_issues_history():
        q = request.args.get('q', '').strip()
        host = request.args.get('host', '').strip()
        channel = request.args.get('channel', '').strip()
        days = min(int(request.args.get('days', 30)), 365)
        limit = min(int(request.args.get('limit', 100)), 500)
        try:
            conn = state._get_conn()
            # Resolved issues from issue_history
            h_where = ["resolved_at > datetime('now', ?)"]
            h_params = [f'-{days} days']
            if q:
                h_where.append("(last_line LIKE ? OR key LIKE ? OR host LIKE ?)")
                h_params += [f'%{q}%', f'%{q}%', f'%{q}%']
            if host:
                h_where.append("host = ?")
                h_params.append(host)
            if channel:
                h_where.append("channel_type = ?")
                h_params.append(channel)

            # Active issues from problems — uses indexed columns
            p_where = ["last_seen > datetime('now', ?)"]
            p_params = [f'-{days} days']
            if q:
                p_where.append("(last_line LIKE ? OR key LIKE ? OR host LIKE ?)")
                p_params += [f'%{q}%', f'%{q}%', f'%{q}%']
            if host:
                p_where.append("host = ?")
                p_params.append(host)
            if channel:
                p_where.append("channel_type = ?")
                p_params.append(channel)

            sql = (
                f"SELECT key, channel_type, host, plugin_name, last_line, last_seen, resolved_at, 'resolved' AS issue_status "
                f"FROM issue_history WHERE {' AND '.join(h_where)} "
                f"UNION ALL "
                f"SELECT key, channel_type, host, plugin_name, last_line, last_seen, NULL, 'active' "
                f"FROM problems WHERE {' AND '.join(p_where)} "
                f"ORDER BY last_seen DESC LIMIT ?"
            )
            rows = conn.execute(sql, h_params + p_params + [limit]).fetchall()
            conn.close()
            cols = ['key', 'channel_type', 'host', 'plugin_name', 'last_line', 'last_seen', 'resolved_at', 'issue_status']
            return jsonify({"items": [dict(zip(cols, r)) for r in rows], "count": len(rows)})
        except Exception as e:
            return jsonify({"error": str(e), "items": []}), 500

    @bp.route('/api/snooze/rules', methods=['GET'])
    @requires_auth
    def api_snooze_rules_get():
        return jsonify({"rules": state.get_snooze_rules()})

    @bp.route('/api/snooze/rules', methods=['POST'])
    @requires_auth
    def api_snooze_rules_add():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.json or {}
        name = d.get('name', '').strip()
        channels = d.get('channels', '*').strip() or '*'
        days = d.get('days', '*').strip() or '*'
        hosts = d.get('hosts', '').strip() or None
        try:
            start_h = int(d.get('start_hour', 0))
            end_h   = int(d.get('end_hour', 6))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid hours"}), 400
        if not name:
            return jsonify({"error": "Name required"}), 400
        if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
            return jsonify({"error": "Hours must be 0-23"}), 400
        ok = state.add_snooze_rule(name, channels, start_h, end_h, days, hosts)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/snooze/rules/<int:rule_id>', methods=['DELETE'])
    @requires_auth
    def api_snooze_rules_delete(rule_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_snooze_rule(rule_id)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/snooze/rules/<int:rule_id>/toggle', methods=['POST'])
    @requires_auth
    def api_snooze_rules_toggle(rule_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        enabled = bool((request.json or {}).get('enabled', True))
        ok = state.toggle_snooze_rule(rule_id, enabled)
        return jsonify({"status": "ok" if ok else "error"})

    @bp.route('/api/suppress/rules', methods=['GET'])
    @requires_auth
    def api_suppress_rules_get():
        try:
            conn = state._get_conn()
            rows = conn.execute(
                "SELECT id, host_pattern, plugin_pattern, reason, created_by, created_at, expires_at "
                "FROM suppress_rules ORDER BY created_at DESC"
            ).fetchall()
            conn.close()
            cols = ['id', 'host_pattern', 'plugin_pattern', 'reason', 'created_by', 'created_at', 'expires_at']
            return jsonify({"rules": [dict(zip(cols, r)) for r in rows]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/suppress/rules', methods=['POST'])
    @requires_auth
    def api_suppress_rules_add():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.get_json(silent=True) or {}
        host_pattern = d.get('host_pattern', '*').strip() or '*'
        plugin_pattern = d.get('plugin_pattern', '*').strip() or '*'
        reason = d.get('reason', '').strip()[:200]
        expires_at = d.get('expires_at', None)
        try:
            conn = state._get_conn()
            conn.execute(
                "INSERT INTO suppress_rules (host_pattern, plugin_pattern, reason, created_by, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (host_pattern, plugin_pattern, reason, g.username, expires_at or None)
            )
            conn.commit()
            conn.close()
            service.log_event("suppress_rule_add", f"{host_pattern} / {plugin_pattern}", user=g.username)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/suppress/rules/<int:rule_id>', methods=['DELETE'])
    @requires_auth
    def api_suppress_rules_delete(rule_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            conn = state._get_conn()
            conn.execute("DELETE FROM suppress_rules WHERE id = ?", (rule_id,))
            conn.commit()
            conn.close()
            service.log_event("suppress_rule_delete", f"id={rule_id}", user=g.username)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── AI Analýza ──────────────────────────────────────────────────────────

    @bp.route('/api/analyze/active_issues', methods=['POST'])
    @requires_auth
    def api_analyze_active_issues():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        channel = (request.json or {}).get('channel', None)
        all_active = state.get_active_issues()
        # Filter by channel if provided
        if channel:
            ch_map = {'infra': lambda i: not i.get('key','').startswith('AGENT|') and (i.get('channel_type','') or '').lower() not in ('security','root'),
                      'agent': lambda i: i.get('key','').startswith('AGENT|'),
                      'security': lambda i: (i.get('channel_type','') or '').lower() == 'security',
                      'root': lambda i: (i.get('channel_type','') or '').lower() == 'root'}
            fn = ch_map.get(channel)
            active = [i for i in all_active if fn(i)] if fn else all_active
        else:
            active = all_active
        if not active:
            return jsonify({"reply": "Žádné aktivní issues k analýze."})
        channel_label = {'infra': 'Infrastruktura', 'agent': 'Agenti', 'security': 'Security', 'root': 'Root'}.get(channel, 'Všechny kategorie')

        # 156: Per-host history context — for each unique host, fetch last 3 resolved issues
        unique_hosts = list({i.get('host') for i in active[:50] if i.get('host') and i.get('host') != 'unknown'})[:10]
        host_history = {}
        if unique_hosts:
            try:
                conn = state._get_conn()
                for h in unique_hosts:
                    rows = conn.execute(
                        "SELECT plugin_name, last_line, resolved_at FROM issue_history "
                        "WHERE host=? ORDER BY resolved_at DESC LIMIT 3", (h,)
                    ).fetchall()
                    if rows:
                        host_history[h] = [f"  [{r[0]}] {(r[1] or '')[:80]} ({(r[2] or '')[:10]})" for r in rows]
                conn.close()
            except Exception:
                pass

        lines = []
        for i in active[:50]:  # max 50
            ch = (i.get('channel_type') or 'GENERAL').upper()
            pl = i.get('plugin_name') or '?'
            host = i.get('host') or '?'
            msg = (i.get('last_line') or '')[:120]
            occ = i.get('occurrence_count', 1)
            occ_str = f" (×{occ})" if occ and occ > 1 else ""
            lines.append(f"[{ch}][{pl}] {host}: {msg}{occ_str}")
        issues_text = "\n".join(lines)
        prompt = (
            f"Jsi senior sysadmin. Analyzuj níže uvedený seznam {len(active)} aktivních alertů "
            f"z monitorovacího systému Sentinel (kategorie: {channel_label}).\n\n"
            f"Pro každou skupinu podobných problémů navrhni jeden konkrétní akční krok. "
            f"Identifikuj nejkritičtější problém. Odpověz strukturovaně, max 300 slov.\n\n"
            f"ALERTY:\n{issues_text}" +
            (("\n\nHISTORIE HOSTŮ (posledně vyřešené issues):\n" +
              "\n".join(f"{h}:\n" + "\n".join(v) for h, v in host_history.items()))
             if host_history else "")
        )
        try:
            reply = service.execute_ollama(prompt, num_ctx=4096, max_tokens=600)
            instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')
            header = (
                f"<div style='margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid var(--border);'>"
                f"<small style='color:var(--text-muted); text-transform:uppercase;'>AI Souhrn — {channel_label} · {len(active)} alertů · {instance}</small>"
                f"</div>"
            )
            return jsonify({"reply": header + reply.replace('\n', '<br>')})
        except Exception as e:
            logger.error(f"analyze_active_issues error: {e}")
            return jsonify({"reply": f"Chyba AI: {e}"}), 500

    # ── AI Trend Report ─────────────────────────────────────────────────────

    @bp.route('/api/analyze/trend_report', methods=['POST'])
    @requires_auth
    def api_analyze_trend():
        days = min(int((request.json or {}).get('days', 7)), 30)
        try:
            conn = state._get_conn()
            # Top pluginy za N dní
            rows_plugin = conn.execute("""
                SELECT plugin_name, COUNT(*) as cnt FROM issues_view_union
                WHERE last_seen >= datetime('now', ?) AND plugin_name IS NOT NULL
                GROUP BY plugin_name ORDER BY cnt DESC LIMIT 10
            """.replace('issues_view_union', '(SELECT plugin_name, last_seen FROM problems UNION ALL SELECT plugin_name, last_seen FROM issue_history)'),
                (f'-{days} days',)
            ).fetchall()
            top_plugins = [(r[0], r[1]) for r in rows_plugin]
            # Top hosté
            rows_host = conn.execute("""
                SELECT host, COUNT(*) as cnt FROM
                (SELECT host, last_seen FROM problems UNION ALL SELECT host, last_seen FROM issue_history)
                WHERE last_seen >= datetime('now', ?) AND host IS NOT NULL AND host != 'unknown'
                GROUP BY host ORDER BY cnt DESC LIMIT 8
            """, (f'-{days} days',)).fetchall()
            top_hosts = [(r[0], r[1]) for r in rows_host]
            # SLA breach count
            active = state.get_active_issues()
            sla_rules = getattr(config, 'SLA_RULES', {})
            sla_breach = 0
            for i in active:
                ch = (i.get('channel_type') or '').lower()
                if ch in sla_rules:
                    try:
                        from datetime import timezone as _tz3
                        fs = datetime.fromisoformat(i.get('first_seen') or i.get('last_seen', ''))
                        if fs.tzinfo is None: fs = fs.replace(tzinfo=_tz3.utc)
                        if (datetime.now(_tz3.utc) - fs).total_seconds() / 3600 > sla_rules[ch]:
                            sla_breach += 1
                    except Exception: pass
            conn.close()
            plugins_str = ", ".join(f"{p}({c})" for p, c in top_plugins)
            hosts_str = ", ".join(f"{h}({c})" for h, c in top_hosts)
            prompt = (
                f"Jsi senior sysadmin. Analyzuj trend za posledních {days} dní v monitoring systému.\n\n"
                f"Aktuálně aktivní issues: {len(active)}\n"
                f"SLA violations: {sla_breach}\n"
                f"Top pluginy (issue count): {plugins_str or 'žádné'}\n"
                f"Top hosté (issue count): {hosts_str or 'žádné'}\n\n"
                f"Navrhni:\n1. Co se zlepšilo/zhoršilo\n2. Systémy vyžadující pozornost\n3. Konkrétní doporučení\n\n"
                f"Odpověz stručně a strukturovaně, max 350 slov."
            )
            reply = service.execute_ollama(prompt, num_ctx=2048, max_tokens=500)
            header = (f"<div style='margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border);'>"
                      f"<small style='color:var(--text-muted);text-transform:uppercase;'>AI Trend report — posledních {days} dní</small></div>")
            return jsonify({"reply": header + reply.replace('\n', '<br>')})
        except Exception as e:
            logger.error(f"trend_report: {e}")
            return jsonify({"reply": f"Chyba: {e}"}), 500

    # ── AI Correlation / Root Cause ─────────────────────────────────────────

    @bp.route('/api/analyze/auto_clusters', methods=['POST'])
    @requires_auth
    def api_auto_clusters():
        """168: Automaticky seskupí aktivní issues algoritmicky, volitelně pojmenuje AI."""
        from datetime import timezone as _tz, timedelta as _td, datetime as _dt
        import fnmatch as _fnm

        d = request.json or {}
        window_min = int(d.get('window_min', 30))
        use_ai = bool(d.get('use_ai', True))
        channel_filter = d.get('channel')

        issues = state.get_active_issues()
        if channel_filter:
            ch_map = {
                'infra': lambda i: (i.get('channel_type','') or '').lower() not in ('security','root','agent'),
                'agent': lambda i: (i.get('channel_type','') or '').lower() == 'agent',
                'security': lambda i: (i.get('channel_type','') or '').lower() == 'security',
                'root': lambda i: (i.get('channel_type','') or '').lower() == 'root',
            }
            fn = ch_map.get(channel_filter)
            if fn:
                issues = [i for i in issues if fn(i)]

        if not issues:
            return jsonify({"clusters": [], "message": "Žádné aktivní issues."})

        window = _td(minutes=window_min)
        now = _dt.now(_tz.utc)

        def _parse_ts(ts):
            if not ts:
                return now
            try:
                return _dt.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                return now

        # Assign each issue to a bucket key: (plugin_name, host) — then time-correlate
        # Cluster by: same plugin across multiple hosts in same time window
        plugin_buckets: dict = {}
        host_buckets: dict = {}
        for issue in issues:
            plugin = (issue.get('plugin_name') or '').lower()
            host = (issue.get('host') or '').lower()
            ts = _parse_ts(issue.get('last_seen'))
            if plugin:
                plugin_buckets.setdefault(plugin, []).append((ts, issue))
            if host:
                host_buckets.setdefault(host, []).append((ts, issue))

        clusters = []
        seen_keys: set = set()

        # 1. Plugin clusters: same plugin, multiple hosts, within window
        for plugin, items in plugin_buckets.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda x: x[0])
            t0 = items[0][0]
            group = [it[1] for it in items if it[0] - t0 <= window]
            if len(group) < 2:
                continue
            hosts = list({i.get('host','?') for i in group})
            if len(hosts) < 2:
                continue  # same-host multi-issue handled by host bucket
            cid = f"plugin:{plugin}"
            if cid in seen_keys:
                continue
            seen_keys.add(cid)
            clusters.append({
                "id": cid, "type": "plugin",
                "label": f"Plugin '{plugin}' na {len(hosts)} hostech",
                "hosts": hosts, "plugin": plugin,
                "issues": [{"key": i.get('key',''), "host": i.get('host',''), "last_line": (i.get('last_line',''))[:120]} for i in group],
                "ai_summary": None,
            })

        # 2. Host clusters: same host, multiple issues within window
        for host, items in host_buckets.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda x: x[0])
            t0 = items[0][0]
            group = [it[1] for it in items if it[0] - t0 <= window]
            if len(group) < 2:
                continue
            cid = f"host:{host}"
            if cid in seen_keys:
                continue
            seen_keys.add(cid)
            plugins = list({i.get('plugin_name','?') for i in group})
            clusters.append({
                "id": cid, "type": "host",
                "label": f"Host '{host}' — {len(group)} issues",
                "hosts": [host], "plugins": plugins,
                "issues": [{"key": i.get('key',''), "plugin": i.get('plugin_name',''), "last_line": (i.get('last_line',''))[:120]} for i in group],
                "ai_summary": None,
            })

        # 3. Optional AI summary per cluster (batch — one call for all clusters)
        if use_ai and clusters:
            try:
                cluster_text = "\n\n".join(
                    f"CLUSTER {idx+1} ({c['type']}): {c['label']}\n"
                    + "\n".join(f"  - {i.get('host') or i.get('plugin','?')}: {i.get('last_line','')[:80]}" for i in c['issues'])
                    for idx, c in enumerate(clusters[:8])  # limit 8
                )
                prompt = (
                    "Jsi senior sysadmin. Pro každý cluster issues níže napiš JEDNU větu s pravděpodobnou root cause.\n"
                    "Odpověz POUZE čísly a větami, bez dalšího textu:\n"
                    "1. <root cause>\n2. <root cause>\n...\n\n" + cluster_text
                )
                raw = service.execute_ollama(prompt, num_ctx=2048, max_tokens=300)
                for line in raw.splitlines():
                    line = line.strip()
                    if line and line[0].isdigit() and '. ' in line:
                        idx_str, summary = line.split('. ', 1)
                        try:
                            idx = int(idx_str) - 1
                            if 0 <= idx < len(clusters):
                                clusters[idx]['ai_summary'] = summary.strip()
                        except ValueError:
                            pass
            except Exception:
                pass

        return jsonify({"clusters": clusters, "total": len(clusters), "window_min": window_min})

    @bp.route('/api/analyze/correlate', methods=['POST'])
    @requires_auth
    def api_analyze_correlate():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        channel = (request.json or {}).get('channel', None)
        all_active = state.get_active_issues()
        if channel:
            ch_map = {'infra': lambda i: not i.get('key','').startswith('AGENT|') and (i.get('channel_type','') or '').lower() not in ('security','root'),
                      'agent': lambda i: i.get('key','').startswith('AGENT|'),
                      'security': lambda i: (i.get('channel_type','') or '').lower() == 'security',
                      'root': lambda i: (i.get('channel_type','') or '').lower() == 'root'}
            fn = ch_map.get(channel)
            active = [i for i in all_active if fn(i)] if fn else all_active
        else:
            active = all_active
        if not active:
            return jsonify({"reply": "Žádné aktivní issues."})
        channel_label = {'infra': 'Infrastruktura', 'agent': 'Agenti', 'security': 'Security', 'root': 'Root'}.get(channel, 'Všechny kategorie')
        lines = [f"[{(i.get('channel_type','?')).upper()}][{i.get('plugin_name','?')}] {i.get('host','?')}: {(i.get('last_line',''))[:100]}"
                 for i in active[:40]]
        prompt = (
            f"Jsi senior sysadmin. Analyzuj {len(active)} aktivních alertů (kategorie: {channel_label}) "
            f"a identifikuj skupiny issues které pravděpodobně sdílí stejnou příčinu (root cause).\n\n"
            f"Pro každou skupinu:\n"
            f"1. Jméno skupiny a počet issues\n"
            f"2. Pravděpodobná příčina (1 věta)\n"
            f"3. Doporučená akce\n\n"
            f"Odpověz stručně a strukturovaně. Max 400 slov.\n\nALERTY:\n" + '\n'.join(lines)
        )
        try:
            reply = service.execute_ollama(prompt, num_ctx=4096, max_tokens=600)
            instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')
            header = (f"<div style='margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border);'>"
                      f"<small style='color:var(--text-muted);text-transform:uppercase;'>AI Korelace — {channel_label} · {len(active)} issues · {instance}</small></div>")
            return jsonify({"reply": header + reply.replace('\n', '<br>')})
        except Exception as e:
            return jsonify({"reply": f"Chyba AI: {e}"}), 500

    # ── Runbooks (060) ──────────────────────────────────────────────────────────

    @bp.route('/api/runbooks', methods=['GET'])
    @requires_auth
    def api_runbooks_list():
        return jsonify({"runbooks": state.list_runbooks()})

    @bp.route('/api/runbooks/<issue_type_b64>', methods=['GET'])
    @requires_auth
    def api_runbook_get(issue_type_b64):
        try:
            issue_type = base64.b64decode(issue_type_b64).decode()
        except Exception:
            return jsonify({"error": "bad key"}), 400
        rb = state.get_runbook(issue_type)
        if not rb:
            return jsonify({"error": "Runbook nenalezen"}), 404
        return jsonify(rb)

    @bp.route('/api/runbooks/generate', methods=['POST'])
    @requires_auth
    def api_runbook_generate():
        """060: AI vygeneruje runbook pro daný issue type."""
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        d = request.get_json(silent=True) or {}
        plugin = (d.get('plugin') or '').strip()
        channel = (d.get('channel') or '').strip()
        last_line = (d.get('last_line') or '').strip()
        if not plugin:
            return jsonify({"error": "plugin je povinný"}), 400
        issue_type = f"{channel.upper()}|{plugin}" if channel else plugin
        prompt = (
            f"Jsi senior sysadmin. Vytvoř stručný runbook (krok-za-krokem postup řešení) "
            f"pro tento typ incidentu:\n\n"
            f"Plugin: {plugin}\nKanál: {channel or 'obecný'}\n"
            f"Příklad zprávy: {last_line[:200] if last_line else 'N/A'}\n\n"
            f"Runbook musí obsahovat:\n"
            f"1. Příčina (1-2 věty)\n"
            f"2. Okamžité kroky (číslovaný seznam, max 5)\n"
            f"3. Ověření opravy\n"
            f"4. Prevence (max 2 body)\n\n"
            f"Odpověz v češtině, strukturovaně, bez HTML tagů. Max 300 slov."
        )
        try:
            content = service.execute_ollama(prompt, num_ctx=2048, max_tokens=500)
            state.save_runbook(issue_type, content, plugin=plugin, channel=channel, created_by=g.username)
            service.log_event("runbook_generate", f"Runbook vygenerován: {issue_type}", user=g.username)
            return jsonify({"status": "ok", "issue_type": issue_type, "content": content})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/runbooks/<int:rb_id>', methods=['DELETE'])
    @requires_auth
    def api_runbook_delete(rb_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        ok = state.delete_runbook(rb_id)
        return jsonify({"status": "ok" if ok else "error"})

    # ── 023 Issue závislosti ────────────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/depends', methods=['GET'])
    @requires_auth
    def api_issue_depends_get(key_b64):
        import base64, json as _json
        key = base64.urlsafe_b64decode(key_b64 + '==').decode()
        with state.db_lock:
            conn = state._get_conn()
            try:
                row = conn.execute("SELECT depends_on FROM problems WHERE key=?", (key,)).fetchone()
                if not row:
                    return jsonify({"error": "Not found"}), 404
                deps = _json.loads(row[0] or '[]')
                # Načti info o blokovacích issues
                dep_infos = []
                for dkey in deps:
                    r = conn.execute(
                        "SELECT key, status, last_line, severity FROM problems WHERE key=?", (dkey,)
                    ).fetchone()
                    if r:
                        dep_infos.append({"key": r[0], "status": r[1],
                                          "last_line": r[2], "severity": r[3]})
                    else:
                        dep_infos.append({"key": dkey, "status": "unknown"})
                return jsonify({"depends_on": dep_infos})
            finally:
                conn.close()

    @bp.route('/api/issues/<key_b64>/depends', methods=['POST'])
    @requires_auth
    def api_issue_depends_add(key_b64):
        import base64, json as _json
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        key = base64.urlsafe_b64decode(key_b64 + '==').decode()
        dep_key = (request.json or {}).get('depends_on_key', '').strip()
        if not dep_key or dep_key == key:
            return jsonify({"error": "Invalid key"}), 400
        with state.db_lock:
            conn = state._get_conn()
            try:
                row = conn.execute("SELECT depends_on FROM problems WHERE key=?", (key,)).fetchone()
                if not row:
                    return jsonify({"error": "Not found"}), 404
                deps = _json.loads(row[0] or '[]')
                if dep_key not in deps:
                    deps.append(dep_key)
                    conn.execute("UPDATE problems SET depends_on=? WHERE key=?",
                                 (_json.dumps(deps), key))
                return jsonify({"status": "ok", "depends_on": deps})
            finally:
                conn.close()

    @bp.route('/api/issues/<key_b64>/depends', methods=['DELETE'])
    @requires_auth
    def api_issue_depends_remove(key_b64):
        import base64, json as _json
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        key = base64.urlsafe_b64decode(key_b64 + '==').decode()
        dep_key = (request.json or {}).get('depends_on_key', '').strip()
        with state.db_lock:
            conn = state._get_conn()
            try:
                row = conn.execute("SELECT depends_on FROM problems WHERE key=?", (key,)).fetchone()
                if not row:
                    return jsonify({"error": "Not found"}), 404
                deps = [d for d in _json.loads(row[0] or '[]') if d != dep_key]
                conn.execute("UPDATE problems SET depends_on=? WHERE key=?",
                             (_json.dumps(deps), key))
                return jsonify({"status": "ok", "depends_on": deps})
            finally:
                conn.close()

    @bp.route('/api/issues/<key_b64>/blocked_by', methods=['GET'])
    @requires_auth
    def api_issue_blocked_by(key_b64):
        """Vrátí seznam issues které závisí na tomto issue (je blokuje)."""
        import base64, json as _json
        key = base64.urlsafe_b64decode(key_b64 + '==').decode()
        with state.db_lock:
            conn = state._get_conn()
            try:
                rows = conn.execute(
                    "SELECT key, status, last_line, severity FROM problems "
                    "WHERE depends_on LIKE ? AND status NOT IN ('resolved','expired')",
                    (f'%{key}%',)
                ).fetchall()
                blockers = [{"key": r[0], "status": r[1], "last_line": r[2], "severity": r[3]}
                            for r in rows if key in _json.loads(
                                conn.execute("SELECT depends_on FROM problems WHERE key=?",
                                             (r[0],)).fetchone()[0] or '[]')]
                return jsonify({"blocked_by": blockers})
            finally:
                conn.close()

    # ── Issues list for dep graph (119) ─────────────────────────────────────

    @bp.route('/api/issues/with_deps', methods=['GET'])
    @requires_auth
    def api_issues_with_deps():
        """Vrátí issues které mají depends_on (pro dep graph)."""
        import json as _json
        with state.db_lock:
            conn = state._get_conn()
            try:
                rows = conn.execute(
                    """SELECT key, host, plugin_name, status, depends_on, severity
                       FROM problems
                       WHERE depends_on != '[]' AND depends_on IS NOT NULL
                         AND status NOT IN ('resolved','expired')
                       LIMIT 200"""
                ).fetchall()
                # Fetch all keys referenced as deps
                all_dep_keys = set()
                result = []
                for r in rows:
                    deps = _json.loads(r[4] or '[]')
                    result.append({"key": r[0], "host": r[1], "plugin_name": r[2], "status": r[3], "depends_on": deps, "severity": r[5]})
                    all_dep_keys.update(deps)
                # Fetch info for dep keys not already in result
                existing = {r["key"] for r in result}
                missing = all_dep_keys - existing
                if missing:
                    placeholders = ','.join(['?'] * len(missing))
                    dep_rows = conn.execute(
                        f"SELECT key, host, plugin_name, status, '[]' as depends_on, severity FROM problems WHERE key IN ({placeholders})",
                        list(missing)
                    ).fetchall()
                    for r in dep_rows:
                        result.append({"key": r[0], "host": r[1], "plugin_name": r[2], "status": r[3], "depends_on": [], "severity": r[5]})
                return jsonify({"issues": result})
            finally:
                conn.close()

    # ── Similar incidents (059) ──────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/similar', methods=['GET'])
    @requires_auth
    def api_issue_similar(key_b64):
        """Najde podobné historické incidenty pomocí textové podobnosti."""
        import base64 as _b64, re as _re
        key = _b64.urlsafe_b64decode(key_b64 + '==').decode()
        with state.db_lock:
            conn = state._get_conn()
            try:
                row = conn.execute(
                    "SELECT plugin_name, host, last_line FROM problems WHERE key=?", (key,)
                ).fetchone()
                if not row:
                    return jsonify({"error": "Issue not found"}), 404
                plugin, host, msg = row

                # Tokenize query message
                def _tokens(s):
                    return set(_re.findall(r'[a-zA-Z0-9_/.-]{3,}', (s or '').lower()))

                q_tokens = _tokens(msg)
                if not q_tokens:
                    return jsonify({"similar": []})

                # Fetch recent history (last 90 days, same plugin preferred)
                rows = conn.execute(
                    """SELECT id, key, channel_type, host, plugin_name, last_line, resolved_at
                       FROM issue_history
                       WHERE resolved_at > datetime('now', '-90 days')
                         AND key != ?
                       ORDER BY resolved_at DESC LIMIT 500""",
                    (key,)
                ).fetchall()

                scored = []
                for r in rows:
                    r_tokens = _tokens(r[5])
                    if not r_tokens: continue
                    overlap = len(q_tokens & r_tokens)
                    union = len(q_tokens | r_tokens)
                    jaccard = overlap / union if union else 0
                    # Boost same plugin
                    if r[4] == plugin: jaccard = min(1.0, jaccard * 1.3)
                    if jaccard > 0.25:
                        scored.append({
                            "id": r[0], "host": r[3], "plugin_name": r[4],
                            "last_line": (r[5] or '')[:120],
                            "resolved_at": r[6],
                            "similarity": round(jaccard, 2)
                        })

                scored.sort(key=lambda x: -x["similarity"])
                return jsonify({"similar": scored[:10], "query_plugin": plugin, "query_host": host})
            finally:
                conn.close()

    # ── False Positive patterns (057) ────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/false_positive', methods=['POST'])
    @requires_auth
    def api_issue_mark_fp(key_b64):
        """Přidá FP pattern z issue (plugin + host_pattern + msg_pattern)."""
        import base64 as _b64
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "admin required"}), 403
        key = _b64.urlsafe_b64decode(key_b64 + '==').decode()
        body = request.json or {}
        with state.db_lock:
            conn = state._get_conn()
            try:
                row = conn.execute(
                    "SELECT plugin_name, host, last_line FROM problems WHERE key=?", (key,)
                ).fetchone()
                if not row:
                    return jsonify({"error": "Issue not found"}), 404
                plugin, host, msg = row
                host_pat = body.get('host_pattern', host or '*')
                msg_pat = body.get('msg_pattern', msg or '*')
                conn.execute(
                    "INSERT INTO false_positive_patterns (plugin_name, host_pattern, msg_pattern, created_by) VALUES (?,?,?,?)",
                    (plugin or '*', host_pat, msg_pat, g.username)
                )
                conn.commit()
                service.log_event("false_positive_added", f"FP: plugin={plugin} host={host_pat} msg={msg_pat[:80]}", user=g.username)
                return jsonify({"status": "ok", "plugin": plugin, "host_pattern": host_pat, "msg_pattern": msg_pat})
            finally:
                conn.close()

    @bp.route('/api/false_positives', methods=['GET'])
    @requires_auth
    def api_fp_list():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        with state.db_lock:
            conn = state._get_conn()
            try:
                rows = conn.execute(
                    "SELECT id, plugin_name, host_pattern, msg_pattern, created_by, created_at, hit_count FROM false_positive_patterns ORDER BY id DESC"
                ).fetchall()
                return jsonify({"patterns": [
                    {"id": r[0], "plugin_name": r[1], "host_pattern": r[2], "msg_pattern": r[3],
                     "created_by": r[4], "created_at": r[5], "hit_count": r[6]}
                    for r in rows
                ]})
            finally:
                conn.close()

    @bp.route('/api/false_positives/<int:fp_id>', methods=['DELETE'])
    @requires_auth
    def api_fp_delete(fp_id):
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        with state.db_lock:
            conn = state._get_conn()
            try:
                conn.execute("DELETE FROM false_positive_patterns WHERE id=?", (fp_id,))
                conn.commit()
                return jsonify({"status": "ok"})
            finally:
                conn.close()

    # ── Sarkastické vtipy o infrastruktuře ─────────────────────────────────────

    @bp.route('/api/analyze/infra_joke', methods=['POST'])
    @requires_auth
    def api_infra_joke():
        """Sarkastický vtip o aktuálním stavu infrastruktury ze šablon."""
        import random as _r
        lang = (request.get_json(silent=True) or {}).get('lang', 'cs')

        TEMPLATES_ISSUE_EN = [
            # knock-knock
            "Knock knock.\n— Who's there?\n— {host}.\n— {host} who?\n— {host}, the one with {plugin} broken for {age} now.",
            "Knock knock.\n— Who's there?\n— {plugin}.\n— {plugin} who?\n— {plugin} on {host}. Still. Always. Forever.",
            "Knock knock.\n— Who's there?\n— Monitoring.\n— Monitoring who?\n— Monitoring, telling you {host} has a problem with {plugin}. Surprise.",
            "Knock knock.\n— Who's there?\n— Alert.\n— Alert who?\n— Alert #{count} today. {host}. {plugin}. Get used to it.",
            "Knock knock.\n— Who's there?\n— On-call.\n— On-call who?\n— On-call, who can't sleep tonight because of {host} and {plugin}.",
            "Knock knock.\n— Who's there?\n— {host}.\n— {host} who?\n— {host}, your favorite server. The one with {plugin}. Again.",
            # one-liners
            "Today's weather forecast: {host} — overcast, {plugin} offline, 20% chance of fix.",
            "Motivational quote of the day: Never give up. {host} didn't either, and look where that got it.",
            "{host} has had {plugin} broken for {age}. Grafana knows. You know. Everyone knows. Nobody does anything.",
            "Is it working? No. Will it be fixed? Maybe. When? {host} will reply when it feels like it.",
            "Infrastructure status: {count} alerts. Team morale: no comment.",
            "Good news: monitoring works. Bad news: {host} with {plugin} definitely doesn't.",
            "{host} celebrates {age} without {plugin}. Should we send a cake?",
            # horoscope
            "Horoscope for {host}: Today is not a good day for {plugin}. Actually, no day is.",
            "Horoscope for the sysadmin: The stars say {host} disappointed you today. The stars are right.",
            # ticket style
            "TICKET #∞ — {host}: {plugin} down for {age}. Priority: critical. Status: unresolved.",
            "Dear customer, your server {host} has been experiencing issues with {plugin} for {age}. We apologize for the inconvenience. Your ops team.",
            # philosophical
            "If {host} crashes in the forest and no one sees it, the crash still gets logged. And {plugin} reports it for {age}.",
            "Which came first: {host} or {plugin}? Neither works today, so it doesn't matter.",
        ]

        TEMPLATES_OK_EN = [
            "Knock knock.\n— Who's there?\n— Infrastructure.\n— Infrastructure who?\n— Infrastructure that has nothing to report today. Probably broken monitoring.",
            "Knock knock.\n— Who's there?\n— Silence.\n— Silence who?\n— Silence in the alerts. Either everything works, or monitoring is offline too.",
            "Knock knock.\n— Who's there?\n— Calm.\n— Calm who?\n— The calm before the storm. All servers green. Backing up now.",
            "All servers are green. This message will self-destruct once that changes.",
            "Zero active alerts. Either everything is fine, or monitoring finally broke too.",
            "Infrastructure is working. Write down the date — this doesn't happen often.",
            "No issues today. Tomorrow will be worse, but we'll deal with that tomorrow.",
            "Zero alerts. Ops team is having coffee. Enjoy this rare moment.",
        ]

        TEMPLATES_ISSUE = [
            # klep-klep
            "Klep klep.\n— Kdo je?\n— {host}.\n— {host} kdo?\n— {host}, ten co má {plugin} v prdeli už {age}.",
            "Klep klep.\n— Kdo je?\n— {plugin}.\n— {plugin} kdo?\n— {plugin} na {host}. Pořád. Furt. Dokola.",
            "Klep klep.\n— Kdo je?\n— Monitoring.\n— Monitoring kdo?\n— Monitoring, co ti hlásí že {host} má problém s {plugin}. Překvapení.",
            "Klep klep.\n— Kdo je?\n— Alert.\n— Alert kdo?\n— Alert číslo {count} dnes. {host}. {plugin}. Zvykej si.",
            "Klep klep.\n— Kdo je?\n— On-call.\n— On-call kdo?\n— On-call, co kvůli {host} a {plugin} dnes zas nespí.",
            "Klep klep.\n— Kdo je?\n— {host}.\n— {host} kdo?\n— {host}, tvůj oblíbený server. Ten s {plugin}. Zase.",
            # jednořádkový sarkazmus
            "Dnešní předpověď počasí: {host} — zataženo, {plugin} mimo provoz, šance na opravu 20 %.",
            "Motivační citát dne: Nevzdávej se. {host} to taky neudělal, a podívej kde je teď.",
            "{host} má {plugin} rozbité už {age}. Grafana to ví. Ty to víš. Všichni to ví. Nikdo nic nedělá.",
            "Funguje to? Ne. Opraví se to? Možná. Kdy? {host} odpoví jakmile bude mít chuť.",
            "Stav infrastruktury: {count} alertů. Nálada týmu: nekomentujeme.",
            "Dobrá zpráva: monitoring funguje. Špatná zpráva: {host} s {plugin} rozhodně ne.",
            "{host} slaví {age} bez {plugin}. Pošleme dort?",
            # horoskop styl
            "Horoskop pro {host}: Dnes není vhodný den pro {plugin}. Vlastně žádný den není.",
            "Horoskop pro správce: Hvězdy říkají, že {host} tě dnes zklamal. Hvězdy mají pravdu.",
            # podpora / ticket styl
            "TICKET #∞ — {host}: {plugin} nefunguje {age}. Priorita: kritická. Status: neřeší se.",
            "Vážený zákazníku, váš server {host} eviduje problém s {plugin} od {age}. Omlováme se za komplikace. Váš tým ops.",
            # filozofický
            "Pokud {host} spadne do lesa a nikdo ho nevidí, pád stejně zaloguje. A {plugin} to hlásí {age}.",
            "Co dřív? {host} nebo {plugin}? Dnes ani jedno nefunguje, takže to je jedno.",
        ]

        TEMPLATES_OK = [
            # klep-klep ok
            "Klep klep.\n— Kdo je?\n— Infrastruktura.\n— Infrastruktura kdo?\n— Infrastruktura, co dnes nic nehlásí. Pravděpodobně rozbitý monitoring.",
            "Klep klep.\n— Kdo je?\n— Silence.\n— Silence kdo?\n— Silence v alertech. Buď vše funguje, nebo je monitoring taky offline.",
            "Klep klep.\n— Kdo je?\n— Klid.\n— Klid kdo?\n— Klid před bouří. Všechny servery zelené. Zálohuji teď.",
            # jednořádkový ok
            "Všechny servery jsou zelené. Tato zpráva se automaticky smaže, až to přestane platit.",
            "Žádné aktivní alerty. Buď je vše v pořádku, nebo je monitoring konečně taky rozbité.",
            "Infrastruktura funguje. Zapište si datum — tohle se nestává často.",
            "Dnes žádné problémy. Zítra bude hůř, ale to řešíme zítra.",
            "Nula alertů. Tým ops si dává kafe. Vychutnávejte tento vzácný okamžik.",
        ]

        tpl_issue = TEMPLATES_ISSUE_EN if lang == 'en' else TEMPLATES_ISSUE
        tpl_ok = TEMPLATES_OK_EN if lang == 'en' else TEMPLATES_OK

        _SKIP_PLUGINS = {'detector_who', 'detector_icinga', 'agent_security_vulnerability_scan', 'agent_security_root_monitor'}

        active = state.get_active_issues()
        if active:
            from datetime import datetime, timezone
            candidates = [i for i in active if i.get('plugin_name') not in _SKIP_PLUGINS]
            if not candidates:
                candidates = active
            # vynechej hosty co byli v posledních 5 vtipcích (in-memory)
            fresh = [i for i in candidates if i.get('host') not in _joke_recent_hosts]
            pool = (fresh if fresh else candidates)[:50]
            _r.shuffle(pool)
            issue = pool[0]
            _joke_recent_hosts.append(issue.get('host', ''))
            host = issue.get('host') or 'server'
            plugin = issue.get('plugin_name') or 'monitoring'
            try:
                fs = issue.get('first_seen') or ''
                if fs:
                    dt = datetime.fromisoformat(fs.replace('Z', '+00:00'))
                    age_sec = int((datetime.now(timezone.utc) - dt).total_seconds())
                else:
                    age_sec = 0
            except Exception:
                age_sec = 0
            age = f"{age_sec // 3600}h" if age_sec >= 3600 else f"{max(1, age_sec // 60)}min"
            count = len(active)
            joke = _r.choice(tpl_issue).format(host=host, plugin=plugin, age=age, count=count)
        else:
            joke = _r.choice(tpl_ok)

        joke = html.escape(joke)
        if joke:
            with state.db_lock:
                conn = state._get_conn()
                try:
                    conn.execute(
                        "INSERT INTO infra_jokes (joke, source) VALUES (?, 'manual')",
                        (joke,)
                    )
                    conn.execute(
                        "DELETE FROM infra_jokes WHERE id NOT IN (SELECT id FROM infra_jokes ORDER BY id DESC LIMIT 50)"
                    )
                    conn.commit()
                finally:
                    conn.close()
        return jsonify({"joke": joke})

    @bp.route('/api/analyze/infra_joke_log', methods=['GET'])
    @requires_auth
    def api_infra_joke_log():
        """Vrátí historii posledních 20 vtipu."""
        with state.db_lock:
            conn = state._get_conn()
            try:
                rows = conn.execute(
                    "SELECT joke, source, created_at FROM infra_jokes ORDER BY id DESC LIMIT 20"
                ).fetchall()
                return jsonify({"log": [
                    {"joke": r[0], "source": r[1], "ts": r[2]}
                    for r in rows
                ]})
            finally:
                conn.close()

    # ── 377: Issue copy as Markdown ─────────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/markdown', methods=['GET'])
    @requires_auth
    def api_issue_markdown(key_b64):
        """377: Return issue formatted as Markdown for copy-to-clipboard."""
        try:
            key = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "bad key"}), 400
        try:
            conn = state._get_conn()
            row = conn.execute(
                "SELECT key, channel_type, host, plugin_name, last_line, first_seen, last_seen, status, severity, occurrence_count, assigned_to FROM problems WHERE key=?",
                (key,)
            ).fetchone()
            comments = conn.execute(
                "SELECT username, created_at, text FROM issue_comments WHERE issue_key=? ORDER BY created_at ASC LIMIT 20",
                (key,)
            ).fetchall()
            conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        if not row:
            return jsonify({"error": "Issue not found"}), 404
        r_key, ch, host, plugin, last_line, first_seen, last_seen, status, severity, occ, assigned = row
        lines = [
            f"## Issue: {r_key}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Status** | {status or 'active'} |",
            f"| **Severity** | {severity or 'N/A'} |",
            f"| **Channel** | {ch or 'N/A'} |",
            f"| **Host** | {host or 'N/A'} |",
            f"| **Plugin** | {plugin or 'N/A'} |",
            f"| **First seen** | {(first_seen or '').replace('T', ' ')[:19]} |",
            f"| **Last seen** | {(last_seen or '').replace('T', ' ')[:19]} |",
            f"| **Occurrences** | {occ or 1} |",
            f"| **Assigned to** | {assigned or 'unassigned'} |",
            f"",
            f"### Message",
            f"```",
            last_line or "(no message)",
            f"```",
        ]
        if comments:
            lines += ["", "### Comments"]
            for user, ts, text in comments:
                lines.append(f"**{user}** ({(ts or '').replace('T', ' ')[:16]}): {text}")
        return jsonify({"markdown": "\n".join(lines), "key": r_key})

    # ── 399: Issue forecast ──────────────────────────────────────────────────────

    @bp.route('/api/analytics/forecast', methods=['GET'])
    @requires_auth
    def api_analytics_forecast():
        """399: Linear regression forecast — predict issue count for next N days."""
        days_back = int(request.args.get('days_back', 14))
        days_ahead = int(request.args.get('days_ahead', 7))
        days_back = max(7, min(90, days_back))
        days_ahead = max(1, min(30, days_ahead))
        try:
            conn = state._get_conn()
            rows = conn.execute("""
                SELECT strftime('%Y-%m-%d', last_seen) as day, COUNT(*) as cnt
                FROM problems
                WHERE last_seen >= datetime('now', ?)
                GROUP BY day ORDER BY day ASC
            """, (f'-{days_back} days',)).fetchall()
            conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        from datetime import date as _date, timedelta as _td
        today = _date.today()
        # Fill missing days with 0
        day_counts = {}
        for day, cnt in rows:
            day_counts[day] = cnt
        x_vals, y_vals = [], []
        for i in range(days_back):
            d = (today - _td(days=days_back - 1 - i)).isoformat()
            x_vals.append(i)
            y_vals.append(day_counts.get(d, 0))
        # Linear regression
        n = len(x_vals)
        if n < 2:
            return jsonify({"error": "Insufficient data"}), 400
        sum_x = sum(x_vals)
        sum_y = sum(y_vals)
        sum_xx = sum(x * x for x in x_vals)
        sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            slope, intercept = 0, sum_y / n
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denom
            intercept = (sum_y - slope * sum_x) / n
        # Build historical + forecast
        history = [{"day": (today - _td(days=days_back - 1 - i)).isoformat(),
                     "actual": y_vals[i],
                     "predicted": round(max(0, intercept + slope * i), 1)}
                   for i in range(n)]
        forecast = []
        for i in range(days_ahead):
            fx = n + i
            forecast.append({"day": (today + _td(days=i + 1)).isoformat(),
                              "predicted": round(max(0, intercept + slope * fx), 1)})
        trend = "up" if slope > 0.1 else ("down" if slope < -0.1 else "stable")
        return jsonify({
            "history": history,
            "forecast": forecast,
            "slope": round(slope, 3),
            "intercept": round(intercept, 3),
            "trend": trend,
            "days_back": days_back,
            "days_ahead": days_ahead,
        })

    # ── 405: Incident postmortem template ────────────────────────────────────────

    @bp.route('/api/issues/<key_b64>/postmortem', methods=['GET'])
    @requires_auth
    def api_issue_postmortem(key_b64):
        """405: AI-generated postmortem Markdown for a resolved/active issue."""
        try:
            key = base64.b64decode(key_b64).decode()
        except Exception:
            return jsonify({"error": "bad key"}), 400
        try:
            conn = state._get_conn()
            row = conn.execute(
                "SELECT key, channel_type, host, plugin_name, last_line, first_seen, last_seen, status, severity FROM problems WHERE key=?",
                (key,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT key, channel_type, host, plugin_name, last_line, first_seen, last_seen, 'resolved', NULL FROM issue_history WHERE key=?",
                    (key,)
                ).fetchone()
            comments = conn.execute(
                "SELECT username, created_at, text FROM issue_comments WHERE issue_key=? ORDER BY created_at ASC LIMIT 10",
                (key,)
            ).fetchall()
            conn.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        if not row:
            return jsonify({"error": "Issue not found"}), 404
        r_key, ch, host, plugin, last_line, first_seen, last_seen, status, severity = row
        comments_text = "\n".join([f"- {u} ({ts[:16]}): {t}" for u, ts, t in comments]) or "Žádné komentáře."
        prompt = (
            f"Vytvoř postmortem report v Markdownu pro incident:\n"
            f"Host: {host}, Plugin: {plugin}, Kanál: {ch}, Severity: {severity}\n"
            f"Zpráva: {last_line}\n"
            f"Začátek: {first_seen}, Konec: {last_seen}, Status: {status}\n"
            f"Komentáře: {comments_text}\n\n"
            f"Postmortem musí obsahovat: Shrnutí, Timeline, Root Cause, Impact, Action Items. Piš česky."
        )
        try:
            md = service.execute_ollama(prompt, num_ctx=2048, max_tokens=800)
        except Exception as e:
            # Fallback template if AI unavailable
            md = (
                f"## Postmortem: {r_key}\n\n"
                f"### Shrnutí\n{last_line}\n\n"
                f"### Timeline\n- **Začátek:** {first_seen}\n- **Konec:** {last_seen}\n\n"
                f"### Root Cause\nTBD\n\n"
                f"### Impact\nHost: {host}, Kanál: {ch}\n\n"
                f"### Action Items\n- [ ] Doplnit příčinu\n- [ ] Preventivní opatření\n\n"
                f"*AI nedostupná: {e}*"
            )
        return jsonify({"postmortem": md, "key": r_key})

    # ── Analytics endpointy (obnoveny) ────────────────────────────────────────

    @bp.route('/api/analytics/resolution_time', methods=['GET'])
    @requires_auth
    def api_resolution_time():
        """258: Průměrná doba řešení per plugin."""
        days = int_param(request.args.get('days', 30), 30, 1, 365)
        return jsonify({"stats": state.get_resolution_time_stats(days), "days": days})

    @bp.route('/api/analytics/flapping', methods=['GET'])
    @requires_auth
    def api_flapping_issues():
        """259: Top flapping issues."""
        days = int_param(request.args.get('days', 7), 7, 1, 90)
        min_count = int_param(request.args.get('min', 3), 3, 2, 50)
        return jsonify({"issues": state.get_flapping_issues(days, min_count)})

    @bp.route('/api/analytics/alert_fatigue', methods=['GET'])
    @requires_auth
    def api_alert_fatigue():
        """260: Alert fatigue stats."""
        days = int_param(request.args.get('days', 30), 30, 1, 365)
        return jsonify({"stats": state.get_alert_fatigue_stats(days)})

    @bp.route('/api/analytics/changes_since_login', methods=['GET'])
    @requires_auth
    def api_changes_since_login():
        """262: Změny od posledního přihlášení."""
        last_login = state.get_user_last_login(g.username)
        if not last_login:
            return jsonify({"new_count": 0, "resolved_count": 0, "since": None})
        try:
            with state._get_conn() as conn:
                new_count = conn.execute("SELECT COUNT(*) FROM problems WHERE first_seen >= ?", (last_login,)).fetchone()[0]
                resolved_count = conn.execute("SELECT COUNT(*) FROM issue_history WHERE resolved_at >= ?", (last_login,)).fetchone()[0]
        except Exception:
            new_count = resolved_count = 0
        return jsonify({"new_count": new_count, "resolved_count": resolved_count, "since": last_login})

    return bp

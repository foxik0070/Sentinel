from flask import Blueprint, request, jsonify, g, Response
from ..auth import requires_auth, int_param
from .. import state, config
import html
import logging
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.chat")


def create_blueprint(service):
    bp = Blueprint('export', __name__)

    @bp.route('/api/export/incidents.csv', methods=['GET'])
    @requires_auth
    def export_incidents_csv():
        import csv
        import io
        issues = state.get_active_issues()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['key', 'channel_type', 'host', 'last_line', 'last_seen', 'status', 'plugin_name'])
        for i in issues:
            writer.writerow([
                i.get('key', ''), i.get('channel_type', ''), i.get('host', ''),
                i.get('last_line', ''), i.get('last_seen', ''),
                i.get('status', ''), i.get('plugin_name', ''),
            ])
        service.log_event("export", "Incident CSV exported", user=g.username)
        return Response(
            buf.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=incidents.csv'}
        )

    @bp.route('/api/export/telemetry.csv', methods=['GET'])
    @requires_auth
    def export_telemetry_csv():
        import csv
        import io
        days = int_param(request.args.get('days', 7), 7, 1, 365)
        category = request.args.get('category', '').strip()
        metric = request.args.get('metric', '').strip()
        try:
            where = ["timestamp > datetime('now', ?)"]
            params = [f'-{days} days']
            if category:
                where.append("category = ?")
                params.append(category)
            if metric:
                where.append("metric LIKE ?")
                params.append(f'%{metric}%')
            conn = state._get_conn()
            rows = conn.execute(
                f"SELECT timestamp, category, metric, value FROM telemetry "
                f"WHERE {' AND '.join(where)} ORDER BY timestamp ASC",
                params
            ).fetchall()
            conn.close()
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(['timestamp', 'category', 'metric', 'value'])
            writer.writerows(rows)
            fname = f"telemetry_{days}d.csv"
            service.log_event("export", f"Telemetry CSV exported ({len(rows)} rows)", user=g.username)
            return Response(
                buf.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={fname}'}
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/export/incidents.md', methods=['GET'])
    @requires_auth
    def export_incidents_md():
        from datetime import datetime as _dt
        issues = state.get_active_issues()
        now = _dt.now().strftime('%Y-%m-%d %H:%M')
        lines = [
            f"# Sentinel Incident Report — {config.INSTANCE_NAME}",
            f"Generated: {now} | Total: {len(issues)} active issues",
            "",
        ]
        by_channel: dict = {}
        for i in issues:
            ch = i.get('channel_type', 'GENERAL').upper()
            by_channel.setdefault(ch, []).append(i)
        for ch, ch_issues in sorted(by_channel.items()):
            lines.append(f"## {ch} ({len(ch_issues)})")
            lines.append("")
            lines.append("| Host | Plugin | Status | Last Seen | Message |")
            lines.append("|------|--------|--------|-----------|---------|")
            for i in ch_issues:
                ts  = i.get('last_seen', '').replace('T', ' ')[:16]
                msg = i.get('last_line', '').replace('|', '\\|')[:120]
                lines.append(
                    f"| {i.get('host','?')} | {i.get('plugin_name','')} "
                    f"| {i.get('status','')} | {ts} | {msg} |"
                )
            lines.append("")
        service.log_event("export", "Incident Markdown exported", user=g.username)
        return Response(
            "\n".join(lines),
            mimetype='text/markdown',
            headers={'Content-Disposition': 'attachment; filename=incidents.md'}
        )

    @bp.route('/api/export/incidents.html', methods=['GET'])
    @requires_auth
    def export_incidents_html():
        all_issues = state.get_active_issues()

        raw_ch  = request.args.get('channels', '').strip()
        raw_pl  = request.args.get('plugins',  '').strip()
        raw_st  = request.args.get('statuses', '').strip()
        raw_host = request.args.get('host', '').strip().lower()

        f_channels = {c.strip().upper() for c in raw_ch.split(',') if c.strip()} if raw_ch else set()
        f_plugins  = {p.strip().lower() for p in raw_pl.split(',') if p.strip()} if raw_pl else set()
        f_statuses = {s.strip().lower() for s in raw_st.split(',') if s.strip()} if raw_st else set()

        def _keep(i):
            if f_channels and i.get('channel_type', '').upper() not in f_channels:
                return False
            if f_plugins and i.get('plugin_name', '').lower() not in f_plugins:
                return False
            if f_statuses and i.get('status', '').lower() not in f_statuses:
                return False
            if raw_host and raw_host not in i.get('host', '').lower():
                return False
            return True

        issues = [i for i in all_issues if _keep(i)]

        filter_parts = []
        if f_channels:  filter_parts.append(f"Channels: {', '.join(sorted(f_channels))}")
        if f_plugins:   filter_parts.append(f"Plugins: {', '.join(sorted(f_plugins))}")
        if f_statuses:  filter_parts.append(f"Status: {', '.join(sorted(f_statuses))}")
        if raw_host:    filter_parts.append(f"Host: *{raw_host}*")
        filter_line = " &nbsp;|&nbsp; ".join(filter_parts) if filter_parts else "All issues (no filter)"

        ch_colours = {
            'SECURITY': '#dc3545', 'INFRA': '#17a2b8', 'ICINGA': '#17a2b8',
            'ROOT': '#ffc107', 'LOGIN': '#6f42c1', 'AGENT': '#0078d4',
        }

        rows = ""
        for idx, i in enumerate(issues, 1):
            ts = (i.get('last_seen') or '').replace('T', ' ').split('.')[0]
            ch = i.get('channel_type', '').upper()
            ch_color = ch_colours.get(ch, '#888')
            rows += (
                f"<tr>"
                f"<td style='text-align:center;'><input type='checkbox' class='done-cb' "
                f"onchange='this.closest(\"tr\").classList.toggle(\"done\",this.checked)'></td>"
                f"<td style='color:#888;'>{idx}</td>"
                f"<td><span style='background:{ch_color};color:#fff;padding:1px 5px;border-radius:3px;"
                f"font-size:10px;font-weight:bold;'>{html.escape(ch)}</span></td>"
                f"<td style='font-weight:bold;'>{html.escape(i.get('host',''))}</td>"
                f"<td style='color:#555;font-size:11px;'>{html.escape(i.get('plugin_name',''))}</td>"
                f"<td style='max-width:340px;'>{html.escape(i.get('last_line',''))}</td>"
                f"<td style='color:#888;white-space:nowrap;'>{html.escape(ts)}</td>"
                f"<td style='color:#888;'>{html.escape(i.get('status',''))}</td>"
                f"</tr>"
            )

        generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        page = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'>
<title>Sentinel Incident Report — {generated}</title>
<style>
*{{box-sizing:border-box;}}
body{{font-family:'Segoe UI',monospace;font-size:12px;margin:24px;color:#111;background:#fff;}}
h1{{font-size:18px;margin:0 0 4px;display:flex;align-items:center;gap:8px;}}
.meta{{color:#666;font-size:11px;margin-bottom:14px;border-bottom:1px solid #ddd;padding-bottom:10px;}}
table{{border-collapse:collapse;width:100%;margin-top:4px;}}
thead tr{{background:#1a1a2e;color:#fff;}}
th{{padding:7px 10px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap;}}
td{{padding:6px 10px;border-bottom:1px solid #eee;vertical-align:top;}}
tr:hover td{{background:#f5f5f5;}}
tr.done td{{text-decoration:line-through;color:#bbb;background:#fafafa;}}
input[type=checkbox]{{width:15px;height:15px;cursor:pointer;accent-color:#0078d4;}}
.actions{{margin-bottom:14px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;}}
button{{padding:6px 14px;cursor:pointer;border:1px solid #ccc;border-radius:4px;background:#f5f5f5;font-size:12px;}}
button:hover{{background:#e0e0e0;}}
.btn-primary{{background:#0078d4;color:#fff;border-color:#0078d4;}}
.btn-primary:hover{{background:#005fa3;}}
.count{{color:#666;font-size:11px;margin-left:auto;}}
@media print{{.no-print{{display:none!important;}} body{{margin:8px;}} thead tr{{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}}}
</style></head><body>
<h1>&#x1F6E1; Sentinel Incident Report</h1>
<div class='meta'>
  Generated: <b>{generated}</b> &nbsp;|&nbsp; Instance: <b>{html.escape(config.INSTANCE_NAME)}</b>
  &nbsp;|&nbsp; Filter: {filter_line}
  &nbsp;|&nbsp; Total shown: <b>{len(issues)}</b> / {len(all_issues)}
</div>
<div class='actions no-print'>
  <button class='btn-primary' onclick='window.print()'>&#x1F5A8; Print</button>
  <button onclick='document.querySelectorAll(".done-cb").forEach(c=>{{c.checked=true;c.closest("tr").classList.add("done")}})'>&#x2611; Mark all done</button>
  <button onclick='document.querySelectorAll(".done-cb").forEach(c=>{{c.checked=false;c.closest("tr").classList.remove("done")}})'>&#x25A1; Clear all</button>
  <span class='count' id='done-count'>0 / {len(issues)} done</span>
</div>
<table>
<thead><tr><th>&#x2713;</th><th>#</th><th>Channel</th><th>Host</th><th>Plugin</th><th>Message</th><th>Last Seen</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<script>
document.querySelectorAll('.done-cb').forEach(cb=>cb.addEventListener('change',()=>{{
  const done=document.querySelectorAll('.done-cb:checked').length;
  const total=document.querySelectorAll('.done-cb').length;
  const el=document.getElementById('done-count');
  if(el) el.textContent=done+' / '+total+' done';
}}));
</script>
</body></html>"""
        return Response(page, mimetype='text/html')

    @bp.route('/api/export/audit.csv', methods=['GET'])
    @requires_auth
    def api_export_audit_csv():
        if g.user_role not in ('admin', 'superadmin'):
            return jsonify({"error": "Forbidden"}), 403
        try:
            limit = int_param(request.args.get('limit', 1000), 1000, 1, 5000)
            conn = state._get_conn()
            rows = conn.execute("""
                SELECT aa.at, aa.event, aa.actor, a.command, a.node, aa.risk_score, a.status, a.problem_key
                FROM action_audit aa LEFT JOIN actions a ON a.id=aa.action_id
                ORDER BY aa.at DESC LIMIT ?
            """, (limit,)).fetchall()
            conn.close()
            import io as _io
            import csv as _csv
            buf = _io.StringIO()
            w = _csv.writer(buf)
            w.writerow(['timestamp','event','actor','command','node','risk_score','action_status','problem_key'])
            for r in rows:
                w.writerow([r[0] or '', r[1] or '', r[2] or '', r[3] or '', r[4] or '', r[5] or '', r[6] or '', r[7] or ''])
            from flask import Response as _Resp
            return _Resp(buf.getvalue(), mimetype='text/csv',
                         headers={'Content-Disposition': f'attachment; filename=audit_{datetime.now().strftime("%Y%m%d")}.csv'})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/export/grafana_dashboard.json', methods=['GET'])
    @requires_auth
    def api_export_grafana():
        instance = getattr(config, 'INSTANCE_NAME', 'Sentinel')
        base_url = f"http://localhost:{getattr(config, 'WEB_PORT', 5050)}"
        dashboard = {
            "title": f"Sentinel — {instance}",
            "uid": "sentinel-main",
            "schemaVersion": 38,
            "refresh": "30s",
            "panels": [
                {"id":1,"type":"stat","title":"Active Issues","gridPos":{"x":0,"y":0,"w":4,"h":4},
                 "targets":[{"expr":"sentinel_active_issues","legendFormat":"Issues"}]},
                {"id":2,"type":"stat","title":"Agents Online","gridPos":{"x":4,"y":0,"w":4,"h":4},
                 "targets":[{"expr":"sentinel_agents_online","legendFormat":"Online"}]},
                {"id":3,"type":"gauge","title":"CPU %","gridPos":{"x":8,"y":0,"w":4,"h":4},
                 "targets":[{"expr":"sentinel_cpu_pct","legendFormat":"CPU"}],"options":{"reduceOptions":{"calcs":["lastNotNull"]},"thresholds":{"steps":[{"value":0,"color":"green"},{"value":75,"color":"orange"},{"value":90,"color":"red"}]}}},
                {"id":4,"type":"gauge","title":"RAM %","gridPos":{"x":12,"y":0,"w":4,"h":4},
                 "targets":[{"expr":"sentinel_ram_pct","legendFormat":"RAM"}],"options":{"reduceOptions":{"calcs":["lastNotNull"]},"thresholds":{"steps":[{"value":0,"color":"green"},{"value":75,"color":"orange"},{"value":90,"color":"red"}]}}},
                {"id":5,"type":"timeseries","title":"Issues over time","gridPos":{"x":0,"y":4,"w":12,"h":8},
                 "targets":[{"expr":"sentinel_active_issues","legendFormat":"Active"},{"expr":"sentinel_security_issues","legendFormat":"Security"}]},
                {"id":6,"type":"timeseries","title":"AI latency (ms)","gridPos":{"x":12,"y":4,"w":12,"h":8},
                 "targets":[{"expr":"sentinel_ai_avg_latency_ms","legendFormat":"Avg latency"}]},
            ],
            "__inputs":[{"name":"DS_PROMETHEUS","type":"datasource","pluginId":"prometheus","value":""}],
            "__requires":[{"type":"datasource","id":"prometheus","name":"Prometheus","version":"1.0.0"}],
            "annotations":{"list":[]},
            "description": f"Auto-generated by Sentinel Commander v{getattr(config,'VERSION','?')}. Import into Grafana, configure Prometheus datasource pointing to {base_url}/metrics."
        }
        return jsonify(dashboard), 200, {'Content-Disposition': 'attachment; filename=sentinel_grafana.json'}

    @bp.route('/api/export/db_backup', methods=['GET'])
    @requires_auth
    def export_db_backup():
        if g.user_role != 'superadmin':
            return jsonify({"error": "Pouze superadmin"}), 403
        import io
        import sqlite3 as _sq
        try:
            buf = io.BytesIO()
            src = _sq.connect(state.DB_FILE)
            dst = _sq.connect(':memory:')
            src.backup(dst)
            src.close()
            for line in dst.iterdump():
                buf.write((line + '\n').encode('utf-8'))
            dst.close()
            buf.seek(0)
            fname = f"sentinel_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
            service.log_event("db_backup", "DB backup exported", user=g.username)
            return Response(buf.read(), mimetype='text/plain',
                            headers={'Content-Disposition': f'attachment; filename={fname}'})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route('/api/history', methods=['GET'])
    @requires_auth
    def api_history():
        try:
            hist_path = config.PROJECT_ROOT / 'HISTORY.md'
            content = hist_path.read_text(encoding='utf-8')
            return jsonify({"content": content})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp

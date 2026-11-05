import json
import logging
import os
from flask import Blueprint, request, jsonify, g
from ..auth import requires_auth
from .. import config

logger = logging.getLogger("sentinel.rt")


def _rt_edit_ticket(rt_cfg, ticket_id, fields):
    """Edit RT ticket fields (Status, Owner, etc.)."""
    import urllib.request
    import urllib.parse
    import ssl

    url = (f"{rt_cfg['url'].rstrip('/')}{rt_cfg.get('api_path', '/REST/1.0')}"
           f"/ticket/{ticket_id}/edit")
    content = "\n".join(f"{k}: {v}" for k, v in fields.items())
    params = urllib.parse.urlencode({
        "user": rt_cfg["user"], "pass": rt_cfg["pass"], "content": content,
    }).encode()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, data=params)
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)
        body = resp.read().decode("utf-8", errors="replace")
        return "200" in body.split("\n")[0], body
    except Exception as e:
        logger.error(f"RT edit failed for #{ticket_id}: {e}")
        return False, str(e)


def _rt_comment_direct(rt_cfg, ticket_id, text):
    import urllib.request
    import urllib.parse
    import ssl

    url = (f"{rt_cfg['url'].rstrip('/')}{rt_cfg.get('api_path', '/REST/1.0')}"
           f"/ticket/{ticket_id}/comment")
    content = f"id: {ticket_id}\nAction: comment\nText: {text}"
    params = urllib.parse.urlencode({
        "user": rt_cfg["user"], "pass": rt_cfg["pass"], "content": content,
    }).encode()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, data=params)
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)
        body = resp.read().decode("utf-8", errors="replace")
        return "200" in body.split("\n")[0]
    except Exception as e:
        logger.error(f"RT comment failed: {e}")
        return False


def create_blueprint(service):
    bp = Blueprint("rt", __name__)

    @bp.route("/api/rt/comment", methods=["POST"])
    @requires_auth
    def rt_comment():
        if g.user_role not in ("admin", "superadmin", "operator"):
            return jsonify({"error": "Insufficient permissions"}), 403

        data = request.get_json(silent=True) or {}
        ticket_id = data.get("ticket_id")
        text = (data.get("text") or "").strip()

        if not ticket_id or not text:
            return jsonify({"error": "ticket_id and text required"}), 400

        rt_cfg = getattr(config, "RT_CONFIG", {})
        if not rt_cfg.get("enabled"):
            return jsonify({"error": "RT integration not enabled"}), 503

        ok = _rt_comment_direct(rt_cfg, ticket_id, text)
        if ok:
            logger.info(f"RT comment on #{ticket_id} by {g.username}")
            return jsonify({"ok": True,
                            "message": f"Comment posted to RT #{ticket_id}"})
        return jsonify({"error": "Failed to post comment to RT"}), 502

    @bp.route("/api/rt/tickets", methods=["GET"])
    @requires_auth
    def rt_tickets():
        rt_cfg = getattr(config, "RT_CONFIG", {})
        if not rt_cfg.get("enabled"):
            return jsonify({"error": "RT not enabled"}), 503

        q = request.args.get("q", "").lower()
        queue = request.args.get("queue", "")

        log_path = os.path.join(config.LOG_DIR, "rt.log")
        if not os.path.exists(log_path):
            return jsonify({"tickets": []})

        tickets = []
        try:
            with open(log_path) as f:
                for line in f:
                    try:
                        row = json.loads(line.strip())
                    except ValueError:
                        continue
                    if row.get("type") != "ticket":
                        continue
                    if queue and row.get("queue") != queue:
                        continue
                    if q and q not in row.get("subject", "").lower():
                        continue
                    tickets.append(row)
        except Exception:
            pass

        return jsonify({"tickets": tickets})

    @bp.route("/api/rt/take", methods=["POST"])
    @requires_auth
    def rt_take():
        if g.user_role not in ("admin", "superadmin", "operator"):
            return jsonify({"error": "Insufficient permissions"}), 403

        data = request.get_json(silent=True) or {}
        ticket_id = data.get("ticket_id")
        if not ticket_id:
            return jsonify({"error": "ticket_id required"}), 400

        rt_cfg = getattr(config, "RT_CONFIG", {})
        if not rt_cfg.get("enabled"):
            return jsonify({"error": "RT not enabled"}), 503

        ok, body = _rt_edit_ticket(rt_cfg, ticket_id, {
            "Owner": rt_cfg.get("user", ""),
            "Status": "open",
        })
        if ok:
            logger.info(f"RT #{ticket_id} taken by {g.username}")
            return jsonify({"ok": True, "message": f"Tiket #{ticket_id} převzat"})
        return jsonify({"error": f"RT edit failed: {body[:200]}"}), 502

    @bp.route("/api/rt/status", methods=["POST"])
    @requires_auth
    def rt_status():
        if g.user_role not in ("admin", "superadmin", "operator"):
            return jsonify({"error": "Insufficient permissions"}), 403

        data = request.get_json(silent=True) or {}
        ticket_id = data.get("ticket_id")
        new_status = data.get("status", "").strip().lower()
        if not ticket_id or not new_status:
            return jsonify({"error": "ticket_id and status required"}), 400
        if new_status not in ("new", "open", "stalled", "resolved", "rejected"):
            return jsonify({"error": "Invalid status"}), 400

        rt_cfg = getattr(config, "RT_CONFIG", {})
        if not rt_cfg.get("enabled"):
            return jsonify({"error": "RT not enabled"}), 503

        ok, body = _rt_edit_ticket(rt_cfg, ticket_id, {"Status": new_status})
        if ok:
            logger.info(f"RT #{ticket_id} status -> {new_status} by {g.username}")
            return jsonify({"ok": True,
                            "message": f"Tiket #{ticket_id} -> {new_status}"})
        return jsonify({"error": f"RT edit failed: {body[:200]}"}), 502

    return bp

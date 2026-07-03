import os
import json
import hmac
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from .. import config, utils

_LOG_DIR_CACHE = None

def _log_dir():
    global _LOG_DIR_CACHE
    if _LOG_DIR_CACHE is None:
        _LOG_DIR_CACHE = getattr(config, 'LOG_DIR', '/var/log/sentinel/logs')
    return _LOG_DIR_CACHE

def _verify_key() -> bool:
    key = getattr(config, 'WINDOWS_INGEST_KEY', '')
    if not key:
        return False
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False
    token = auth[7:]
    return hmac.compare_digest(token, key)

def create_blueprint(_service):
    bp = Blueprint('windows_ingest', __name__)

    @bp.route('/api/ingest/windows', methods=['POST'])
    def ingest_windows():
        if not _verify_key():
            return jsonify({'error': 'Unauthorized'}), 403

        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if not body or 'host' not in body or 'events' not in body:
            return jsonify({'error': 'Invalid payload'}), 400

        host   = str(body['host']).lower().replace('/', '_').replace('..', '')[:64]
        events = body.get('events', [])
        if not isinstance(events, list):
            return jsonify({'error': 'events must be array'}), 400

        log_path = os.path.join(_log_dir(), f'windows-{host}.log')
        accepted = 0
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                for ev in events[:500]:  # max 500 per request
                    if not isinstance(ev, dict):
                        continue
                    ev['_host'] = host
                    ev['_recv'] = datetime.now(timezone.utc).isoformat()
                    f.write(json.dumps(ev, ensure_ascii=False) + '\n')
                    accepted += 1
        except Exception as e:
            utils.log_message(f'[windows_ingest] write error: {e}')
            return jsonify({'error': 'write failed'}), 500

        return jsonify({'accepted': accepted}), 200

    return bp

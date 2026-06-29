import threading
import logging
import sqlite3
import json
import os
import time
import secrets
from queue import Queue
from datetime import datetime, timezone, timedelta
from . import config
from . import utils

logger = logging.getLogger(__name__)

# DB musí ležet MIMO inotify-sledovaný LOG_DIR. Když je uvnitř, každý DB zápis
# (-wal/-shm) budí watcher a soutěží o disk I/O s log churnem (8 get-* timerů
# zapisuje logy každou minutu) → sqlite3.connect() tuhne → watchdog SIGABRT.
_DB_DIR = os.environ.get("SENTINEL_DB_DIR") or "/var/lib/sentinel"
try:
    os.makedirs(_DB_DIR, exist_ok=True)
except Exception:
    _DB_DIR = config.LOG_DIR  # fallback (zpětná kompatibilita)
DB_FILE = os.path.join(_DB_DIR, "sentinel_state.db")
db_lock = threading.Lock()

def _db_file():
    """Returns current DB_FILE, respecting overrides set on sentinel.state (used by tests)."""
    import sys
    m = sys.modules.get('sentinel.state')
    if m is None:
        return DB_FILE
    v = m.__dict__.get('DB_FILE')
    return v if v else DB_FILE

class _DBErrorHandler(logging.Handler):
    """Zapisuje ERROR+ záznamy z libovolného sentinel loggeru do tabulky sentinel_errors."""
    def emit(self, record):
        if record.levelno < logging.ERROR:
            return
        try:
            msg = self.format(record)
            tb = None
            if record.exc_info:
                import traceback as _tb
                tb = ''.join(_tb.format_exception(*record.exc_info))
            conn = sqlite3.connect(_db_file(), timeout=5.0, isolation_level=None)
            conn.execute(
                "INSERT INTO sentinel_errors (source, level, message, traceback) VALUES (?,?,?,?)",
                (record.name[:64], record.levelname, msg[:1000], (tb or '')[:2000])
            )
            conn.close()
        except Exception:
            pass  # Nesmí rekurzivně selhat

_db_error_handler = _DBErrorHandler()
_db_error_handler.setLevel(logging.ERROR)
logging.getLogger('sentinel').addHandler(_db_error_handler)

shutdown_event = threading.Event()

# 425: Issue lifecycle webhook callbacks — registered by ChatService
# Each callback: fn(event: str, issue: dict)
_issue_lifecycle_callbacks: list = []

def _get_conn():
    conn = sqlite3.connect(_db_file(), timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=15000")
    return conn

def init_db():
    try:
        with db_lock:
            conn = sqlite3.connect(_db_file())
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA wal_autocheckpoint=500;')
            conn.execute('PRAGMA busy_timeout=15000;')
            c = conn.cursor()
            
            c.execute('''CREATE TABLE IF NOT EXISTS problems
                         (key TEXT PRIMARY KEY,
                          status TEXT,
                          channel_type TEXT,
                          last_seen TEXT,
                          missing_count INTEGER,
                          details TEXT,
                          snoozed_until TEXT DEFAULT NULL)''')

            # Idempotent migration for pre-existing DBs (problems)
            c.execute("PRAGMA table_info(problems)")
            _prob_cols = {r[1] for r in c.fetchall()}
            if 'snoozed_until' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN snoozed_until TEXT DEFAULT NULL")
            if 'plugin_name' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN plugin_name TEXT DEFAULT NULL")
                c.execute("UPDATE problems SET plugin_name = json_extract(details, '$.plugin_name') WHERE plugin_name IS NULL")
            if 'host' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN host TEXT DEFAULT NULL")
                c.execute("UPDATE problems SET host = json_extract(details, '$.host') WHERE host IS NULL")
            if 'last_line' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN last_line TEXT DEFAULT NULL")
                c.execute("UPDATE problems SET last_line = json_extract(details, '$.last_line') WHERE last_line IS NULL")
            if 'occurrence_count' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN occurrence_count INTEGER DEFAULT 1")
            if 'first_seen' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN first_seen TEXT DEFAULT NULL")
                c.execute("UPDATE problems SET first_seen = last_seen WHERE first_seen IS NULL")
            if 'severity' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN severity TEXT DEFAULT NULL")
            if 'acknowledged_by' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN acknowledged_by TEXT DEFAULT NULL")
            if 'acknowledged_at' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN acknowledged_at TEXT DEFAULT NULL")
            if 'label_color' not in _prob_cols:
                c.execute("ALTER TABLE problems ADD COLUMN label_color TEXT DEFAULT NULL")

            c.execute('''CREATE TABLE IF NOT EXISTS actions
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          problem_key TEXT,
                          cluster TEXT,
                          node TEXT,
                          command TEXT,
                          reason TEXT,
                          status TEXT,
                          created_at TEXT,
                          executed_at TEXT,
                          output TEXT,
                          executed_by TEXT,
                          mode TEXT NOT NULL DEFAULT 'dry_run',
                          dry_run_output TEXT,
                          risk_score INTEGER DEFAULT 0,
                          risk_reasons TEXT,
                          raw_line TEXT)''')

            # Idempotent migration for pre-existing DBs
            c.execute("PRAGMA table_info(actions)")
            _existing_cols = {r[1] for r in c.fetchall()}
            for _col, _ddl in (
                ("mode", "TEXT NOT NULL DEFAULT 'dry_run'"),
                ("dry_run_output", "TEXT"),
                ("risk_score", "INTEGER DEFAULT 0"),
                ("risk_reasons", "TEXT"),
                ("raw_line", "TEXT"),
            ):
                if _col not in _existing_cols:
                    c.execute(f"ALTER TABLE actions ADD COLUMN {_col} {_ddl}")

            c.execute('''CREATE TABLE IF NOT EXISTS issue_user_order
                         (username TEXT NOT NULL,
                          channel TEXT NOT NULL,
                          issue_key TEXT NOT NULL,
                          position INTEGER NOT NULL,
                          PRIMARY KEY (username, channel, issue_key))''')

            c.execute('''CREATE TABLE IF NOT EXISTS task_queue
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          priority INTEGER DEFAULT 1,
                          payload TEXT,
                          status TEXT DEFAULT 'pending',
                          created_at TEXT,
                          processed_at TEXT,
                          worker_id TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS telemetry
                         (id INTEGER PRIMARY KEY, 
                          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                          category TEXT, 
                          metric TEXT, 
                          value REAL)''')

            c.execute('''CREATE TABLE IF NOT EXISTS agents
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          hostname TEXT UNIQUE,
                          token TEXT,
                          registered_at TEXT,
                          last_seen TEXT,
                          status TEXT,
                          ignore_offline INTEGER DEFAULT 0)''')

            # Idempotent migration for pre-existing DBs
            c.execute("PRAGMA table_info(agents)")
            _agent_cols = {r[1] for r in c.fetchall()}
            if 'ignore_offline' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN ignore_offline INTEGER DEFAULT 0")
            if 'notes' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN notes TEXT DEFAULT ''")
            if 'category' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN category TEXT")
                c.execute("UPDATE agents SET category='hw' WHERE hostname LIKE 'sentinel-hw-%'")
                c.execute("UPDATE agents SET category='alert' WHERE hostname LIKE 'sentinel-alert%'")
            # Backfill missing registered_at from last_seen for pre-existing agents
            c.execute("UPDATE agents SET registered_at=last_seen WHERE registered_at IS NULL AND last_seen IS NOT NULL")
            if 'ip_addresses' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN ip_addresses TEXT DEFAULT '[]'")
            if 'agent_group' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN agent_group TEXT DEFAULT NULL")
            if 'maintenance_until' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN maintenance_until TEXT DEFAULT NULL")
            if 'agent_version' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN agent_version TEXT DEFAULT NULL")
            if 'last_data_lag_ms' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN last_data_lag_ms INTEGER DEFAULT NULL")
            if 'labels' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN labels TEXT DEFAULT '{}'")  # 038
            if 'heartbeat_timeout' not in _agent_cols:
                c.execute("ALTER TABLE agents ADD COLUMN heartbeat_timeout INTEGER DEFAULT NULL")  # 037

            c.execute('''CREATE TABLE IF NOT EXISTS issue_history
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          key TEXT NOT NULL,
                          channel_type TEXT,
                          host TEXT,
                          plugin_name TEXT,
                          last_line TEXT,
                          first_seen TEXT,
                          last_seen TEXT,
                          resolved_at TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_issue_history_host ON issue_history(host)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_issue_history_resolved ON issue_history(resolved_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_issue_history_channel ON issue_history(channel_type)')

            c.execute('''CREATE TABLE IF NOT EXISTS root_audit
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          server TEXT, ip TEXT, connected_at TEXT,
                          disconnected_at TEXT, is_active INTEGER)''')

            c.execute('''CREATE TABLE IF NOT EXISTS action_audit
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          action_id INTEGER NOT NULL,
                          event TEXT NOT NULL,
                          actor TEXT,
                          at TEXT NOT NULL,
                          risk_score INTEGER,
                          details TEXT)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_action_audit_action ON action_audit(action_id, at)')
            # Performance indexes
            c.execute('CREATE INDEX IF NOT EXISTS idx_problems_channel ON problems(channel_type)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_problems_last_seen ON problems(last_seen)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_problems_plugin ON problems(plugin_name)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_problems_host ON problems(host)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_root_audit_server ON root_audit(server, is_active)')

            c.execute('''CREATE TABLE IF NOT EXISTS allowed_commands
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          pattern TEXT NOT NULL,
                          description TEXT DEFAULT '',
                          auto_execute INTEGER DEFAULT 0,
                          risk_max INTEGER DEFAULT 30,
                          note TEXT DEFAULT '',
                          created_at TEXT)''')

            c.execute('CREATE INDEX IF NOT EXISTS idx_telemetry_metric ON telemetry(metric, timestamp)')

            c.execute('''CREATE TABLE IF NOT EXISTS issue_comments
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          problem_key TEXT NOT NULL,
                          author TEXT NOT NULL,
                          text TEXT NOT NULL,
                          created_at TEXT DEFAULT (datetime('now')))''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_issue_comments_key ON issue_comments(problem_key)')

            c.execute('''CREATE TABLE IF NOT EXISTS snooze_rules
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT NOT NULL,
                          channels TEXT DEFAULT '*',
                          start_hour INTEGER NOT NULL,
                          end_hour INTEGER NOT NULL,
                          days TEXT DEFAULT '*',
                          hosts TEXT DEFAULT NULL,
                          enabled INTEGER DEFAULT 1,
                          created_at TEXT)''')
            # 207 — migrate existing snooze_rules tables that lack the hosts column
            _snooze_cols = {row[1] for row in c.execute("PRAGMA table_info(snooze_rules)").fetchall()}
            if 'hosts' not in _snooze_cols:
                c.execute("ALTER TABLE snooze_rules ADD COLUMN hosts TEXT DEFAULT NULL")

            c.execute('''CREATE TABLE IF NOT EXISTS user_roles
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          username TEXT UNIQUE NOT NULL,
                          role TEXT NOT NULL,
                          updated_at TEXT DEFAULT (datetime('now')))''')

            c.execute('''CREATE TABLE IF NOT EXISTS kv_settings
                         (key TEXT PRIMARY KEY,
                          value TEXT NOT NULL,
                          updated_at TEXT DEFAULT (datetime('now')))''')

            c.execute('''CREATE TABLE IF NOT EXISTS suppress_rules
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          host_pattern TEXT NOT NULL,
                          plugin_pattern TEXT NOT NULL,
                          reason TEXT DEFAULT '',
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')),
                          expires_at TEXT DEFAULT NULL)''')

            c.execute('''CREATE TABLE IF NOT EXISTS issue_tags
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          problem_key TEXT NOT NULL,
                          tag TEXT NOT NULL,
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')))''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_issue_tags_key ON issue_tags(problem_key)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_issue_tags_tag ON issue_tags(tag)')

            c.execute('''CREATE TABLE IF NOT EXISTS auto_remediation_log
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          problem_key TEXT NOT NULL,
                          command TEXT NOT NULL,
                          host TEXT,
                          attempted_at TEXT DEFAULT (datetime('now')),
                          success INTEGER DEFAULT 0,
                          output TEXT)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_autorem_key ON auto_remediation_log(problem_key)')

            c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT NOT NULL,
                          key_hash TEXT NOT NULL UNIQUE,
                          scope TEXT DEFAULT 'read',
                          expires_at TEXT DEFAULT NULL,
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')),
                          last_used TEXT DEFAULT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)')

            c.execute('''CREATE TABLE IF NOT EXISTS comment_templates
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT NOT NULL,
                          text TEXT NOT NULL,
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')))''')

            c.execute('''CREATE TABLE IF NOT EXISTS sentinel_errors
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          timestamp TEXT DEFAULT (datetime('now')),
                          source TEXT NOT NULL,
                          level TEXT DEFAULT 'ERROR',
                          message TEXT NOT NULL,
                          traceback TEXT DEFAULT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_sentinel_errors_ts ON sentinel_errors(timestamp)')

            c.execute('''CREATE TABLE IF NOT EXISTS agent_config_queue
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          hostname TEXT NOT NULL,
                          config_json TEXT NOT NULL,
                          created_at TEXT DEFAULT (datetime('now')),
                          delivered_at TEXT DEFAULT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_agent_cfg_host ON agent_config_queue(hostname, delivered_at)')

            c.execute('''CREATE TABLE IF NOT EXISTS health_snapshots
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          timestamp TEXT DEFAULT (datetime('now')),
                          score INTEGER NOT NULL,
                          issues_count INTEGER DEFAULT 0,
                          agents_online INTEGER DEFAULT 0,
                          agents_total INTEGER DEFAULT 0)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_health_snap_ts ON health_snapshots(timestamp)')

            # 219: Internal wiki
            c.execute('''CREATE TABLE IF NOT EXISTS wiki_pages
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          slug TEXT UNIQUE NOT NULL,
                          title TEXT NOT NULL,
                          content TEXT DEFAULT '',
                          updated_at TEXT DEFAULT (datetime('now')),
                          updated_by TEXT DEFAULT '')''')

            c.execute('''CREATE TABLE IF NOT EXISTS custom_patterns
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          name TEXT NOT NULL,
                          plugin TEXT NOT NULL,
                          pattern TEXT NOT NULL,
                          channel TEXT DEFAULT 'agent',
                          enabled INTEGER DEFAULT 1,
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')))''')

            c.execute('''CREATE TABLE IF NOT EXISTS runbooks
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          issue_type TEXT NOT NULL UNIQUE,
                          plugin TEXT DEFAULT '',
                          channel TEXT DEFAULT '',
                          content TEXT NOT NULL,
                          created_by TEXT DEFAULT 'AI',
                          updated_at TEXT DEFAULT (datetime('now')))''')

            c.execute('''CREATE TABLE IF NOT EXISTS ssh_execute_log
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          hostname TEXT NOT NULL,
                          command TEXT NOT NULL,
                          actor TEXT DEFAULT '',
                          executed_at TEXT DEFAULT (datetime('now')),
                          success INTEGER DEFAULT 0,
                          output TEXT DEFAULT '')''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_ssh_log_host ON ssh_execute_log(hostname, executed_at)')

            c.execute('''CREATE TABLE IF NOT EXISTS agent_thresholds
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          hostname TEXT NOT NULL,
                          metric_pattern TEXT NOT NULL,
                          above REAL DEFAULT NULL,
                          below REAL DEFAULT NULL,
                          channel TEXT DEFAULT 'agent',
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')))''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_agent_thresh_host ON agent_thresholds(hostname)')

            c.execute('''CREATE TABLE IF NOT EXISTS config_history
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          timestamp TEXT DEFAULT (datetime('now')),
                          content TEXT NOT NULL,
                          content_hash TEXT NOT NULL)''')

            c.execute('''CREATE TABLE IF NOT EXISTS active_sessions
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          session_uuid TEXT NOT NULL UNIQUE,
                          username TEXT NOT NULL,
                          role TEXT DEFAULT 'viewer',
                          ip TEXT DEFAULT '',
                          user_agent TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')),
                          last_seen TEXT DEFAULT (datetime('now')))''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_uuid ON active_sessions(session_uuid)')

            # merged_into column for issue merge
            c.execute("PRAGMA table_info(problems)")
            _prob_cols2 = {r[1] for r in c.fetchall()}
            if 'merged_into' not in _prob_cols2:
                c.execute("ALTER TABLE problems ADD COLUMN merged_into TEXT DEFAULT NULL")
            if 'assigned_to' not in _prob_cols2:
                c.execute("ALTER TABLE problems ADD COLUMN assigned_to TEXT DEFAULT NULL")
            if 'depends_on' not in _prob_cols2:
                c.execute("ALTER TABLE problems ADD COLUMN depends_on TEXT DEFAULT '[]'")

            # Seed výchozích allowed_commands pro auto-remediaci (jen pokud tabulka prázdná)
            existing_cmds = c.execute("SELECT COUNT(*) FROM allowed_commands").fetchone()[0]
            if existing_cmds == 0:
                _now = datetime.now(timezone.utc).isoformat()
                _defaults = [
                    ("systemctl restart *.service", "Restart systemd service (auto-remediation)", 1, 25, "Automatický restart selhaných služeb"),
                    ("mount -a", "Mount all filesystems from /etc/fstab", 1, 20, "Automatické připojení souborových systémů"),
                    ("systemctl restart *", "Restart any systemd unit", 0, 30, "Manuální restart — vyžaduje schválení"),
                    ("journalctl --rotate && journalctl --vacuum-time=7d", "Rotate and vacuum journal logs", 0, 10, "Údržba logů"),
                    ("df -h", "Disk usage overview", 1, 5, "Bezpečný diagnostický příkaz"),
                    ("systemctl status *.service", "Check service status", 1, 5, "Bezpečný diagnostický příkaz"),
                ]
                for pattern, desc, auto_ex, risk, note in _defaults:
                    c.execute(
                        "INSERT INTO allowed_commands (pattern, description, auto_execute, risk_max, note, created_at) VALUES (?,?,?,?,?,?)",
                        (pattern, desc, auto_ex, risk, note, _now)
                    )

            c.execute("UPDATE task_queue SET status='pending' WHERE status='processing'")

            c.execute('''CREATE TABLE IF NOT EXISTS false_positive_patterns
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          plugin_name TEXT NOT NULL,
                          host_pattern TEXT NOT NULL DEFAULT '*',
                          msg_pattern TEXT NOT NULL,
                          created_by TEXT DEFAULT '',
                          created_at TEXT DEFAULT (datetime('now')),
                          hit_count INTEGER DEFAULT 0)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_fp_plugin ON false_positive_patterns(plugin_name)')

            # 427: Prompt library table
            c.execute('''CREATE TABLE IF NOT EXISTS prompt_library
                         (name TEXT PRIMARY KEY,
                          template TEXT NOT NULL,
                          updated_by TEXT DEFAULT '',
                          updated_at TEXT DEFAULT (datetime('now')))''')

            # 346: TOTP 2FA — per-user secret + enabled flag
            c.execute('''CREATE TABLE IF NOT EXISTS user_totp
                         (username TEXT PRIMARY KEY,
                          totp_secret TEXT NOT NULL,
                          enabled INTEGER DEFAULT 0,
                          created_at TEXT DEFAULT (datetime('now')))''')

            # infra_jokes: log vtipu generovaného AI (dvouklik logo + hodinový)
            c.execute('''CREATE TABLE IF NOT EXISTS infra_jokes
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          joke TEXT NOT NULL,
                          source TEXT DEFAULT 'manual',
                          created_at TEXT DEFAULT (datetime('now')))''')

            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Failed to init DB: {e}")

init_db()

class DBQueueAdapter:
    def put(self, item):
        priority = 1
        if isinstance(item, dict):
            channel = item.get("channel", "general")
            if channel in ["security", "racks", "root", "infra"]: 
                priority = 10
            elif item.get("type") == "ai_request": 
                priority = 5
        
        try:
            json_payload = json.dumps(item)
            with db_lock:
                conn = _get_conn()
                now = datetime.now(timezone.utc).isoformat()
                conn.execute("INSERT INTO task_queue (priority, payload, status, created_at) VALUES (?, ?, 'pending', ?)",
                             (priority, json_payload, now))
                conn.commit()
                conn.close()
        except Exception as e:
            logger.error(f"Failed to enqueue task: {e}")

ollama_queue = DBQueueAdapter()
frontend_queue = Queue() 

def fetch_next_task(worker_id):
    with db_lock:
        try:
            conn = _get_conn()
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT id, payload FROM task_queue 
                WHERE status='pending' 
                ORDER BY priority DESC, created_at ASC 
                LIMIT 1
            """)
            row = c.fetchone()
            if row:
                task_id = row['id']
                now = datetime.now(timezone.utc).isoformat()
                c.execute("UPDATE task_queue SET status='processing', processed_at=?, worker_id=? WHERE id=?",
                          (now, worker_id, task_id))
                conn.commit()
                conn.close()
                return {"id": task_id, "payload": json.loads(row['payload'])}
            conn.close()
            return None
        except Exception as e:
            logger.error(f"DB Error fetch_next_task: {e}")
            return None

def complete_task(task_id):
    with db_lock:
        try:
            conn = _get_conn()
            conn.execute("DELETE FROM task_queue WHERE id=?", (task_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Error complete_task: {e}")


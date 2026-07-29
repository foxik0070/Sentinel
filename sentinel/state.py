# Facade: re-exports all symbols from sub-modules.
# Other files use `from . import state` and call e.g. `state.save_problem()` — unchanged.
from .state_base import (
    logger, DB_FILE, db_lock, shutdown_event,
    _get_conn, init_db,
    _DBErrorHandler,
    DBQueueAdapter, ollama_queue, frontend_queue,
    fetch_next_task, complete_task,
)
from .state_issues import *
from .state_issues import (
    _telemetry_flush_loop, _flush_telemetry_buffer, _write_influxdb,
    _archive_problem, _try_auto_remediate,
    _get_suppress_rules, _is_suppressed, _hash_api_key,
    _telemetry_buffer, _telemetry_buffer_lock,
)
from .state_agents import *

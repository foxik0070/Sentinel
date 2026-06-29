"""
M2-1: Scheduler — background maintenance loop izolovaný od ChatService.

Spuštění (z ChatService.run()):
    from sentinel.scheduler import Scheduler
    sched = Scheduler(service)
    threading.Thread(target=sched.run, daemon=True, name="Scheduler").start()
"""
import logging
import math
import os
import threading
import time
from datetime import datetime

from . import config, state

logger = logging.getLogger("sentinel.scheduler")


class Scheduler:
    """Provádí pravidelné údržbové úlohy v pozadí."""

    _last_joke_hour: int = -1
    _last_weekly_report_date = None

    def __init__(self, service):
        self._service = service

    def run(self) -> None:
        self._service.log_event("task_scheduler", "Scheduler started.")
        last_cleanup_date = None
        last_report_date = None
        last_snooze_check: float = 0

        while True:
            try:
                now = datetime.now()

                # ── Noční cleanup (03:00) ─────────────────────────────────────
                if now.hour == 3 and now.minute == 0 and last_cleanup_date != now.date():
                    self._nightly_cleanup(now)
                    last_cleanup_date = now.date()

                # ── Denní report ──────────────────────────────────────────────
                _report_hour = int(getattr(config, 'ANALYTICS', {}).get('daily_report_hour', 8))
                if (now.hour == _report_hour and now.minute == 0
                        and last_report_date != now.date()):
                    last_report_date = now.date()
                    threading.Thread(target=self._service._send_daily_report,
                                     daemon=True, name="DailyReport").start()

                # ── Každominutové úlohy ───────────────────────────────────────
                cur_ts = time.time()
                if cur_ts - last_snooze_check >= 60:
                    self._minutely_tasks()
                    last_snooze_check = cur_ts

                # ── Hodinové úlohy ────────────────────────────────────────────
                if now.minute == 0 and now.hour != Scheduler._last_joke_hour:
                    Scheduler._last_joke_hour = now.hour
                    self._hourly_tasks()

                # ── Týdenní digest ────────────────────────────────────────────
                _wr_day = int(getattr(config, 'WEEKLY_REPORT_DAY', 0))
                _wr_hour = int(getattr(config, 'WEEKLY_REPORT_HOUR', 8))
                if (now.weekday() == _wr_day and now.hour == _wr_hour
                        and now.minute == 0
                        and Scheduler._last_weekly_report_date != now.date()):
                    Scheduler._last_weekly_report_date = now.date()
                    threading.Thread(target=self._service._send_weekly_report,
                                     daemon=True, name="WeeklyReport").start()

                time.sleep(30)
            except Exception as e:
                self._service.log_event("maintenance_error", str(e),
                                        level=logging.ERROR)
                time.sleep(60)

    # ── Interní metody ────────────────────────────────────────────────────────

    def _nightly_cleanup(self, now: datetime) -> None:
        retention = getattr(config, 'DB_RETENTION_DAYS', 2)
        self._service.log_event(
            "maintenance",
            f"Running telemetry cleanup (3:00 AM, retention={retention}d)...")
        state.prune_telemetry(days=retention)
        state.prune_sentinel_errors(days=7)
        state.prune_health_snapshots(days=30)
        state.prune_stale_sessions(hours=24)
        state.prune_revoked_sessions(days=30)

        _agg_hours = getattr(config, 'TELEMETRY_AGGREGATE_AFTER_HOURS', 24)
        if _agg_hours > 0:
            threading.Thread(target=state.aggregate_telemetry, args=(_agg_hours,),
                             daemon=True, name="TelemetryAgg").start()
        if now.weekday() == 6:
            threading.Thread(target=state.run_db_vacuum,
                             daemon=True, name="DBVacuum").start()
            self._service.log_event("maintenance", "DB VACUUM spuštěn (neděle 03:00)")

        self._service.last_cleanup_time = datetime.now()
        db_path = os.path.abspath(state.DB_FILE)
        db_size = _format_size(os.path.getsize(db_path)) if os.path.exists(db_path) else "N/A"
        self._service.log_event("maintenance_done", f"Cleanup finished. DB size: {db_size}")

    def _minutely_tasks(self) -> None:
        state.apply_snooze_rules()
        state.auto_resolve_old_problems(days=getattr(config, 'DB_RETENTION_DAYS', 30))
        self._service._run_escalation_rules()
        self._service._save_health_snapshot()
        self._service._run_self_monitor_webhook()
        self._service._save_sentinel_self_metrics()
        # FIM check
        try:
            from . import watcher as _watcher
            _watcher.fim_check()
        except Exception as e:
            logger.warning(f"fim_check: {e}")
        # Sentinel health checks (DB size, synthetic HTTP, no-agent)
        threading.Thread(target=self._service._run_sentinel_health_checks,
                         daemon=True, name="SentinelHealthChecks").start()

    def _hourly_tasks(self) -> None:
        # Joke log
        threading.Thread(target=self._service._generate_hourly_joke,
                         daemon=True, name="HourlyJoke").start()
        # Geo-IP cache prune
        try:
            from .routes.agents import _geo_cache  # type: ignore
            now_t = time.time()
            for ip in list(_geo_cache):
                if now_t - _geo_cache[ip].get('ts', 0) > 3600:
                    del _geo_cache[ip]
        except Exception as e:
            logger.warning(f"geo_cache_prune: {e}")
        # Session GC
        try:
            timeout = 3600 * 24
            now_t = time.time()
            for sid in list(self._service.user_sessions):
                if now_t - self._service.user_sessions[sid].get('last_seen', 0) > timeout:
                    del self._service.user_sessions[sid]
        except Exception as e:
            logger.warning(f"session_gc: {e}")


def _format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    return f"{round(size_bytes / math.pow(1024, i), 2)} {units[i]}"

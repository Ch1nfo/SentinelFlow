from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta

from sentinelflow.config.runtime import load_runtime_config
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.dispatch_service import AlertDispatchService


class WeeklyAlertCleanupService:
    def __init__(
        self,
        dispatch_service: AlertDispatchService,
        audit_service: AuditService,
        check_interval_seconds: float = 300.0,
    ) -> None:
        self.dispatch_service = dispatch_service
        self.audit_service = audit_service
        self.check_interval_seconds = check_interval_seconds
        self._loop_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_cleanup_week: str = ""

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run_loop(), name="sentinelflow-weekly-alert-cleanup")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._loop_task:
            try:
                await self._loop_task
            finally:
                self._loop_task = None

    def run_due_cleanup(self, now: datetime | None = None) -> int:
        config = load_runtime_config()
        if not config.weekly_alert_cleanup_enabled:
            return 0

        current = now or datetime.now().astimezone()
        week_start = datetime.combine(current.date() - timedelta(days=current.weekday()), time.min, tzinfo=current.tzinfo)
        cleanup_at = week_start + timedelta(hours=1)
        week_key = week_start.date().isoformat()
        if current < cleanup_at or self._last_cleanup_week == week_key:
            return 0

        deleted = self.dispatch_service.delete_tasks_before(week_start)
        self._last_cleanup_week = week_key
        self.audit_service.record(
            "weekly_alert_cleanup_checked",
            "Weekly alert cleanup completed.",
            {
                "deleted": deleted,
                "cutoff": week_start.isoformat(),
                "cleanupAt": cleanup_at.isoformat(),
            },
        )
        return deleted

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_due_cleanup()
            except Exception as exc:
                self.audit_service.record(
                    "weekly_alert_cleanup_failed",
                    "Weekly alert cleanup failed.",
                    {"error": str(exc)},
                )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.check_interval_seconds)
            except asyncio.TimeoutError:
                continue

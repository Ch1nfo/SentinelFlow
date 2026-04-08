from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.dispatch_service import AlertDispatchService

if TYPE_CHECKING:
    from sentinelflow.services.task_runner_service import AlertTaskRunnerService


class AlertAutoExecutionService:
    def __init__(
        self,
        dispatch_service: AlertDispatchService,
        task_runner_service: "AlertTaskRunnerService",
        audit_service: AuditService,
        interval_seconds: float = 1.0,
    ) -> None:
        self.dispatch_service = dispatch_service
        self.task_runner_service = task_runner_service
        self.audit_service = audit_service
        self.interval_seconds = interval_seconds
        self._enabled = False
        self._running = False
        self._loop_task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run_loop(), name="sentinelflow-auto-executor")

    async def stop(self) -> None:
        self._enabled = False
        self._stop_event.set()
        self._wake_event.set()
        if self._loop_task:
            try:
                await self._loop_task
            finally:
                self._loop_task = None

    def enable(self) -> None:
        if self._enabled:
            return
        self._enabled = True
        self.audit_service.record("auto_execution_enabled", "Enabled continuous automatic alert execution.", {})
        self._wake_event.set()

    def disable(self) -> None:
        if not self._enabled:
            return
        self._enabled = False
        self.audit_service.record("auto_execution_disabled", "Disabled continuous automatic alert execution.", {})
        self._wake_event.set()

    def state(self) -> dict[str, bool]:
        return {
            "enabled": self._enabled,
            "running": self._running,
        }

    def apply_persisted_state(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._wake_event.set()

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._enabled:
                await self._wait_for_wake()
                continue

            await self._run_pending_once()
            if self._stop_event.is_set():
                break
            await self._wait_for_wake(timeout=self.interval_seconds)

    async def _wait_for_wake(self, timeout: float | None = None) -> bool:
        self._wake_event.clear()
        if timeout is None:
            await self._wake_event.wait()
            return True
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _run_pending_once(self) -> list[dict[str, Any]]:
        queued_tasks = [task for task in self.dispatch_service.list_tasks() if task.status == "queued"]
        if not queued_tasks:
            return []

        self._running = True
        results: list[dict[str, Any]] = []
        try:
            for task in queued_tasks:
                if self._stop_event.is_set() or not self._enabled:
                    break
                results.append(await self.task_runner_service.run_task(task))
        finally:
            self._running = False
        return results

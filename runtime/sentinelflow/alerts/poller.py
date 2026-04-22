from __future__ import annotations

import asyncio
import threading

from sentinelflow.alerts.client import SOCAlertApiClient
from sentinelflow.alerts.dedup import AlertDedupStore
from sentinelflow.domain.models import PollingDispatchResult
from sentinelflow.services.dispatch_service import AlertDispatchService
from sentinelflow.config.runtime import load_runtime_config


class AlertPollingService:
    def __init__(
        self,
        client: SOCAlertApiClient,
        dedup: AlertDedupStore,
        dispatch_service: AlertDispatchService,
    ) -> None:
        self.client = client
        self.dedup = dedup
        self.dispatch_service = dispatch_service
        self._latest_result = PollingDispatchResult(tasks=self.dispatch_service.list_tasks())
        self._loop_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._wake_lock = threading.Lock()
        self._wake_requested = False

    def get_latest_result(self) -> PollingDispatchResult:
        return PollingDispatchResult(
            fetched_count=self._latest_result.fetched_count,
            queued_count=self._latest_result.queued_count,
            updated_count=self._latest_result.updated_count,
            completed_count=self._latest_result.completed_count,
            skipped_count=self._latest_result.skipped_count,
            failed_count=self._latest_result.failed_count,
            snapshot_complete=self._latest_result.snapshot_complete,
            auto_execute_enabled=self._latest_result.auto_execute_enabled,
            auto_execute_running=self._latest_result.auto_execute_running,
            tasks=self.dispatch_service.list_tasks(),
            errors=list(self._latest_result.errors),
        )

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._wake_requested = False
        self._loop_task = asyncio.create_task(self._run_scheduler(), name="sentinelflow-alert-poller")

    async def stop(self) -> None:
        self._signal_event(self._stop_event)
        self._signal_event(self._wake_event)
        if self._loop_task:
            try:
                await self._loop_task
            finally:
                self._loop_task = None
                self._loop = None

    def refresh_schedule(self) -> None:
        self._request_wake()

    def _signal_event(self, event: asyncio.Event) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            event.set()
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            event.set()
            return
        loop.call_soon_threadsafe(event.set)

    def _request_wake(self) -> None:
        with self._wake_lock:
            self._wake_requested = True
        self._signal_event(self._wake_event)

    def _consume_wake_request(self) -> bool:
        with self._wake_lock:
            if not self._wake_requested:
                return False
            self._wake_requested = False
            return True

    async def _run_scheduler(self) -> None:
        while not self._stop_event.is_set():
            config = load_runtime_config()
            interval = max(int(config.poll_interval_seconds or 0), 0)
            if not config.alert_source_enabled or interval <= 0:
                await self._wait_for_reconfigure()
                continue

            reconfigured = await self._wait_for_reconfigure(timeout=interval)
            if reconfigured or self._stop_event.is_set():
                continue

            await self.poll_once()

    async def _wait_for_reconfigure(self, timeout: int | None = None) -> bool:
        if self._consume_wake_request():
            return True
        self._wake_event.clear()
        if self._consume_wake_request():
            return True
        if timeout is None:
            await self._wake_event.wait()
            return self._consume_wake_request() or True
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=timeout)
            return self._consume_wake_request() or True
        except asyncio.TimeoutError:
            return self._consume_wake_request()

    async def poll_once(self) -> PollingDispatchResult:
        response = self.client.fetch_open_alerts()
        if "error" in response:
            self._latest_result = PollingDispatchResult(
                fetched_count=0,
                queued_count=0,
                skipped_count=0,
                failed_count=1,
                snapshot_complete=False,
                auto_execute_enabled=self._latest_result.auto_execute_enabled,
                auto_execute_running=self._latest_result.auto_execute_running,
                errors=[str(response.get("error", "Unknown polling error"))],
            )
            return self.get_latest_result()

        alerts = response.get("alerts", [])
        if not isinstance(alerts, list):
            self._latest_result = PollingDispatchResult(
                fetched_count=0,
                queued_count=0,
                skipped_count=0,
                failed_count=1,
                snapshot_complete=False,
                auto_execute_enabled=self._latest_result.auto_execute_enabled,
                auto_execute_running=self._latest_result.auto_execute_running,
                errors=["Polling response has invalid alerts structure."],
            )
            return self.get_latest_result()

        if response.get("demo_mode") and not alerts and not response.get("fallback_triggered"):
            self.dispatch_service.clear_demo_tasks()

        snapshot_complete = bool(response.get("snapshot_complete"))
        queued_tasks, skipped, updated, completed, errors = await self.dispatch_service.dispatch(
            alerts,
            allow_missing_completion=snapshot_complete,
        )
        
        fallback_errors = []
        if response.get("fallback_triggered") and response.get("fallback_reason"):
            fallback_errors.append(f"由于告警源故障触发降级回退：{response['fallback_reason']}")
            
        combined_errors = fallback_errors + errors

        self._latest_result = PollingDispatchResult(
            fetched_count=len(alerts),
            queued_count=len(queued_tasks),
            updated_count=updated,
            completed_count=len(completed),
            skipped_count=skipped,
            failed_count=len(combined_errors),
            snapshot_complete=snapshot_complete,
            auto_execute_enabled=self._latest_result.auto_execute_enabled,
            auto_execute_running=self._latest_result.auto_execute_running,
            tasks=self.dispatch_service.list_tasks(),
            errors=combined_errors,
        )
        return self.get_latest_result()

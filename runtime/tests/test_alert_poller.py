from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.alerts.poller import AlertPollingService


class _FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_open_alerts(self) -> dict:
        self.calls += 1
        return {"count": 0, "alerts": []}


class _FakeDispatchService:
    def __init__(self) -> None:
        self.tasks = []
        self.dispatch_calls = 0
        self.cleared = 0

    async def dispatch(self, alerts):
        self.dispatch_calls += 1
        self.tasks = [SimpleNamespace(task_id="task-1")] if alerts else self.tasks
        return [], 0, 0, [], []

    def list_tasks(self):
        return list(self.tasks)

    def clear_demo_tasks(self):
        self.cleared += 1
        self.tasks = []


class AlertPollingServiceSchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_respects_interval_and_refreshes_on_config_change(self) -> None:
        client = _FakeClient()
        dispatch_service = _FakeDispatchService()
        service = AlertPollingService(client=client, dedup=SimpleNamespace(), dispatch_service=dispatch_service)

        config = SimpleNamespace(alert_source_enabled=True, poll_interval_seconds=3600)

        with patch("sentinelflow.alerts.poller.load_runtime_config", return_value=config):
            await service.start()
            await asyncio.sleep(0.05)
            self.assertEqual(client.calls, 0)

            config.poll_interval_seconds = 0
            service.refresh_schedule()
            await asyncio.sleep(0.05)
            self.assertEqual(client.calls, 0)

            config.poll_interval_seconds = 1
            service.refresh_schedule()
            await asyncio.sleep(1.1)
            self.assertGreaterEqual(client.calls, 1)
            await service.stop()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.auto_execution_service import AlertAutoExecutionService


class _FakeDispatchService:
    def __init__(self) -> None:
        self.tasks = []

    def list_tasks(self):
        return list(self.tasks)


class _FakeTaskRunnerService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_task(self, task, action: str | None = None):
        self.calls.append(task.task_id)
        task.status = "succeeded"
        return {"success": True, "task_id": task.task_id, "action": action or "triage_close"}


class AutoExecutionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_enable_processes_queued_tasks_until_disabled(self) -> None:
        dispatch_service = _FakeDispatchService()
        runner = _FakeTaskRunnerService()
        service = AlertAutoExecutionService(
            dispatch_service=dispatch_service,
            task_runner_service=runner,
            audit_service=AuditService(),
            interval_seconds=0.05,
        )

        task = SimpleNamespace(task_id="task-1", status="queued")
        dispatch_service.tasks = [task]

        await service.start()
        service.enable()
        await asyncio.sleep(0.12)

        self.assertIn("task-1", runner.calls)
        self.assertFalse(service.state()["running"])
        self.assertTrue(service.state()["enabled"])

        service.disable()
        second_task = SimpleNamespace(task_id="task-2", status="queued")
        dispatch_service.tasks = [second_task]
        await asyncio.sleep(0.12)

        self.assertNotIn("task-2", runner.calls)
        self.assertFalse(service.state()["enabled"])
        await service.stop()


if __name__ == "__main__":
    unittest.main()

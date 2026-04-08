from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.alerts.dedup import AlertDedupStore
from sentinelflow.domain.models import AlertHandlingTask
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.dispatch_service import AlertDispatchService
import sentinelflow.alerts.dedup as dedup_module
import sentinelflow.services.dispatch_service as dispatch_module


class _FakeTriageService:
    async def build_task(self, alert: dict) -> AlertHandlingTask:
        return AlertHandlingTask(
            task_id=f"task-{alert['eventIds']}",
            event_ids=str(alert["eventIds"]),
            workflow_name="agent_react",
            title=str(alert.get("alert_name", "")),
            description="demo",
            alert_time=str(alert.get("alert_time", "")),
            payload={"alert_data": alert, "workflow_selection": {"strategy": "direct"}},
        )


class DispatchServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "sys_queue.db"
        self.config_dir = Path(self.temp_dir.name)
        self.dispatch_db_patch = patch.object(dispatch_module, "DB_PATH", self.db_path)
        self.dispatch_cfg_patch = patch.object(dispatch_module, "CONFIG_DIR", self.config_dir)
        self.dedup_db_patch = patch.object(dedup_module, "DB_PATH", self.db_path)
        self.dispatch_db_patch.start()
        self.dispatch_cfg_patch.start()
        self.dedup_db_patch.start()

        self.audit = AuditService()
        self.service = AlertDispatchService(
            dedup=AlertDedupStore(),
            triage_service=_FakeTriageService(),
            audit_service=self.audit,
        )

    def tearDown(self) -> None:
        self.dispatch_db_patch.stop()
        self.dispatch_cfg_patch.stop()
        self.dedup_db_patch.stop()
        self.temp_dir.cleanup()

    def test_dispatch_updates_existing_queued_task(self) -> None:
        first_alert = {"eventIds": "E-1", "alert_name": "old", "alert_time": "2026-04-08 10:00:00", "payload": "old-payload"}
        second_alert = {"eventIds": "E-1", "alert_name": "new", "alert_time": "2026-04-08 11:00:00", "payload": "new-payload"}

        queued, skipped, updated, completed, errors = asyncio.run(self.service.dispatch([first_alert]))
        self.assertEqual(len(queued), 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(updated, 0)
        self.assertEqual(len(completed), 0)
        self.assertEqual(errors, [])

        queued, skipped, updated, completed, errors = asyncio.run(self.service.dispatch([second_alert]))
        self.assertEqual(len(queued), 0)
        self.assertEqual(skipped, 0)
        self.assertEqual(updated, 1)
        self.assertEqual(len(completed), 0)
        self.assertEqual(errors, [])

        task = self.service.get_task_by_event_id("E-1")
        assert task is not None
        self.assertEqual(task.status, "queued")
        self.assertEqual(task.alert_time, "2026-04-08 11:00:00")
        self.assertEqual(task.title, "new")
        self.assertEqual(task.payload["alert_data"]["payload"], "new-payload")

    def test_dispatch_completes_missing_queued_task(self) -> None:
        alert = {"eventIds": "E-2", "alert_name": "demo", "alert_time": "2026-04-08 12:00:00"}
        asyncio.run(self.service.dispatch([alert]))

        queued, skipped, updated, completed, errors = asyncio.run(self.service.dispatch([]))

        self.assertEqual(len(queued), 0)
        self.assertEqual(skipped, 0)
        self.assertEqual(updated, 0)
        self.assertEqual(len(completed), 1)
        self.assertEqual(errors, [])

        task = self.service.get_task_by_event_id("E-2")
        assert task is not None
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.last_result_success, True)
        self.assertEqual(task.last_result_data["summary"], "已被人工处置")


if __name__ == "__main__":
    unittest.main()

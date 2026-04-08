from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.services.triage_service import TriageService


class TriageServiceTest(unittest.TestCase):
    def test_build_task_keeps_alert_time(self) -> None:
        service = TriageService()
        task = asyncio.run(
            service.build_task(
                {
                    "eventIds": "E-1",
                    "alert_name": "demo",
                    "alert_time": "2026-04-08 18:00:00",
                }
            )
        )

        self.assertEqual(task.event_ids, "E-1")
        self.assertEqual(task.alert_time, "2026-04-08 18:00:00")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sentinelflow.alerts.client import SOCAlertApiClient  # noqa: E402
from sentinelflow.alerts.dedup import AlertDedupStore  # noqa: E402
from sentinelflow.alerts.poller import AlertPollingService  # noqa: E402
from sentinelflow.services.audit_service import AuditService  # noqa: E402
from sentinelflow.services.dispatch_service import AlertDispatchService  # noqa: E402
from sentinelflow.services.triage_service import TriageService  # noqa: E402


async def main() -> None:
    dedup = AlertDedupStore()
    audit = AuditService()
    dispatch = AlertDispatchService(
        dedup=dedup,
        triage_service=TriageService(),
        audit_service=audit,
    )
    poller = AlertPollingService(
        client=SOCAlertApiClient(),
        dedup=dedup,
        dispatch_service=dispatch,
    )
    result = await poller.poll_once()
    print(
        json.dumps(
            {
                "fetched_count": result.fetched_count,
                "queued_count": result.queued_count,
                "skipped_count": result.skipped_count,
                "failed_count": result.failed_count,
                "tasks": [
                    {
                        "task_id": task.task_id,
                        "event_ids": task.event_ids,
                        "workflow_name": task.workflow_name,
                        "title": task.title,
                    }
                    for task in result.tasks
                ],
                "errors": result.errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

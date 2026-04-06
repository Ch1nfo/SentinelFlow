import sqlite3
import json
import threading
from pathlib import Path
from typing import Any

from sentinelflow.alerts.dedup import AlertDedupStore
from sentinelflow.domain.models import AlertHandlingTask
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.triage_service import TriageService
from sentinelflow.config.runtime import CONFIG_DIR

DB_PATH = CONFIG_DIR / "sys_queue.db"

class AlertDispatchService:
    """Dispatches fresh alerts into queued SentinelFlow handling tasks (SQLite backed)."""

    def __init__(
        self,
        dedup: AlertDedupStore,
        triage_service: TriageService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.dedup = dedup
        self.triage_service = triage_service
        self.audit_service = audit_service or AuditService()
        
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS alert_tasks (
                    task_id TEXT PRIMARY KEY,
                    event_ids TEXT,
                    workflow_name TEXT,
                    title TEXT,
                    description TEXT,
                    status TEXT,
                    retry_count INTEGER,
                    last_action TEXT,
                    last_result_success INTEGER,
                    last_result_error TEXT,
                    last_result_data TEXT,
                    payload TEXT
                )
            ''')

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(DB_PATH), check_same_thread=False)

    def _row_to_task(self, row) -> AlertHandlingTask:
        return AlertHandlingTask(
            task_id=row[0],
            event_ids=row[1],
            workflow_name=row[2],
            title=row[3],
            description=row[4],
            status=row[5],
            retry_count=row[6],
            last_action=row[7],
            last_result_success=bool(row[8]) if row[8] is not None else None,
            last_result_error=row[9],
            last_result_data=json.loads(row[10]) if row[10] else {},
            payload=json.loads(row[11]) if row[11] else {}
        )

    def _save_task(self, task: AlertHandlingTask) -> None:
        with self.lock, self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO alert_tasks
                (task_id, event_ids, workflow_name, title, description, status, retry_count, last_action, last_result_success, last_result_error, last_result_data, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task.task_id, task.event_ids, task.workflow_name, task.title, task.description,
                task.status, task.retry_count, task.last_action, 
                1 if task.last_result_success else (0 if task.last_result_success is False else None),
                task.last_result_error, json.dumps(task.last_result_data), json.dumps(task.payload)
            ))
            conn.commit()

    async def dispatch(self, alerts: list[dict]) -> tuple[list[AlertHandlingTask], int, list[str]]:
        queued: list[AlertHandlingTask] = []
        skipped = 0
        errors: list[str] = []

        for alert in alerts:
            event_id = str(alert.get("eventIds", "")).strip()
            if not event_id:
                errors.append("Skipping alert with empty eventIds.")
                continue
            if not self.dedup.mark_processing(event_id):
                skipped += 1
                self.audit_service.record(
                    "alert_dispatch_skipped",
                    f"Skipped duplicate or concurrently processing alert {event_id}.",
                    {"eventIds": event_id},
                )
                continue

            try:
                task = await self.triage_service.build_task(alert)
                self._save_task(task)
                queued.append(task)
                self.audit_service.record(
                    "alert_dispatched",
                    f"Dispatched alert {event_id} to workflow {task.workflow_name}.",
                    {"eventIds": event_id, "taskId": task.task_id, "workflow": task.workflow_name},
                )
            except Exception as exc:
                self.dedup.mark_failed(event_id)
                errors.append(f"Failed to dispatch alert {event_id}: {exc}")
                self.audit_service.record(
                    "alert_dispatch_failed",
                    f"Failed to dispatch alert {event_id}.",
                    {"eventIds": event_id, "error": str(exc)},
                )

        return queued, skipped, errors

    def list_queued_tasks(self) -> list[AlertHandlingTask]:
        return self.list_tasks()

    def list_tasks(self) -> list[AlertHandlingTask]:
        with self.lock, self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM alert_tasks").fetchall()
            return [self._row_to_task(row) for row in rows]

    def clear_demo_tasks(self) -> int:
        removed_event_ids: list[str] = []
        tasks = self.list_tasks()
        
        for task in tasks:
            payload = task.payload if isinstance(task.payload, dict) else {}
            alert_data = payload.get("alert_data") if isinstance(payload.get("alert_data"), dict) else {}
            if str(alert_data.get("alert_source", "")).strip() == "sentinelflow_demo":
                removed_event_ids.append(task.event_ids)
                with self.lock, self._get_conn() as conn:
                    conn.execute("DELETE FROM alert_tasks WHERE task_id = ?", (task.task_id,))
                    conn.commit()
        
        for event_id in removed_event_ids:
            self.dedup.forget(event_id)
            
        return len(removed_event_ids)

    def get_task(self, task_id: str) -> AlertHandlingTask | None:
        with self.lock, self._get_conn() as conn:
            row = conn.execute("SELECT * FROM alert_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row:
                return self._row_to_task(row)
        return None

    def get_task_by_event_id(self, event_id: str) -> AlertHandlingTask | None:
        with self.lock, self._get_conn() as conn:
            row = conn.execute("SELECT * FROM alert_tasks WHERE event_ids = ? ORDER BY rowid DESC LIMIT 1", (event_id,)).fetchone()
            if row:
                return self._row_to_task(row)
        return None

    def mark_task_running(self, task_id: str, action: str) -> AlertHandlingTask | None:
        task = self.get_task(task_id)
        if not task:
            return None
        task.status = "running"
        task.last_action = action
        task.last_result_error = None
        task.last_result_data = {}
        self._save_task(task)
        
        self.audit_service.record(
            "task_running",
            f"Task {task_id} entered running state.",
            {"taskId": task_id, "eventIds": task.event_ids, "action": action},
        )
        return task

    def prepare_retry(self, task_id: str) -> AlertHandlingTask | None:
        task = self.get_task(task_id)
        if not task:
            return None
        task.status = "queued"
        task.retry_count += 1
        task.last_result_error = None
        task.last_result_success = None
        task.last_result_data = {}
        self._save_task(task)
        
        self.audit_service.record(
            "task_retry_prepared",
            f"Task {task_id} prepared for retry.",
            {"taskId": task_id, "eventIds": task.event_ids, "retryCount": task.retry_count},
        )
        return task

    def finalize_task(
        self,
        task_id: str,
        action: str,
        success: bool,
        result_data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AlertHandlingTask | None:
        task = self.get_task(task_id)
        if not task:
            return None
        task.status = "succeeded" if success else "failed"
        task.last_action = action
        task.last_result_success = success
        task.last_result_error = error
        task.last_result_data = result_data or {}
        self._save_task(task)
        
        if success:
            self.dedup.mark_done(task.event_ids)
        else:
            self.dedup.mark_failed(task.event_ids)
            
        self.audit_service.record(
            "task_finished",
            f"Task {task_id} finished execution. Success: {success}",
            {
                "taskId": task_id,
                "eventIds": task.event_ids,
                "success": success,
                "error": error,
                "action": action,
            },
        )
        return task

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
                    alert_time TEXT,
                    status TEXT,
                    retry_count INTEGER,
                    last_action TEXT,
                    last_result_success INTEGER,
                    last_result_error TEXT,
                    last_result_data TEXT,
                    payload TEXT
                )
            ''')
            self._ensure_schema(conn)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_tasks)").fetchall()}
        if "alert_time" not in columns:
            conn.execute("ALTER TABLE alert_tasks ADD COLUMN alert_time TEXT DEFAULT ''")
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(DB_PATH), check_same_thread=False)

    def _row_to_task(self, row) -> AlertHandlingTask:
        has_alert_time = len(row) > 12
        status_index = 6 if has_alert_time else 5
        retry_index = 7 if has_alert_time else 6
        action_index = 8 if has_alert_time else 7
        success_index = 9 if has_alert_time else 8
        error_index = 10 if has_alert_time else 9
        result_index = 11 if has_alert_time else 10
        payload_index = 12 if has_alert_time else 11
        return AlertHandlingTask(
            task_id=row[0],
            event_ids=row[1],
            workflow_name=row[2],
            title=row[3],
            description=row[4],
            alert_time=row[5] if has_alert_time else "",
            status=row[status_index],
            retry_count=row[retry_index],
            last_action=row[action_index],
            last_result_success=bool(row[success_index]) if row[success_index] is not None else None,
            last_result_error=row[error_index],
            last_result_data=json.loads(row[result_index]) if row[result_index] else {},
            payload=json.loads(row[payload_index]) if row[payload_index] else {},
        )

    def _save_task(self, task: AlertHandlingTask) -> None:
        with self.lock, self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO alert_tasks
                (task_id, event_ids, workflow_name, title, description, alert_time, status, retry_count, last_action, last_result_success, last_result_error, last_result_data, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task.task_id, task.event_ids, task.workflow_name, task.title, task.description,
                task.alert_time, task.status, task.retry_count, task.last_action, 
                1 if task.last_result_success else (0 if task.last_result_success is False else None),
                task.last_result_error, json.dumps(task.last_result_data), json.dumps(task.payload)
            ))
            conn.commit()

    def _refresh_existing_task(
        self,
        existing: AlertHandlingTask,
        alert: dict,
        workflow_selection: dict[str, Any] | None = None,
        *,
        reset_to_queued: bool = False,
    ) -> AlertHandlingTask:
        alert_name = str(alert.get("alert_name", "未知告警")).strip() or "未知告警"
        workflow_name = str(existing.workflow_name or "agent_react").strip() or "agent_react"
        payload = dict(existing.payload) if isinstance(existing.payload, dict) else {}
        payload["alert_data"] = alert
        if workflow_selection is not None:
            payload["workflow_selection"] = workflow_selection
        existing.title = alert_name
        existing.description = f"Handle alert {existing.event_ids} through workflow {workflow_name}."
        existing.alert_time = str(alert.get("alert_time", "")).strip()
        existing.payload = payload
        if reset_to_queued:
            existing.status = "queued"
            existing.last_action = "refresh_poll"
            existing.last_result_success = None
            existing.last_result_error = None
            existing.last_result_data = {}
            self.dedup.mark_processing(existing.event_ids)
        self._save_task(existing)
        self.audit_service.record(
            "alert_task_updated",
            f"Updated alert task for {existing.event_ids} with latest payload.",
            {
                "eventIds": existing.event_ids,
                "taskId": existing.task_id,
                "workflow": workflow_name,
                "resetToQueued": reset_to_queued,
                "status": existing.status,
            },
        )
        return existing

    def _complete_missing_queued_tasks(self, active_event_ids: set[str]) -> list[AlertHandlingTask]:
        completed: list[AlertHandlingTask] = []
        for task in self.list_tasks():
            if task.status != "queued":
                continue
            if task.event_ids in active_event_ids:
                continue
            task.status = "completed"
            task.last_action = "refresh_poll"
            task.last_result_success = True
            task.last_result_error = None
            task.last_result_data = {
                "summary": "已被人工处置",
                "reason": "本次轮询未再发现该 queued 告警，按人工处置完成收口。",
                "disposition": "handled_manually",
            }
            self._save_task(task)
            self.dedup.mark_done(task.event_ids)
            self.audit_service.record(
                "alert_task_completed_externally",
                f"Marked queued alert {task.event_ids} as completed because it disappeared from the latest poll.",
                {"eventIds": task.event_ids, "taskId": task.task_id},
            )
            completed.append(task)
        return completed

    async def dispatch(self, alerts: list[dict]) -> tuple[list[AlertHandlingTask], int, int, list[AlertHandlingTask], list[str]]:
        queued: list[AlertHandlingTask] = []
        skipped = 0
        updated = 0
        errors: list[str] = []
        active_event_ids: set[str] = set()

        for alert in alerts:
            event_id = str(alert.get("eventIds", "")).strip()
            if not event_id:
                errors.append("Skipping alert with empty eventIds.")
                continue
            active_event_ids.add(event_id)
            existing = self.get_task_by_event_id(event_id)
            if existing and existing.status == "queued":
                workflow_selection = existing.payload.get("workflow_selection", {}) if isinstance(existing.payload, dict) else {}
                self._refresh_existing_task(existing, alert, workflow_selection if isinstance(workflow_selection, dict) else {})
                updated += 1
                continue
            if existing and existing.status == "failed":
                workflow_selection = existing.payload.get("workflow_selection", {}) if isinstance(existing.payload, dict) else {}
                self._refresh_existing_task(
                    existing,
                    alert,
                    workflow_selection if isinstance(workflow_selection, dict) else {},
                    reset_to_queued=True,
                )
                updated += 1
                continue
            if existing and existing.status == "running":
                skipped += 1
                self.audit_service.record(
                    "alert_dispatch_skipped_running",
                    f"Skipped duplicate alert {event_id} because the original task is still running.",
                    {"eventIds": event_id, "taskId": existing.task_id},
                )
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

        completed = self._complete_missing_queued_tasks(active_event_ids)
        return queued, skipped, updated, completed, errors

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

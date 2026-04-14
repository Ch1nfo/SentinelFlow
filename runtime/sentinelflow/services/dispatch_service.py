import sqlite3
import json
import threading
from typing import Any, Iterable

from sentinelflow.alerts.dedup import AlertDedupStore
from sentinelflow.domain.models import AlertHandlingTask
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.sqlite_support import open_sqlite_connection, sqlite_transaction
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_tasks_event_ids ON alert_tasks(event_ids)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_tasks_status ON alert_tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_tasks_event_status ON alert_tasks(event_ids, status)")

    def _get_conn(self) -> sqlite3.Connection:
        return open_sqlite_connection(DB_PATH)

    def _row_to_task(self, row) -> AlertHandlingTask:
        result_raw = row["last_result_data"] if "last_result_data" in row.keys() else None
        payload_raw = row["payload"] if "payload" in row.keys() else None
        return AlertHandlingTask(
            task_id=row["task_id"],
            event_ids=row["event_ids"],
            workflow_name=row["workflow_name"],
            title=row["title"],
            description=row["description"],
            alert_time=row["alert_time"] if "alert_time" in row.keys() else "",
            status=row["status"],
            retry_count=row["retry_count"],
            last_action=row["last_action"],
            last_result_success=bool(row["last_result_success"]) if row["last_result_success"] is not None else None,
            last_result_error=row["last_result_error"],
            last_result_data=json.loads(result_raw) if result_raw else {},
            payload=json.loads(payload_raw) if payload_raw else {},
        )

    def _save_task(self, task: AlertHandlingTask) -> None:
        with self.lock, sqlite_transaction(DB_PATH, begin_mode="IMMEDIATE") as conn:
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

    def _insert_task_if_event_absent(self, task: AlertHandlingTask) -> bool:
        with self.lock, sqlite_transaction(DB_PATH, begin_mode="IMMEDIATE") as conn:
            cursor = conn.execute(
                '''
                INSERT INTO alert_tasks
                (task_id, event_ids, workflow_name, title, description, alert_time, status, retry_count, last_action, last_result_success, last_result_error, last_result_data, payload)
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM alert_tasks WHERE event_ids = ?
                )
                ''',
                (
                    task.task_id,
                    task.event_ids,
                    task.workflow_name,
                    task.title,
                    task.description,
                    task.alert_time,
                    task.status,
                    task.retry_count,
                    task.last_action,
                    1 if task.last_result_success else (0 if task.last_result_success is False else None),
                    task.last_result_error,
                    json.dumps(task.last_result_data),
                    json.dumps(task.payload),
                    task.event_ids,
                ),
            )
            return cursor.rowcount > 0

    def _update_task_columns(
        self,
        task_id: str,
        updates: dict[str, Any],
        *,
        expected_statuses: Iterable[str] | None = None,
    ) -> AlertHandlingTask | None:
        if not updates:
            return self.get_task(task_id)

        assignments = ", ".join(f"{column} = ?" for column in updates)
        params: list[Any] = list(updates.values())
        query = f"UPDATE alert_tasks SET {assignments} WHERE task_id = ?"
        params.append(task_id)
        if expected_statuses:
            status_list = list(expected_statuses)
            placeholders = ", ".join("?" for _ in status_list)
            query += f" AND status IN ({placeholders})"
            params.extend(status_list)

        with self.lock, sqlite_transaction(DB_PATH, begin_mode="IMMEDIATE") as conn:
            cursor = conn.execute(query, tuple(params))
            if cursor.rowcount <= 0:
                return None
            row = conn.execute("SELECT * FROM alert_tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._row_to_task(row) if row else None

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

        updates: dict[str, Any] = {
            "title": alert_name,
            "description": f"Handle alert {existing.event_ids} through workflow {workflow_name}.",
            "alert_time": str(alert.get("alert_time", "")).strip(),
            "payload": json.dumps(payload),
        }
        expected_statuses = ["queued"]
        if reset_to_queued:
            expected_statuses = ["failed"]
            updates.update(
                {
                    "status": "queued",
                    "last_action": "refresh_poll",
                    "last_result_success": None,
                    "last_result_error": None,
                    "last_result_data": json.dumps({}),
                }
            )
            self.dedup.mark_processing(existing.event_ids)
        updated_task = self._update_task_columns(existing.task_id, updates, expected_statuses=expected_statuses)
        if not updated_task:
            latest = self.get_task(existing.task_id)
            return latest or existing
        self.audit_service.record(
            "alert_task_updated",
            f"Updated alert task for {existing.event_ids} with latest payload.",
            {
                "eventIds": existing.event_ids,
                "taskId": updated_task.task_id,
                "workflow": workflow_name,
                "resetToQueued": reset_to_queued,
                "status": updated_task.status,
            },
        )
        return updated_task

    def _complete_missing_polled_tasks(self, active_event_ids: set[str]) -> list[AlertHandlingTask]:
        completed: list[AlertHandlingTask] = []
        for task in self.list_open_polled_tasks():
            if task.event_ids in active_event_ids:
                continue
            previous_status = task.status
            updated_task = self._update_task_columns(
                task.task_id,
                {
                    "status": "completed",
                    "last_action": "refresh_poll",
                    "last_result_success": 1,
                    "last_result_error": None,
                    "last_result_data": json.dumps(
                        {
                            "summary": "已被人工处置",
                            "reason": f"本次轮询未再发现该 {previous_status} 告警，按人工处置完成收口。",
                            "disposition": "handled_manually",
                            "execution_trace": [
                                {
                                    "phase": "alert_received",
                                    "title": "接收告警",
                                    "summary": "已接收任务告警上下文。",
                                    "success": True,
                                    "data": {
                                        "eventIds": task.event_ids,
                                        "alert_name": str(
                                            (
                                                task.payload.get("alert_data", {})
                                                if isinstance(task.payload, dict) and isinstance(task.payload.get("alert_data"), dict)
                                                else {}
                                            ).get("alert_name", task.title)
                                        ).strip(),
                                        "sip": (
                                            task.payload.get("alert_data", {}).get("sip", "")
                                            if isinstance(task.payload, dict) and isinstance(task.payload.get("alert_data"), dict)
                                            else ""
                                        ),
                                        "dip": (
                                            task.payload.get("alert_data", {}).get("dip", "")
                                            if isinstance(task.payload, dict) and isinstance(task.payload.get("alert_data"), dict)
                                            else ""
                                        ),
                                        "alert_time": (
                                            task.payload.get("alert_data", {}).get("alert_time", task.alert_time)
                                            if isinstance(task.payload, dict) and isinstance(task.payload.get("alert_data"), dict)
                                            else task.alert_time
                                        ),
                                    },
                                },
                                {
                                    "phase": "final_status",
                                    "title": "最终执行状态",
                                    "summary": f"本次轮询未再发现该 {previous_status} 告警，按人工处置完成收口。",
                                    "success": True,
                                    "data": {
                                        "success": True,
                                        "status": "completed",
                                        "previous_status": previous_status,
                                        "action": "refresh_poll",
                                    },
                                },
                            ],
                        }
                    ),
                },
                expected_statuses=["queued", "failed"],
            )
            if not updated_task:
                continue
            self.dedup.mark_done(task.event_ids)
            self.audit_service.record(
                "alert_task_completed_externally",
                f"Marked {previous_status} alert {task.event_ids} as completed because it disappeared from the latest poll.",
                {"eventIds": task.event_ids, "taskId": task.task_id, "previousStatus": previous_status},
            )
            completed.append(updated_task)
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
                    reset_to_queued=False,
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
            if existing and existing.status in {"succeeded", "completed"}:
                skipped += 1
                self.audit_service.record(
                    "alert_dispatch_skipped_finished",
                    f"Skipped duplicate alert {event_id} because the original task has already been finalized.",
                    {"eventIds": event_id, "taskId": existing.task_id, "status": existing.status},
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
                inserted = self._insert_task_if_event_absent(task)
                if not inserted:
                    self.dedup.forget(event_id)
                    skipped += 1
                    self.audit_service.record(
                        "alert_dispatch_skipped_race",
                        f"Skipped duplicate alert {event_id} because another task was inserted concurrently.",
                        {"eventIds": event_id, "taskId": task.task_id},
                    )
                    continue
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

        completed = self._complete_missing_polled_tasks(active_event_ids)
        return queued, skipped, updated, completed, errors

    def list_queued_tasks(self) -> list[AlertHandlingTask]:
        return self.list_tasks()

    def list_open_polled_tasks(self) -> list[AlertHandlingTask]:
        with self.lock, self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_tasks WHERE status IN ('queued', 'failed')"
            ).fetchall()
            return [self._row_to_task(row) for row in rows]

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
                with self.lock, sqlite_transaction(DB_PATH) as conn:
                    conn.execute("DELETE FROM alert_tasks WHERE task_id = ?", (task.task_id,))
        
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
        task = self._update_task_columns(
            task_id,
            {
                "status": "running",
                "last_action": action,
                "last_result_error": None,
                "last_result_data": json.dumps({}),
            },
            expected_statuses=["queued"],
        )
        if not task:
            return None
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
        updated_task = self._update_task_columns(
            task_id,
            {
                "status": "queued",
                "retry_count": task.retry_count + 1,
                "last_result_error": None,
                "last_result_success": None,
                "last_result_data": json.dumps({}),
            },
            expected_statuses=["failed"],
        )
        if not updated_task:
            return None
        
        self.audit_service.record(
            "task_retry_prepared",
            f"Task {task_id} prepared for retry.",
            {"taskId": task_id, "eventIds": updated_task.event_ids, "retryCount": updated_task.retry_count},
        )
        return updated_task

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
        updated_task = self._update_task_columns(
            task_id,
            {
                "status": "succeeded" if success else "failed",
                "last_action": action,
                "last_result_success": 1 if success else 0,
                "last_result_error": error,
                "last_result_data": json.dumps(result_data or {}),
            },
            expected_statuses=["running"],
        )
        if not updated_task:
            return self.get_task(task_id)
        
        if success:
            self.dedup.mark_done(updated_task.event_ids)
        else:
            self.dedup.mark_failed(updated_task.event_ids)
            
        self.audit_service.record(
            "task_finished",
            f"Task {task_id} finished execution. Success: {success}",
            {
                "taskId": task_id,
                "eventIds": updated_task.event_ids,
                "success": success,
                "error": error,
                "action": action,
            },
        )
        return updated_task

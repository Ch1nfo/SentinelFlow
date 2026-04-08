from __future__ import annotations

from pathlib import Path
from typing import Any

from sentinelflow.agent.service import SentinelFlowAgentService
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.dispatch_service import AlertDispatchService
from sentinelflow.workflows.agent_workflow_registry import load_agent_workflow
from sentinelflow.workflows.agent_workflow_runner import SentinelFlowAgentWorkflowRunner


class AlertTaskRunnerService:
    def __init__(
        self,
        dispatch_service: AlertDispatchService,
        audit_service: AuditService,
        agent_service: SentinelFlowAgentService,
        agent_workflow_runner: SentinelFlowAgentWorkflowRunner,
        workflow_root: Path,
    ) -> None:
        self.dispatch_service = dispatch_service
        self.audit_service = audit_service
        self.agent_service = agent_service
        self.agent_workflow_runner = agent_workflow_runner
        self.workflow_root = workflow_root

    async def run_task(self, task, action: str | None = None) -> dict[str, Any]:
        alert = {}
        if isinstance(task.payload, dict):
            payload_alert = task.payload.get("alert_data")
            if isinstance(payload_alert, dict):
                alert = payload_alert

        if not alert:
            task = self.dispatch_service.finalize_task(task.task_id, action or "unknown", False, {}, "任务缺少告警上下文。")
            return {
                "action": action or "unknown",
                "success": False,
                "task_id": task.task_id if task else "",
                "event_ids": "",
                "data": {},
                "task": task,
                "error": "任务缺少告警上下文。",
            }

        selected_action = action
        if not selected_action:
            if task.workflow_name == "agent_react":
                selected_action = "triage_close"
            else:
                try:
                    workflow_definition = load_agent_workflow(self.workflow_root, task.workflow_name)
                    selected_action = workflow_definition.recommended_action
                except Exception:
                    selected_action = "triage_close"

        self.dispatch_service.mark_task_running(task.task_id, selected_action)

        agent_available, _agent_error = self.agent_service.is_available()
        if task.workflow_name == "agent_react" and self.agent_service.is_configured() and agent_available:
            try:
                agent_result = await self.agent_service.run_alert(alert, selected_action)
                if bool(agent_result.get("success")):
                    task = self.dispatch_service.finalize_task(task.task_id, selected_action, True, agent_result, None)
                    return {
                        "action": selected_action,
                        "success": True,
                        "task_id": task.task_id if task else "",
                        "event_ids": str(agent_result.get("event_ids", "")).strip(),
                        "data": agent_result,
                        "task": task,
                        "error": None,
                    }
            except Exception as exc:
                self.audit_service.record("agent_react_task_failed", "Agent ReAct runtime failed.", {"error": str(exc)})

        if selected_action in {"triage_close", "triage_dispose"} and self.agent_service.is_configured() and agent_available:
            try:
                workflow_definition = load_agent_workflow(self.workflow_root, task.workflow_name)
                agent_result = await self.agent_workflow_runner.run_alert_workflow(workflow_definition, alert, selected_action)
                if bool(agent_result.get("success")):
                    task = self.dispatch_service.finalize_task(task.task_id, selected_action, True, agent_result, None)
                    return {
                        "action": selected_action,
                        "success": True,
                        "task_id": task.task_id if task else "",
                        "event_ids": str(agent_result.get("event_ids", "")).strip(),
                        "data": agent_result,
                        "task": task,
                        "error": None,
                    }
            except FileNotFoundError:
                try:
                    agent_result = await self.agent_service.run_alert(alert, selected_action)
                    if bool(agent_result.get("success")):
                        task = self.dispatch_service.finalize_task(task.task_id, selected_action, True, agent_result, None)
                        return {
                            "action": selected_action,
                            "success": True,
                            "task_id": task.task_id if task else "",
                            "event_ids": str(agent_result.get("event_ids", "")).strip(),
                            "data": agent_result,
                            "task": task,
                            "error": None,
                        }
                except Exception as exc:
                    self.audit_service.record("agent_task_failed", f"Agent runtime failed during {selected_action}.", {"error": str(exc)})
            except Exception as exc:
                self.audit_service.record("agent_workflow_task_failed", f"Workflow failed during {selected_action}.", {"error": str(exc)})

        task = self.dispatch_service.finalize_task(task.task_id, selected_action, False, {}, "当前任务没有可用的 Agent Workflow，且主 Agent 处理未成功。")
        return {
            "action": selected_action,
            "success": False,
            "task_id": task.task_id if task else "",
            "event_ids": str(alert.get("eventIds", "")).strip(),
            "data": {},
            "task": task,
            "error": "当前任务没有可用的 Agent Workflow，且主 Agent 处理未成功。",
        }

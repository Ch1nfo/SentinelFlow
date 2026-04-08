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

    def _finalize_success(self, task, selected_action: str, result_data: dict[str, Any]) -> dict[str, Any]:
        task = self.dispatch_service.finalize_task(task.task_id, selected_action, True, result_data, None)
        return {
            "action": selected_action,
            "success": True,
            "task_id": task.task_id if task else "",
            "event_ids": str(result_data.get("event_ids", "")).strip(),
            "data": result_data,
            "task": task,
            "error": None,
        }

    def _finalize_failure(self, task, selected_action: str, error: str) -> dict[str, Any]:
        task = self.dispatch_service.finalize_task(task.task_id, selected_action, False, {}, error)
        return {
            "action": selected_action,
            "success": False,
            "task_id": task.task_id if task else "",
            "event_ids": str((task.event_ids if task else "")),
            "data": {},
            "task": task,
            "error": error,
        }

    async def _run_agent_react(self, task, alert: dict[str, Any], selected_action: str) -> dict[str, Any]:
        try:
            agent_result = await self.agent_service.run_alert(alert, selected_action)
        except Exception as exc:
            self.audit_service.record("agent_react_task_failed", "Agent ReAct runtime failed.", {"error": str(exc)})
            return self._finalize_failure(task, selected_action, f"主 Agent 执行失败：{exc}")

        if bool(agent_result.get("success")):
            return self._finalize_success(task, selected_action, agent_result)
        return self._finalize_failure(task, selected_action, "主 Agent 未返回成功结果。")

    async def _run_workflow_or_fallback(self, task, alert: dict[str, Any], selected_action: str) -> dict[str, Any]:
        if selected_action not in {"triage_close", "triage_dispose"}:
            return self._finalize_failure(task, selected_action, "当前动作不支持工作流执行。")
        if not self.agent_service.is_configured():
            return self._finalize_failure(task, selected_action, "当前未完成系统主 Agent 配置。")

        try:
            workflow_definition = load_agent_workflow(self.workflow_root, task.workflow_name)
        except FileNotFoundError:
            try:
                agent_result = await self.agent_service.run_alert(alert, selected_action)
            except Exception as exc:
                self.audit_service.record("agent_task_failed", f"Agent runtime failed during {selected_action}.", {"error": str(exc)})
                return self._finalize_failure(task, selected_action, f"主 Agent 执行失败：{exc}")
            if bool(agent_result.get("success")):
                return self._finalize_success(task, selected_action, agent_result)
            return self._finalize_failure(task, selected_action, "主 Agent 未返回成功结果。")
        except Exception as exc:
            self.audit_service.record("agent_workflow_task_failed", f"Workflow failed during {selected_action}.", {"error": str(exc)})
            return self._finalize_failure(task, selected_action, f"Workflow 加载失败：{exc}")

        try:
            agent_result = await self.agent_workflow_runner.run_alert_workflow(workflow_definition, alert, selected_action)
        except Exception as exc:
            self.audit_service.record("agent_workflow_task_failed", f"Workflow failed during {selected_action}.", {"error": str(exc)})
            return self._finalize_failure(task, selected_action, f"Workflow 执行失败：{exc}")

        if bool(agent_result.get("success")):
            return self._finalize_success(task, selected_action, agent_result)
        return self._finalize_failure(task, selected_action, "Workflow 未返回成功结果。")

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
        if not agent_available:
            return self._finalize_failure(task, selected_action, f"当前 Agent Runtime 不可用：{_agent_error or 'unknown'}")
        if task.workflow_name == "agent_react":
            if not self.agent_service.is_configured():
                return self._finalize_failure(task, selected_action, "当前未完成系统主 Agent 配置。")
            return await self._run_agent_react(task, alert, selected_action)
        return await self._run_workflow_or_fallback(task, alert, selected_action)

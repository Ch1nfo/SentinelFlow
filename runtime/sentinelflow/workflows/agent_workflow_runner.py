from __future__ import annotations

import json
from typing import Any

from sentinelflow.workflows.agent_workflow_registry import AgentWorkflowDefinition


class SentinelFlowAgentWorkflowRunner:
    def __init__(self, agent_service, audit_service) -> None:
        self.agent_service = agent_service
        self.audit_service = audit_service

    async def run_alert_workflow(
        self,
        workflow: AgentWorkflowDefinition,
        alert: dict[str, Any],
        action_hint: str | None = None,
    ) -> dict[str, Any]:
        step_results: list[dict[str, Any]] = []

        for step_index, step in enumerate(workflow.steps, start=1):
            worker_prompt = self._build_worker_prompt(
                workflow=workflow,
                alert=alert,
                step_index=step_index,
                step_name=step.name,
                task_prompt=step.task_prompt,
                step_results=step_results,
            )
            # ✅ Critical fix: run_command is async — must be awaited
            worker_result = await self.agent_service.run_command(
                worker_prompt,
                history=[],
                agent_name=step.agent,
            )
            messages = worker_result.get("messages", [])
            has_error = False
            for m in messages:
                if m.get("type") == "tool":
                    content = str(m.get("content", "")).strip()
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            if not parsed.get("success", True):
                                has_error = True
                                break
                            if parsed.get("error"):
                                has_error = True
                                break
                    except Exception:
                        has_error = True
                        break

            has_action = bool(str(worker_result.get("final_response", "")).strip() or worker_result.get("tool_calls"))

            compact = {
                "step": step_index,
                "step_id": step.id,
                "step_name": step.name,
                "worker_agent": step.agent,
                "task_prompt": step.task_prompt,
                "final_response": str(worker_result.get("final_response", "")).strip(),
                "messages": messages,
                "tool_calls": worker_result.get("tool_calls", []),
                "success": has_action and not has_error,
            }
            step_results.append(compact)
            self.audit_service.record(
                "agent_workflow_step_finished",
                f"Agent workflow {workflow.id} finished step {step.id}.",
                {
                    "workflowId": workflow.id,
                    "stepId": step.id,
                    "stepName": step.name,
                    "workerAgent": step.agent,
                    "eventIds": str(alert.get("eventIds", "")).strip(),
                    "success": compact["success"],
                },
            )
            if not compact["success"]:
                return {
                    "success": False,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "execution_mode": "agent_workflow",
                    "event_ids": str(alert.get("eventIds", "")).strip(),
                    "worker_results": step_results,
                    "error": f"步骤 {step.name} 未返回有效结果。",
                }

        final_action = action_hint or workflow.final_handler.action or workflow.recommended_action
        if workflow.final_handler.type == "primary":
            final_alert = dict(alert)
            final_alert["payload"] = json.dumps(
                {
                    "original_alert": alert,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "workflow_step_results": step_results,
                    "instruction": "请基于这些固定子 Agent 步骤结果给出最终值班结论，并在需要时完成处置或结单。",
                },
                ensure_ascii=False,
            )
            # ✅ Critical fix: run_alert is async — must be awaited
            final_result = await self.agent_service.run_alert(final_alert, final_action)
        else:
            latest = step_results[-1] if step_results else {}
            final_result = {
                "success": bool(latest.get("success")),
                "event_ids": str(alert.get("eventIds", "")).strip(),
                "summary": str(latest.get("final_response", "")).strip(),
                "reason": str(latest.get("final_response", "")).strip(),
                "evidence": [],
                "final_response": str(latest.get("final_response", "")).strip(),
            }

        return {
            **final_result,
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "workflow_description": workflow.description,
            "workflow_steps": [
                {
                    "id": step.id,
                    "name": step.name,
                    "agent": step.agent,
                }
                for step in workflow.steps
            ],
            "worker_results": step_results,
            "execution_mode": "agent_workflow",
            "used_agent_workflow": True,
        }

    def _build_worker_prompt(
        self,
        workflow: AgentWorkflowDefinition,
        alert: dict[str, Any],
        step_index: int,
        step_name: str,
        task_prompt: str,
        step_results: list[dict[str, Any]],
    ) -> str:
        effective_task_prompt = task_prompt.strip() or f"请作为流程中的子 Agent 完成第 {step_index} 步《{step_name}》需要承担的工作，并输出你的阶段性结果。"
        return (
            f"你当前处于 Agent Workflow《{workflow.name}》的第 {step_index}/{len(workflow.steps)} 步：{step_name}\n\n"
            f"原始告警：\n{json.dumps(alert, ensure_ascii=False, indent=2)}\n\n"
            f"已完成步骤结果：\n{json.dumps(step_results, ensure_ascii=False, indent=2)}\n\n"
            f"本步骤固定任务：\n{effective_task_prompt}\n\n"
            "要求：\n"
            "- 只完成当前步骤，不要尝试规划整个流程\n"
            "- 不要假设自己能调度其他 Agent\n"
            "- 输出简洁中文结果，必要时调用你已授权的 Skill\n"
        )

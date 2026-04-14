from __future__ import annotations

import json
from typing import Any

from sentinelflow.workflows.agent_workflow_registry import AgentWorkflowDefinition


class SentinelFlowAgentWorkflowRunner:
    def __init__(self, agent_service, audit_service) -> None:
        self.agent_service = agent_service
        self.audit_service = audit_service

    async def execute_workflow(
        self,
        workflow: AgentWorkflowDefinition,
        workflow_input: dict[str, Any],
        *,
        task_prompt: str = "",
    ) -> dict[str, Any]:
        step_results: list[dict[str, Any]] = []

        for step_index, step in enumerate(workflow.steps, start=1):
            worker_prompt = self._build_worker_prompt(
                workflow=workflow,
                workflow_input=workflow_input,
                step_index=step_index,
                step_name=step.name,
                task_prompt=step.task_prompt,
                delegated_task_prompt=task_prompt,
                step_results=step_results,
            )
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

            final_response = str(worker_result.get("final_response", "")).strip()
            has_action = bool(final_response or worker_result.get("tool_calls"))
            compact = {
                "step": step_index,
                "step_id": step.id,
                "step_name": step.name,
                "worker_agent": step.agent,
                "task_prompt": step.task_prompt,
                "workflow_task_prompt": task_prompt,
                "final_response": final_response,
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
                    "eventIds": str(workflow_input.get("eventIds", "")).strip(),
                    "success": compact["success"],
                },
            )
            if not compact["success"]:
                execution_trace = self._build_workflow_execution_trace(
                    workflow=workflow,
                    workflow_input=workflow_input,
                    task_prompt=task_prompt,
                    step_results=step_results,
                    success=False,
                    error=f"步骤 {step.name} 未返回有效结果。",
                )
                return {
                    "success": False,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "workflow_description": workflow.description,
                    "execution_mode": "agent_workflow",
                    "event_ids": str(workflow_input.get("eventIds", "")).strip(),
                    "task_prompt": task_prompt,
                    "worker_results": step_results,
                    "summary": f"Workflow《{workflow.name}》在步骤《{step.name}》未返回有效结果。",
                    "reason": f"Workflow《{workflow.name}》执行失败，失败步骤：{step.name}。",
                    "evidence": self._build_workflow_evidence(step_results),
                    "error": f"步骤 {step.name} 未返回有效结果。",
                    "actions": self._build_workflow_actions(step_results),
                    "execution_trace": execution_trace,
                }

        latest = step_results[-1] if step_results else {}
        final_response = str(latest.get("final_response", "")).strip()
        execution_trace = self._build_workflow_execution_trace(
            workflow=workflow,
            workflow_input=workflow_input,
            task_prompt=task_prompt,
            step_results=step_results,
            success=bool(latest.get("success")),
            error="",
        )
        return {
            "success": bool(latest.get("success")),
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "workflow_description": workflow.description,
            "execution_mode": "agent_workflow",
            "event_ids": str(workflow_input.get("eventIds", "")).strip(),
            "task_prompt": task_prompt,
            "summary": final_response or f"Workflow《{workflow.name}》已完成。",
            "reason": final_response or f"Workflow《{workflow.name}》已按既定步骤完成执行。",
            "evidence": self._build_workflow_evidence(step_results),
            "final_response": final_response,
            "worker_results": step_results,
            "workflow_steps": [
                {
                    "id": step.id,
                    "name": step.name,
                    "agent": step.agent,
                }
                for step in workflow.steps
            ],
            "used_agent_workflow": True,
            "actions": self._build_workflow_actions(step_results),
            "closure_step": {"attempted": False, "success": False},
            "execution_trace": execution_trace,
        }

    async def run_alert_workflow(
        self,
        workflow: AgentWorkflowDefinition,
        alert: dict[str, Any],
        action_hint: str | None = None,
    ) -> dict[str, Any]:
        workflow_result = await self.execute_workflow(workflow, alert)
        if not workflow_result.get("success"):
            return workflow_result

        final_action = action_hint or workflow.final_handler.action or workflow.recommended_action
        if workflow.final_handler.type == "primary":
            final_alert = dict(alert)
            final_alert["payload"] = json.dumps(
                {
                    "original_alert": alert,
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "workflow_step_results": workflow_result.get("worker_results", []),
                    "instruction": "请基于这些固定子 Agent 步骤结果给出最终值班结论，并在需要时完成处置或结单。",
                },
                ensure_ascii=False,
            )
            # ✅ Critical fix: run_alert is async — must be awaited
            final_result = await self.agent_service.run_alert(final_alert, final_action)
        else:
            latest = workflow_result.get("worker_results", [])[-1] if workflow_result.get("worker_results") else {}
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
            "workflow_steps": workflow_result.get("workflow_steps", []),
            "worker_results": workflow_result.get("worker_results", []),
            "execution_mode": "agent_workflow",
            "used_agent_workflow": True,
            "actions": workflow_result.get("actions", {}),
            "workflow_execution_trace": workflow_result.get("execution_trace", []),
        }

    def _build_worker_prompt(
        self,
        workflow: AgentWorkflowDefinition,
        workflow_input: dict[str, Any],
        step_index: int,
        step_name: str,
        task_prompt: str,
        delegated_task_prompt: str,
        step_results: list[dict[str, Any]],
    ) -> str:
        effective_task_prompt = task_prompt.strip() or f"请作为流程中的子 Agent 完成第 {step_index} 步《{step_name}》需要承担的工作，并输出你的阶段性结果。"
        delegated_instruction = f"\n主 Agent 额外要求：\n{delegated_task_prompt}\n" if delegated_task_prompt.strip() else ""
        return (
            f"你当前处于 Agent Workflow《{workflow.name}》的第 {step_index}/{len(workflow.steps)} 步：{step_name}\n\n"
            f"原始上下文：\n{json.dumps(workflow_input, ensure_ascii=False, indent=2)}\n\n"
            f"已完成步骤结果：\n{json.dumps(step_results, ensure_ascii=False, indent=2)}\n\n"
            f"{delegated_instruction}\n"
            f"本步骤固定任务：\n{effective_task_prompt}\n\n"
            "要求：\n"
            "- 只完成当前步骤，不要尝试规划整个流程\n"
            "- 不要假设自己能调度其他 Agent\n"
            "- 输出简洁中文结果，必要时调用你已授权的 Skill\n"
        )

    def _build_workflow_evidence(self, step_results: list[dict[str, Any]]) -> list[str]:
        evidence: list[str] = []
        for step in step_results:
            if not isinstance(step, dict):
                continue
            step_name = str(step.get("step_name", "")).strip()
            final_response = str(step.get("final_response", "")).strip()
            if not step_name or not final_response:
                continue
            snippet = final_response[:120].strip()
            evidence.append(f"{step_name}: {snippet}")
        return evidence[:5]

    def _build_workflow_actions(self, step_results: list[dict[str, Any]]) -> dict[str, Any]:
        action_items: list[dict[str, Any]] = []
        for step in step_results:
            if not isinstance(step, dict):
                continue
            tool_calls = step.get("tool_calls", [])
            if not isinstance(tool_calls, list) or not tool_calls:
                continue
            action_items.append(
                {
                    "step_id": step.get("step_id", ""),
                    "step_name": step.get("step_name", ""),
                    "worker_agent": step.get("worker_agent", ""),
                    "tool_calls": tool_calls,
                }
            )
        return {
            "workers_used": [str(step.get("worker_agent", "")).strip() for step in step_results if isinstance(step, dict) and str(step.get("worker_agent", "")).strip()],
            "tool_runs": action_items,
        }

    def _build_workflow_execution_trace(
        self,
        *,
        workflow: AgentWorkflowDefinition,
        workflow_input: dict[str, Any],
        task_prompt: str,
        step_results: list[dict[str, Any]],
        success: bool,
        error: str,
    ) -> list[dict[str, Any]]:
        trace: list[dict[str, Any]] = [
            {
                "phase": "workflow_received",
                "title": "接收 Workflow 调用",
                "summary": f"主 Agent 调用了 Workflow《{workflow.name}》。",
                "success": True,
                "data": {
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "task_prompt": task_prompt,
                    "eventIds": str(workflow_input.get("eventIds", "")).strip(),
                    "alert_name": str(workflow_input.get("alert_name", "")).strip(),
                },
            }
        ]
        for step in step_results:
            if not isinstance(step, dict):
                continue
            trace.append(
                {
                    "phase": "workflow_step",
                    "title": f"步骤：{str(step.get('step_name', '')).strip() or str(step.get('step_id', '')).strip() or '未命名步骤'}",
                    "summary": str(step.get("final_response", "")).strip() or "该步骤已执行完成。",
                    "success": bool(step.get("success")),
                    "data": step,
                }
            )
        trace.append(
            {
                "phase": "workflow_final_status",
                "title": "Workflow 执行结果",
                "summary": "Workflow 已完成执行。" if success else (error or "Workflow 执行失败。"),
                "success": success,
                "data": {
                    "success": success,
                    "error": error,
                    "steps_count": len(step_results),
                    "workflow_id": workflow.id,
                },
            }
        )
        return trace

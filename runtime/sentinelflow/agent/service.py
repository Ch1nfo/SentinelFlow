from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from sentinelflow.agent.catalog import load_skill_catalog
from sentinelflow.agent.graph import build_agent_graph
from sentinelflow.agent.policy import can_agent_delegate_to_worker, can_agent_execute_skill, can_agent_read_skill
from sentinelflow.agent.prompt_builder import PromptBuildContext, build_prompt
from sentinelflow.agent.prompts import (
    PRIMARY_ALERT_ORCHESTRATION_APPENDIX,
    PRIMARY_ALERT_SYNTHESIS_APPENDIX,
    PRIMARY_COMMAND_ORCHESTRATION_APPENDIX,
    PRIMARY_COMMAND_SYNTHESIS_APPENDIX,
)
from sentinelflow.agent.registry import list_agent_definitions, resolve_default_agent
from sentinelflow.config.runtime import load_runtime_config
from sentinelflow.services.triage_service import TriageService
from sentinelflow.skills.adapters import SentinelFlowSkillRuntime
from sentinelflow.workflows.agent_workflow_registry import list_agent_workflows


THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)


def _clean_model_text(text: str) -> str:
    cleaned = THINK_BLOCK_PATTERN.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _normalize_markdown_line(text: str) -> str:
    cleaned = text.strip()
    cleaned = cleaned.strip("|").strip()
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__(.*?)__", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = cleaned.lstrip("-*#>").strip()
    parts = [part.strip() for part in cleaned.split("|") if part.strip()]
    if parts:
        cleaned = " ".join(parts)
    return cleaned


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _clean_model_text(text)
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
    try:
        decoded = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            decoded = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return decoded if isinstance(decoded, dict) else None


class SentinelFlowAgentService:
    def __init__(self, project_root: Path, skill_runtime: SentinelFlowSkillRuntime) -> None:
        self.project_root = project_root
        self.skill_runtime = skill_runtime
        self.triage_service = TriageService()
        self.agent_root = project_root / ".sentinelflow" / "plugins" / "agents"
        self.workflow_root = project_root / ".sentinelflow" / "plugins" / "workflows"
        self.workflow_runner = None

    def attach_workflow_runner(self, workflow_runner) -> None:
        self.workflow_runner = workflow_runner

    def is_configured(self, agent_name: str | None = None) -> bool:
        config = load_runtime_config()
        if not config.agent_enabled:
            return False
        agent_definition = resolve_default_agent(self.agent_root, agent_name)
        effective_config = agent_definition.resolve_runtime_config(config) if agent_definition else config
        return bool(
            effective_config.llm_model
            and effective_config.llm_api_key
            and effective_config.llm_api_base_url
        )

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import langgraph  # noqa: F401
            import langchain_openai  # noqa: F401
            import langchain_core  # noqa: F401
        except ModuleNotFoundError as exc:
            return False, str(exc)
        return True, None

    def _resolve_skill_permissions(self, agent_definition) -> tuple[list[str], list[str]]:
        if agent_definition is None:
            return self.skill_runtime.list_skills(), self.skill_runtime.list_skills()
        readable_skills: list[str] = []
        executable_skills: list[str] = []
        for skill in self.skill_runtime.loader.list_skills():
            if can_agent_read_skill(agent_definition, skill):
                readable_skills.append(skill.spec.name)
            if can_agent_execute_skill(agent_definition, skill):
                executable_skills.append(skill.spec.name)
        return readable_skills, executable_skills

    def _resolve_worker_candidates(self, primary_agent, entry_type: str = "conversation") -> list:
        if primary_agent is None or primary_agent.role != "primary" or not primary_agent.enabled:
            return []
        # Allow multi-agent routing for both conversation and alert entry types
        workers = [agent for agent in list_agent_definitions(self.agent_root) if agent.role == "worker" and agent.enabled]
        return [agent for agent in workers if can_agent_delegate_to_worker(primary_agent, agent.name)]

    async def _run_agent_graph(
        self,
        agent_definition,
        alert_data: dict[str, Any],
        history: list[dict[str, str]] | None = None,
        cancel_event=None,
    ) -> dict[str, Any]:
        config = load_runtime_config()
        effective_config = agent_definition.resolve_runtime_config(config) if agent_definition else config
        readable_skills, executable_skills = self._resolve_skill_permissions(agent_definition)
        prompt_mode = "agent_command" if alert_data.get("alert_source") == "human_command" else "agent_alert"
        graph = build_agent_graph(
            self.project_root,
            self.skill_runtime,
            effective_config,
            enable_read_skill_document=bool(readable_skills),
            enable_execute_skill=bool(executable_skills),
        )
        state = await graph.ainvoke(
            {
                "alert_data": alert_data,
                "messages": self._build_history_messages(history or []),
                "event_id_ref": str(alert_data.get("eventIds", "")).strip(),
                "input_seeded": False,
                "cancel_event": cancel_event,
                "readable_skills": readable_skills,
                "executable_skills": executable_skills,
                "system_prompt_override": agent_definition.prompt_for_mode(prompt_mode) if agent_definition else "",
                "agent_name": agent_definition.name if agent_definition else "",
            }
        )
        return self._serialize_graph_result(
            str(alert_data.get("payload") or alert_data.get("eventIds") or "").strip(),
            state,
            agent_definition.name if agent_definition else "",
        )

    async def _run_planner_graph(
        self,
        agent_definition,
        alert_data: dict[str, Any],
        history: list[dict[str, str]] | None = None,
        cancel_event=None,
    ) -> dict[str, Any]:
        from pydantic import BaseModel, Field
        from langchain_openai import ChatOpenAI
        from sentinelflow.agent.prompts import DEFAULT_COMMAND_SYSTEM_PROMPT, DEFAULT_ALERT_SYSTEM_PROMPT
        from langchain_core.messages import SystemMessage, HumanMessage

        class PlannerResult(BaseModel):
            strategy: str = Field(description="The strategy to handle the task: 'self_handle', 'finish', 'self_execute', 'delegate', 'workflow', or 'direct'")
            response: str = Field(description="Direct response to the user, if strategy is self_handle or finish", default="")
            worker: str = Field(description="Target sub-agent to delegate to, if strategy is delegate", default="")
            task_prompt: str = Field(description="The instructions to send to the worker, if strategy is delegate", default="")
            reason: str = Field(description="The internal reasoning for this decision.", default="")
            workflow_id: str = Field(description="Target workflow id if strategy is workflow", default="")

        config = load_runtime_config()
        effective_config = agent_definition.resolve_runtime_config(config) if agent_definition else config
        try:
            llm_instance = ChatOpenAI(
                model=effective_config.llm_model,
                api_key=effective_config.llm_api_key,
                base_url=effective_config.llm_api_base_url,
                temperature=effective_config.llm_temperature,
                timeout=effective_config.llm_timeout,
            )
            llm = llm_instance.with_structured_output(PlannerResult)
        except Exception as exc:
            raise RuntimeError(f"模型加载失败，可能是它不支持强绑定 Function Calling({exc})。")

        custom_prompt = agent_definition.prompt_for_mode(
            "agent_command" if alert_data.get("alert_source") == "human_command" else "agent_alert"
        ) if agent_definition else ""
        system_msg = SystemMessage(content=custom_prompt)
        
        is_human_command = alert_data.get("alert_source") == "human_command"
        if is_human_command:
            payload = str(alert_data.get("payload", "")).strip()
            initial_msg = HumanMessage(content=f"请执行以下人工指令：{payload}")
        else:
            alert_json = json.dumps(alert_data, ensure_ascii=False, indent=2)
            initial_msg = HumanMessage(content=f"请分析并调度以下告警：\n\n```json\n{alert_json}\n```")

        messages = [system_msg] + self._build_history_messages(history or []) + [initial_msg]
        
        try:
            response_obj = await llm.ainvoke(messages)
            if hasattr(response_obj, "model_dump_json"):
                final_response = response_obj.model_dump_json()
            else:
                final_response = json.dumps(dict(response_obj), ensure_ascii=False)
        except Exception as exc:
            raise RuntimeError(f"结构化输出解析失败 (可能是模型智商不足或配置错误): {exc}")

        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            raise RuntimeError("用户已停止当前任务。")

        return {
            "final_response": final_response,
            "success": True,
            "route": "structured_planner",
            "messages": []
        }

    def _build_worker_catalog(self, workers: list) -> str:
        if not workers:
            return "（当前没有可用子 Agent）"
        items: list[str] = []
        for worker in workers:
            items.append(f"- name: {worker.name}\n  description: {worker.description or worker.name}")
        return "\n".join(items)

    def _build_primary_prompt(self, primary_agent, appendix_template: str, workers: list) -> str:
        mode_map = {
            PRIMARY_COMMAND_ORCHESTRATION_APPENDIX: "primary_orchestrate_command",
            PRIMARY_ALERT_ORCHESTRATION_APPENDIX: "primary_orchestrate_alert",
        }
        readable_skills, _ = self._resolve_skill_permissions(primary_agent)
        skill_catalog = load_skill_catalog(self.project_root / ".sentinelflow" / "plugins" / "skills", readable_skills)
        workflows = [workflow for workflow in list_agent_workflows(self.workflow_root) if workflow.enabled]
        return build_prompt(
            PromptBuildContext(
                base_prompt=primary_agent.prompt_for_mode(mode_map.get(appendix_template, "primary_orchestrate_alert")).strip() if primary_agent else "",
                mode=mode_map.get(appendix_template, "primary_orchestrate_alert"),
                skill_catalog=skill_catalog,
                worker_catalog=self._build_worker_catalog(workers),
                workflow_catalog=self._build_workflow_catalog(workflows),
            )
        )

    def _build_workflow_catalog(self, workflows: list) -> str:
        if not workflows:
            return "（当前没有可用 Agent Workflow）"
        items: list[str] = []
        for workflow in workflows:
            items.append(
                "\n".join(
                    [
                        f"- id: {workflow.id}",
                        f"  name: {workflow.name}",
                        f"  description: {workflow.description or workflow.name}",
                        f"  scenarios: {', '.join(workflow.scenarios) if workflow.scenarios else '未设置'}",
                        f"  recommended_action: {workflow.recommended_action}",
                        f"  selection_keywords: {', '.join(workflow.selection_keywords) if workflow.selection_keywords else '未设置'}",
                        f"  step_agents: {', '.join(step.agent for step in workflow.steps) if workflow.steps else '无步骤'}",
                    ]
                )
            )
        return "\n".join(items)

    def _build_primary_synthesis_prompt(self, primary_agent, appendix_template: str) -> str:
        mode_map = {
            PRIMARY_COMMAND_SYNTHESIS_APPENDIX: "primary_synthesize_command",
            PRIMARY_ALERT_SYNTHESIS_APPENDIX: "primary_synthesize_alert",
        }
        return build_prompt(
            PromptBuildContext(
                base_prompt=primary_agent.prompt_for_mode(mode_map.get(appendix_template, "primary_synthesize_alert")).strip() if primary_agent else "",
                mode=mode_map.get(appendix_template, "primary_synthesize_alert"),
            )
        )

    async def _summarize_worker_command(
        self,
        primary_agent,
        command_text: str,
        step_results: list[dict[str, Any]],
        cancel_event=None,
    ) -> dict[str, Any]:
        latest = step_results[-1] if step_results else {}
        synthesis_agent = replace(
            primary_agent,
            prompt=self._build_primary_synthesis_prompt(primary_agent, PRIMARY_COMMAND_SYNTHESIS_APPENDIX),
        )
        synthesis_payload = {
            "eventIds": f"SUM-{uuid4().hex[:12].upper()}",
            "alert_name": "子 Agent 执行结果汇总",
            "payload": json.dumps(
                {
                    "user_command": command_text,
                    "step_results": step_results,
                    "latest_worker_agent": latest.get("worker_agent", ""),
                    "latest_worker_final_response": latest.get("final_response", ""),
                },
                ensure_ascii=False,
            ),
            "alert_source": "agent_synthesis",
        }
        return await self._run_agent_graph(synthesis_agent, synthesis_payload, history=[], cancel_event=cancel_event)

    async def _summarize_worker_alert(
        self,
        primary_agent,
        alert: dict[str, Any],
        action_hint: str | None,
        step_results: list[dict[str, Any]],
        cancel_event=None,
    ) -> dict[str, Any]:
        latest = step_results[-1] if step_results else {}
        synthesis_agent = replace(
            primary_agent,
            prompt=self._build_primary_synthesis_prompt(primary_agent, PRIMARY_ALERT_SYNTHESIS_APPENDIX),
        )
        synthesis_payload = {
            **dict(alert),
            "handling_intent": action_hint or "",
            "payload": json.dumps(
                {
                    "original_alert": alert,
                    "step_results": step_results,
                    "latest_worker_agent": latest.get("worker_agent", ""),
                    "latest_worker_final_response": latest.get("final_response", ""),
                },
                ensure_ascii=False,
            ),
            "alert_source": "agent_synthesis",
        }
        return await self._run_agent_graph(synthesis_agent, synthesis_payload, history=[], cancel_event=cancel_event)

    def _build_command_planner_payload(self, command_text: str, step_results: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "eventIds": f"PLAN-{uuid4().hex[:12].upper()}",
            "alert_name": "主 Agent 调度",
            "payload": json.dumps(
                {
                    "original_command": command_text,
                    "completed_steps": step_results,
                },
                ensure_ascii=False,
            ),
            "alert_source": "human_command",
        }

    def _build_command_self_execute_payload(self, command_text: str, step_results: list[dict[str, Any]]) -> dict[str, Any]:
        if not step_results:
            payload = command_text
        else:
            payload = json.dumps(
                {
                    "original_command": command_text,
                    "completed_steps": step_results,
                    "instruction": "请结合上面的原始任务和已完成步骤结果，必要时继续使用你自己的技能，并直接给用户最终回复。",
                },
                ensure_ascii=False,
            )
        return {
            "eventIds": f"CMD-{uuid4().hex[:12].upper()}",
            "alert_name": "人工指令",
            "payload": payload,
            "alert_source": "human_command",
        }

    def _build_alert_planner_payload(self, alert: dict[str, Any], action_hint: str | None, step_results: list[dict[str, Any]]) -> dict[str, Any]:
        planner_alert = dict(alert)
        planner_alert["handling_intent"] = action_hint or ""
        planner_alert["payload"] = json.dumps(
            {
                "original_alert": alert,
                "handling_intent": action_hint or "",
                "completed_steps": step_results,
            },
            ensure_ascii=False,
        )
        return planner_alert

    def _build_alert_self_execute_payload(
        self,
        alert: dict[str, Any],
        action_hint: str | None,
        step_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not step_results:
            delegated_alert = dict(alert)
            if action_hint:
                delegated_alert["handling_intent"] = action_hint
            return delegated_alert
        delegated_alert = dict(alert)
        delegated_alert["handling_intent"] = action_hint or ""
        delegated_alert["payload"] = json.dumps(
            {
                "original_alert": alert,
                "handling_intent": action_hint or "",
                "completed_steps": step_results,
                "instruction": "请结合上面的原始告警和已完成步骤结果，必要时继续使用你自己的技能，并直接给出最终值班结论。",
            },
            ensure_ascii=False,
        )
        return delegated_alert

    def _compact_worker_result(
        self,
        worker_name: str,
        task_prompt: str,
        reason: str,
        worker_result: dict[str, Any],
        step_index: int,
    ) -> dict[str, Any]:
        return {
            "step": step_index,
            "worker_agent": worker_name,
            "task_prompt": task_prompt,
            "delegation_reason": reason,
            "route": worker_result.get("route", ""),
            "final_response": worker_result.get("final_response", ""),
            "tool_calls": worker_result.get("tool_calls", []),
            "messages": worker_result.get("messages", []),
            "success": worker_result.get("success", True),
            "disposition": worker_result.get("disposition", ""),
            "reason": worker_result.get("reason", ""),
            "evidence": worker_result.get("evidence", []),
            "actions": worker_result.get("actions", {}),
        }

    def _should_use_orchestrator(self, primary_agent, workers: list) -> bool:
        if primary_agent is None or primary_agent.role != "primary":
            return False
        if workers:
            return True
        if self.workflow_runner is None:
            return False
        return any(workflow.enabled for workflow in list_agent_workflows(self.workflow_root))

    def _resolve_worker_max_steps(self, primary_agent) -> int:
        raw_value = getattr(primary_agent, "worker_max_steps", 3)
        if not isinstance(raw_value, int):
            return 3
        return max(1, raw_value)

    def _resolve_worker_parallel_limit(self, primary_agent) -> int:
        raw_value = getattr(primary_agent, "worker_parallel_limit", 3)
        if not isinstance(raw_value, int):
            return 3
        return max(1, raw_value)

    def _serialize_orchestrator_result(
        self,
        final_state: dict[str, Any],
        alert_data: dict[str, Any],
        primary_agent,
        action_hint: str | None,
    ) -> dict[str, Any]:
        """Deserialize the completed OrchestratorState into a result dict."""
        messages = final_state.get("messages", [])

        # Final supervisor response = last AI message with non-empty content
        final_text = ""
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if msg_type == "ai" and content:
                final_text = _clean_model_text(content)
                break

        # Worker results surfaced from ToolMessages
        worker_results: list[dict[str, Any]] = []
        workflow_runs: list[dict[str, Any]] = []
        for msg in messages:
            try:
                from langchain_core.messages import ToolMessage
                if not isinstance(msg, ToolMessage):
                    continue
            except ModuleNotFoundError:
                pass
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                continue
            try:
                result = json.loads(content)
                if isinstance(result, dict) and "worker" in result:
                    worker_results.append(result)
                elif isinstance(result, dict) and result.get("workflow_id"):
                    workflow_runs.append(result)
                elif isinstance(result, dict) and result.get("mode") == "parallel" and isinstance(result.get("results"), list):
                    for item in result["results"]:
                        if isinstance(item, dict) and "worker" in item:
                            worker_results.append(item)
            except (json.JSONDecodeError, TypeError):
                pass

        # Tool calls summary for upstream compatibility
        tool_calls: list[dict[str, Any]] = []
        for msg in messages:
            for tc in (getattr(msg, "tool_calls", None) or []):
                if isinstance(tc, dict):
                    tool_calls.append(tc)

        # Serialized message list
        serialized_messages: list[dict[str, Any]] = []
        for msg in messages:
            msg_type = getattr(msg, "type", msg.__class__.__name__.lower())
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                content = _clean_model_text(content)
            item: dict[str, Any] = {"type": msg_type, "content": content}
            if getattr(msg, "tool_calls", None):
                item["tool_calls"] = msg.tool_calls
            if getattr(msg, "name", None):
                item["name"] = msg.name
            serialized_messages.append(item)

        return {
            "source": str(alert_data.get("payload") or alert_data.get("eventIds") or "").strip(),
            "agent_name": primary_agent.name if primary_agent else "",
            "final_response": final_text,
            "messages": serialized_messages,
            "tool_calls": tool_calls,
            "event_id_ref": str(alert_data.get("eventIds", "")).strip(),
            "orchestrated": True,
            "orchestration_strategy": "subgraph_supervisor",
            "primary_agent": primary_agent.name if primary_agent else "",
            "worker_results": worker_results,
            "workflow_runs": workflow_runs,
            "worker_agent": worker_results[-1]["worker"] if worker_results else "",
            "success": bool(final_text),
        }

    async def _orchestrate_command(
        self,
        primary_agent,
        workers: list,
        command_text: str,
        history: list[dict[str, str]] | None,
        cancel_event=None,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        from sentinelflow.agent.orchestrator_graph import build_orchestrator_graph

        config = load_runtime_config()
        effective_config = primary_agent.resolve_runtime_config(config)
        max_steps = self._resolve_worker_max_steps(primary_agent)
        parallel_limit = self._resolve_worker_parallel_limit(primary_agent)
        readable_skills, executable_skills = self._resolve_skill_permissions(primary_agent)
        alert_data = {
            "eventIds": f"CMD-{uuid4().hex[:12].upper()}",
            "alert_name": "人工指令",
            "payload": command_text,
            "alert_source": "human_command",
            "_primary_readable_skills": readable_skills,
            "_primary_executable_skills": executable_skills,
            "_primary_worker_parallel_limit": parallel_limit,
        }
        system_prompt = self._build_primary_prompt(
            primary_agent, PRIMARY_COMMAND_ORCHESTRATION_APPENDIX, workers
        )
        if status_callback:
            status_callback("正在构建多 Agent 编排图...")

        orchestrator = build_orchestrator_graph(
            primary_agent,
            workers,
            self.project_root,
            self.skill_runtime,
            effective_config,
            alert_data=alert_data,
            cancel_event=cancel_event,
            workflow_root=self.workflow_root,
            workflow_runner=self.workflow_runner,
        )
        initial_state = {
            "alert_data": alert_data,
            "action_hint": "",
            "entry_type": "conversation",
            "messages": [],
            "conversation_history": list(history or []),
            "worker_results": [],
            "system_prompt_override": system_prompt,
            "cancel_event": cancel_event,
            "readable_skills": readable_skills,
            "executable_skills": executable_skills,
        }
        if status_callback:
            status_callback("主 Agent 正在分析任务并调度子 Agent...")
        final_state = await orchestrator.ainvoke(
            initial_state,
            {"recursion_limit": max(10, max_steps * 4 + 4)},
        )
        return self._serialize_orchestrator_result(final_state, alert_data, primary_agent, action_hint=None)

    async def _orchestrate_alert(
        self,
        primary_agent,
        workers: list,
        alert: dict[str, Any],
        action_hint: str | None,
        cancel_event=None,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        from sentinelflow.agent.orchestrator_graph import build_orchestrator_graph

        config = load_runtime_config()
        effective_config = primary_agent.resolve_runtime_config(config)
        max_steps = self._resolve_worker_max_steps(primary_agent)
        parallel_limit = self._resolve_worker_parallel_limit(primary_agent)
        readable_skills, executable_skills = self._resolve_skill_permissions(primary_agent)

        alert_data = dict(alert)
        if action_hint:
            alert_data["handling_intent"] = action_hint
        alert_data["_primary_readable_skills"] = readable_skills
        alert_data["_primary_executable_skills"] = executable_skills
        alert_data["_primary_worker_parallel_limit"] = parallel_limit

        system_prompt = self._build_primary_prompt(
            primary_agent, PRIMARY_ALERT_ORCHESTRATION_APPENDIX, workers
        )
        orchestrator = build_orchestrator_graph(
            primary_agent,
            workers,
            self.project_root,
            self.skill_runtime,
            effective_config,
            alert_data=alert_data,
            cancel_event=cancel_event,
            workflow_root=self.workflow_root,
            workflow_runner=self.workflow_runner,
        )
        initial_state = {
            "alert_data": alert_data,
            "action_hint": action_hint or "",
            "entry_type": "alert",
            "messages": [],
            "conversation_history": [],
            "worker_results": [],
            "system_prompt_override": system_prompt,
            "cancel_event": cancel_event,
            "readable_skills": readable_skills,
            "executable_skills": executable_skills,
        }
        if status_callback:
            status_callback("主 Agent 正在分析告警并调度子 Agent...")
        final_state = await orchestrator.ainvoke(
            initial_state,
            {"recursion_limit": max(10, max_steps * 4 + 4)},
        )
        graph_result = self._serialize_orchestrator_result(final_state, alert, primary_agent, action_hint)
        return self._serialize_alert_result(alert, graph_result, action_hint)


    async def run_command(
        self,
        command_text: str,
        history: list[dict[str, str]] | None = None,
        cancel_event=None,
        agent_name: str | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        config = load_runtime_config()
        agent_definition = resolve_default_agent(self.agent_root, agent_name)
        workers = self._resolve_worker_candidates(agent_definition, entry_type="conversation")
        if self._should_use_orchestrator(agent_definition, workers):
            return await self._orchestrate_command(agent_definition, workers, command_text, history, cancel_event, status_callback=status_callback)
        alert = {
            "eventIds": f"CMD-{uuid4().hex[:12].upper()}",
            "alert_name": "人工指令",
            "payload": command_text,
            "alert_source": "human_command",
        }
        return await self._run_agent_graph(agent_definition, alert, history=history, cancel_event=cancel_event)

    async def run_alert(
        self,
        alert: dict[str, Any],
        action_hint: str | None = None,
        cancel_event=None,
        agent_name: str | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        agent_definition = resolve_default_agent(self.agent_root, agent_name)
        workers = self._resolve_worker_candidates(agent_definition, entry_type="alert")
        if self._should_use_orchestrator(agent_definition, workers):
            return await self._orchestrate_alert(agent_definition, workers, alert, action_hint, cancel_event, status_callback=status_callback)
        alert_payload = dict(alert)
        if action_hint:
            alert_payload["handling_intent"] = action_hint
        serialized = await self._run_agent_graph(agent_definition, alert_payload, history=[], cancel_event=cancel_event)
        return self._serialize_alert_result(alert, serialized, action_hint)


    def _serialize_graph_result(self, source: str, state: dict[str, Any], agent_name: str = "") -> dict[str, Any]:
        messages = state.get("messages", [])
        final_text = ""
        serialized_messages: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []

        for msg in messages:
            msg_type = getattr(msg, "type", msg.__class__.__name__.lower())
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                content = _clean_model_text(content)
            item: dict[str, Any] = {"type": msg_type, "content": content}
            if getattr(msg, "tool_calls", None):
                item["tool_calls"] = msg.tool_calls
                tool_calls.extend(msg.tool_calls)
            if getattr(msg, "name", None):
                item["name"] = msg.name
            if getattr(msg, "tool_call_id", None):
                item["tool_call_id"] = msg.tool_call_id
            serialized_messages.append(item)
            if msg_type == "ai" and content:
                final_text = content

        return {
            "source": source,
            "agent_name": agent_name,
            "final_response": final_text,
            "messages": serialized_messages,
            "tool_calls": tool_calls,
            "event_id_ref": state.get("event_id_ref", ""),
        }

    def _serialize_alert_result(
        self,
        alert: dict[str, Any],
        graph_result: dict[str, Any],
        action_hint: str | None,
    ) -> dict[str, Any]:
        skill_runs = self._extract_skill_runs(graph_result)
        fallback_judgment = self.triage_service.analyze_alert(alert)
        final_text = str(graph_result.get("final_response", "")).strip()
        disposition = self._infer_disposition(final_text, fallback_judgment.disposition.value)
        summary = self._infer_summary(final_text, fallback_judgment.summary)
        reason = self._infer_reason(final_text, alert, fallback_judgment)
        if not summary or summary in {"--", "-", "—"}:
            summary = reason or fallback_judgment.summary
        evidence = self._infer_evidence(final_text, alert, fallback_judgment)
        analysis_step = self._build_analysis_step(graph_result, disposition, summary, reason, evidence)
        enrichment = self._first_enrichment_payload(skill_runs)
        closure_run = self._select_closure_run(skill_runs, action_hint)
        closure_result = self._first_closure_payload(skill_runs, closure_run)
        actions = self._build_actions(skill_runs, closure_run)
        action_steps = self._build_action_steps(skill_runs, closure_run)
        closure_step = self._build_closure_step(skill_runs, closure_run)
        workflow_runs = graph_result.get("workflow_runs", [])
        if not isinstance(workflow_runs, list):
            workflow_runs = []
        success = self._compute_alert_task_success(
            action_hint=action_hint,
            closure_step=closure_step,
            action_steps=action_steps,
            skill_runs=skill_runs,
            actions=actions,
        )
        workflow_selection = self._extract_workflow_selection(alert, graph_result)
        execution_trace = self._build_execution_trace(
            alert=alert,
            graph_result=graph_result,
            workflow_selection=workflow_selection,
            workflow_runs=workflow_runs,
            analysis_step=analysis_step,
            disposition=disposition,
            summary=summary,
            reason=reason,
            evidence=evidence,
            enrichment=enrichment,
            action_steps=action_steps,
            closure_step=closure_step,
            closure_result=closure_result,
            actions=actions,
            skill_runs=skill_runs,
            success=success,
        )

        return {
            **graph_result,
            "event_ids": str(alert.get("eventIds", "")).strip(),
            "disposition": disposition,
            "summary": summary,
            "reason": reason,
            "evidence": evidence,
            "analysis_step": analysis_step,
            "memo": self._infer_closure_field(skill_runs, "memo", self.triage_service.build_memo(summary)),
            "detail_msg": self._infer_closure_field(skill_runs, "detailMsg", self._default_detail_msg(disposition)),
            "closure_status": self._infer_closure_field(skill_runs, "status", self._default_closure_status(disposition)),
            "enrichment": enrichment,
            "workflow_selection": workflow_selection,
            "workflow_runs": workflow_runs,
            "action_steps": action_steps,
            "closure_step": closure_step,
            "closure_result": closure_result,
            "actions": actions,
            "success": success,
            "execution_mode": "agent",
            "execution_trace": execution_trace,
            "used_agent": True,
            "has_close_action": closure_run is not None,
            "has_disposal_action": bool(actions),
        }

    def _extract_workflow_selection(
        self,
        alert: dict[str, Any],
        graph_result: dict[str, Any],
    ) -> dict[str, Any]:
        direct = graph_result.get("workflow_selection")
        if isinstance(direct, dict):
            return dict(direct)
        payload = alert.get("_workflow_selection")
        if isinstance(payload, dict):
            return dict(payload)
        raw_payload = alert.get("payload")
        if isinstance(raw_payload, str) and raw_payload.strip().startswith("{"):
            try:
                decoded = json.loads(raw_payload)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, dict):
                candidate = decoded.get("workflow_selection")
                if isinstance(candidate, dict):
                    return dict(candidate)
        return {}

    def _build_execution_trace(
        self,
        *,
        alert: dict[str, Any],
        graph_result: dict[str, Any],
        workflow_selection: dict[str, Any],
        workflow_runs: list[dict[str, Any]],
        analysis_step: dict[str, Any],
        disposition: str,
        summary: str,
        reason: str,
        evidence: list[str],
        enrichment: dict[str, Any],
        action_steps: list[dict[str, Any]],
        closure_step: dict[str, Any],
        closure_result: dict[str, Any],
        actions: dict[str, Any],
        skill_runs: list[dict[str, Any]],
        success: bool,
    ) -> list[dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        trace.append(
            {
                "phase": "alert_received",
                "title": "接收告警",
                "summary": "已接收任务告警上下文。",
                "success": True,
                "data": {
                    "eventIds": str(alert.get("eventIds", "")).strip(),
                    "alert_name": str(alert.get("alert_name", alert.get("alert_name") or alert.get("alertName", ""))).strip(),
                    "sip": alert.get("sip", ""),
                    "dip": alert.get("dip", ""),
                    "alert_time": alert.get("alert_time", ""),
                    "alert_source": alert.get("alert_source", ""),
                    "current_judgment": alert.get("current_judgment", ""),
                    "history_judgment": alert.get("history_judgment", ""),
                    "payload": alert.get("payload", ""),
                },
            }
        )
        if workflow_selection:
            trace.append(
                {
                    "phase": "workflow_selection",
                    "title": "Workflow 记录",
                    "summary": (
                        f"历史流程记录：{workflow_selection.get('workflow_id')}"
                        if workflow_selection.get("workflow_id")
                        else str(workflow_selection.get("reason", "")).strip() or "存在历史 Workflow 记录。"
                    ),
                    "success": True,
                    "data": workflow_selection,
                }
            )
        for workflow_run in workflow_runs:
            if not isinstance(workflow_run, dict):
                continue
            trace.append(
                {
                    "phase": "workflow_run",
                    "title": f"调用 Workflow：{str(workflow_run.get('workflow_name', workflow_run.get('workflow_id', '未命名流程'))).strip()}",
                    "summary": str(workflow_run.get("summary", "")).strip() or "主 Agent 调用了一个固定多步骤 Workflow。",
                    "success": bool(workflow_run.get("success")),
                    "data": workflow_run,
                }
            )
            nested_trace = workflow_run.get("execution_trace", [])
            if isinstance(nested_trace, list):
                for nested_item in nested_trace:
                    if not isinstance(nested_item, dict):
                        continue
                    trace.append(
                        {
                            "phase": f"workflow_nested_{str(nested_item.get('phase', '')).strip() or 'step'}",
                            "title": f"Workflow 内部：{str(nested_item.get('title', '')).strip() or '步骤'}",
                            "summary": str(nested_item.get("summary", "")).strip(),
                            "success": nested_item.get("success"),
                            "data": nested_item.get("data", nested_item),
                        }
                    )
        trace.append(
            {
                "phase": "agent_analysis",
                "title": "主 Agent 研判",
                "summary": summary or reason or "主 Agent 已输出研判结论。",
                "success": bool(analysis_step.get("success", True)),
                "data": analysis_step,
            }
        )
        if enrichment:
            trace.append(
                {
                    "phase": "enrichment",
                    "title": "情报补充",
                    "summary": "已产生额外情报或上下文补充结果。",
                    "success": not bool(enrichment.get("error")),
                    "data": enrichment,
                }
            )
        if skill_runs:
            trace.append(
                {
                    "phase": "skill_runs",
                    "title": "技能调用记录",
                    "summary": f"共调用 {len(skill_runs)} 个技能。",
                    "success": all(bool(run.get("success")) for run in skill_runs),
                    "data": {
                        "runs": skill_runs,
                    },
                }
            )
        if actions:
            trace.append(
                {
                    "phase": "actions",
                    "title": "处置动作",
                    "summary": f"共执行 {len(actions)} 类处置动作。",
                    "success": all(bool(step.get("success")) for step in action_steps) if action_steps else all(not bool(payload.get("error")) for payload in actions.values() if isinstance(payload, dict)),
                    "data": {
                        "steps": action_steps,
                        "actions": actions,
                    },
                }
            )
        if closure_step.get("attempted") or closure_result:
            trace.append(
                {
                    "phase": "closure",
                    "title": "结单结果",
                    "summary": str(
                        closure_step.get("summary")
                        or closure_result.get("detailMsg")
                        or closure_result.get("detail_msg")
                        or closure_result.get("result")
                        or "已执行结单。"
                    ).strip(),
                    "success": bool(closure_step.get("success")),
                    "data": {
                        **closure_step,
                        "closure_result": closure_result,
                    },
                }
            )
        trace.append(
            {
                "phase": "final_status",
                "title": "最终执行状态",
                "summary": "任务成功完成。" if success else "任务未完成或未返回成功结果。",
                "success": success,
                "data": {
                    "success": success,
                    "has_close_action": bool(closure_step.get("attempted")),
                    "has_disposal_action": bool(action_steps) or bool(actions),
                    "tool_calls": graph_result.get("tool_calls", []),
                    "messages": graph_result.get("messages", []),
                },
            }
        )
        return trace

    def _build_analysis_step(
        self,
        graph_result: dict[str, Any],
        disposition: str,
        summary: str,
        reason: str,
        evidence: list[str],
    ) -> dict[str, Any]:
        return {
            "attempted": True,
            "success": True,
            "agent_name": graph_result.get("agent_name", ""),
            "used_agent": True,
            "execution_mode": "agent",
            "disposition": disposition,
            "summary": summary,
            "reason": reason,
            "evidence": evidence,
            "final_response": graph_result.get("final_response", ""),
        }

    def _build_action_steps(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for run in skill_runs:
            skill_name = str(run.get("skill_name", "")).strip()
            if not skill_name or self._is_same_skill_run(run, closure_run) or self._is_enrichment_run(run):
                continue
            payload = run.get("payload", {})
            steps.append(
                {
                    "attempted": True,
                    "success": bool(run.get("success")),
                    "skill_name": skill_name,
                    "tool_name": run.get("tool_name", ""),
                    "tool_call_id": run.get("tool_call_id", ""),
                    "tool_success": run.get("tool_success"),
                    "tool_error": run.get("tool_error"),
                    "arguments": run.get("arguments", {}) if isinstance(run.get("arguments"), dict) else {},
                    "result": payload if isinstance(payload, dict) else {},
                    "error": payload.get("error") if isinstance(payload, dict) else None,
                }
            )
        return steps

    def _build_closure_step(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if closure_run is not None:
            skill_name = str(closure_run.get("skill_name", "")).strip()
            payload = closure_run.get("payload", {})
            arguments = closure_run.get("arguments", {})
            payload = payload if isinstance(payload, dict) else {}
            arguments = arguments if isinstance(arguments, dict) else {}
            success = self._is_successful_closure_run(closure_run)
            summary = str(
                payload.get("detailMsg")
                or payload.get("detail_msg")
                or payload.get("result")
                or payload.get("message")
                or ("结单执行成功。" if success else "结单执行失败。")
            ).strip()
            return {
                "attempted": True,
                "success": success,
                "skill_name": skill_name,
                "tool_name": closure_run.get("tool_name", ""),
                "tool_call_id": closure_run.get("tool_call_id", ""),
                "tool_success": closure_run.get("tool_success"),
                "tool_error": closure_run.get("tool_error"),
                "arguments": arguments,
                "result": payload,
                "error": payload.get("error"),
                "summary": summary,
            }
        return {
            "attempted": False,
            "success": False,
            "skill_name": "",
            "tool_name": "",
            "tool_call_id": "",
            "tool_success": False,
            "tool_error": None,
            "arguments": {},
            "result": {},
            "error": None,
            "summary": "",
        }

    def _compute_alert_task_success(
        self,
        *,
        action_hint: str | None,
        closure_step: dict[str, Any],
        action_steps: list[dict[str, Any]],
        skill_runs: list[dict[str, Any]],
        actions: dict[str, Any],
    ) -> bool:
        if bool(closure_step.get("attempted")) and bool(closure_step.get("success")):
            return True
        if action_hint == "triage_dispose" and action_steps and all(bool(step.get("success")) for step in action_steps):
            return True
        closure_success = any(self._is_successful_closure_run(run) for run in skill_runs)
        disposal_success = any(not bool(payload.get("error")) for payload in actions.values() if isinstance(payload, dict))
        return closure_success or (action_hint == "triage_dispose" and disposal_success)

    def _extract_skill_runs(self, graph_result: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = [item for item in graph_result.get("tool_calls", []) if isinstance(item, dict)]
        tool_messages = [
            item
            for item in graph_result.get("messages", [])
            if isinstance(item, dict) and str(item.get("type", "")).strip() == "tool"
        ]
        tool_messages_by_id: dict[str, dict[str, Any]] = {}
        ordered_tool_messages: list[dict[str, Any]] = []
        for tool_message in tool_messages:
            tool_call_id = str(tool_message.get("tool_call_id", "")).strip()
            if tool_call_id:
                tool_messages_by_id[tool_call_id] = tool_message
            ordered_tool_messages.append(tool_message)
        runs: list[dict[str, Any]] = []
        tool_index = 0
        for call in tool_calls:
            tool_name = str(call.get("name", "")).strip()
            if tool_name not in {"execute_skill", "execute_skill_no_args"}:
                continue
            args = call.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            skill_name = str(args.get("skill_name", "")).strip()
            arguments = args.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            if tool_name == "execute_skill_no_args":
                arguments = {}

            payload: dict[str, Any] = {}
            matched_message = None
            tool_call_id = str(call.get("id", "")).strip()
            if tool_call_id:
                matched_message = tool_messages_by_id.get(tool_call_id)
            if matched_message is None:
                while tool_index < len(ordered_tool_messages):
                    tool_message = ordered_tool_messages[tool_index]
                    tool_index += 1
                    candidate_id = str(tool_message.get("tool_call_id", "")).strip()
                    if candidate_id and candidate_id != tool_call_id:
                        continue
                    matched_message = tool_message
                    break
            if matched_message is not None:
                content = matched_message.get("content", "")
                if isinstance(content, str):
                    try:
                        decoded = json.loads(content)
                    except json.JSONDecodeError:
                        decoded = {"raw": content}
                elif isinstance(content, dict):
                    decoded = content
                else:
                    decoded = {"result": content}
                if isinstance(decoded, dict):
                    payload = decoded

            tool_payload = dict(payload)
            business_payload = tool_payload.get("data", {})
            if not isinstance(business_payload, dict):
                business_payload = {"result": business_payload}

            merged_payload = dict(business_payload)
            for key, value in arguments.items():
                merged_payload.setdefault(key, value)
            runs.append(
                {
                    "skill_name": skill_name,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "tool_success": bool(tool_payload.get("success")) if isinstance(tool_payload.get("success"), bool) else not bool(tool_payload.get("error")),
                    "tool_error": tool_payload.get("error"),
                    "tool_payload": tool_payload,
                    "arguments": arguments,
                    "payload": merged_payload,
                    "success": (bool(tool_payload.get("success")) if isinstance(tool_payload.get("success"), bool) else not bool(tool_payload.get("error")))
                    and not bool(merged_payload.get("error"))
                    and not (isinstance(merged_payload.get("success"), bool) and not bool(merged_payload.get("success"))),
                }
            )
        return runs

    def _build_actions(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        actions: dict[str, Any] = {}
        for run in skill_runs:
            skill_name = str(run.get("skill_name", "")).strip()
            if not skill_name or self._is_same_skill_run(run, closure_run) or self._is_enrichment_run(run):
                continue
            payload = run.get("payload", {})
            if isinstance(payload, dict) and payload:
                actions[skill_name.replace("-", "_")] = payload
        return actions

    def _first_closure_payload(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        selected = closure_run or self._select_closure_run(skill_runs, None)
        if selected is not None:
            payload = selected.get("payload", {})
            return payload if isinstance(payload, dict) else {}
        return {}

    def _first_enrichment_payload(self, skill_runs: list[dict[str, Any]]) -> dict[str, Any]:
        for run in skill_runs:
            if self._is_enrichment_run(run):
                payload = run.get("payload", {})
                return payload if isinstance(payload, dict) else {}
        return {}

    def _is_closure_run(self, run: dict[str, Any]) -> bool:
        skill_name = str(run.get("skill_name", "")).strip().lower()
        if self._is_closure_skill_name(skill_name):
            return True
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        combined_keys = set(payload.keys()) | set(arguments.keys())
        if {"status", "memo", "detailMsg"}.issubset(combined_keys):
            return True
        closure_markers = {"status", "memo", "detailMsg", "detail_msg", "closeStatus", "close_status", "result", "success"}
        return bool(combined_keys & closure_markers) and (
            "memo" in combined_keys or "detailMsg" in combined_keys or "detail_msg" in combined_keys or "status" in combined_keys
        )

    def _is_closure_skill_name(self, skill_name: str) -> bool:
        normalized = skill_name.strip().lower()
        if normalized in {"exec", "close", "soc_close", "alert_close"}:
            return True
        closure_keywords = (
            "exec",
            "close",
            "closure",
            "socclose",
            "alertclose",
            "ticketclose",
            "结单",
            "闭环",
            "关单",
        )
        compact = normalized.replace("-", "").replace("_", "").replace(" ", "")
        return any(keyword in compact for keyword in closure_keywords)

    def _looks_like_closure_fallback(self, run: dict[str, Any]) -> bool:
        skill_name = str(run.get("skill_name", "")).strip()
        if self._is_closure_skill_name(skill_name):
            return True
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        combined_keys = set(payload.keys()) | set(arguments.keys())
        if {"status", "memo", "detailMsg"} <= combined_keys:
            return True
        closure_markers = {"status", "memo", "detailMsg", "detail_msg", "closeStatus", "close_status"}
        if combined_keys & closure_markers:
            return True
        text_candidates = [
            skill_name,
            str(payload.get("message", "")),
            str(payload.get("result", "")),
            str(payload.get("raw", "")),
            str(arguments.get("message", "")),
            str(arguments.get("result", "")),
        ]
        normalized_text = " ".join(item.strip().lower() for item in text_candidates if item and str(item).strip())
        return any(marker in normalized_text for marker in ("结单", "闭环", "关单", "close", "closed", "closure", "exec"))

    def _select_closure_run(
        self,
        skill_runs: list[dict[str, Any]],
        action_hint: str | None,
    ) -> dict[str, Any] | None:
        for run in skill_runs:
            if self._is_closure_run(run):
                return run
        if action_hint not in {"triage_close", "triage_dispose"}:
            return None
        fallback_candidates = [
            run
            for run in skill_runs
            if str(run.get("skill_name", "")).strip()
            and not self._is_enrichment_run(run)
            and self._looks_like_closure_fallback(run)
        ]
        if fallback_candidates:
            return fallback_candidates[-1]
        return None

    def _is_same_skill_run(self, left: dict[str, Any], right: dict[str, Any] | None) -> bool:
        if right is None:
            return False
        left_id = str(left.get("tool_call_id", "")).strip()
        right_id = str(right.get("tool_call_id", "")).strip()
        if left_id and right_id:
            return left_id == right_id
        return left is right

    def _is_successful_closure_run(self, run: dict[str, Any]) -> bool:
        if not (self._is_closure_run(run) or self._looks_like_closure_fallback(run)):
            return False
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        tool_success = run.get("tool_success")
        tool_error = run.get("tool_error")
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        if bool(tool_error):
            return False
        if isinstance(tool_success, bool) and not tool_success:
            return False
        if bool(payload.get("error")):
            return False
        status_value = payload.get("status", arguments.get("status"))
        result_value = payload.get("result", arguments.get("result"))
        success_value = payload.get("success", tool_success)
        if isinstance(success_value, bool):
            return success_value
        if isinstance(result_value, str) and result_value.strip():
            normalized = result_value.strip().lower()
            if normalized in {"ok", "success", "done", "closed", "completed", "true"}:
                return True
            if normalized in {"fail", "failed", "false", "error"}:
                return False
        if isinstance(status_value, str) and status_value.strip():
            return True
        if isinstance(tool_success, bool):
            return tool_success
        return bool(payload)

    def _is_enrichment_run(self, run: dict[str, Any]) -> bool:
        if self._is_closure_run(run):
            return False
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        combined_keys = set(payload.keys()) | set(arguments.keys())
        ip_markers = {"ip", "source_ip", "sip", "target_ip", "dest_ip", "dip"}
        detail_markers = {"country", "province", "city", "asn", "isp", "risk_level"}
        return bool(combined_keys & ip_markers) and bool(combined_keys & detail_markers)

    def _infer_disposition(self, final_text: str, fallback: str) -> str:
        normalized = _clean_model_text(final_text).replace(" ", "")
        if any(keyword in normalized for keyword in ("非真实攻击", "不是真实攻击", "并非真实攻击", "不是攻击")):
            if "误报" in normalized:
                return "false_positive"
            return "business_trigger"
        if any(keyword in normalized for keyword in ("规则误报", "误报")):
            return "false_positive"
        if any(keyword in normalized for keyword in ("业务触发", "测试触发", "正常业务", "测试流量", "业务流量", "业务测试")):
            return "business_trigger"
        if any(keyword in normalized for keyword in ("真实攻击", "恶意攻击", "确认攻击", "高危攻击")):
            return "true_attack"
        return fallback or "unknown"

    def _infer_summary(self, final_text: str, fallback: str) -> str:
        for line in final_text.splitlines():
            stripped = _normalize_markdown_line(line)
            if not stripped:
                continue
            if any(marker in stripped for marker in ("最终分类", "简短理由", "关键依据", "执行结果")):
                continue
            if stripped in {"--", "-", "—"}:
                continue
            if stripped:
                return stripped[:120]
        return fallback

    def _infer_reason(self, final_text: str, alert: dict[str, Any], fallback_judgment) -> str:
        for raw_line in final_text.splitlines():
            normalized = _normalize_markdown_line(raw_line)
            if not normalized or normalized in {"--", "-", "—"}:
                continue
            lowered = normalized.lower()
            if any(marker in lowered for marker in ("简短理由", "原因", "理由")):
                parts = re.split(r"[:：]", normalized, maxsplit=1)
                candidate = parts[1].strip() if len(parts) > 1 else normalized
                candidate = candidate.replace("简短理由", "").replace("理由", "").replace("原因", "").strip("：: ").strip()
                if candidate and candidate not in {"--", "-", "—"}:
                    return candidate[:120]

        current = str(alert.get("current_judgment", "")).strip()
        history = str(alert.get("history_judgment", "")).strip()
        alert_name = str(alert.get("alert_name", "")).strip() or "该告警"
        if current:
            return f"{alert_name} 的当前研判信息显示：{current[:90]}"
        if history:
            return f"{alert_name} 的历史处置记录显示：{history[:90]}"
        return fallback_judgment.summary

    def _infer_evidence(self, final_text: str, alert: dict[str, Any], fallback_judgment) -> list[str]:
        evidence: list[str] = []
        capture = False
        for raw_line in final_text.splitlines():
            normalized = _normalize_markdown_line(raw_line)
            if not normalized:
                if capture and evidence:
                    break
                continue
            lowered = normalized.lower()
            if any(marker in lowered for marker in ("关键依据", "依据", "证据")):
                capture = True
                parts = re.split(r"[:：]", normalized, maxsplit=1)
                trailing = parts[1].strip() if len(parts) > 1 else ""
                trailing = trailing.replace("关键依据", "").replace("依据", "").replace("证据", "").strip("：: ").strip()
                if trailing and trailing not in {"--", "-", "—"}:
                    evidence.append(trailing[:160])
                continue
            if capture:
                if any(marker in normalized for marker in ("执行结果", "最终分类", "简短理由")):
                    break
                if normalized in {"--", "-", "—"}:
                    continue
                evidence.append(normalized[:160])
                if len(evidence) >= 3:
                    break

        if evidence:
            return evidence[:3]

        fallback = list(getattr(fallback_judgment, "evidence", []) or [])
        if fallback:
            return [str(item).strip()[:160] for item in fallback if str(item).strip()][:3]

        current = str(alert.get("current_judgment", "")).strip()
        history = str(alert.get("history_judgment", "")).strip()
        result: list[str] = []
        if current:
            result.append(f"当前研判：{current[:140]}")
        if history:
            result.append(f"历史处置：{history[:140]}")
        return result[:3]

    def _infer_closure_field(self, skill_runs: list[dict[str, Any]], field_name: str, fallback: str) -> str:
        closure_run = self._select_closure_run(skill_runs, None)
        if closure_run is None:
            return fallback
        for run in [closure_run]:
            if not self._is_same_skill_run(run, closure_run):
                continue
            payload = run.get("payload", {})
            if isinstance(payload, dict):
                value = str(payload.get(field_name, "")).strip()
                if value:
                    return value
            arguments = run.get("arguments", {})
            if isinstance(arguments, dict):
                value = str(arguments.get(field_name, "")).strip()
                if value:
                    return value
        return fallback

    def _default_detail_msg(self, disposition: str) -> str:
        if disposition == "false_positive":
            return "规则误报"
        return "测试/业务触发" if disposition == "business_trigger" else "真实攻击"

    def _default_closure_status(self, disposition: str) -> str:
        return "4" if disposition == "false_positive" else "6"

    def _build_history_messages(self, history: list[dict[str, str]]) -> list[Any]:
        try:
            from langchain_core.messages import AIMessage, HumanMessage
        except ModuleNotFoundError:
            return []

        messages: list[Any] = []
        for item in history[-12:]:
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

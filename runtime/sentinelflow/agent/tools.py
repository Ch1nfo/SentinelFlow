from __future__ import annotations

import json
from typing import Annotated, Any

from sentinelflow.agent.state import SentinelFlowAgentState
from sentinelflow.skills.adapters import SentinelFlowSkillRuntime
from sentinelflow.services.skill_approval_service import SkillApprovalService

try:
    from langchain_core.tools import tool
    from langgraph.prebuilt import InjectedState
except ModuleNotFoundError:  # pragma: no cover
    tool = None  # type: ignore[assignment]
    InjectedState = object  # type: ignore[assignment]


def build_agent_tools(
    skill_runtime: SentinelFlowSkillRuntime,
    approval_service: SkillApprovalService,
    *,
    enable_read_skill_document: bool = True,
    enable_execute_skill: bool = True,
) -> list:
    if tool is None:
        raise ModuleNotFoundError("langchain_core/langgraph 未安装，无法构建 Agent tools。")

    tools: list = []

    def _skill_cache_key(skill_name: str, fingerprint: str) -> str:
        return f"{skill_name}:{fingerprint}"

    def _approval_payload(
        *,
        skill_name: str,
        arguments: dict[str, Any],
        state: SentinelFlowAgentState,
    ) -> str:
        fingerprint = approval_service.fingerprint_arguments(arguments)
        return json.dumps(
            {
                "success": False,
                "data": {},
                "error": "该 Skill 需要审批后才能执行。",
                "approval_pending": True,
                "approval_request": {
                    "skill_name": skill_name,
                    "arguments": approval_service.normalize_arguments(arguments),
                    "arguments_fingerprint": fingerprint,
                    "run_id": str(state.get("run_id", "")).strip(),
                    "scope_type": str(state.get("scope_type", "")).strip(),
                    "scope_ref": str(state.get("scope_ref", "")).strip(),
                    "checkpoint_thread_id": str(state.get("checkpoint_thread_id", "")).strip(),
                    "checkpoint_ns": str(state.get("graph_checkpoint_ns", state.get("checkpoint_ns", ""))).strip(),
                    "message": f"Skill「{skill_name}」需要人工审批后才能执行。",
                },
            },
            ensure_ascii=False,
        )

    def _rejected_payload(skill_name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(
            {
                "success": False,
                "data": {
                    "approval_rejected": True,
                    "skill_name": skill_name,
                    "arguments": approval_service.normalize_arguments(arguments),
                },
                "error": "用户拒绝执行需要审批的 Skill。",
            },
            ensure_ascii=False,
        )

    if enable_read_skill_document:
        @tool
        def read_skill_document(
            skill_name: str,
            state: Annotated[SentinelFlowAgentState, InjectedState()],  # type: ignore[misc]
        ) -> str:
            """读取指定技能的完整说明文档并返回 JSON 结果。"""
            readable_skills_raw = state.get("readable_skills")
            readable_skills = set(readable_skills_raw or [])
            if readable_skills_raw is not None and skill_name not in readable_skills:
                return json.dumps(
                    {"success": False, "data": {}, "error": f"当前 Agent 未被授权读取技能 {skill_name} 的文档。"},
                    ensure_ascii=False,
                )
            try:
                result = skill_runtime.read_skill(skill_name)
                return json.dumps(
                    {"success": True, "data": result.markdown, "error": None},
                    ensure_ascii=False,
                )
            except Exception as exc:
                return json.dumps(
                    {"success": False, "data": {}, "error": f"读取技能文档失败：{exc}"},
                    ensure_ascii=False,
                )

        tools.append(read_skill_document)

    if enable_execute_skill:
        @tool
        def execute_skill(
            skill_name: str,
            state: Annotated[SentinelFlowAgentState, InjectedState()],  # type: ignore[misc]
            arguments: dict[str, Any] | None = None,
        ) -> str:
            """执行指定技能并返回 JSON 字符串结果。"""
            cancel_event = state.get("cancel_event")
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                return json.dumps(
                    {"success": False, "data": {}, "error": "用户已停止当前任务。"},
                    ensure_ascii=False,
                )
            executable_skills_raw = state.get("executable_skills")
            executable_skills = set(executable_skills_raw or [])
            if executable_skills_raw is not None and skill_name not in executable_skills:
                return json.dumps(
                    {"success": False, "data": {}, "error": f"当前 Agent 未被授权执行技能 {skill_name}。"},
                    ensure_ascii=False,
                )
            fingerprint = approval_service.fingerprint_arguments(arguments or {})
            cache_key = _skill_cache_key(skill_name, fingerprint)
            cached_results = state.get("executed_skill_cache", {})
            if isinstance(cached_results, dict):
                cached_payload = cached_results.get(cache_key)
                if isinstance(cached_payload, dict):
                    return json.dumps(cached_payload, ensure_ascii=False)
            approved_fingerprints = set(state.get("approved_fingerprints") or [])
            rejected_fingerprints = set(state.get("rejected_fingerprints") or [])
            execution_entry = str(state.get("execution_entry", "")).strip()
            skill = skill_runtime.resolver.resolve(skill_name)
            if skill.spec.approval_required and execution_entry not in {"auto_alert", "debug"}:
                if fingerprint in rejected_fingerprints:
                    return _rejected_payload(skill_name, arguments or {})
                if fingerprint not in approved_fingerprints:
                    return _approval_payload(skill_name=skill_name, arguments=arguments or {}, state=state)
            context = {
                "event_id_ref": state.get("event_id_ref", ""),
                "alert_data": state.get("alert_data", {}),
            }
            try:
                result = skill_runtime.execute_skill(skill_name, arguments or {}, context)
                payload = result.data if isinstance(result.data, dict) else {"result": result.data}
                return json.dumps(
                    {
                        "success": result.success,
                        "data": payload,
                        "error": result.error
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                return json.dumps(
                    {
                        "success": False,
                        "data": {},
                        "error": f"Tool Execution Exception: {exc}"
                    },
                    ensure_ascii=False,
                )

        tools.append(execute_skill)

        @tool
        def execute_skill_no_args(
            skill_name: str,
            state: Annotated[SentinelFlowAgentState, InjectedState()],  # type: ignore[misc]
        ) -> str:
            """执行无入参技能并返回 JSON 字符串结果。"""
            cancel_event = state.get("cancel_event")
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                return json.dumps(
                    {"success": False, "data": {}, "error": "用户已停止当前任务。"},
                    ensure_ascii=False,
                )
            executable_skills_raw = state.get("executable_skills")
            executable_skills = set(executable_skills_raw or [])
            if executable_skills_raw is not None and skill_name not in executable_skills:
                return json.dumps(
                    {"success": False, "data": {}, "error": f"当前 Agent 未被授权执行技能 {skill_name}。"},
                    ensure_ascii=False,
                )
            fingerprint = approval_service.fingerprint_arguments({})
            cache_key = _skill_cache_key(skill_name, fingerprint)
            cached_results = state.get("executed_skill_cache", {})
            if isinstance(cached_results, dict):
                cached_payload = cached_results.get(cache_key)
                if isinstance(cached_payload, dict):
                    return json.dumps(cached_payload, ensure_ascii=False)
            approved_fingerprints = set(state.get("approved_fingerprints") or [])
            rejected_fingerprints = set(state.get("rejected_fingerprints") or [])
            execution_entry = str(state.get("execution_entry", "")).strip()
            skill = skill_runtime.resolver.resolve(skill_name)
            if skill.spec.approval_required and execution_entry not in {"auto_alert", "debug"}:
                if fingerprint in rejected_fingerprints:
                    return _rejected_payload(skill_name, {})
                if fingerprint not in approved_fingerprints:
                    return _approval_payload(skill_name=skill_name, arguments={}, state=state)
            context = {
                "event_id_ref": state.get("event_id_ref", ""),
                "alert_data": state.get("alert_data", {}),
            }
            try:
                result = skill_runtime.execute_skill(skill_name, {}, context)
                payload = result.data if isinstance(result.data, dict) else {"result": result.data}
                return json.dumps(
                    {
                        "success": result.success,
                        "data": payload,
                        "error": result.error,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                return json.dumps(
                    {
                        "success": False,
                        "data": {},
                        "error": f"Tool Execution Exception: {exc}",
                    },
                    ensure_ascii=False,
                )

        tools.append(execute_skill_no_args)

    return tools

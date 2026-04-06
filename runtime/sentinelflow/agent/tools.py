from __future__ import annotations

import json
from typing import Annotated, Any

from sentinelflow.agent.state import SentinelFlowAgentState
from sentinelflow.skills.adapters import SentinelFlowSkillRuntime

try:
    from langchain_core.tools import tool
    from langgraph.prebuilt import InjectedState
except ModuleNotFoundError:  # pragma: no cover
    tool = None  # type: ignore[assignment]
    InjectedState = object  # type: ignore[assignment]


def build_agent_tools(
    skill_runtime: SentinelFlowSkillRuntime,
    *,
    enable_read_skill_document: bool = True,
    enable_execute_skill: bool = True,
) -> list:
    if tool is None:
        raise ModuleNotFoundError("langchain_core/langgraph 未安装，无法构建 Agent tools。")

    tools: list = []

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
            context = {
                "event_id_ref": state.get("event_id_ref", ""),
                "alert_data": state.get("alert_data", {}),
                "cancel_event": cancel_event,
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

    return tools

from __future__ import annotations

import json
from typing import Literal

from sentinelflow.agent.catalog import load_skill_catalog
from sentinelflow.agent.context_utils import build_context_envelope
from sentinelflow.agent.prompt_builder import PromptBuildContext, build_prompt
from sentinelflow.agent.state import SentinelFlowAgentState

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
except ModuleNotFoundError:  # pragma: no cover
    AIMessage = HumanMessage = SystemMessage = object  # type: ignore[assignment]


async def agent_node(state: SentinelFlowAgentState, llm, skill_root) -> dict:
    cancel_event = state.get("cancel_event")
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        raise RuntimeError("用户已停止当前任务。")

    alert_data = state["alert_data"]
    is_human_command = alert_data.get("alert_source") == "human_command"
    readable_skills = state.get("readable_skills")
    skill_catalog = load_skill_catalog(skill_root, readable_skills)
    custom_prompt = str(state.get("system_prompt_override", "")).strip()

    if is_human_command:
        prompt = build_prompt(
            PromptBuildContext(
                base_prompt=custom_prompt,
                mode="agent_command",
                entry_type="conversation",
                skill_catalog=skill_catalog,
            )
        )
        system_msg = SystemMessage(content=prompt)
        payload = str(alert_data.get("payload", "")).strip()
        delegated_task_prompt = str(alert_data.get("delegated_task_prompt", "")).strip()
        if delegated_task_prompt:
            envelope = build_context_envelope(
                original_input=payload,
                delegated_task=delegated_task_prompt,
                prior_facts=alert_data.get("prior_facts", {}) if isinstance(alert_data.get("prior_facts"), dict) else {},
            )
            initial_msg = HumanMessage(
                content=(
                    "请执行以下主 Agent 分派任务。当前执行目标以 delegated_task 为准，"
                    "original_input 只作为背景：\n\n"
                    f"```json\n{json.dumps(envelope, ensure_ascii=False, indent=2)}\n```"
                )
            )
        else:
            initial_msg = HumanMessage(content=f"请执行以下人工指令：{payload}")
    else:
        handling_intent = str(alert_data.get("handling_intent", "")).strip()
        prompt = build_prompt(
            PromptBuildContext(
                base_prompt=custom_prompt,
                mode="agent_alert",
                entry_type="alert",
                action_hint=handling_intent,
                skill_catalog=skill_catalog,
            )
        )
        system_msg = SystemMessage(content=prompt)
        alert_json = json.dumps(alert_data, ensure_ascii=False, indent=2)
        delegated_task_prompt = str(alert_data.get("delegated_task_prompt", "")).strip()
        if delegated_task_prompt:
            envelope = build_context_envelope(
                original_input=alert_data,
                delegated_task=delegated_task_prompt,
                prior_facts=alert_data.get("prior_facts", {}) if isinstance(alert_data.get("prior_facts"), dict) else {},
            )
            initial_msg = HumanMessage(
                content=(
                    "请分析并处置以下上下文。当前执行目标以 delegated_task 为准，"
                    "original_input 只作为背景：\n\n"
                    f"```json\n{json.dumps(envelope, ensure_ascii=False, indent=2)}\n```"
                )
            )
        else:
            initial_msg = HumanMessage(content=f"请分析并处置以下告警：\n\n```json\n{alert_json}\n```")

    current_messages = list(state.get("messages", []))
    input_seeded = bool(state.get("input_seeded"))
    if not current_messages:
        messages_to_send = [system_msg, initial_msg]
        seeded_messages = [initial_msg]
        seeded_flag = True
    elif not input_seeded:
        messages_to_send = [system_msg] + current_messages + [initial_msg]
        seeded_messages = [initial_msg]
        seeded_flag = True
    else:
        messages_to_send = [system_msg] + current_messages
        seeded_messages = []
        seeded_flag = True

    response = await llm.ainvoke(messages_to_send)
    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
        raise RuntimeError("用户已停止当前任务。")
    return {"messages": seeded_messages + [response], "input_seeded": seeded_flag}


def should_continue(state: SentinelFlowAgentState) -> Literal["tools", "__end__"]:
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
        return "tools"
    return "__end__"

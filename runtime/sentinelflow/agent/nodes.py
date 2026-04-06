from __future__ import annotations

import json
from typing import Literal

from sentinelflow.agent.catalog import load_skill_catalog
from sentinelflow.agent.prompts import ALERT_HANDLING_HINTS, DEFAULT_ALERT_SYSTEM_PROMPT, DEFAULT_COMMAND_SYSTEM_PROMPT
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

    def _render_prompt(base_prompt: str) -> str:
        if not custom_prompt:
            return base_prompt
        if "{skill_catalog}" in custom_prompt:
            return custom_prompt.format(skill_catalog=skill_catalog)
        return f"{custom_prompt}\n\n可用技能目录：\n{skill_catalog}"

    if is_human_command:
        system_msg = SystemMessage(content=_render_prompt(DEFAULT_COMMAND_SYSTEM_PROMPT.format(skill_catalog=skill_catalog)))
        payload = str(alert_data.get("payload", "")).strip()
        initial_msg = HumanMessage(content=f"请执行以下人工指令：{payload}")
    else:
        handling_intent = str(alert_data.get("handling_intent", "")).strip()
        prompt = _render_prompt(DEFAULT_ALERT_SYSTEM_PROMPT.format(skill_catalog=skill_catalog))
        if handling_intent in ALERT_HANDLING_HINTS:
            prompt = f"{prompt}\n\n{ALERT_HANDLING_HINTS[handling_intent]}"
        system_msg = SystemMessage(content=prompt)
        alert_json = json.dumps(alert_data, ensure_ascii=False, indent=2)
        delegated_task_prompt = str(alert_data.get("delegated_task_prompt", "")).strip()
        task_block = f"\n\n主 Agent 分派要求：\n{delegated_task_prompt}" if delegated_task_prompt else ""
        initial_msg = HumanMessage(content=f"请分析并处置以下告警：\n\n```json\n{alert_json}\n```{task_block}")

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

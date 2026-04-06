from __future__ import annotations

from pathlib import Path

from sentinelflow.agent.nodes import agent_node, should_continue
from sentinelflow.agent.state import SentinelFlowAgentState
from sentinelflow.agent.tools import build_agent_tools
from sentinelflow.config.runtime import SentinelFlowRuntimeConfig
from sentinelflow.skills.adapters import SentinelFlowSkillRuntime


def build_agent_graph(
    project_root: Path,
    skill_runtime: SentinelFlowSkillRuntime,
    runtime_config: SentinelFlowRuntimeConfig,
    *,
    enable_read_skill_document: bool = True,
    enable_execute_skill: bool = True,
):
    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.prebuilt import ToolNode
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ModuleNotFoundError(
            "缺少 Agent 运行依赖，请安装 langgraph、langchain-openai 和 langchain-core。"
        ) from exc

    tools = build_agent_tools(
        skill_runtime,
        enable_read_skill_document=enable_read_skill_document,
        enable_execute_skill=enable_execute_skill,
    )
    llm = ChatOpenAI(
        model=runtime_config.llm_model,
        api_key=runtime_config.llm_api_key,
        base_url=runtime_config.llm_api_base_url,
        temperature=runtime_config.llm_temperature,
        timeout=runtime_config.llm_timeout,
    ).bind_tools(tools)

    skill_root = project_root / ".sentinelflow" / "plugins" / "skills"

    async def _agent(state: SentinelFlowAgentState) -> dict:
        alert_data = state.get("alert_data", {})
        current_event_id = str(alert_data.get("eventIds", "")).strip()
        ref_event_id = str(state.get("event_id_ref", "")).strip()
        if current_event_id and ref_event_id and current_event_id != ref_event_id:
            raise ValueError("检测到 event_id_ref 与当前 alert_data.eventIds 不一致。")
        output = await agent_node(state, llm, skill_root)
        if current_event_id and not ref_event_id:
            output["event_id_ref"] = current_event_id
        return output

    builder = StateGraph(SentinelFlowAgentState)
    builder.add_node("agent_node", _agent)
    builder.add_node("tools_node", ToolNode(tools))
    builder.add_edge(START, "agent_node")
    builder.add_conditional_edges("agent_node", should_continue, {"tools": "tools_node", "__end__": END})
    builder.add_edge("tools_node", "agent_node")
    return builder.compile()

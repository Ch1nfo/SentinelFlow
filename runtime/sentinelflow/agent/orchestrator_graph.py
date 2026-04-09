"""
SentinelFlow Multi-Agent Orchestrator Graph
=========================================

Implements a LangGraph **Supervisor + Worker SubGraph** pattern:

  START → supervisor_node (LLM bound with worker tools)
            ↓ tool_calls?
          tools_node  (ToolNode — each worker is a compiled SubGraph wrapped as @tool)
            ↓
          supervisor_node  (re-evaluates results, decides next step)
            ↓ no more tool_calls
          END

Each Worker SubGraph is the same single-agent ReAct graph built by
`build_agent_graph()`, wrapped in an async @tool function so the Supervisor
can invoke it just like any other tool.  The Worker's internal messages are
fully isolated — only `final_response` surfaces back to the Supervisor as a
ToolMessage.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from sentinelflow.agent.graph import build_agent_graph
from sentinelflow.agent.orchestrator_state import OrchestratorState
from sentinelflow.agent.policy import can_agent_execute_skill, can_agent_read_skill
from sentinelflow.agent.tools import build_agent_tools
from sentinelflow.skills.adapters import SentinelFlowSkillRuntime

try:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode
except ModuleNotFoundError as _exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "缺少 Agent 运行依赖，请安装 langgraph、langchain-openai 和 langchain-core。"
    ) from _exc


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_worker_permissions(
    worker_agent_def,
    skill_runtime: SentinelFlowSkillRuntime,
) -> tuple[list[str], list[str]]:
    readable: list[str] = []
    executable: list[str] = []
    for skill in skill_runtime.loader.list_skills():
        if can_agent_read_skill(worker_agent_def, skill):
            readable.append(skill.spec.name)
        if can_agent_execute_skill(worker_agent_def, skill):
            executable.append(skill.spec.name)
    return readable, executable


# ── Worker SubGraph Tool Builder ──────────────────────────────────────────────

def _build_worker_subgraph_tool(
    worker_agent_def,
    project_root: Path,
    skill_runtime: SentinelFlowSkillRuntime,
    runtime_config,
    *,
    alert_data: dict[str, Any],
    cancel_event: Any = None,
    step_counter: list[int],
):
    """
    Compile a Worker SubGraph and wrap it as a LangChain @tool.

    The Supervisor calls this tool with a plain-text `task_prompt`.
    Internally it runs a full ReAct SubGraph and returns a JSON summary
    of the worker's final response and skills used.
    """
    worker_config = worker_agent_def.resolve_runtime_config(runtime_config)
    subgraph = build_agent_graph(
        project_root,
        skill_runtime,
        worker_config,
        enable_read_skill_document=True,
        enable_execute_skill=True,
    )
    readable_skills, executable_skills = _resolve_worker_permissions(worker_agent_def, skill_runtime)

    async def _invoke(task_prompt: str) -> str:
        step_counter[0] += 1
        step_idx = step_counter[0]

        # Inject the delegated task prompt into the worker's alert context
        worker_alert_data = dict(alert_data)
        worker_alert_data["delegated_task_prompt"] = task_prompt

        worker_state = await subgraph.ainvoke({
            "alert_data": worker_alert_data,
            "messages": [],
            "event_id_ref": str(alert_data.get("eventIds", "")).strip(),
            "input_seeded": False,
            "cancel_event": cancel_event,
            "readable_skills": readable_skills,
            "executable_skills": executable_skills,
            "system_prompt_override": worker_agent_def.prompt or "",
            "agent_name": worker_agent_def.name,
        })

        # Extract final response text from worker's message history
        final_text = ""
        skills_used: list[str] = []
        for msg in worker_state.get("messages", []):
            msg_type = getattr(msg, "type", "")
            if msg_type == "ai" and getattr(msg, "content", ""):
                final_text = msg.content
            for tc in (getattr(msg, "tool_calls", None) or []):
                if isinstance(tc, dict) and tc.get("name"):
                    skills_used.append(tc["name"])

        return json.dumps(
            {
                "step": step_idx,
                "worker": worker_agent_def.name,
                "task_prompt": task_prompt,
                "final_response": final_text[:3000],   # truncate to keep context manageable
                "skills_used": skills_used,
                "success": bool(final_text),
            },
            ensure_ascii=False,
        )

    # Give the tool a deterministic name and helpful docstring
    safe_name = worker_agent_def.name.replace("-", "_").replace(" ", "_")
    worker_desc = (worker_agent_def.description or worker_agent_def.name).strip()
    _invoke.__name__ = f"call_{safe_name}"
    _invoke.__doc__ = (
        f"委托子 Agent【{worker_agent_def.name}】执行指定任务。"
        f"该 Agent 的专项能力：{worker_desc}。"
        f"参数 task_prompt 必须是具体、可操作的中文任务描述，包含当前步骤需要完成的具体工作内容。"
    )
    return tool(_invoke)


# ── Routing ───────────────────────────────────────────────────────────────────

def _should_orchestrate_continue(
    state: OrchestratorState,
) -> Literal["tools", "__end__"]:
    """Route: delegate to a worker tool, or finish the orchestration."""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"
    last_msg = messages[-1]
    if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
        return "tools"
    return "__end__"


# ── Orchestrator Graph Builder ────────────────────────────────────────────────

def build_orchestrator_graph(
    primary_agent,
    workers: list,
    project_root: Path,
    skill_runtime: SentinelFlowSkillRuntime,
    runtime_config,
    *,
    alert_data: dict[str, Any],
    cancel_event: Any = None,
):
    """
    Build and return the compiled Supervisor + Worker SubGraph orchestrator.

    Args:
        primary_agent: The primary agent definition (role="primary").
        workers:       List of worker agent definitions (role="worker").
        project_root:  Absolute path to the project root.
        skill_runtime: Shared SentinelFlowSkillRuntime instance.
        runtime_config: Global LLM runtime configuration.
        alert_data:    The initial alert payload or command dict.
        cancel_event:  Optional threading.Event for cancellation.

    Returns:
        A compiled LangGraph StateGraph ready for `ainvoke()`.
    """
    # ── Build Worker tools ────────────────────────────────────────────────────
    step_counter: list[int] = [0]
    worker_tools = [
        _build_worker_subgraph_tool(
            w,
            project_root,
            skill_runtime,
            runtime_config,
            alert_data=alert_data,
            cancel_event=cancel_event,
            step_counter=step_counter,
        )
        for w in workers
    ]
    readable_skills = list(alert_data.get("_primary_readable_skills", []) or [])
    executable_skills = list(alert_data.get("_primary_executable_skills", []) or [])
    primary_skill_tools = build_agent_tools(
        skill_runtime,
        enable_read_skill_document=bool(readable_skills),
        enable_execute_skill=bool(executable_skills),
    )
    supervisor_tools = worker_tools + primary_skill_tools

    # ── Build Supervisor LLM (bound with worker + primary skill tools) ───────
    supervisor_config = primary_agent.resolve_runtime_config(runtime_config)
    supervisor_llm = ChatOpenAI(
        model=supervisor_config.llm_model,
        api_key=supervisor_config.llm_api_key,
        base_url=supervisor_config.llm_api_base_url,
        temperature=supervisor_config.llm_temperature,
        timeout=supervisor_config.llm_timeout,
    ).bind_tools(supervisor_tools)

    # ── Supervisor node ───────────────────────────────────────────────────────
    async def _supervisor_node(state: OrchestratorState) -> dict:
        cancel = state.get("cancel_event")
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            raise RuntimeError("用户已停止当前任务。")

        system_prompt = str(state.get("system_prompt_override", "")).strip()
        system_msg = SystemMessage(content=system_prompt)
        current_messages = list(state.get("messages", []))

        if not current_messages:
            # ── First invocation: seed with conversation history + initial task ──
            seed_messages: list = []
            for item in (state.get("conversation_history") or [])[-12:]:
                role = str(item.get("role", "")).strip().lower()
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                if role == "user":
                    seed_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    seed_messages.append(AIMessage(content=content))

            # Build human message from alert_data / command payload
            ad = state.get("alert_data", {})
            entry_type = state.get("entry_type", "conversation")
            if entry_type == "conversation" or ad.get("alert_source") == "human_command":
                payload = str(ad.get("payload", "")).strip()
                human_content = f"请处理以下人工指令：{payload}" if payload else "请开始处理当前任务。"
            else:
                alert_json = json.dumps(ad, ensure_ascii=False, indent=2)
                action_hint = state.get("action_hint", "")
                hint_text = f"\n\n处置意图：{action_hint}" if action_hint else ""
                human_content = f"请分析并处置以下告警：\n\n```json\n{alert_json}\n```{hint_text}"

            initial_msg = HumanMessage(content=human_content)
            messages_to_send = [system_msg] + seed_messages + [initial_msg]
            # Persist seed + initial into state so subsequent loops see them
            new_messages = seed_messages + [initial_msg]
        else:
            # ── Subsequent invocation: full message history already in state ──
            messages_to_send = [system_msg] + current_messages
            new_messages = []

        response = await supervisor_llm.ainvoke(messages_to_send)

        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            raise RuntimeError("用户已停止当前任务。")

        return {"messages": new_messages + [response]}

    # ── Assemble the graph ────────────────────────────────────────────────────
    builder: StateGraph = StateGraph(OrchestratorState)
    builder.add_node("supervisor", _supervisor_node)
    builder.add_node("tools", ToolNode(supervisor_tools))
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        _should_orchestrate_continue,
        {"tools": "tools", "__end__": END},
    )
    builder.add_edge("tools", "supervisor")
    return builder.compile()

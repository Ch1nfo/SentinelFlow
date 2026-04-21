from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from sentinelflow.agent import orchestrator_graph as orch_module


class _WorkerAgent:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.prompt = ""

    def resolve_runtime_config(self, runtime_config):
        return runtime_config


def _runtime_config():
    return SimpleNamespace(
        llm_model="test-model",
        llm_api_key="test-key",
        llm_api_base_url="https://example.invalid",
        llm_temperature=0,
        llm_timeout=30,
    )


def test_build_worker_subgraph_tool_uses_unique_explicit_name() -> None:
    skill_runtime = SimpleNamespace(loader=SimpleNamespace(list_skills=lambda: []))
    worker = _WorkerAgent("internet-ip-ban", "封禁互联网 IP")

    tool_obj, _runner = orch_module._build_worker_subgraph_tool(
        worker,
        Path("."),
        skill_runtime,
        SimpleNamespace(),
        _runtime_config(),
        alert_data={},
        cancel_event=None,
        step_counter=[0],
    )

    assert getattr(tool_obj, "name", "") == "call_internet_ip_ban"
    assert getattr(tool_obj, "name", "") != "_invoke"


def test_build_orchestrator_graph_binds_unique_worker_tool_names(monkeypatch) -> None:
    captured_tools: list[object] = []

    class _FakeChatOpenAI:
        def __init__(self, **_kwargs) -> None:
            pass

        def bind_tools(self, tools):
            captured_tools[:] = list(tools)
            return self

    class _FakeStateGraph:
        def __init__(self, _state_type) -> None:
            self.nodes: dict[str, object] = {}

        def add_node(self, name: str, node: object) -> None:
            self.nodes[name] = node

        def add_edge(self, *_args) -> None:
            return None

        def add_conditional_edges(self, *_args) -> None:
            return None

        def compile(self):
            return self

    monkeypatch.setattr(orch_module, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(orch_module, "StateGraph", _FakeStateGraph)
    monkeypatch.setattr(orch_module, "ToolNode", lambda tools: tools)
    monkeypatch.setattr(orch_module, "build_agent_tools", lambda *args, **kwargs: [])
    monkeypatch.setattr(orch_module, "list_agent_workflows", lambda *_args, **_kwargs: [])

    primary_agent = SimpleNamespace(resolve_runtime_config=lambda runtime_config: runtime_config)
    workers = [
        _WorkerAgent("internet-ip-ban", "封禁互联网 IP"),
        _WorkerAgent("sgp-ip-ban", "封禁 SGP IP"),
        _WorkerAgent("soc-exec", "SOC 研判处置"),
    ]
    skill_runtime = SimpleNamespace(loader=SimpleNamespace(list_skills=lambda: []))

    orch_module.build_orchestrator_graph(
        primary_agent,
        workers,
        Path("."),
        skill_runtime,
        SimpleNamespace(),
        _runtime_config(),
        alert_data={},
    )

    tool_names = [getattr(tool_obj, "name", getattr(tool_obj, "__name__", "")) for tool_obj in captured_tools]
    worker_tool_names = [name for name in tool_names if str(name).startswith("call_")]

    assert worker_tool_names == ["call_internet_ip_ban", "call_sgp_ip_ban", "call_soc_exec"]
    assert len(set(worker_tool_names)) == len(worker_tool_names)
    assert "_invoke" not in worker_tool_names


def test_resolve_current_tool_call_id_matches_named_worker_tool() -> None:
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "call_soc_exec",
                        "args": {"task_prompt": "已完成的任务"},
                        "id": "call-done",
                        "type": "tool_call",
                    },
                    {
                        "name": "call_internet_ip_ban",
                        "args": {"task_prompt": "请封禁互联网IP地址212.47.230.32"},
                        "id": "call-target",
                        "type": "tool_call",
                    },
                ],
            ),
            ToolMessage(content='{"success": true}', tool_call_id="call-done"),
        ]
    }

    call_id = orch_module._resolve_current_tool_call_id(
        state,
        orch_module._worker_tool_name("internet-ip-ban"),
        expected_args={"task_prompt": "请封禁互联网IP地址212.47.230.32"},
    )

    assert call_id == "call-target"

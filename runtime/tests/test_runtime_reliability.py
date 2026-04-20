from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from sentinelflow.agent import service as agent_service_module
from sentinelflow.agent.service import SentinelFlowAgentService
from sentinelflow.alerts.client import SOCAlertApiClient
from sentinelflow.config import runtime as runtime_module
from sentinelflow.domain.models import AlertHandlingTask
from sentinelflow.services import auto_execution_service as auto_exec_module
from sentinelflow.services import dispatch_service as dispatch_module
from sentinelflow.services.audit_service import AuditService
from sentinelflow.services.auto_execution_service import AlertAutoExecutionService
from sentinelflow.services.dispatch_service import AlertDispatchService


def test_save_runtime_config_concurrent_writes_remain_readable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(runtime_module, "CONFIG_PATH", tmp_path / "runtime.json")

    errors: list[Exception] = []

    def writer(index: int) -> None:
        try:
            for offset in range(20):
                runtime_module.save_runtime_config(
                    {
                        "poll_interval_seconds": 10 + index + offset,
                        "failed_retry_interval_seconds": index,
                        "alert_source_enabled": index % 2 == 0,
                    }
                )
        except Exception as exc:  # pragma: no cover - test should not hit
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    persisted = runtime_module.read_persisted_runtime_config()
    assert isinstance(persisted, dict)
    loaded = runtime_module.load_runtime_config()
    assert isinstance(loaded.poll_interval_seconds, int)
    assert isinstance(loaded.failed_retry_interval_seconds, int)


def test_fetch_open_alerts_marks_complete_snapshot_from_total_count(monkeypatch) -> None:
    client = SOCAlertApiClient()
    client.fetch_raw_alert_payload = lambda _config=None: {  # type: ignore[method-assign]
        "raw_payload": {
            "alerts": [{"eventIds": "evt-1"}, {"eventIds": "evt-2"}],
            "total_count": 2,
        }
    }
    client.parser_runtime = SimpleNamespace(
        normalize=lambda payload, _rule: {"count": 2, "alerts": payload.get("alerts", [])}
    )
    monkeypatch.setattr(
        "sentinelflow.alerts.client.load_runtime_config",
        lambda: SimpleNamespace(
            demo_mode=False,
            alert_source_enabled=True,
            alert_source_type="api",
            alert_source_url="https://example.invalid",
            alert_parser_rule={"enabled": True},
            demo_fallback=False,
        ),
    )

    result = client.fetch_open_alerts()

    assert result["count"] == 2
    assert result["snapshot_complete"] is True


def test_dispatch_skips_missing_completion_without_complete_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dispatch_module, "DB_PATH", tmp_path / "sys_queue.db")
    service = AlertDispatchService(
        dedup=SimpleNamespace(
            mark_processing=lambda _event_id: True,
            mark_done=lambda _event_id: None,
            mark_failed=lambda _event_id: None,
            forget=lambda _event_id: None,
        ),
        triage_service=SimpleNamespace(),
        audit_service=AuditService(),
    )
    task = AlertHandlingTask(
        task_id="task-1",
        event_ids="evt-1",
        workflow_name="agent_react",
        title="Queued alert",
        description="queued",
        status="queued",
        payload={"alert_data": {"eventIds": "evt-1"}},
    )
    service._save_task(task)

    queued, skipped, updated, completed, errors = asyncio.run(service.dispatch([], allow_missing_completion=False))

    assert queued == []
    assert skipped == 0
    assert updated == 0
    assert completed == []
    assert errors == []
    assert service.get_task("task-1").status == "queued"
    assert any(event.event_type == "alert_missing_completion_skipped" for event in service.audit_service.list_events())


def test_dispatch_completes_missing_alert_with_complete_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dispatch_module, "DB_PATH", tmp_path / "sys_queue.db")
    service = AlertDispatchService(
        dedup=SimpleNamespace(
            mark_processing=lambda _event_id: True,
            mark_done=lambda _event_id: None,
            mark_failed=lambda _event_id: None,
            forget=lambda _event_id: None,
        ),
        triage_service=SimpleNamespace(),
        audit_service=AuditService(),
    )
    task = AlertHandlingTask(
        task_id="task-2",
        event_ids="evt-2",
        workflow_name="agent_react",
        title="Failed alert",
        description="failed",
        status="failed",
        payload={"alert_data": {"eventIds": "evt-2"}},
    )
    service._save_task(task)

    *_prefix, completed, _errors = asyncio.run(service.dispatch([], allow_missing_completion=True))

    assert len(completed) == 1
    assert service.get_task("task-2").status == "completed"


def test_auto_execution_request_run_once_drains_pending_tasks(monkeypatch) -> None:
    monkeypatch.setattr(
        auto_exec_module,
        "load_runtime_config",
        lambda: SimpleNamespace(failed_retry_interval_seconds=0),
    )

    task = SimpleNamespace(task_id="task-1", status="queued")
    dispatch = SimpleNamespace(
        list_tasks=lambda: [task],
        list_failed_retry_candidates=lambda *_args, **_kwargs: [],
        prepare_retry=lambda _task_id: None,
    )

    class _Runner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def run_task(self, current_task, execution_entry="manual_alert"):
            self.calls.append((current_task.task_id, execution_entry))
            return {"success": True}

    runner = _Runner()
    service = AlertAutoExecutionService(dispatch, runner, AuditService(), interval_seconds=0.01)

    async def scenario() -> list[tuple[str, str]]:
        await service.start()
        service.request_run_once()
        await asyncio.sleep(0.05)
        await service.stop()
        return list(runner.calls)

    calls = asyncio.run(scenario())

    assert calls == [("task-1", "auto_alert")]


def test_run_planner_graph_sanitizes_initialization_error(monkeypatch) -> None:
    service = object.__new__(SentinelFlowAgentService)
    fake_langchain_openai = ModuleType("langchain_openai")

    class _BrokenChatOpenAI:
        def __init__(self, **_kwargs) -> None:
            raise RuntimeError("secret-api-key-leak")

    fake_langchain_openai.ChatOpenAI = _BrokenChatOpenAI  # type: ignore[attr-defined]
    fake_messages = ModuleType("langchain_core.messages")
    fake_messages.AIMessage = lambda content: {"role": "assistant", "content": content}  # type: ignore[attr-defined]
    fake_messages.SystemMessage = lambda content: {"role": "system", "content": content}  # type: ignore[attr-defined]
    fake_messages.HumanMessage = lambda content: {"role": "user", "content": content}  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "langchain_openai", fake_langchain_openai)
    monkeypatch.setitem(sys.modules, "langchain_core.messages", fake_messages)
    monkeypatch.setattr(
        agent_service_module,
        "load_runtime_config",
        lambda: SimpleNamespace(
            llm_model="test-model",
            llm_api_key="secret",
            llm_api_base_url="https://example.invalid",
            llm_temperature=0,
            llm_timeout=30,
        ),
    )

    agent_definition = SimpleNamespace(
        resolve_runtime_config=lambda config: config,
        prompt_for_mode=lambda _mode: "planner prompt",
    )

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            SentinelFlowAgentService._run_planner_graph(
                service,
                agent_definition,
                {"alert_source": "human_command", "payload": "hello"},
                history=[],
                cancel_event=None,
            )
        )

    assert "secret-api-key-leak" not in str(exc.value)
    assert "Planner 模型初始化失败" in str(exc.value)


def test_infer_disposition_supports_english_keywords() -> None:
    service = object.__new__(SentinelFlowAgentService)

    assert SentinelFlowAgentService._infer_disposition(service, "This is a false positive.", "unknown") == "false_positive"
    assert SentinelFlowAgentService._infer_disposition(service, "This looks like benign business activity.", "unknown") == "business_trigger"
    assert SentinelFlowAgentService._infer_disposition(service, "This is a confirmed attack.", "unknown") == "true_attack"

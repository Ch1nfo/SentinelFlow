from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from sentinelflow.agent.service import SentinelFlowAgentService
from sentinelflow.workflows.agent_workflow_registry import AgentWorkflowDefinition, AgentWorkflowStepDefinition
from sentinelflow.workflows.agent_workflow_runner import SentinelFlowAgentWorkflowRunner


class _ImmutableToolMessage:
    type = "tool"

    def __init__(self, content: str, tool_call_id: str = "tool-1") -> None:
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "tool_call_id", tool_call_id)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("immutable message")

    def model_copy(self, update: dict[str, object] | None = None):
        payload = dict(update or {})
        return _ImmutableToolMessage(str(payload.get("content", self.content)), self.tool_call_id)


class _MemoryApprovalService:
    def __init__(self) -> None:
        self.checkpoints: dict[str, dict[str, object]] = {}

    def save_checkpoint(self, **kwargs) -> None:
        self.checkpoints[str(kwargs["checkpoint_thread_id"])] = {
            "checkpoint_thread_id": kwargs["checkpoint_thread_id"],
            "checkpoint_ns": kwargs["checkpoint_ns"],
            "checkpoint_kind": kwargs["checkpoint_kind"],
            "run_id": kwargs["run_id"],
            "scope_type": kwargs["scope_type"],
            "scope_ref": kwargs["scope_ref"],
            "agent_name": kwargs["agent_name"],
            "execution_entry": kwargs["execution_entry"],
            "action_hint": kwargs["action_hint"],
            "state": kwargs["state_payload"],
        }


class _WorkflowAgentService:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.approval_service = _MemoryApprovalService()

    def _build_execution_context(self, **kwargs):
        return kwargs

    async def run_command(self, command_text: str, history: list[dict[str, str]], agent_name: str, execution_context=None):
        self.calls.append(
            {
                "command_text": command_text,
                "history": history,
                "agent_name": agent_name,
                "execution_context": dict(execution_context or {}),
            }
        )
        if not self.responses:
            raise AssertionError("No more stubbed workflow agent responses.")
        return self.responses.pop(0)


class _AuditStub:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event_type: str, message: str, payload: dict[str, object]) -> None:
        self.events.append(
            {
                "event_type": event_type,
                "message": message,
                "payload": payload,
            }
        )


def test_replace_tool_message_content_uses_safe_copy() -> None:
    service = object.__new__(SentinelFlowAgentService)
    original_message = _ImmutableToolMessage(
        json.dumps({"approval_pending": True, "approval_request": {"approval_id": "appr-1"}}, ensure_ascii=False),
        "tool-1",
    )
    state = {
        "messages": [original_message],
        "approval_pending": True,
        "approval_request": {"approval_id": "appr-1"},
    }

    updated = SentinelFlowAgentService._replace_tool_message_content(
        service,
        state,
        "tool-1",
        {"success": True, "data": {"ok": True}, "error": None},
    )

    assert updated["approval_pending"] is False
    assert updated["approval_request"] == {}
    assert updated["messages"][0] is not original_message
    assert json.loads(updated["messages"][0].content)["success"] is True


def test_workflow_runner_resume_checkpoint_after_approval() -> None:
    workflow = AgentWorkflowDefinition(
        id="wf-test",
        name="WF Test",
        description="workflow approval resume",
        enabled=True,
        steps=[
            AgentWorkflowStepDefinition(id="step-1", name="step 1", agent="worker-a", task_prompt="collect evidence"),
            AgentWorkflowStepDefinition(id="step-2", name="step 2", agent="worker-b", task_prompt="finish analysis"),
        ],
    )
    agent_service = _WorkflowAgentService(
        [
            {
                "approval_pending": True,
                "approval_request": {"approval_id": "appr-1", "skill_name": "ban-ip"},
            },
            {
                "final_response": "workflow finished",
                "messages": [],
                "tool_calls": [{"name": "close_alert"}],
                "success": True,
            },
        ]
    )
    runner = SentinelFlowAgentWorkflowRunner(agent_service, _AuditStub())
    base_context = {
        "run_id": "run-1",
        "execution_entry": "manual_alert",
        "scope_type": "alert_task",
        "scope_ref": "task-1",
        "checkpoint_thread_id": "workflow-root",
        "parent_checkpoint_thread_id": "",
        "parent_checkpoint_ns": "",
        "parent_tool_call_id": "",
        "approved_fingerprints": [],
        "rejected_fingerprints": [],
    }

    first_result = asyncio.run(
        runner.execute_workflow(
            workflow,
            {"eventIds": "evt-1"},
            task_prompt="process alert",
            execution_context=base_context,
        )
    )

    assert first_result["approval_pending"] is True
    checkpoint = agent_service.approval_service.checkpoints["workflow-root"]

    resumed = asyncio.run(
        runner.resume_checkpoint(
            checkpoint,
            {
                "final_response": "step 1 approved and done",
                "messages": [],
                "tool_calls": [{"name": "ban_ip"}],
                "success": True,
            },
            SimpleNamespace(status="approved", arguments_fingerprint="fp-1"),
        )
    )

    assert resumed["success"] is True
    assert len(resumed["worker_results"]) == 2
    assert agent_service.calls[1]["execution_context"]["approved_fingerprints"] == ["fp-1"]

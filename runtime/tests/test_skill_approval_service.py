from __future__ import annotations

from sentinelflow.services import skill_approval_service as approval_module


def test_create_or_reuse_pending_and_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(approval_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(approval_module, "DB_PATH", tmp_path / "sys_queue.db")

    service = approval_module.SkillApprovalService()

    record = service.create_or_reuse_pending(
        run_id="run-1",
        scope_type="conversation",
        scope_ref="run-1",
        skill_name="ban-ip",
        arguments={"ip": "198.51.100.10"},
        approval_required=True,
        checkpoint_thread_id="cp-1",
        checkpoint_ns="agent_graph",
        tool_call_id="tool-1",
        message="need approval",
    )

    assert record.status == "pending"
    assert record.skill_name == "ban-ip"

    reused = service.create_or_reuse_pending(
        run_id="run-1",
        scope_type="conversation",
        scope_ref="run-1",
        skill_name="ban-ip",
        arguments={"ip": "198.51.100.10"},
        approval_required=True,
        checkpoint_thread_id="cp-1",
        checkpoint_ns="agent_graph",
        tool_call_id="tool-1",
        message="need approval",
    )

    assert reused.approval_id == record.approval_id

    service.save_checkpoint(
        checkpoint_thread_id="cp-1",
        checkpoint_ns="agent_graph",
        checkpoint_kind="agent_graph",
        run_id="run-1",
        scope_type="conversation",
        scope_ref="run-1",
        agent_name="system-primary",
        execution_entry="conversation",
        action_hint="",
        state_payload={"messages": [], "run_id": "run-1"},
    )

    checkpoint = service.load_checkpoint("cp-1")
    assert checkpoint is not None
    assert checkpoint["checkpoint_kind"] == "agent_graph"
    assert checkpoint["state"]["run_id"] == "run-1"

    approved = service.set_decision(record.approval_id, "approved")
    assert approved is not None
    assert approved.status == "approved"

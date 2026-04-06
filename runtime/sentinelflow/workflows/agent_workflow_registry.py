from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentWorkflowStepDefinition:
    id: str
    name: str
    agent: str
    task_prompt: str = ""


@dataclass(frozen=True, slots=True)
class AgentWorkflowFinalHandler:
    type: str = "primary"
    action: str = "triage_close"


@dataclass(frozen=True, slots=True)
class AgentWorkflowDefinition:
    id: str
    name: str
    description: str
    enabled: bool
    scenarios: list[str] = field(default_factory=list)
    selection_keywords: list[str] = field(default_factory=list)
    recommended_action: str = "triage_close"
    steps: list[AgentWorkflowStepDefinition] = field(default_factory=list)
    final_handler: AgentWorkflowFinalHandler = field(default_factory=AgentWorkflowFinalHandler)
    location: str = ""


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _parse_workflow_file(workflow_dir: Path) -> AgentWorkflowDefinition:
    workflow_json = workflow_dir / "workflow.json"
    if not workflow_json.is_file():
        raise FileNotFoundError(f"Agent workflow not found: {workflow_dir.name}")

    raw = json.loads(workflow_json.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"workflow.json must contain an object: {workflow_json}")

    steps: list[AgentWorkflowStepDefinition] = []
    for index, item in enumerate(raw.get("steps") or [], start=1):
        if not isinstance(item, dict):
            continue
        agent_name = str(item.get("agent", "")).strip()
        task_prompt = str(item.get("task_prompt", "")).strip()
        if not agent_name:
            continue
        step_id = str(item.get("id", "")).strip() or f"step-{index}"
        step_name = str(item.get("name", "")).strip() or step_id
        steps.append(
            AgentWorkflowStepDefinition(
                id=step_id,
                name=step_name,
                agent=agent_name,
                task_prompt=task_prompt,
            )
        )

    final_handler_raw = raw.get("final_handler") or {}
    if not isinstance(final_handler_raw, dict):
        final_handler_raw = {}

    return AgentWorkflowDefinition(
        id=workflow_dir.name,
        name=str(raw.get("name") or workflow_dir.name).strip(),
        description=str(raw.get("description") or "").strip(),
        enabled=_coerce_bool(raw.get("enabled"), True),
        scenarios=_coerce_list(raw.get("scenarios")),
        selection_keywords=_coerce_list(raw.get("selection_keywords")),
        recommended_action=str(raw.get("recommended_action") or "triage_close").strip() or "triage_close",
        steps=steps,
        final_handler=AgentWorkflowFinalHandler(
            type=str(final_handler_raw.get("type") or "primary").strip() or "primary",
            action=str(final_handler_raw.get("action") or raw.get("recommended_action") or "triage_close").strip()
            or "triage_close",
        ),
        location=str(workflow_dir),
    )


def list_agent_workflows(workflow_root: Path) -> list[AgentWorkflowDefinition]:
    if not workflow_root.is_dir():
        return []
    workflows: list[AgentWorkflowDefinition] = []
    for workflow_json in sorted(workflow_root.glob("*/workflow.json")):
        workflows.append(_parse_workflow_file(workflow_json.parent))
    return workflows


def load_agent_workflow(workflow_root: Path, workflow_id: str) -> AgentWorkflowDefinition:
    return _parse_workflow_file(workflow_root / workflow_id)


def serialize_agent_workflow_summary(workflow: AgentWorkflowDefinition) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "enabled": workflow.enabled,
        "scenarios": workflow.scenarios,
        "recommended_action": workflow.recommended_action,
        "steps_count": len(workflow.steps),
        "step_agents": [step.agent for step in workflow.steps],
        "final_handler_type": workflow.final_handler.type,
        "final_handler_action": workflow.final_handler.action,
        "location": workflow.location,
    }


def serialize_agent_workflow_detail(workflow: AgentWorkflowDefinition) -> dict[str, Any]:
    return {
        **serialize_agent_workflow_summary(workflow),
        "selection_keywords": workflow.selection_keywords,
        "steps": [
            {
                "id": step.id,
                "name": step.name,
                "agent": step.agent,
                "task_prompt": step.task_prompt,
            }
            for step in workflow.steps
        ],
        "final_handler": {
            "type": workflow.final_handler.type,
            "action": workflow.final_handler.action,
        },
        "validation": {
            "valid": workflow.enabled and bool(workflow.steps),
            "errors": [] if workflow.enabled and workflow.steps else ["Workflow 必须至少包含一个启用步骤。"],
        },
    }

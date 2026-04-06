from __future__ import annotations

from pathlib import Path
from typing import Any

from sentinelflow.skills.adapters import SentinelFlowSkillRuntime


def read_sentinelflow_skill(project_root: Path, name: str) -> dict[str, Any]:
    runtime = SentinelFlowSkillRuntime(project_root / ".sentinelflow" / "plugins" / "skills")
    result = runtime.read_skill(name)
    return {
        "name": result.name,
        "type": result.type.value,
        "description": result.description,
        "markdown": result.markdown,
        "executable": result.executable,
        "input_schema": result.input_schema,
        "output_schema": result.output_schema,
        "entry": result.entry,
        "mode": result.mode.value if result.mode else None,
    }


def execute_sentinelflow_skill(
    project_root: Path,
    name: str,
    arguments: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = SentinelFlowSkillRuntime(project_root / ".sentinelflow" / "plugins" / "skills")
    result = runtime.execute_skill(name, arguments or {}, context or {})
    return {
        "success": result.success,
        "skill": result.skill,
        "data": result.data,
        "error": result.error,
        "audit_id": result.audit_id,
    }

from __future__ import annotations

from pathlib import Path

from sentinelflow.domain.models import SkillExecutionRequest, SkillExecutionResult, SkillReadResult
from sentinelflow.skills.executor import SentinelFlowSkillExecutor
from sentinelflow.skills.loader import SentinelFlowSkillLoader
from sentinelflow.skills.resolver import SentinelFlowSkillResolver


class SentinelFlowSkillRuntime:
    """Unified runtime entrypoint used by tools, workflows, and agents."""

    def __init__(self, skill_root: Path) -> None:
        self.loader = SentinelFlowSkillLoader(skill_root)
        self.resolver = SentinelFlowSkillResolver(skill_root)
        self.executor = SentinelFlowSkillExecutor()

    def list_skills(self) -> list[str]:
        return [skill.name for skill in self.loader.list_skills()]

    def read_skill(self, name: str) -> SkillReadResult:
        skill = self.resolver.resolve(name)
        return SkillReadResult(
            name=skill.spec.name,
            type=skill.spec.type,
            description=skill.spec.description,
            markdown=skill.markdown,
            executable=skill.executable,
            input_schema=skill.spec.input_schema,
            output_schema=skill.spec.output_schema,
            entry=skill.spec.entry,
            mode=skill.spec.mode,
        )

    def execute_skill(
        self,
        name: str,
        arguments: dict | None = None,
        context: dict | None = None,
    ) -> SkillExecutionResult:
        skill = self.resolver.resolve(name)
        request = SkillExecutionRequest(
            name=name,
            arguments=arguments or {},
            context=context or {},
        )
        return self.executor.execute(skill, request)

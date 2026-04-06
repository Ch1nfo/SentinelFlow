from dataclasses import dataclass

from sentinelflow.domain.models import SkillSpec


@dataclass(slots=True)
class SentinelFlowSkill:
    spec: SkillSpec
    markdown: str

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def executable(self) -> bool:
        return self.spec.execute_enabled

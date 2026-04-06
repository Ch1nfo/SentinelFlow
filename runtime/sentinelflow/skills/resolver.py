from __future__ import annotations

from pathlib import Path

from sentinelflow.domain.errors import SkillNotFoundError
from sentinelflow.skills.loader import SentinelFlowSkillLoader
from sentinelflow.skills.models import SentinelFlowSkill


class SentinelFlowSkillResolver:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.loader = SentinelFlowSkillLoader(root)

    def resolve_dir(self, name: str) -> Path:
        target = self.root / name
        if not target.is_dir():
            raise SkillNotFoundError(f"SentinelFlow skill not found: {name}")
        return target

    def resolve(self, name: str) -> SentinelFlowSkill:
        return self.loader.load(name)

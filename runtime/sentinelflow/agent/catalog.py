from __future__ import annotations

from pathlib import Path

from sentinelflow.skills.loader import SentinelFlowSkillLoader


def load_skill_catalog(skill_root: Path, readable_skills: list[str] | None = None) -> str:
    loader = SentinelFlowSkillLoader(skill_root)
    items: list[str] = []
    allowed = set(readable_skills or [])
    for skill in loader.list_skills():
        if readable_skills is not None and skill.spec.name not in allowed:
            continue
        items.append(f"- name: {skill.spec.name}\n  description: {skill.spec.description}")
    if not items:
        return "（当前没有已加载技能）"
    return "\n".join(items)

from __future__ import annotations

from sentinelflow.agent.registry import SentinelFlowAgentDefinition
from sentinelflow.domain.enums import SkillType
from sentinelflow.skills.models import SentinelFlowSkill


def can_agent_read_skill(agent: SentinelFlowAgentDefinition, skill: SentinelFlowSkill) -> bool:
    if not agent.enabled:
        return False
    if skill.spec.type == SkillType.DOC:
        if agent.doc_skill_mode == "none":
            return False
        if skill.spec.name in agent.doc_skill_denylist:
            return False
        if agent.doc_skill_mode == "selected":
            return skill.spec.name in agent.doc_skill_allowlist
        return True
    return skill.spec.name in agent.hybrid_doc_allowlist


def can_agent_execute_skill(agent: SentinelFlowAgentDefinition, skill: SentinelFlowSkill) -> bool:
    if not agent.enabled:
        return False
    if skill.spec.type != SkillType.HYBRID:
        return False
    return skill.spec.name in agent.exec_skill_allowlist


def can_agent_delegate_to_worker(agent: SentinelFlowAgentDefinition, worker_name: str) -> bool:
    if not agent.enabled:
        return False
    if agent.role != "primary":
        return False
    if not agent.worker_allowlist:
        return False
    return worker_name in agent.worker_allowlist

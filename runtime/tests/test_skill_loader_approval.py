from __future__ import annotations

from sentinelflow.skills.loader import SentinelFlowSkillLoader


def test_loader_reads_approval_required_from_frontmatter(tmp_path):
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo
type: hybrid
mode: subprocess
entry: main.py
execute_policy:
  enabled: true
  approval_required: true
  audit: true
---

# Demo
""",
        encoding="utf-8",
    )

    skill = SentinelFlowSkillLoader(tmp_path).load("demo-skill")

    assert skill.spec.execute_enabled is True
    assert skill.spec.approval_required is True

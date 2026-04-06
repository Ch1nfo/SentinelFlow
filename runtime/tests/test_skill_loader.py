from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.domain.enums import SkillType
from sentinelflow.skills.loader import SentinelFlowSkillLoader


class SkillLoaderTest(unittest.TestCase):
    def test_load_hybrid_skill_from_plugin_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            skill_dir = root / "ip-enrich"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: ip-enrich\n"
                "type: hybrid\n"
                "description: Query IP context\n"
                "entry: main.py\n"
                "mode: subprocess\n"
                "---\n"
                "# SentinelFlow Skill\n",
                encoding="utf-8",
            )
            (skill_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")

            loader = SentinelFlowSkillLoader(root)
            skill = loader.load("ip-enrich")

            self.assertEqual(skill.spec.name, "ip-enrich")
            self.assertEqual(skill.spec.type, SkillType.HYBRID)
            self.assertEqual(skill.spec.entry, "main.py")

from __future__ import annotations

from pathlib import Path
from typing import Any

from sentinelflow.domain.enums import SkillRuntimeMode, SkillType
from sentinelflow.domain.errors import SkillConfigurationError
from sentinelflow.domain.models import SkillSpec
from sentinelflow.skills.models import SentinelFlowSkill

try:
    import yaml  # type: ignore
except ModuleNotFoundError:
    yaml = None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Extract YAML frontmatter and body from a SKILL.md string.

    A valid frontmatter block starts with a line containing exactly '---'
    and ends with another such line.  Everything after the closing '---'
    is the document body.

    Returns (metadata_dict, body_text).  If no valid frontmatter is found,
    returns ({}, full_text).
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_index = i
            break

    if end_index is None:
        return {}, text

    frontmatter_text = "".join(lines[1:end_index])
    body = "".join(lines[end_index + 1:]).lstrip("\n")

    if yaml is not None:
        try:
            parsed = yaml.safe_load(frontmatter_text)
            if isinstance(parsed, dict):
                return parsed, body
        except yaml.YAMLError:
            pass

    # Fallback: minimal line-by-line key:value parser (no nesting)
    data: dict[str, Any] = {}
    current_parent: str | None = None
    for line in frontmatter_text.splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw.startswith("  ") and current_parent and ":" in stripped:
            key, _, value = stripped.partition(":")
            nested = data.get(current_parent)
            if not isinstance(nested, dict):
                nested = {}
                data[current_parent] = nested
            nested[key.strip()] = value.strip()
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current_parent = key.strip()
        if value.strip():
            data[current_parent] = value.strip()
            current_parent = None
        else:
            data[current_parent] = {}

    return data, body


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return default


class SentinelFlowSkillLoader:
    """
    Discover and load SentinelFlow skills from a plugin directory.

    Each skill lives in its own sub-directory and must contain a SKILL.md
    file whose YAML frontmatter holds all configuration metadata:

        ---
        name: my-skill
        description: One-line description shown to the agent
        type: doc           # or: hybrid
        # --- hybrid-only fields ---
        mode: subprocess
        entry: main.py
        execute_policy:
          enabled: true
          approval_required: false
          audit: true
        ---

        # Skill documentation body (what the agent reads)
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_skill_dirs(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(p for p in self.root.iterdir() if p.is_dir())

    def list_skills(self) -> list[SentinelFlowSkill]:
        skills: list[SentinelFlowSkill] = []
        for path in self.list_skill_dirs():
            try:
                skills.append(self.load_from_dir(path))
            except SkillConfigurationError:
                continue
        return skills

    def load(self, name: str) -> SentinelFlowSkill:
        return self.load_from_dir(self.root / name)

    def load_from_dir(self, skill_dir: Path) -> SentinelFlowSkill:
        if not skill_dir.is_dir():
            raise SkillConfigurationError(
                f"Skill directory does not exist: {skill_dir}"
            )

        doc_path = skill_dir / "SKILL.md"
        if not doc_path.is_file():
            raise SkillConfigurationError(
                f"Missing SKILL.md in {skill_dir}"
            )

        raw_text = doc_path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw_text)

        if not meta:
            raise SkillConfigurationError(
                f"SKILL.md has no frontmatter in {skill_dir}"
            )

        spec = self._build_spec(skill_dir, doc_path, meta)
        # Expose the full original markdown (frontmatter + body) to agents
        return SentinelFlowSkill(spec=spec, markdown=raw_text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_spec(
        self, skill_dir: Path, doc_path: Path, meta: dict[str, Any]
    ) -> SkillSpec:
        name = str(meta.get("name", "")).strip()
        description = str(meta.get("description", "")).strip()
        type_raw = str(meta.get("type", "doc")).strip().lower()

        # Legacy alias kept for hand-crafted files
        if type_raw == "exec":
            type_raw = "hybrid"

        if not name:
            raise SkillConfigurationError(
                f"'name' is required in SKILL.md frontmatter: {skill_dir}"
            )
        if not description:
            raise SkillConfigurationError(
                f"'description' is required in SKILL.md frontmatter: {skill_dir}"
            )

        try:
            skill_type = SkillType(type_raw)
        except ValueError as exc:
            raise SkillConfigurationError(
                f"Unsupported skill type {type_raw!r} in {skill_dir}"
            ) from exc

        # --- mode (runtime mode for hybrid skills) ---
        mode_raw = str(meta.get("mode", "")).strip().lower()
        runtime_mode: SkillRuntimeMode | None = None
        if mode_raw:
            try:
                runtime_mode = SkillRuntimeMode(mode_raw)
            except ValueError as exc:
                raise SkillConfigurationError(
                    f"Unsupported mode {mode_raw!r} in {skill_dir}"
                ) from exc

        # --- execute_policy block ---
        exec_policy: dict[str, Any] = {}
        raw_policy = meta.get("execute_policy")
        if isinstance(raw_policy, dict):
            exec_policy = raw_policy

        execute_enabled = _coerce_bool(
            exec_policy.get("enabled", skill_type == SkillType.HYBRID), False
        )
        approval_required = _coerce_bool(exec_policy.get("approval_required"), False)
        audit_enabled = _coerce_bool(exec_policy.get("audit", True), True)

        # --- entry (only meaningful for hybrid) ---
        entry: str | None = None
        if skill_type == SkillType.HYBRID:
            entry_raw = str(meta.get("entry", "main.py")).strip()
            if runtime_mode is None:
                raise SkillConfigurationError(
                    f"Hybrid skill requires 'mode' in frontmatter: {skill_dir}"
                )
            entry_path = skill_dir / entry_raw
            if not entry_path.is_file():
                raise SkillConfigurationError(
                    f"Skill entry file not found: {entry_path}"
                )
            entry = entry_raw

        # --- optional schemas ---
        input_schema: dict[str, Any] = {}
        output_schema: dict[str, Any] = {}
        if isinstance(meta.get("input_schema"), dict):
            input_schema = meta["input_schema"]
        if isinstance(meta.get("output_schema"), dict):
            output_schema = meta["output_schema"]

        return SkillSpec(
            name=name,
            type=skill_type,
            description=description,
            base_dir=skill_dir,
            doc_path=doc_path,
            entry=entry,
            mode=runtime_mode,
            input_schema=input_schema,
            output_schema=output_schema,
            execute_enabled=execute_enabled,
            approval_required=approval_required,
            audit_enabled=audit_enabled,
        )

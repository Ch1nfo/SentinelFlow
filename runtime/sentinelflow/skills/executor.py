from __future__ import annotations

import json
import subprocess
import sys

from sentinelflow.domain.enums import SkillRuntimeMode, SkillType
from sentinelflow.domain.errors import SkillExecutionError
from sentinelflow.domain.models import SkillExecutionRequest, SkillExecutionResult
from sentinelflow.skills.models import SentinelFlowSkill


class SentinelFlowSkillExecutor:
    """Execution facade for document-only and document+executable SentinelFlow skills."""

    def execute(self, skill: SentinelFlowSkill, request: SkillExecutionRequest) -> SkillExecutionResult:
        if skill.spec.type == SkillType.DOC:
            return SkillExecutionResult(
                success=False,
                skill=request.name,
                error=f"SentinelFlow skill '{request.name}' is doc-only and cannot be executed.",
            )
        if not skill.spec.execute_enabled:
            return SkillExecutionResult(
                success=False,
                skill=request.name,
                error=f"SentinelFlow skill '{request.name}' is not enabled for execution.",
            )

        if skill.spec.mode == SkillRuntimeMode.SUBPROCESS:
            return self._execute_subprocess(skill, request)

        raise SkillExecutionError(
            f"SentinelFlow skill '{request.name}' uses unsupported execution mode: {skill.spec.mode}"
        )

    def _execute_subprocess(self, skill: SentinelFlowSkill, request: SkillExecutionRequest) -> SkillExecutionResult:
        assert skill.spec.entry is not None
        entry_path = skill.spec.base_dir / skill.spec.entry
        payload = self._build_payload(request.arguments, request.context)
        cmd = [sys.executable, str(entry_path), json.dumps(payload, ensure_ascii=False)]

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(skill.spec.base_dir),
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SkillExecutionResult(
                success=False,
                skill=request.name,
                error=f"SentinelFlow skill '{request.name}' execution timed out: {exc}",
            )
        except OSError as exc:
            raise SkillExecutionError(f"Failed to start SentinelFlow skill '{request.name}': {exc}") from exc

        stdout = self._decode_output(proc.stdout)
        stderr = self._decode_output(proc.stderr)
        if proc.returncode != 0:
            return SkillExecutionResult(
                success=False,
                skill=request.name,
                error=f"exit code {proc.returncode}",
                data={"stdout": stdout, "stderr": stderr},
            )

        parsed = self._parse_stdout(stdout)
        if isinstance(parsed, dict) and "error" in parsed:
            return SkillExecutionResult(
                success=False,
                skill=request.name,
                error=str(parsed.get("error", "")),
                data=parsed,
            )
        return SkillExecutionResult(
            success=True,
            skill=request.name,
            data=parsed,
        )

    def _build_payload(self, arguments: dict, context: dict) -> dict:
        payload = dict(arguments)
        if context:
            payload["_context"] = self._json_safe(context)
        return payload

    def _json_safe(self, value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items() if self._is_json_safe_value(item)}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(item) for item in value if self._is_json_safe_value(item)]
        return str(value)

    def _is_json_safe_value(self, value) -> bool:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return True
        if isinstance(value, dict):
            return True
        if isinstance(value, (list, tuple)):
            return True
        return False

    def _parse_stdout(self, stdout: str):
        text = stdout.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_output": text}

    def _decode_output(self, raw: bytes) -> str:
        for encoding in ("utf-8", "gbk", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace").strip()

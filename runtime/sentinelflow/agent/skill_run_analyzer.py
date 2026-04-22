"""
Skill run extraction and analysis utilities for SentinelFlow agent results.

Extracted from agent/service.py to isolate the domain logic for parsing
LangGraph tool call/message pairs and classifying skill runs by type
(closure, enrichment, action).
"""
from __future__ import annotations

import json
from typing import Any


class SkillRunAnalyzerMixin:
    """
    Mixin providing skill-run analysis methods for SentinelFlowAgentService.

    All methods operate on plain dicts (graph_result, tool calls, messages)
    and are stateless with respect to service infrastructure.
    """

    # ── Core extraction ───────────────────────────────────────────────────────

    def _extract_skill_runs(self, graph_result: dict[str, Any]) -> list[dict[str, Any]]:
        tool_calls = [item for item in graph_result.get("tool_calls", []) if isinstance(item, dict)]
        tool_messages = [
            item
            for item in graph_result.get("messages", [])
            if isinstance(item, dict) and str(item.get("type", "")).strip() == "tool"
        ]
        tool_messages_by_id: dict[str, dict[str, Any]] = {}
        ordered_tool_messages: list[dict[str, Any]] = []
        for tool_message in tool_messages:
            tool_call_id = str(tool_message.get("tool_call_id", "")).strip()
            if tool_call_id:
                tool_messages_by_id[tool_call_id] = tool_message
            ordered_tool_messages.append(tool_message)
        runs: list[dict[str, Any]] = []
        tool_index = 0
        for call in tool_calls:
            tool_name = str(call.get("name", "")).strip()
            if tool_name not in {"execute_skill", "execute_skill_no_args"}:
                continue
            args = call.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            skill_name = str(args.get("skill_name", "")).strip()
            arguments = args.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            if tool_name == "execute_skill_no_args":
                arguments = {}

            payload: dict[str, Any] = {}
            matched_message = None
            tool_call_id = str(call.get("id", "")).strip()
            if tool_call_id:
                matched_message = tool_messages_by_id.get(tool_call_id)
            if matched_message is None:
                while tool_index < len(ordered_tool_messages):
                    tool_message = ordered_tool_messages[tool_index]
                    tool_index += 1
                    candidate_id = str(tool_message.get("tool_call_id", "")).strip()
                    candidate_name = str(tool_message.get("name", "")).strip()
                    if candidate_id and candidate_id != tool_call_id:
                        continue
                    if candidate_name and candidate_name != tool_name:
                        continue
                    matched_message = tool_message
                    break
            if matched_message is not None:
                content = matched_message.get("content", "")
                if isinstance(content, str):
                    try:
                        decoded = json.loads(content)
                    except json.JSONDecodeError:
                        decoded = {"raw": content}
                elif isinstance(content, dict):
                    decoded = content
                else:
                    decoded = {"result": content}
                if isinstance(decoded, dict):
                    payload = decoded

            tool_payload = dict(payload)
            business_payload = tool_payload.get("data", {})
            if not isinstance(business_payload, dict):
                business_payload = {"result": business_payload}

            computed_success = self._compute_skill_run_success(
                tool_payload=tool_payload,
                business_payload=business_payload,
            )
            runs.append(
                {
                    "skill_name": skill_name,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "tool_success": bool(tool_payload.get("success")) if isinstance(tool_payload.get("success"), bool) else not bool(tool_payload.get("error")),
                    "tool_error": tool_payload.get("error"),
                    "tool_payload": tool_payload,
                    "arguments": arguments,
                    "payload": dict(business_payload),
                    "success": computed_success,
                }
            )
        return runs

    def _compute_skill_run_success(
        self,
        *,
        tool_payload: dict[str, Any],
        business_payload: dict[str, Any],
    ) -> bool:
        tool_error = tool_payload.get("error")
        if bool(tool_error):
            return False
        tool_success = tool_payload.get("success")
        if isinstance(tool_success, bool) and not tool_success:
            return False
        if bool(business_payload.get("error")):
            return False
        business_success = business_payload.get("success")
        if isinstance(business_success, bool):
            return business_success
        return True

    # ── Run classification ────────────────────────────────────────────────────

    def _is_closure_run(self, run: dict[str, Any]) -> bool:
        skill_name = str(run.get("skill_name", "")).strip().lower()
        if self._is_closure_skill_name(skill_name):
            return True
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        combined_keys = set(payload.keys()) | set(arguments.keys())
        if {"status", "memo", "detailMsg"}.issubset(combined_keys):
            return True
        closure_markers = {"status", "memo", "detailMsg", "detail_msg", "closeStatus", "close_status"}
        return bool(combined_keys & closure_markers) and (
            "memo" in combined_keys or "detailMsg" in combined_keys or "detail_msg" in combined_keys or "status" in combined_keys
        )

    def _is_closure_skill_name(self, skill_name: str) -> bool:
        normalized = skill_name.strip().lower()
        if normalized in {"exec", "close", "soc_close", "alert_close"}:
            return True
        closure_keywords = (
            "exec",
            "close",
            "closure",
            "socclose",
            "alertclose",
            "ticketclose",
            "结单",
            "闭环",
            "关单",
        )
        compact = normalized.replace("-", "").replace("_", "").replace(" ", "")
        return any(keyword in compact for keyword in closure_keywords)

    def _looks_like_closure_fallback(self, run: dict[str, Any]) -> bool:
        skill_name = str(run.get("skill_name", "")).strip()
        if self._is_closure_skill_name(skill_name):
            return True
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        combined_keys = set(payload.keys()) | set(arguments.keys())
        if {"status", "memo", "detailMsg"} <= combined_keys:
            return True
        closure_markers = {"status", "memo", "detailMsg", "detail_msg", "closeStatus", "close_status"}
        if combined_keys & closure_markers:
            return True
        text_candidates = [
            skill_name,
            str(payload.get("message", "")),
            str(payload.get("result", "")),
            str(payload.get("raw", "")),
            str(arguments.get("message", "")),
            str(arguments.get("result", "")),
        ]
        normalized_text = " ".join(item.strip().lower() for item in text_candidates if item and str(item).strip())
        return any(marker in normalized_text for marker in ("结单", "闭环", "关单", "close", "closed", "closure", "exec"))

    def _select_closure_run(
        self,
        skill_runs: list[dict[str, Any]],
        action_hint: str | None,
    ) -> dict[str, Any] | None:
        for run in skill_runs:
            if self._is_closure_run(run):
                return run
        if action_hint not in {"triage_close", "triage_dispose"}:
            return None
        fallback_candidates = [
            run
            for run in skill_runs
            if str(run.get("skill_name", "")).strip()
            and not self._is_enrichment_run(run)
            and self._looks_like_closure_fallback(run)
        ]
        if fallback_candidates:
            return fallback_candidates[-1]
        return None

    def _is_same_skill_run(self, left: dict[str, Any], right: dict[str, Any] | None) -> bool:
        if right is None:
            return False
        left_id = str(left.get("tool_call_id", "")).strip()
        right_id = str(right.get("tool_call_id", "")).strip()
        if left_id and right_id:
            return left_id == right_id
        return left is right

    def _is_successful_closure_run(self, run: dict[str, Any]) -> bool:
        if not (self._is_closure_run(run) or self._looks_like_closure_fallback(run)):
            return False
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        tool_success = run.get("tool_success")
        tool_error = run.get("tool_error")
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        if bool(tool_error):
            return False
        if isinstance(tool_success, bool) and not tool_success:
            return False
        if bool(payload.get("error")):
            return False
        status_value = payload.get("status", arguments.get("status"))
        result_value = payload.get("result", arguments.get("result"))
        success_value = payload.get("success", tool_success)
        if isinstance(success_value, bool):
            return success_value
        if isinstance(result_value, str) and result_value.strip():
            normalized = result_value.strip().lower()
            if normalized in {"ok", "success", "done", "closed", "completed", "true"}:
                return True
            if normalized in {"fail", "failed", "false", "error"}:
                return False
        if isinstance(status_value, str) and status_value.strip():
            normalized_status = status_value.strip().lower()
            if normalized_status in {"fail", "failed", "false", "error", "0", "-1"}:
                return False
            return True
        if isinstance(tool_success, bool):
            return tool_success
        return False

    def _is_enrichment_run(self, run: dict[str, Any]) -> bool:
        if self._is_closure_run(run):
            return False
        payload = run.get("payload", {})
        arguments = run.get("arguments", {})
        payload = payload if isinstance(payload, dict) else {}
        arguments = arguments if isinstance(arguments, dict) else {}
        combined_keys = set(payload.keys()) | set(arguments.keys())
        ip_markers = {"ip", "source_ip", "sip", "target_ip", "dest_ip", "dip"}
        detail_markers = {"country", "province", "city", "asn", "isp", "risk_level"}
        return bool(combined_keys & ip_markers) and bool(combined_keys & detail_markers)

    # ── Run aggregation helpers ───────────────────────────────────────────────

    def _build_actions(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        actions: dict[str, Any] = {}
        for run in skill_runs:
            skill_name = str(run.get("skill_name", "")).strip()
            if not skill_name or self._is_same_skill_run(run, closure_run) or self._is_enrichment_run(run):
                continue
            payload = run.get("payload", {})
            if isinstance(payload, dict) and payload:
                actions[skill_name.replace("-", "_")] = payload
        return actions

    def _first_closure_payload(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        selected = closure_run or self._select_closure_run(skill_runs, None)
        if selected is not None:
            payload = selected.get("payload", {})
            return payload if isinstance(payload, dict) else {}
        return {}

    def _first_enrichment_payload(self, skill_runs: list[dict[str, Any]]) -> dict[str, Any]:
        for run in skill_runs:
            if self._is_enrichment_run(run):
                payload = run.get("payload", {})
                return payload if isinstance(payload, dict) else {}
        return {}

    def _build_closure_step(
        self,
        skill_runs: list[dict[str, Any]],
        closure_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if closure_run is not None:
            skill_name = str(closure_run.get("skill_name", "")).strip()
            payload = closure_run.get("payload", {})
            arguments = closure_run.get("arguments", {})
            payload = payload if isinstance(payload, dict) else {}
            arguments = arguments if isinstance(arguments, dict) else {}
            success = self._is_successful_closure_run(closure_run)
            summary = str(
                payload.get("detailMsg")
                or payload.get("detail_msg")
                or payload.get("result")
                or payload.get("message")
                or ("结单执行成功。" if success else "结单执行失败。")
            ).strip()
            return {
                "attempted": True,
                "success": success,
                "skill_name": skill_name,
                "tool_name": closure_run.get("tool_name", ""),
                "tool_call_id": closure_run.get("tool_call_id", ""),
                "tool_success": closure_run.get("tool_success"),
                "tool_error": closure_run.get("tool_error"),
                "arguments": arguments,
                "result": payload,
                "error": payload.get("error"),
                "summary": summary,
            }
        return {
            "attempted": False,
            "success": False,
            "skill_name": "",
            "tool_name": "",
            "tool_call_id": "",
            "tool_success": False,
            "tool_error": None,
            "arguments": {},
            "result": {},
            "error": None,
            "summary": "",
        }

    def _extract_nested_side_effects(
        self,
        nested_result: dict[str, Any],
        *,
        action_hint: str | None,
        source_type: str,
        source_name: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
        skill_runs = self._extract_skill_runs(nested_result)
        closure_run = self._select_closure_run(skill_runs, action_hint)
        actions = self._build_actions(skill_runs, closure_run)
        action_steps = self._build_action_steps(skill_runs, closure_run)  # type: ignore[attr-defined]
        closure_step = self._build_closure_step(skill_runs, closure_run)
        if action_steps:
            for step in action_steps:
                if not isinstance(step, dict):
                    continue
                step["source_type"] = source_type
                step["source_name"] = source_name
        if bool(closure_step.get("attempted")):
            closure_step = {
                **closure_step,
                "source_type": source_type,
                "source_name": source_name,
            }
        return action_steps, actions, closure_step if bool(closure_step.get("attempted")) else None

    def _aggregate_action_side_effects(
        self,
        *,
        primary_action_steps: list[dict[str, Any]],
        primary_actions: dict[str, Any],
        worker_results: list[dict[str, Any]],
        workflow_runs: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        aggregated_steps: list[dict[str, Any]] = []
        aggregated_actions: dict[str, Any] = {}

        for step in primary_action_steps:
            if not isinstance(step, dict):
                continue
            aggregated_steps.append({**step, "source_type": "primary", "source_name": "primary"})
        for action_name, payload in primary_actions.items():
            aggregated_actions[action_name] = payload

        for worker_result in worker_results:
            if not isinstance(worker_result, dict):
                continue
            worker_name = str(worker_result.get("worker") or worker_result.get("worker_agent") or "").strip() or "worker"
            nested_steps, nested_actions, _ = self._extract_nested_side_effects(
                worker_result,
                action_hint=None,
                source_type="worker",
                source_name=worker_name,
            )
            aggregated_steps.extend(nested_steps)
            for action_name, payload in nested_actions.items():
                aggregated_actions[f"{worker_name}:{action_name}"] = payload

        for workflow_run in workflow_runs:
            if not isinstance(workflow_run, dict):
                continue
            workflow_name = str(workflow_run.get("workflow_name", workflow_run.get("workflow_id", ""))).strip() or "workflow"
            workflow_action_steps = workflow_run.get("action_steps", [])
            if isinstance(workflow_action_steps, list):
                for step in workflow_action_steps:
                    if not isinstance(step, dict):
                        continue
                    aggregated_steps.append({**step, "source_type": "workflow", "source_name": workflow_name})
            workflow_actions = workflow_run.get("actions", {})
            if isinstance(workflow_actions, dict):
                for action_name, payload in workflow_actions.items():
                    if action_name == "tool_runs":
                        continue
                    aggregated_actions[f"{workflow_name}:{action_name}"] = payload
            nested_worker_results = workflow_run.get("worker_results", [])
            if isinstance(nested_worker_results, list):
                for worker_result in nested_worker_results:
                    if not isinstance(worker_result, dict):
                        continue
                    worker_name = str(worker_result.get("worker") or worker_result.get("worker_agent") or "").strip() or "worker"
                    nested_steps, nested_actions, _ = self._extract_nested_side_effects(
                        worker_result,
                        action_hint=None,
                        source_type="workflow_worker",
                        source_name=f"{workflow_name}/{worker_name}",
                    )
                    aggregated_steps.extend(nested_steps)
                    for action_name, payload in nested_actions.items():
                        aggregated_actions[f"{workflow_name}/{worker_name}:{action_name}"] = payload

        return aggregated_steps, aggregated_actions

    def _aggregate_closure_steps(
        self,
        *,
        primary_closure_step: dict[str, Any],
        worker_results: list[dict[str, Any]],
        workflow_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        aggregated: list[dict[str, Any]] = []
        if bool(primary_closure_step.get("attempted")):
            aggregated.append({**primary_closure_step, "source_type": "primary", "source_name": "primary"})

        for worker_result in worker_results:
            if not isinstance(worker_result, dict):
                continue
            worker_name = str(worker_result.get("worker") or worker_result.get("worker_agent") or "").strip() or "worker"
            _, _, nested_closure = self._extract_nested_side_effects(
                worker_result,
                action_hint=None,
                source_type="worker",
                source_name=worker_name,
            )
            if nested_closure:
                aggregated.append(nested_closure)

        for workflow_run in workflow_runs:
            if not isinstance(workflow_run, dict):
                continue
            workflow_name = str(workflow_run.get("workflow_name", workflow_run.get("workflow_id", ""))).strip() or "workflow"
            workflow_closure = workflow_run.get("closure_step", {})
            if isinstance(workflow_closure, dict) and bool(workflow_closure.get("attempted")):
                aggregated.append({**workflow_closure, "source_type": "workflow", "source_name": workflow_name})
            nested_worker_results = workflow_run.get("worker_results", [])
            if isinstance(nested_worker_results, list):
                for worker_result in nested_worker_results:
                    if not isinstance(worker_result, dict):
                        continue
                    worker_name = str(worker_result.get("worker") or worker_result.get("worker_agent") or "").strip() or "worker"
                    _, _, nested_closure = self._extract_nested_side_effects(
                        worker_result,
                        action_hint=None,
                        source_type="workflow_worker",
                        source_name=f"{workflow_name}/{worker_name}",
                    )
                    if nested_closure:
                        aggregated.append(nested_closure)
        return aggregated

    def _resolve_effective_closure_step(
        self,
        *,
        primary_closure_step: dict[str, Any],
        aggregated_closure_steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if bool(primary_closure_step.get("attempted")) and bool(primary_closure_step.get("success")):
            return {**primary_closure_step, "source_type": "primary", "source_name": "primary"}
        for closure_step in aggregated_closure_steps:
            if isinstance(closure_step, dict) and bool(closure_step.get("attempted")) and bool(closure_step.get("success")):
                return closure_step
        if bool(primary_closure_step.get("attempted")):
            return {**primary_closure_step, "source_type": "primary", "source_name": "primary"}
        for closure_step in aggregated_closure_steps:
            if isinstance(closure_step, dict) and bool(closure_step.get("attempted")):
                return closure_step
        return {
            "attempted": False,
            "success": False,
            "skill_name": "",
            "tool_name": "",
            "tool_call_id": "",
            "tool_success": False,
            "tool_error": None,
            "arguments": {},
            "result": {},
            "error": None,
            "summary": "",
            "source_type": "",
            "source_name": "",
        }

    def _compute_alert_task_success(
        self,
        *,
        action_hint: str | None,
        closure_step: dict[str, Any],
        action_steps: list[dict[str, Any]],
        skill_runs: list[dict[str, Any]],
        actions: dict[str, Any],
    ) -> bool:
        return bool(closure_step.get("attempted")) and bool(closure_step.get("success"))

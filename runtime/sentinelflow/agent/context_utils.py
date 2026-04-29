from __future__ import annotations

import json
import re
from typing import Any


KEY_FACT_FIELDS = {
    "to",
    "notify_to",
    "recipient",
    "recipients",
    "recipient_id",
    "receiver",
    "receiver_id",
    "target",
    "target_ip",
    "ip",
    "sip",
    "dip",
    "alert_id",
    "event_id",
    "eventIds",
    "action_object",
    "notification_channel",
    "channel",
    "user",
    "user_id",
    "username",
    "account",
    "chat_id",
    "group_id",
    "mobile",
    "phone",
    "email",
    "webhook",
}

KEY_FACT_ALIASES = {
    "to": ("to", "recipient"),
    "notify_to": ("notify_to", "to", "recipient"),
    "recipient": ("recipient", "to"),
    "receiver": ("receiver", "recipient", "to"),
    "recipient_id": ("recipient_id", "recipient", "to"),
    "receiver_id": ("receiver_id", "recipient", "to"),
}

DEFAULT_KEY_FACT_MAX_DEPTH = 20


def compact_text(value: Any, limit: int = 800) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _json_safe(value: Any, *, max_depth: int | None = None, _depth: int = 0) -> Any:
    if max_depth is not None and _depth >= max_depth:
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item, max_depth=max_depth, _depth=_depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, max_depth=max_depth, _depth=_depth + 1) for item in value]
    return str(value)


def _merge_fact(facts: dict[str, Any], key: str, value: Any) -> None:
    if value in ("", None, [], {}):
        return
    safe_value = _json_safe(value, max_depth=DEFAULT_KEY_FACT_MAX_DEPTH)
    if key not in facts:
        facts[key] = safe_value
        return
    current = facts[key]
    if current == safe_value:
        return
    if not isinstance(current, list):
        current = [current]
    values = current + ([safe_value] if not isinstance(safe_value, list) else safe_value)
    deduped: list[Any] = []
    seen: set[str] = set()
    for item in values:
        safe_item = _json_safe(item, max_depth=DEFAULT_KEY_FACT_MAX_DEPTH)
        marker = json.dumps(safe_item, ensure_ascii=False, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(safe_item)
    facts[key] = deduped


def _collect_key_facts(
    value: Any,
    facts: dict[str, Any],
    *,
    depth: int = 0,
    max_depth: int = DEFAULT_KEY_FACT_MAX_DEPTH,
    seen_containers: set[int] | None = None,
) -> None:
    if depth > max_depth:
        return
    if seen_containers is None:
        seen_containers = set()
    if isinstance(value, dict):
        marker = id(value)
        if marker in seen_containers:
            return
        seen_containers.add(marker)
        for key, item in value.items():
            normalized_key = str(key).strip()
            if normalized_key in KEY_FACT_FIELDS:
                for fact_key in KEY_FACT_ALIASES.get(normalized_key, (normalized_key,)):
                    _merge_fact(facts, fact_key, item)
            if isinstance(item, (dict, list, tuple)):
                _collect_key_facts(
                    item,
                    facts,
                    depth=depth + 1,
                    max_depth=max_depth,
                    seen_containers=seen_containers,
                )
    elif isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in seen_containers:
            return
        seen_containers.add(marker)
        for item in value:
            _collect_key_facts(
                item,
                facts,
                depth=depth + 1,
                max_depth=max_depth,
                seen_containers=seen_containers,
            )
    elif isinstance(value, str):
        ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", value)
        emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
        if ips:
            _merge_fact(facts, "ip", ips)
        if emails:
            _merge_fact(facts, "email", emails)


def extract_key_facts(*values: Any, max_depth: int = DEFAULT_KEY_FACT_MAX_DEPTH) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for value in values:
        _collect_key_facts(value, facts, max_depth=max_depth)
    return facts


def _parse_tool_message_payload(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content}
    if isinstance(content, dict):
        return content
    return {"result": content}


def _tool_payloads_by_id(tool_messages: Any) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    if not isinstance(tool_messages, list):
        return payloads
    for message in tool_messages:
        if isinstance(message, dict):
            msg_type = str(message.get("type", "")).strip()
            tool_call_id = str(message.get("tool_call_id", "")).strip()
            content = message.get("content", "")
        else:
            msg_type = str(getattr(message, "type", "")).strip()
            tool_call_id = str(getattr(message, "tool_call_id", "")).strip()
            content = getattr(message, "content", "")
        if msg_type != "tool" or not tool_call_id:
            continue
        payload = _parse_tool_message_payload(content)
        if isinstance(payload, dict):
            payloads[tool_call_id] = _json_safe(payload)
    return payloads


def summarize_tool_calls(
    tool_calls: Any,
    *,
    limit: int | None = None,
    tool_messages: Any = None,
) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    summaries: list[dict[str, Any]] = []
    selected_calls = tool_calls if limit is None else tool_calls[:limit]
    payloads_by_id = _tool_payloads_by_id(tool_messages)
    for call in selected_calls:
        if not isinstance(call, dict):
            continue
        args = call.get("args", {})
        if not isinstance(args, dict):
            args = {}
        item = {
            "name": str(call.get("name", "")).strip(),
            "args": _json_safe(args),
            "key_facts": extract_key_facts(args),
        }
        if call.get("id"):
            item["id"] = str(call.get("id", "")).strip()
        if call.get("type"):
            item["type"] = str(call.get("type", "")).strip()
        tool_payload = payloads_by_id.get(str(call.get("id", "")).strip())
        if isinstance(tool_payload, dict):
            item["tool_payload"] = tool_payload
            data = tool_payload.get("data", {})
            if isinstance(data, dict):
                item["payload"] = data
            elif data not in (None, ""):
                item["payload"] = {"result": data}
        summaries.append(item)
    return [item for item in summaries if item.get("name")]


def compact_worker_result_for_llm(worker_result: dict[str, Any]) -> dict[str, Any]:
    tool_calls_summary = worker_result.get("tool_calls_summary", [])
    if not isinstance(tool_calls_summary, list) or not tool_calls_summary:
        tool_calls_summary = summarize_tool_calls(worker_result.get("tool_calls", []))
    key_facts = extract_key_facts(
        worker_result.get("key_facts", {}),
        tool_calls_summary,
        worker_result.get("final_response", ""),
    )
    final_response = str(worker_result.get("final_response", ""))
    error = worker_result.get("error")
    compact: dict[str, Any] = {
        "step": worker_result.get("step", 0),
        "worker": str(worker_result.get("worker", worker_result.get("worker_agent", ""))).strip(),
        "task_prompt": str(worker_result.get("task_prompt", "")),
        "final_response": final_response,
        "display_summary": compact_text(final_response, 1600),
        "skills_used": list(worker_result.get("skills_used", []) or []),
        "tool_calls_summary": tool_calls_summary,
        "key_facts": key_facts,
        "success": bool(worker_result.get("success")),
        "error": error,
    }
    if worker_result.get("approval_pending"):
        compact["approval_pending"] = True
        compact["approval_request"] = worker_result.get("approval_request", {})
    return compact


def build_context_envelope(
    *,
    original_input: Any,
    delegated_task: str = "",
    workflow_step: dict[str, Any] | None = None,
    prior_facts: dict[str, Any] | None = None,
    authoritative_inputs: dict[str, Any] | None = None,
    constraints: list[str] | None = None,
) -> dict[str, Any]:
    default_constraints = [
        "当前任务以 delegated_task / workflow_step 为准，原始输入只作为背景。",
        "不得从历史噪声中猜测发送对象、处置对象或结单对象。",
        "关键对象只能来自当前任务、authoritative_inputs、原始输入中的明确字段或 prior_facts。",
        "如果关键对象缺失，必须说明缺失，不要编造。",
    ]
    return {
        "original_input": _json_safe(original_input),
        "delegated_task": delegated_task,
        "workflow_step": workflow_step or {},
        "prior_facts": prior_facts or {},
        "authoritative_inputs": _json_safe(authoritative_inputs or {}),
        "constraints": list(constraints or default_constraints),
    }

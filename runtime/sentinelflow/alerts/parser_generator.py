from __future__ import annotations

import json
import re
from typing import Any

import requests

from sentinelflow.alerts.parser_runtime import ensure_parser_rule, parse_jsonish
from sentinelflow.config.runtime import load_runtime_config


FIELD_CANDIDATES: dict[str, list[str]] = {
    "eventIds": ["event.id", "id", "event_id", "eventId", "alert.id", "record_id"],
    "alert_name": ["event.title", "title", "name", "alert_name", "event.name"],
    "sip": ["network.src.ip", "src.ip", "source.ip", "sip", "src_ip", "source_ip"],
    "dip": ["network.dst.ip", "dst.ip", "destination.ip", "dip", "dst_ip", "dest_ip", "target.ip"],
    "alert_time": ["event.occurred_at", "occurred_at", "event.time", "alert_time", "timestamp", "created_at"],
    "alert_source": ["source.name", "alert_source", "source", "vendor", "platform"],
    "current_judgment": ["judgment.current", "current_judgment", "judgment.result", "status.current"],
    "history_judgment": ["judgment.history", "history_judgment", "status.history", "history"],
}

PAYLOAD_FIELD_CANDIDATES = [
    "summary",
    "details",
    "detail",
    "description",
    "message",
    "event.category",
    "event.severity",
]


def _extract_text_from_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested
        return ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item)
                continue
            if isinstance(item, dict):
                if isinstance(item.get("text"), str) and item.get("text", "").strip():
                    parts.append(str(item["text"]))
                    continue
                if isinstance(item.get("content"), str) and item.get("content", "").strip():
                    parts.append(str(item["content"]))
                    continue
                nested_text = item.get("text")
                if isinstance(nested_text, dict) and isinstance(nested_text.get("value"), str) and nested_text.get("value", "").strip():
                    parts.append(str(nested_text["value"]))
        return "\n".join(part for part in parts if part.strip())
    return ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()
    try:
        decoded = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            decoded = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return decoded if isinstance(decoded, dict) else None


def _extract_rule_from_response(data: dict[str, Any]) -> dict[str, Any] | None:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else {}
        if isinstance(message, dict):
            parsed = message.get("parsed")
            if isinstance(parsed, dict):
                return parsed
            content_text = _extract_text_from_content(message.get("content"))
            extracted = _extract_json_object(content_text)
            if extracted:
                return extracted

    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            content_text = _extract_text_from_content(content)
            extracted = _extract_json_object(content_text)
            if extracted:
                return extracted

    output_text = _extract_text_from_content(data.get("output_text"))
    extracted = _extract_json_object(output_text)
    if extracted:
        return extracted

    text = _extract_text_from_content(data.get("text"))
    return _extract_json_object(text)


def _walk_path(value: Any, path: str) -> Any:
    current = value
    for part in [item.strip() for item in path.split(".") if item.strip()]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _iter_dict_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.append(path)
            paths.extend(_iter_dict_paths(nested, path))
    return paths


def _find_candidate_items_paths(value: Any, prefix: str = "") -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        candidates.append((prefix, len(value)))
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            candidates.extend(_find_candidate_items_paths(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value[:3]):
            path = f"{prefix}.{index}" if prefix else str(index)
            candidates.extend(_find_candidate_items_paths(nested, path))
    return candidates


def _choose_items_path(sample: Any) -> str:
    candidates = _find_candidate_items_paths(sample)
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (item[1], len(item[0])), reverse=True)
    return candidates[0][0]


def _find_first_matching_path(item: dict[str, Any], candidates: list[str]) -> str:
    available_paths = set(_iter_dict_paths(item))
    for path in candidates:
        if path in available_paths and _walk_path(item, path) not in (None, "", []):
            return path
    return ""


def _infer_rule_from_sample(sample: Any) -> dict[str, Any]:
    items_path = _choose_items_path(sample)
    source_items = _walk_path(sample, items_path) if items_path else sample
    if isinstance(source_items, dict):
        source_items = [source_items]
    first_item = source_items[0] if isinstance(source_items, list) and source_items and isinstance(source_items[0], dict) else {}
    field_mapping = {
        field: _find_first_matching_path(first_item, candidates)
        for field, candidates in FIELD_CANDIDATES.items()
    }
    payload_fields = [path for path in PAYLOAD_FIELD_CANDIDATES if _find_first_matching_path(first_item, [path])]

    defaults: dict[str, Any] = {}
    source_name = _walk_path(sample, "source.name")
    if isinstance(source_name, str) and source_name.strip():
        defaults["alert_source"] = source_name.strip()

    return ensure_parser_rule(
        {
            "items_path": items_path,
            "field_mapping": field_mapping,
            "payload_fields": payload_fields,
            "payload_template": "",
            "defaults": defaults,
        }
    )


class AlertParserGenerator:
    def generate(self, sample_payload: Any) -> dict[str, Any]:
        sample = parse_jsonish(sample_payload)
        if sample is None:
            raise ValueError("告警样本不是合法 JSON。")
        inferred_rule = _infer_rule_from_sample(sample)

        runtime_config = load_runtime_config()
        if not (runtime_config.llm_api_base_url and runtime_config.llm_api_key and runtime_config.llm_model):
            raise ValueError("当前未配置可用的大模型，无法自动生成解析规则。")

        payload = {
            "model": runtime_config.llm_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "你是告警 JSON 结构解析专家。你只输出 JSON 对象，不要输出解释。"},
                {"role": "user", "content": self._build_prompt(sample)},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {runtime_config.llm_api_key}",
        }
        url = runtime_config.llm_api_base_url.rstrip("/") + "/chat/completions"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=runtime_config.llm_timeout)
            response.raise_for_status()
            data = response.json()
            generated = _extract_rule_from_response(data if isinstance(data, dict) else {})
            if not generated:
                return {
                    "parser_rule": inferred_rule,
                    "strategy": "heuristic",
                    "reason": "大模型没有返回有效 JSON，已根据样本结构生成一版候选解析规则。",
                }
            return {
                "parser_rule": ensure_parser_rule(generated),
                "strategy": "llm",
                "reason": "已基于大模型生成候选解析规则。",
            }
        except Exception as exc:
            return {
                "parser_rule": inferred_rule,
                "strategy": "heuristic",
                "reason": f"大模型解析失败，已根据样本结构生成一版候选解析规则：{exc}",
            }

    def _build_prompt(self, sample: Any) -> str:
        candidate_items_path = _choose_items_path(sample)
        return (
            "请根据下面的原始告警样本，生成一份用于 SentinelFlow 的告警解析规则 JSON。\n"
            "只输出一个 JSON 对象，字段必须包含：items_path、field_mapping、payload_fields、payload_template、defaults。\n"
            "field_mapping 可选键包括：eventIds、alert_name、sip、dip、alert_time、alert_source、current_judgment、history_judgment。\n"
            "样本中可能包含 1 条或多条告警。如果有多条，请先识别公共告警数组路径，再基于单条告警对象生成字段映射。\n"
            f"如果你识别到公共告警数组路径，优先考虑：{candidate_items_path or '请自行判断'}。\n"
            "映射值必须是点路径字符串，不要输出解释，不要使用任何预置厂商格式，也不要假设固定字段名以外的背景信息。\n\n"
            f"原始样本：\n{json.dumps(sample, ensure_ascii=False, indent=2)}"
        )

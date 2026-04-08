from __future__ import annotations

from hashlib import sha1
import json
import re
from typing import Any


DEFAULT_ALERT_PARSER_RULE: dict[str, Any] = {
    "items_path": "",
    "field_mapping": {
        "eventIds": "",
        "alert_name": "",
        "sip": "",
        "dip": "",
        "alert_time": "",
        "alert_source": "",
        "current_judgment": "",
        "history_judgment": "",
    },
    "payload_fields": [],
    "payload_template": "",
    "defaults": {},
}


def parse_jsonish(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def ensure_parser_rule(rule: Any) -> dict[str, Any]:
    if isinstance(rule, str):
        rule = parse_jsonish(rule)
    if not isinstance(rule, dict):
        return dict(DEFAULT_ALERT_PARSER_RULE)
    merged = dict(DEFAULT_ALERT_PARSER_RULE)
    merged["field_mapping"] = dict(DEFAULT_ALERT_PARSER_RULE["field_mapping"])
    merged["field_mapping"].update(rule.get("field_mapping", {}) if isinstance(rule.get("field_mapping"), dict) else {})
    merged["payload_fields"] = list(rule.get("payload_fields", [])) if isinstance(rule.get("payload_fields"), list) else []
    merged["defaults"] = dict(rule.get("defaults", {})) if isinstance(rule.get("defaults"), dict) else {}
    merged["items_path"] = str(rule.get("items_path", "")).strip()
    merged["payload_template"] = str(rule.get("payload_template", "")).strip()
    return merged


def validate_and_prepare_parser_rule(rule: Any) -> tuple[dict[str, Any] | None, str | None]:
    if rule is None:
        return None, "当前还没有保存告警解析规则。"
    if isinstance(rule, str):
        parsed = parse_jsonish(rule)
        if parsed is None:
            return None, "告警解析规则不是合法 JSON。"
        rule = parsed
    if not isinstance(rule, dict):
        return None, "告警解析规则格式无效，必须是 JSON 对象。"
    if not rule:
        return None, "当前还没有保存告警解析规则。"
    return ensure_parser_rule(rule), None


def _walk_path(value: Any, path: str) -> Any:
    current = value
    cleaned = path.strip().strip(".")
    if not cleaned:
        return current
    for raw_part in cleaned.split("."):
        part = raw_part.strip()
        if not part:
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return None
            index = int(part)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict):
            if isinstance(current, str):
                current = parse_jsonish(current)
            if not isinstance(current, dict):
                return None
        current = current.get(part)
    return current


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _join_payload_fields(item: dict[str, Any], fields: list[str]) -> str:
    parts: list[str] = []
    for field in fields:
        value = _walk_path(item, str(field))
        text = _stringify(value)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _render_payload_template(item: dict[str, Any], template: str) -> str:
    rendered = template
    for token in set(re.findall(r"\{([^{}]+)\}", template)):
        value = _stringify(_walk_path(item, token))
        rendered = rendered.replace(f"{{{token}}}", value)
    return rendered.strip()


def _normalize_alert_time_bucket(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if len(text) >= 16:
        return text[:16]
    return text


def _stable_event_id(normalized: dict[str, Any], item: dict[str, Any], index: int) -> tuple[str, str | None]:
    stable_fields = [
        _stringify(normalized.get("alert_source")),
        _stringify(normalized.get("alert_name")),
        _stringify(normalized.get("sip")),
        _stringify(normalized.get("dip")),
        _normalize_alert_time_bucket(_stringify(normalized.get("alert_time"))),
    ]
    stable_parts = [part for part in stable_fields if part]
    if len(stable_parts) >= 3:
        digest = sha1("||".join(stable_parts).encode("utf-8")).hexdigest()[:16]
        return f"STABLE-{digest}", "当前告警未提取到 eventIds，已回退为稳定字段组合指纹。建议尽快配置真正的唯一事件 ID。"

    for candidate in (
        "event_id",
        "eventId",
        "id",
        "alert_id",
        "alertId",
        "alarm_id",
        "alarmId",
        "uuid",
        "_id",
    ):
        candidate_value = _stringify(_walk_path(item, candidate))
        if candidate_value:
            digest = sha1(f"{candidate}:{candidate_value}".encode("utf-8")).hexdigest()[:16]
            return f"FALLBACK-{digest}", f"当前告警未提取到 eventIds，已回退为原始字段 {candidate} 的指纹。建议尽快配置真正的唯一事件 ID。"

    digest = sha1(_stringify(item).encode("utf-8")).hexdigest()[:12]
    return f"AUTO-{index + 1}-{digest}", "当前告警未提取到 eventIds，且缺少稳定候选字段，已退回整条记录哈希。可能导致重复建单风险。"


class AlertParserRuntime:
    def normalize(self, raw_payload: Any, parser_rule: Any) -> dict[str, Any]:
        rule, error = validate_and_prepare_parser_rule(parser_rule)
        if error:
            return {"error": error, "alerts": []}
        assert rule is not None
        source_items = _walk_path(raw_payload, rule["items_path"]) if rule["items_path"] else raw_payload
        if isinstance(source_items, dict):
            source_items = [source_items]
        if not isinstance(source_items, list):
            return {"error": "解析规则未命中告警数组，请检查 items_path。", "alerts": []}

        alerts: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, item in enumerate(source_items):
            if not isinstance(item, dict):
                continue
            normalized, warning = self._normalize_item(item, rule, index)
            if any(normalized.get(key) for key in ("eventIds", "alert_name", "sip", "dip", "payload")):
                alerts.append(normalized)
            if warning and warning not in warnings:
                warnings.append(warning)
        return {"count": len(alerts), "alerts": alerts, "warnings": warnings}

    def preview(self, raw_payload: Any, parser_rule: Any, limit: int = 3) -> dict[str, Any]:
        result = self.normalize(raw_payload, parser_rule)
        return {
            "count": result.get("count", 0),
            "alerts": list(result.get("alerts", []))[:limit],
            "error": result.get("error"),
            "warnings": list(result.get("warnings", [])),
        }

    def _normalize_item(self, item: dict[str, Any], rule: dict[str, Any], index: int) -> tuple[dict[str, Any], str | None]:
        field_mapping = rule["field_mapping"]
        defaults = rule["defaults"]
        payload_template = str(rule.get("payload_template", "")).strip()
        payload_fields = list(rule.get("payload_fields", []))

        normalized: dict[str, Any] = {}
        for target_field, source_path in field_mapping.items():
            if source_path:
                normalized[target_field] = _stringify(_walk_path(item, str(source_path)))
            else:
                normalized[target_field] = _stringify(defaults.get(target_field, ""))

        payload = _render_payload_template(item, payload_template) if payload_template else ""
        if not payload and payload_fields:
            payload = _join_payload_fields(item, payload_fields)
        if not payload:
            payload = _stringify(item)[:4000]
        normalized["payload"] = payload
        normalized["response_body"] = _stringify(item)[:4000]
        normalized["raw_data"] = item
        normalized["alert_source"] = normalized.get("alert_source") or _stringify(defaults.get("alert_source", "custom_alert_source"))
        warning: str | None = None
        if not normalized.get("eventIds"):
            normalized["eventIds"], warning = _stable_event_id(normalized, item, index)
        return normalized, warning

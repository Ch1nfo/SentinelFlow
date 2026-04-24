from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any
from uuid import uuid4

import requests
import urllib3

from sentinelflow.alerts.parser_runtime import AlertParserRuntime, parse_jsonish
from sentinelflow.config.runtime import (
    ALERT_SOURCE_SCRIPT_DIR,
    DEFAULT_ALERT_SOURCE_ID,
    PROJECT_ROOT,
    AlertSourceConfig,
    SentinelFlowRuntimeConfig,
    load_runtime_config,
)


def _build_headers(user_headers: Any) -> dict[str, str]:
    parsed = parse_jsonish(user_headers)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "SentinelFlow/1.0",
    }
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            if key:
                headers[str(key)] = str(value)
    return headers


def _build_payload(text: str) -> Any:
    parsed = parse_jsonish(text)
    return parsed if parsed is not None else (text.strip() or None)


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


def _normalize_script_alert(alert: dict[str, Any], index: int, batch_id: str) -> dict[str, Any]:
    event_ids = _stringify(alert.get("eventIds") or alert.get("event_ids") or alert.get("id"))
    normalized = {
        "eventIds": event_ids or f"SCRIPT-{batch_id}-{index + 1}",
        "alert_name": _stringify(alert.get("alert_name") or alert.get("alertName") or alert.get("title") or alert.get("name")),
        "sip": _stringify(alert.get("sip") or alert.get("source_ip") or alert.get("sourceIp")),
        "dip": _stringify(alert.get("dip") or alert.get("destination_ip") or alert.get("destinationIp")),
        "payload": _stringify(alert.get("payload")),
        "response_body": _stringify(alert.get("response_body") or alert.get("responseBody")),
        "alert_time": _stringify(alert.get("alert_time") or alert.get("alertTime") or alert.get("timestamp")),
        "alert_source": _stringify(alert.get("alert_source") or alert.get("alertSource")),
        "current_judgment": _stringify(alert.get("current_judgment") or alert.get("currentJudgment")),
        "history_judgment": _stringify(alert.get("history_judgment") or alert.get("historyJudgment")),
        "raw_data": alert.get("raw_data") if isinstance(alert.get("raw_data"), dict) else dict(alert),
    }
    if not normalized["payload"]:
        normalized["payload"] = _stringify(alert)[:4000]
    if not normalized["response_body"]:
        normalized["response_body"] = _stringify(alert)[:4000]
    if not normalized["alert_source"]:
        normalized["alert_source"] = "custom_script"
    return normalized


def _normalize_script_result(payload: Any, *, batch_id: str) -> dict[str, Any]:
    if isinstance(payload, list):
        alerts = payload
    elif isinstance(payload, dict):
        alerts = payload.get("alerts", [])
    else:
        raise ValueError("脚本输出必须是 JSON 对象或数组。")

    if not isinstance(alerts, list):
        raise ValueError("脚本输出中的 alerts 字段必须是数组。")

    normalized_alerts: list[dict[str, Any]] = []
    for index, item in enumerate(alerts):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_script_alert(item, index, batch_id)
        if any(normalized.get(key) for key in ("eventIds", "alert_name", "sip", "dip", "payload")):
            normalized_alerts.append(normalized)
    return {"count": len(normalized_alerts), "alerts": normalized_alerts}


def _read_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _read_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _iter_snapshot_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return candidates
    candidates.append(payload)
    for key in ("meta", "pagination", "page", "page_info", "pageInfo", "result", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    return candidates


def _has_pending_pagination(candidate: dict[str, Any]) -> bool:
    for key in ("has_more", "hasMore"):
        value = _read_bool(candidate.get(key))
        if value is True:
            return True
    for key in ("next", "next_page", "nextPage", "next_cursor", "nextCursor"):
        value = candidate.get(key)
        if value not in (None, "", False):
            return True
    return False


def _infer_snapshot_complete(raw_payload: Any, parsed_count: int) -> bool:
    if isinstance(raw_payload, list):
        return len(raw_payload) == parsed_count

    for candidate in _iter_snapshot_candidates(raw_payload):
        for key in ("snapshot_complete", "is_complete_snapshot"):
            value = _read_bool(candidate.get(key))
            if value is True and not _has_pending_pagination(candidate):
                return True
        for key in ("total_count", "total", "totalCount", "count_total"):
            total = _read_int(candidate.get(key))
            if total is not None and total == parsed_count and not _has_pending_pagination(candidate):
                return True
    return False


class SOCAlertApiClient:
    """Fetches alerts from a single configured alert source and normalizes them."""

    def __init__(self, timeout: int | None = None) -> None:
        self.timeout = timeout
        self.parser_runtime = AlertParserRuntime()

    def _default_source(self, runtime: Any) -> Any:
        sources = getattr(runtime, "alert_sources", None)
        if isinstance(sources, list) and sources:
            return sources[0]
        return runtime

    def _source_name(self, source: Any) -> str:
        return str(getattr(source, "name", "") or "默认告警源").strip() or "默认告警源"

    def _source_id(self, source: Any) -> str:
        return str(getattr(source, "id", "") or DEFAULT_ALERT_SOURCE_ID).strip() or DEFAULT_ALERT_SOURCE_ID

    def _attach_source_metadata(self, result: dict[str, Any], source: Any) -> dict[str, Any]:
        source_id = self._source_id(source)
        source_name = self._source_name(source)
        alerts = result.get("alerts")
        if isinstance(alerts, list):
            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                alert["alert_source_id"] = source_id
                alert["alert_source_name"] = source_name
                if not str(alert.get("alert_source", "")).strip():
                    alert["alert_source"] = source_name
        result["source_id"] = source_id
        result["source_name"] = source_name
        return result

    def fetch_open_alerts(self, source: AlertSourceConfig | None = None) -> dict[str, Any]:
        config = load_runtime_config()
        active_source = source or self._default_source(config)
        if config.demo_mode:
            return self._attach_source_metadata(self._demo_alerts(), active_source)
        if not getattr(active_source, "alert_source_enabled", False):
            return {"error": "当前未启用告警接入配置。"}
        if getattr(active_source, "alert_source_type", "api") == "script":
            fetched = self.fetch_script_alerts(active_source)
            if "error" in fetched:
                if config.demo_fallback:
                    return self._attach_source_metadata(self._demo_alerts(error=str(fetched["error"])), active_source)
                return fetched
            return self._attach_source_metadata(fetched, active_source)

        if not getattr(active_source, "alert_source_url", ""):
            return {"error": "当前未配置告警接入 URL。"}
        if not getattr(active_source, "alert_parser_rule", {}):
            return {"error": "当前还没有保存告警解析规则。"}

        try:
            fetched = self.fetch_raw_alert_payload(active_source, config)
        except TypeError:
            fetched = self.fetch_raw_alert_payload(active_source)
        if "error" in fetched:
            if config.demo_fallback:
                return self._attach_source_metadata(self._demo_alerts(error=str(fetched["error"])), active_source)
            return fetched
        parsed = self.parser_runtime.normalize(fetched.get("raw_payload"), getattr(active_source, "alert_parser_rule", {}))
        if parsed.get("error"):
            return {
                "error": parsed["error"],
                "raw_payload": fetched.get("raw_payload"),
            }
        parsed_count = int(parsed.get("count", 0) or 0)
        result = {
            "count": parsed_count,
            "alerts": parsed.get("alerts", []),
            "raw_payload": fetched.get("raw_payload"),
            "snapshot_complete": _infer_snapshot_complete(fetched.get("raw_payload"), parsed_count),
        }
        return self._attach_source_metadata(result, active_source)

    def fetch_raw_alert_payload(
        self,
        config: AlertSourceConfig | SentinelFlowRuntimeConfig | None = None,
        runtime_config: SentinelFlowRuntimeConfig | None = None,
    ) -> dict[str, Any]:
        runtime = runtime_config or load_runtime_config()
        source = config or self._default_source(runtime)
        if not runtime.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        effective_timeout = self.timeout or getattr(source, "alert_source_timeout", 15)
        method = str(getattr(source, "alert_source_method", "GET")).strip().upper() or "GET"
        query = _build_payload(getattr(source, "alert_source_query", ""))
        body = _build_payload(getattr(source, "alert_source_body", ""))
        headers = _build_headers(getattr(source, "alert_source_headers", ""))
        try:
            response = requests.request(
                method,
                getattr(source, "alert_source_url", ""),
                params=query if isinstance(query, dict) else None,
                json=body if isinstance(body, (dict, list)) else None,
                data=body if isinstance(body, str) else None,
                headers=headers,
                timeout=effective_timeout,
                verify=runtime.verify_ssl,
            )
        except requests.exceptions.Timeout:
            return {"error": f"请求超时（>{effective_timeout}s）：{getattr(source, 'alert_source_url', '')}"}
        except requests.exceptions.ConnectionError as exc:
            return {"error": f"网络连接失败：{exc}"}
        except requests.exceptions.RequestException as exc:
            return {"error": f"HTTP 请求异常：{exc}"}

        if response.status_code >= 400:
            return {"error": f"接口返回异常状态码（{response.status_code}）", "raw_response": response.text[:2000]}

        try:
            payload = response.json()
        except json.JSONDecodeError:
            return {"error": "接口响应无法解析为 JSON", "raw_response": response.text[:2000]}
        return {"raw_payload": payload, "status_code": response.status_code}

    def preview_parse(self, raw_payload: Any, parser_rule: Any) -> dict[str, Any]:
        return self.parser_runtime.preview(raw_payload, parser_rule)

    def fetch_script_alerts(self, config: AlertSourceConfig | SentinelFlowRuntimeConfig | None = None) -> dict[str, Any]:
        runtime = config or self._default_source(load_runtime_config())
        code = str(getattr(runtime, "alert_script_code", "")).strip()
        if not code:
            return {"error": "当前未配置告警接入脚本。"}

        try:
            ALERT_SOURCE_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
            safe_source_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", self._source_id(runtime)) or DEFAULT_ALERT_SOURCE_ID
            script_path = ALERT_SOURCE_SCRIPT_DIR / f"{safe_source_id}_custom_fetch.py"
            script_path.write_text(code + ("" if code.endswith("\n") else "\n"), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=self.timeout or getattr(runtime, "alert_script_timeout", 30),
            )
        except subprocess.TimeoutExpired:
            return {"error": f"脚本执行超时（>{self.timeout or getattr(runtime, 'alert_script_timeout', 30)}s）。"}
        except OSError as exc:
            return {"error": f"脚本执行失败：{exc}"}

        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            return {"error": f"脚本执行失败（退出码 {completed.returncode}）：{stderr or '无错误输出'}"}

        stdout = completed.stdout.strip()
        if not stdout:
            return {"error": "脚本没有输出任何内容，请向 stdout 打印标准 JSON。"}

        try:
            decoded = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return {"error": f"脚本 stdout 不是合法 JSON：{exc}"}

        batch_id = uuid4().hex[:12].upper()
        try:
            normalized = _normalize_script_result(decoded, batch_id=batch_id)
        except ValueError as exc:
            return {"error": str(exc)}
        return {
            **normalized,
            "batch_id": batch_id,
            "raw_payload": decoded,
            "snapshot_complete": True,
        }

    def _demo_alerts(self, error: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"count": 0, "alerts": [], "demo_mode": True, "snapshot_complete": True}
        if error:
            result["demo_mode"] = False
            result["fallback_triggered"] = True
            result["fallback_reason"] = error
        return result

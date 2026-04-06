from __future__ import annotations

import json
from typing import Any

import requests
import urllib3

from sentinelflow.alerts.parser_runtime import AlertParserRuntime, parse_jsonish
from sentinelflow.config.runtime import SentinelFlowRuntimeConfig, load_runtime_config


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


class SOCAlertApiClient:
    """Fetches alerts from a single configured alert source and normalizes them."""

    def __init__(self, timeout: int | None = None) -> None:
        self.timeout = timeout
        self.parser_runtime = AlertParserRuntime()

    def fetch_open_alerts(self) -> dict[str, Any]:
        config = load_runtime_config()
        if config.demo_mode:
            return self._demo_alerts()
        if not config.alert_source_enabled:
            return {"error": "当前未启用告警接入配置。"}
        if not config.alert_source_url:
            return {"error": "当前未配置告警接入 URL。"}
        if not config.alert_parser_rule:
            return {"error": "当前还没有保存告警解析规则。"}

        fetched = self.fetch_raw_alert_payload(config)
        if "error" in fetched:
            if config.demo_fallback:
                return self._demo_alerts(error=str(fetched["error"]))
            return fetched
        parsed = self.parser_runtime.normalize(fetched.get("raw_payload"), config.alert_parser_rule)
        if parsed.get("error"):
            return {
                "error": parsed["error"],
                "raw_payload": fetched.get("raw_payload"),
            }
        return {
            "count": parsed.get("count", 0),
            "alerts": parsed.get("alerts", []),
            "raw_payload": fetched.get("raw_payload"),
        }

    def fetch_raw_alert_payload(self, config: SentinelFlowRuntimeConfig | None = None) -> dict[str, Any]:
        runtime = config or load_runtime_config()
        if not runtime.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        effective_timeout = self.timeout or runtime.alert_source_timeout
        method = runtime.alert_source_method.strip().upper() or "GET"
        query = _build_payload(runtime.alert_source_query)
        body = _build_payload(runtime.alert_source_body)
        headers = _build_headers(runtime.alert_source_headers)
        try:
            response = requests.request(
                method,
                runtime.alert_source_url,
                params=query if isinstance(query, dict) else None,
                json=body if isinstance(body, (dict, list)) else None,
                data=body if isinstance(body, str) else None,
                headers=headers,
                timeout=effective_timeout,
                verify=runtime.verify_ssl,
            )
        except requests.exceptions.Timeout:
            return {"error": f"请求超时（>{effective_timeout}s）：{runtime.alert_source_url}"}
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

    def _demo_alerts(self, error: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"count": 0, "alerts": [], "demo_mode": True}
        if error:
            result["demo_mode"] = False
            result["fallback_triggered"] = True
            result["fallback_reason"] = error
        return result

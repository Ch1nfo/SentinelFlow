from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / ".sentinelflow"
CONFIG_PATH = CONFIG_DIR / "runtime.json"
ALERT_SOURCE_SCRIPT_DIR = CONFIG_DIR / "alert_sources"
ALERT_SOURCE_SCRIPT_PATH = ALERT_SOURCE_SCRIPT_DIR / "custom_fetch.py"


def _read_bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_env_bool(name: str, default: bool = False) -> bool:
    return _read_bool_value(os.getenv(name), default)


def _normalize_alert_source_type(value: Any) -> str:
    normalized = str(value or "api").strip().lower()
    return normalized if normalized in {"api", "script"} else "api"


@dataclass(frozen=True, slots=True)
class SentinelFlowRuntimeConfig:
    demo_mode: bool
    demo_fallback: bool
    verify_ssl: bool
    agent_enabled: bool
    llm_api_base_url: str
    llm_api_key: str
    llm_model: str
    llm_temperature: float
    llm_timeout: int
    alert_source_enabled: bool
    alert_source_type: str
    alert_source_url: str
    alert_source_method: str
    alert_source_headers: str
    alert_source_query: str
    alert_source_body: str
    alert_source_timeout: int
    alert_source_sample_payload: str
    alert_parser_rule: dict[str, Any]
    alert_script_code: str
    alert_script_timeout: int
    poll_interval_seconds: int


def _default_values() -> dict[str, Any]:
    return {
        "demo_mode": _read_env_bool("SENTINELFLOW_DEMO_MODE", True),
        "demo_fallback": _read_env_bool("SENTINELFLOW_DEMO_FALLBACK", True),
        "verify_ssl": _read_env_bool("SENTINELFLOW_VERIFY_SSL", True),
        "agent_enabled": _read_env_bool("SENTINELFLOW_AGENT_ENABLED", True),
        "llm_api_base_url": os.getenv("SENTINELFLOW_LLM_API_BASE_URL", "https://api.openai.com/v1").strip(),
        "llm_api_key": os.getenv("SENTINELFLOW_LLM_API_KEY", "").strip(),
        "llm_model": os.getenv("SENTINELFLOW_LLM_MODEL", "").strip(),
        "llm_temperature": float(os.getenv("SENTINELFLOW_LLM_TEMPERATURE", "0")),
        "llm_timeout": int(os.getenv("SENTINELFLOW_LLM_TIMEOUT", "60")),
        "alert_source_enabled": _read_env_bool("SENTINELFLOW_ALERT_SOURCE_ENABLED", False),
        "alert_source_type": os.getenv("SENTINELFLOW_ALERT_SOURCE_TYPE", "api").strip().lower() or "api",
        "alert_source_url": os.getenv("SENTINELFLOW_ALERT_SOURCE_URL", "").strip(),
        "alert_source_method": os.getenv("SENTINELFLOW_ALERT_SOURCE_METHOD", "GET").strip().upper(),
        "alert_source_headers": os.getenv("SENTINELFLOW_ALERT_SOURCE_HEADERS", "").strip(),
        "alert_source_query": os.getenv("SENTINELFLOW_ALERT_SOURCE_QUERY", "").strip(),
        "alert_source_body": os.getenv("SENTINELFLOW_ALERT_SOURCE_BODY", "").strip(),
        "alert_source_timeout": int(os.getenv("SENTINELFLOW_ALERT_SOURCE_TIMEOUT", "15")),
        "alert_source_sample_payload": os.getenv("SENTINELFLOW_ALERT_SOURCE_SAMPLE_PAYLOAD", "").strip(),
        "alert_parser_rule": {},
        "alert_script_code": os.getenv("SENTINELFLOW_ALERT_SCRIPT_CODE", "").strip(),
        "alert_script_timeout": int(os.getenv("SENTINELFLOW_ALERT_SCRIPT_TIMEOUT", "30")),
        "poll_interval_seconds": int(os.getenv("SENTINELFLOW_POLL_INTERVAL_SECONDS", "60")),
    }


def _normalize_config(values: dict[str, Any]) -> SentinelFlowRuntimeConfig:
    return SentinelFlowRuntimeConfig(
        demo_mode=_read_bool_value(values.get("demo_mode"), True),
        demo_fallback=_read_bool_value(values.get("demo_fallback"), True),
        verify_ssl=_read_bool_value(values.get("verify_ssl"), True),
        agent_enabled=_read_bool_value(values.get("agent_enabled"), True),
        llm_api_base_url=str(values.get("llm_api_base_url", "")).strip() or "https://api.openai.com/v1",
        llm_api_key=str(values.get("llm_api_key", "")).strip(),
        llm_model=str(values.get("llm_model", "")).strip(),
        llm_temperature=float(values.get("llm_temperature", 0)),
        llm_timeout=int(values.get("llm_timeout", 60)),
        alert_source_enabled=_read_bool_value(values.get("alert_source_enabled"), False),
        alert_source_type=_normalize_alert_source_type(values.get("alert_source_type", "api")),
        alert_source_url=str(values.get("alert_source_url", "")).strip(),
        alert_source_method=str(values.get("alert_source_method", "GET")).strip().upper() or "GET",
        alert_source_headers=str(values.get("alert_source_headers", "")).strip(),
        alert_source_query=str(values.get("alert_source_query", "")).strip(),
        alert_source_body=str(values.get("alert_source_body", "")).strip(),
        alert_source_timeout=int(values.get("alert_source_timeout", 15)),
        alert_source_sample_payload=str(values.get("alert_source_sample_payload", "")).strip(),
        alert_parser_rule=values.get("alert_parser_rule", {}) if isinstance(values.get("alert_parser_rule", {}), dict) else {},
        alert_script_code=str(values.get("alert_script_code", "")),
        alert_script_timeout=int(values.get("alert_script_timeout", 30)),
        poll_interval_seconds=int(values.get("poll_interval_seconds", 60)),
    )


def read_persisted_runtime_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_runtime_config() -> SentinelFlowRuntimeConfig:
    merged = _default_values()
    merged.update(read_persisted_runtime_config())
    return _normalize_config(merged)


def save_runtime_config(values: dict[str, Any]) -> SentinelFlowRuntimeConfig:
    current = _default_values()
    current.update(read_persisted_runtime_config())
    current.update(values)
    normalized = _normalize_config(current)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(normalized), ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def reset_runtime_config() -> SentinelFlowRuntimeConfig:
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    return load_runtime_config()


def should_use_demo_mode() -> bool:
    return load_runtime_config().demo_mode

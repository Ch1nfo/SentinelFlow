from typing import Any
from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from sentinelflow.api.schemas import RuntimeConfigRequest, AlertSourceParserGenerateRequest, AlertSourceParserPreviewRequest
from sentinelflow.config.runtime import _normalize_config, load_runtime_config, read_persisted_runtime_config, reset_runtime_config, save_runtime_config
from sentinelflow.api.deps import agent_service, branding, audit_service, polling_service, alert_parser_generator, _serialize, auto_execution_service
from sentinelflow.alerts.client import SOCAlertApiClient
from sentinelflow.alerts.parser_runtime import parse_jsonish
from sentinelflow.api.utils import VISIBLE_RUNTIME_OVERRIDE_KEYS

router = APIRouter(prefix="/api/sentinelflow")


def _serialize_alert_source(source) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "enabled": source.alert_source_enabled,
        "type": source.alert_source_type,
        "url": source.alert_source_url,
        "method": source.alert_source_method,
        "headers": source.alert_source_headers,
        "query": source.alert_source_query,
        "body": source.alert_source_body,
        "timeout": source.alert_source_timeout,
        "sample_payload": source.alert_source_sample_payload,
        "parser_rule": source.alert_parser_rule,
        "parser_configured": bool(source.alert_parser_rule),
        "script_code": source.alert_script_code,
        "script_timeout": source.alert_script_timeout,
        "auto_execute_enabled": source.auto_execute_enabled,
        "poll_interval_seconds": str(source.poll_interval_seconds),
        "failed_retry_interval_seconds": str(source.failed_retry_interval_seconds),
        "analysis_prompt": source.analysis_prompt,
    }

@router.get("/health")
def health() -> dict[str, Any]:
    runtime_config = load_runtime_config()
    agent_available, _ = agent_service.is_available()
    return {
        "name": branding.api_title,
        "status": "ok",
        "demo_mode": runtime_config.demo_mode,
        "agent_enabled": runtime_config.agent_enabled,
        "agent_configured": agent_service.is_configured(),
        "agent_available": agent_available,
    }


@router.get("/audit/events")
def list_audit_events() -> dict[str, Any]:
    return {"events": [_serialize(event) for event in audit_service.list_events()]}


@router.get("/runtime/settings")
def runtime_settings() -> dict[str, Any]:
    runtime_config = load_runtime_config()
    persisted_config = {
        key: value
        for key, value in read_persisted_runtime_config().items()
        if key in VISIBLE_RUNTIME_OVERRIDE_KEYS
    }
    agent_available, agent_reason = agent_service.is_available()
    alert_sources = [_serialize_alert_source(source) for source in runtime_config.alert_sources]
    primary_source = runtime_config.alert_sources[0]
    return {
        "branding": {
            "product_name": branding.product_name,
            "console_title": branding.console_title,
        },
        "runtime": {
            "poll_interval_seconds": str(runtime_config.poll_interval_seconds),
            "failed_retry_interval_seconds": str(runtime_config.failed_retry_interval_seconds),
            "workflow_engine": branding.workflow_engine_label,
            "agent_enabled": runtime_config.agent_enabled,
            "auto_execute_enabled": runtime_config.auto_execute_enabled,
            "weekly_alert_cleanup_enabled": runtime_config.weekly_alert_cleanup_enabled,
        },
        "llm": {
            "api_base_url": runtime_config.llm_api_base_url,
            "api_key": "",
            "api_key_configured": bool(runtime_config.llm_api_key),
            "model": runtime_config.llm_model,
            "temperature": runtime_config.llm_temperature,
            "timeout": runtime_config.llm_timeout,
            "agent_configured": agent_service.is_configured(),
            "agent_available": agent_available,
            "agent_unavailable_reason": agent_reason or "",
        },
        "alert_source": {
            **_serialize_alert_source(primary_source),
        },
        "alert_sources": alert_sources,
        "default_alert_source_id": primary_source.id,
        "features": {
            "natural_language_dispatch": True,
            "alert_polling": runtime_config.alert_source_enabled,
            "hybrid_skills": True,
            "audit_timeline": True,
            "agent_runtime": True,
        },
        "persisted_overrides": persisted_config,
    }

@router.post("/runtime/settings")
def save_settings(payload: RuntimeConfigRequest) -> dict[str, Any]:
    current = load_runtime_config()
    next_payload = payload.to_payload()
    if not payload.llm_api_key:
        next_payload["llm_api_key"] = current.llm_api_key
    save_runtime_config(next_payload)
    polling_service.refresh_schedule()
    auto_execution_service.apply_persisted_state()
    return runtime_settings()


@router.post("/runtime/settings/reset")
def reset_settings() -> dict[str, Any]:
    reset_runtime_config()
    polling_service.refresh_schedule()
    auto_execution_service.apply_persisted_state()
    return runtime_settings()


@router.post("/runtime/settings/alert-source/test-fetch")
def test_alert_source_fetch(payload: RuntimeConfigRequest) -> dict[str, Any]:
    current = load_runtime_config()
    payload_values = payload.to_payload()
    merged_values = {
        **asdict(current),
        **payload_values,
    }
    if "alert_sources" not in payload_values:
        merged_values["alert_sources"] = [
            {
                "id": current.alert_sources[0].id if current.alert_sources else "default",
                "name": current.alert_sources[0].name if current.alert_sources else "默认告警源",
                "alert_source_enabled": merged_values.get("alert_source_enabled"),
                "alert_source_type": merged_values.get("alert_source_type"),
                "alert_source_url": merged_values.get("alert_source_url"),
                "alert_source_method": merged_values.get("alert_source_method"),
                "alert_source_headers": merged_values.get("alert_source_headers"),
                "alert_source_query": merged_values.get("alert_source_query"),
                "alert_source_body": merged_values.get("alert_source_body"),
                "alert_source_timeout": merged_values.get("alert_source_timeout"),
                "alert_source_sample_payload": merged_values.get("alert_source_sample_payload"),
                "alert_parser_rule": merged_values.get("alert_parser_rule"),
                "alert_script_code": merged_values.get("alert_script_code"),
                "alert_script_timeout": merged_values.get("alert_script_timeout"),
                "auto_execute_enabled": merged_values.get("auto_execute_enabled"),
                "poll_interval_seconds": merged_values.get("poll_interval_seconds"),
                "failed_retry_interval_seconds": merged_values.get("failed_retry_interval_seconds"),
            }
        ]
    temp_config = _normalize_config(merged_values)
    temp_source = temp_config.alert_sources[0]
    client = SOCAlertApiClient()
    if temp_source.alert_source_type == "script":
        result = client.fetch_script_alerts(temp_source)
    else:
        result = client.fetch_raw_alert_payload(temp_source, temp_config)
    if "error" in result:
        raise HTTPException(status_code=400, detail=str(result["error"]))
    return result


@router.post("/runtime/settings/alert-source/generate-parser")
def generate_alert_source_parser(payload: AlertSourceParserGenerateRequest) -> dict[str, Any]:
    try:
        generated = alert_parser_generator.generate(payload.sample_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raw_sample = parse_jsonish(payload.sample_payload)
    preview = polling_service.client.preview_parse(raw_sample, generated.get("parser_rule"))
    return {
        **generated,
        "preview": preview,
    }


@router.post("/runtime/settings/alert-source/test-parse")
def test_alert_source_parse(payload: AlertSourceParserPreviewRequest) -> dict[str, Any]:
    raw_sample = parse_jsonish(payload.sample_payload)
    if raw_sample is None:
        raise HTTPException(status_code=400, detail="告警样本不是合法 JSON。")
    parser_rule = payload.parser_rule or load_runtime_config().alert_parser_rule
    if not parser_rule:
        raise HTTPException(status_code=400, detail="当前还没有可用的告警解析规则。")
    preview = polling_service.client.preview_parse(raw_sample, parser_rule)
    if preview.get("error"):
        raise HTTPException(status_code=400, detail=str(preview["error"]))
    return preview

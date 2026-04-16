import json
import re
import queue
import threading
import time
from typing import Any
from uuid import uuid4
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sentinelflow.agent.registry import list_agent_definitions
from sentinelflow.api.schemas import CommandDispatchRequest, AlertActionRequest
from sentinelflow.api.deps import agent_service, dispatch_service, audit_service, polling_service, skill_runtime, _serialize, auto_execution_service, task_runner_service, WORKFLOW_ROOT, AGENT_ROOT
from sentinelflow.api.utils import _extract_alert_payload, _resolve_task
from sentinelflow.config.runtime import load_runtime_config, save_runtime_config

router = APIRouter(prefix="/api/sentinelflow")

active_command_cancellations: dict[str, threading.Event] = {}
active_command_lock = threading.Lock()


def _is_successful_ban_action(action_name: str, payload: dict[str, Any]) -> bool:
    normalized_name = action_name.lower().strip()
    if "ban" not in normalized_name:
        return False
    if bool(payload.get("error")):
        return False
    success_value = payload.get("success")
    if isinstance(success_value, bool):
        return success_value
    status_value = str(payload.get("status", "")).strip().lower()
    if status_value in {"fail", "failed", "error"}:
        return False
    return True


def _extract_ban_ip(payload: dict[str, Any]) -> str:
    for candidate in ("ban_ip", "banned_ip", "blocked_ip", "ip", "source_ip", "sip"):
        value = str(payload.get(candidate, "")).strip()
        if value:
            return value
    return ""


def _collect_banned_ips_from_result(result: dict[str, Any]) -> set[str]:
    banned_ips: set[str] = set()
    final_facts = result.get("final_facts")
    if isinstance(final_facts, dict):
        disposal = final_facts.get("disposal", {})
        if isinstance(disposal, dict):
            actions = disposal.get("actions", [])
            if isinstance(actions, list):
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    if str(action.get("kind", "")).strip() != "ban_ip" or not bool(action.get("success")):
                        continue
                    banned_ip = str(action.get("target", "")).strip()
                    if banned_ip:
                        banned_ips.add(banned_ip)
            if banned_ips:
                return banned_ips
    aggregated_action_steps = result.get("aggregated_action_steps")
    if isinstance(aggregated_action_steps, list):
        for step in aggregated_action_steps:
            if not isinstance(step, dict):
                continue
            skill_name = str(step.get("skill_name", "")).strip()
            payload = step.get("result", {})
            if not isinstance(payload, dict):
                continue
            if not _is_successful_ban_action(skill_name, payload):
                continue
            banned_ip = _extract_ban_ip(payload)
            if banned_ip:
                banned_ips.add(banned_ip)
        if banned_ips:
            return banned_ips
    actions = result.get("actions")
    if isinstance(actions, dict):
        for action_name, item in actions.items():
            if not isinstance(item, dict):
                continue
            if not _is_successful_ban_action(str(action_name), item):
                continue
            banned_ip = _extract_ban_ip(item)
            if banned_ip:
                banned_ips.add(banned_ip)
    return banned_ips


def _resolve_result_disposition(result: dict[str, Any]) -> str:
    final_facts = result.get("final_facts")
    if isinstance(final_facts, dict):
        judgment = final_facts.get("judgment", {})
        if isinstance(judgment, dict):
            value = str(judgment.get("disposition", "")).strip()
            if value:
                return value
    return str(result.get("disposition", "")).strip() or "unknown"


def _resolve_task_outcome_status(task, result: dict[str, Any]) -> str:
    final_facts = result.get("final_facts")
    if isinstance(final_facts, dict):
        outcome = final_facts.get("task_outcome", {})
        if isinstance(outcome, dict):
            value = str(outcome.get("status", "")).strip()
            if value:
                return value
    return str(task.status or "").strip()


def _dashboard_summary() -> dict[str, Any]:
    tasks = dispatch_service.list_tasks()
    agents = [
        agent
        for agent in list_agent_definitions(AGENT_ROOT, include_system_primary=True)
        if agent.enabled and agent.role == "worker"
    ]
    dispositions = {
        "business_trigger": 0,
        "false_positive": 0,
        "true_attack": 0,
        "unknown": 0,
    }
    closed_success = 0
    disposed_success = 0
    manual_completed = 0
    banned_ips: set[str] = set()
    recent_results: list[dict[str, Any]] = []

    for task in tasks:
        result = task.last_result_data if isinstance(task.last_result_data, dict) else {}
        disposition = _resolve_result_disposition(result)
        if disposition not in dispositions:
            disposition = "unknown"
        dispositions[disposition] += 1
        task_outcome_status = _resolve_task_outcome_status(task, result)
        if task_outcome_status == "succeeded":
            if task.last_action == "triage_close":
                closed_success += 1
            if task.last_action == "triage_dispose":
                disposed_success += 1
        if task_outcome_status == "completed":
            manual_completed += 1

        banned_ips.update(_collect_banned_ips_from_result(result))

        if len(recent_results) < 8 and result:
            recent_results.append(
                {
                    "task_id": task.task_id,
                    "event_ids": task.event_ids,
                    "title": task.title,
                    "status": task.status,
                    "last_action": task.last_action,
                    "disposition": disposition,
                }
            )

    return {
        "totals": {
            "tasks": len(tasks),
            "queued": len([task for task in tasks if task.status == "queued"]),
            "running": len([task for task in tasks if task.status == "running"]),
            "succeeded": len([task for task in tasks if task.status == "succeeded"]),
            "failed": len([task for task in tasks if task.status == "failed"]),
            "audit_events": len(audit_service.list_events()),
            "skills": len(skill_runtime.list_skills()),
            "workflows": len(list(WORKFLOW_ROOT.glob("*/workflow.json"))) if WORKFLOW_ROOT.is_dir() else 0,
            "agents": len(agents),
        },
        "judgment": dispositions,
        "operations": {
            "closed_success": closed_success,
            "disposed_success": disposed_success,
            "manual_completed": manual_completed,
            "banned_ip_count": len(banned_ips),
            "banned_ips": sorted(banned_ips),
        },
        "recent_results": recent_results,
    }


@router.get("/dashboard/summary")
def dashboard_summary() -> dict[str, Any]:
    summary = _dashboard_summary()
    summary["automation"] = auto_execution_service.state()
    return summary


@router.get("/alerts/poll")
async def poll_alerts() -> dict[str, Any]:
    result = await polling_service.poll_once()
    auto_state = auto_execution_service.state()
    result.auto_execute_enabled = auto_state["enabled"]
    result.auto_execute_running = auto_state["running"]
    return _serialize(result)


@router.get("/alerts/state")
def alerts_state() -> dict[str, Any]:
    result = polling_service.get_latest_result()
    auto_state = auto_execution_service.state()
    result.auto_execute_enabled = auto_state["enabled"]
    result.auto_execute_running = auto_state["running"]
    return _serialize(result)



@router.post("/alerts/handle")
async def handle_alert(payload: AlertActionRequest) -> dict[str, Any]:
    alert = _extract_alert_payload(payload)
    event_ids = str(alert.get("eventIds", "")).strip()
    task = _resolve_task(payload)
    task_id = task.task_id if task else ""

    if payload.action == "refresh_poll":
        result = await polling_service.poll_once()
        return {
            "action": payload.action,
            "success": not result.errors,
            "task_id": task_id,
            "event_ids": event_ids,
            "data": _serialize(result),
            "error": result.errors[0] if result.errors else None,
        }

    if payload.action == "auto_run_pending":
        results = []
        for queued_task in dispatch_service.list_tasks():
            if queued_task.status != "queued":
                continue
            results.append(_serialize(await task_runner_service.run_task(queued_task)))
        return {
            "action": payload.action,
            "success": all(item.get("success", False) for item in results) if results else True,
            "task_id": "",
            "event_ids": "",
            "data": {"results": results, "count": len(results)},
            "task": None,
            "error": None,
        }

    if payload.action == "auto_execute_start":
        save_runtime_config({"auto_execute_enabled": True})
        auto_execution_service.enable()
        return {
            "action": payload.action,
            "success": True,
            "task_id": "",
            "event_ids": "",
            "data": {"auto_execution": auto_execution_service.state()},
            "task": None,
            "error": None,
        }

    if payload.action == "auto_execute_stop":
        save_runtime_config({"auto_execute_enabled": False})
        auto_execution_service.disable()
        return {
            "action": payload.action,
            "success": True,
            "task_id": "",
            "event_ids": "",
            "data": {"auto_execution": auto_execution_service.state()},
            "task": None,
            "error": None,
        }

    if payload.action == "retry_task":
        if not task:
            return {
                "action": payload.action,
                "success": False,
                "error": "未找到待重试任务。",
            }
        dispatch_service.prepare_retry(task.task_id)
        return _serialize(await task_runner_service.run_task(task))

    if not alert:
        return {"action": payload.action, "success": False, "error": "未提供可处理的告警上下文。"}

    if task:
        return _serialize(await task_runner_service.run_task(task, payload.action))

    return {"action": payload.action, "success": False, "error": "当前动作需要绑定任务上下文。"}

async def _dispatch_command_internal(
    payload: CommandDispatchRequest,
    cancel_event: threading.Event | None = None,
    status_callback=None,
) -> dict[str, Any]:
    if cancel_event is not None and cancel_event.is_set():
        return {"command_text": payload.command_text, "route": "stopped", "success": False, "data": {"interrupted": True}, "error": "已停止当前任务"}
    if not agent_service.is_configured(payload.agent_name):
        return {"command_text": payload.command_text, "route": "agent_not_configured", "success": False, "error": "当前未完成系统主 Agent 配置。"}
    available, reason = agent_service.is_available()
    if not available:
        return {"command_text": payload.command_text, "route": "agent_runtime_unavailable", "success": False, "error": f"当前 Agent Runtime 不可用：{reason}"}

    try:
        agent_data = await agent_service.run_command(payload.command_text, payload.history or [], cancel_event=cancel_event, agent_name=payload.agent_name, status_callback=status_callback)
        return {"command_text": payload.command_text, "route": "agent_dispatch", "success": True, "data": agent_data, "error": None}
    except Exception as exc:
        if cancel_event is not None and cancel_event.is_set():
            return {"command_text": payload.command_text, "route": "stopped", "success": False, "error": "已停止当前任务"}
        return {"command_text": payload.command_text, "route": "agent_dispatch_failed", "success": False, "error": f"主 Agent 执行失败：{exc}"}


def _build_stream_text(response: dict[str, Any]) -> str:
    data = response.get("data")
    data = data if isinstance(data, dict) else {}
    final_response = str(data.get("final_response", "")).strip()
    if final_response:
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"<think\b[^>]*>.*?</think>", "", final_response, flags=re.IGNORECASE | re.DOTALL)).strip()
    error = str(response.get("error", "")).strip()
    if error: return error
    return "命令已执行完成。"

def _stream_command_response(payload: CommandDispatchRequest):
    request_id = uuid4().hex
    cancel_event = threading.Event()
    with active_command_lock:
        active_command_cancellations[request_id] = cancel_event
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

    def run_dispatch() -> None:
        try:
            import asyncio
            response = asyncio.run(_dispatch_command_internal(payload, cancel_event=cancel_event, status_callback=lambda text: result_queue.put(("status", text))))
            result_queue.put(("response", response))
        except Exception as error:
            result_queue.put(("error", error))
        finally:
            with active_command_lock:
                active_command_cancellations.pop(request_id, None)

    worker = threading.Thread(target=run_dispatch, daemon=True)
    worker.start()

    yield f"data: {json.dumps({'type': 'request', 'payload': {'request_id': request_id}}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'type': 'status', 'payload': {'text': '正在建立会话...'}}, ensure_ascii=False)}\n\n"

    status_messages = [
        "正在分析输入内容...",
        "正在规划处理路径...",
        "正在调用所需能力...",
    ]
    status_index = 0
    last_status_at = 0.0
    last_custom_status_at = 0.0

    while True:
        if cancel_event.is_set():
            response = {"command_text": payload.command_text, "route": "stopped", "success": False, "error": "已停止当前任务"}
            break
        try:
            event_type, payload_data = result_queue.get(timeout=0.2)
            if event_type == "status":
                yield f"data: {json.dumps({'type': 'status', 'payload': {'text': str(payload_data)}}, ensure_ascii=False)}\n\n"
                last_custom_status_at = time.monotonic()
                continue
            if event_type == "error":
                raise payload_data
            response = payload_data
            break
        except queue.Empty:
            now = time.monotonic()
            if now - last_custom_status_at < 1.5:
                continue
            if now - last_status_at >= 0.6:
                yield f"data: {json.dumps({'type': 'status', 'payload': {'text': status_messages[min(status_index, len(status_messages) - 1)]}}, ensure_ascii=False)}\n\n"
                last_status_at = now
                if status_index < len(status_messages) - 1:
                    status_index += 1


    stream_text = _build_stream_text(response)
    yield f"data: {json.dumps({'type': 'meta', 'payload': {'route': response.get('route', ''), 'success': response.get('success', False)}}, ensure_ascii=False)}\n\n"
    chunk_size = 18
    for index in range(0, len(stream_text), chunk_size):
        yield f"data: {json.dumps({'type': 'delta', 'payload': {'text': stream_text[index:index + chunk_size]}}, ensure_ascii=False)}\n\n"
        time.sleep(0.03)
    yield f"data: {json.dumps({'type': 'done', 'payload': response}, ensure_ascii=False)}\n\n"

@router.post("/commands/stop")
def stop_command(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("request_id", "")).strip()
    if not request_id:
        return {"stopped": False, "error": "缺少 request_id"}
    with active_command_lock:
        cancel_event = active_command_cancellations.get(request_id)
    if cancel_event is None:
        return {"stopped": False, "error": "当前任务不存在或已结束"}
    cancel_event.set()
    return {"stopped": True, "request_id": request_id}

@router.post("/commands/dispatch")
async def dispatch_command(payload: CommandDispatchRequest) -> dict[str, Any]:
    return await _dispatch_command_internal(payload)

@router.post("/commands/stream")
def stream_command(payload: CommandDispatchRequest):
    return StreamingResponse(_stream_command_response(payload), media_type="text/event-stream")

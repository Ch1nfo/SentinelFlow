import json
import re
import queue
import threading
import time
from typing import Any
from uuid import uuid4
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sentinelflow.api.schemas import CommandDispatchRequest, AlertActionRequest
from sentinelflow.api.deps import agent_service, dispatch_service, audit_service, polling_service, skill_runtime, _serialize, WORKFLOW_ROOT
from sentinelflow.api.utils import _extract_alert_payload, _resolve_task
from sentinelflow.workflows.agent_workflow_registry import load_agent_workflow
from sentinelflow.workflows.agent_workflow_runner import SentinelFlowAgentWorkflowRunner
from sentinelflow.api.deps import agent_workflow_runner

router = APIRouter(prefix="/api/sentinelflow")

active_command_cancellations: dict[str, threading.Event] = {}
active_command_lock = threading.Lock()


def _dashboard_summary() -> dict[str, Any]:
    tasks = dispatch_service.list_tasks()
    dispositions = {
        "business_trigger": 0,
        "false_positive": 0,
        "true_attack": 0,
        "unknown": 0,
    }
    closed_success = 0
    disposed_success = 0
    banned_ips: set[str] = set()
    recent_results: list[dict[str, Any]] = []

    for task in tasks:
        result = task.last_result_data if isinstance(task.last_result_data, dict) else {}
        disposition = str(result.get("disposition", "")).strip() or "unknown"
        if disposition not in dispositions:
            disposition = "unknown"
        dispositions[disposition] += 1
        if task.last_result_success:
            if task.last_action == "triage_close":
                closed_success += 1
            if task.last_action == "triage_dispose":
                disposed_success += 1

        actions = result.get("actions")
        if isinstance(actions, dict):
            for item in actions.values():
                if isinstance(item, dict):
                    for candidate in ("name", "ban", "ip", "target_ip"):
                        value = str(item.get(candidate, "")).strip()
                        if value:
                            banned_ips.add(value)

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
        },
        "judgment": dispositions,
        "operations": {
            "closed_success": closed_success,
            "disposed_success": disposed_success,
            "banned_ip_count": len(banned_ips),
            "banned_ips": sorted(banned_ips),
        },
        "recent_results": recent_results,
    }


@router.get("/dashboard/summary")
def dashboard_summary() -> dict[str, Any]:
    return _dashboard_summary()


@router.get("/alerts/poll")
async def poll_alerts() -> dict[str, Any]:
    result = await polling_service.poll_once()
    return _serialize(result)


async def _run_task(task, action: str | None = None) -> dict[str, Any]:
    alert = {}
    if isinstance(task.payload, dict):
        payload_alert = task.payload.get("alert_data")
        if isinstance(payload_alert, dict):
            alert = payload_alert

    if not alert:
        task = dispatch_service.finalize_task(task.task_id, action or "unknown", False, {}, "任务缺少告警上下文。")
        return {
            "action": action or "unknown",
            "success": False,
            "task_id": task.task_id if task else "",
            "event_ids": "",
            "data": {},
            "task": _serialize(task) if task else None,
            "error": "任务缺少告警上下文。",
        }

    selected_action = action
    if not selected_action:
        if task.workflow_name == "agent_react":
            selected_action = "triage_close"
        else:
            try:
                workflow_definition = load_agent_workflow(WORKFLOW_ROOT, task.workflow_name)
                selected_action = workflow_definition.recommended_action
            except Exception:
                selected_action = "triage_close"

    dispatch_service.mark_task_running(task.task_id, selected_action)

    agent_available, _agent_error = agent_service.is_available()
    if task.workflow_name == "agent_react" and agent_service.is_configured() and agent_available:
        try:
            agent_result = await agent_service.run_alert(alert, selected_action)
            if bool(agent_result.get("success")):
                task = dispatch_service.finalize_task(task.task_id, selected_action, True, _serialize(agent_result), None)
                return {
                    "action": selected_action, "success": True,
                    "task_id": task.task_id if task else "",
                    "event_ids": str(agent_result.get("event_ids", "")).strip(),
                    "data": _serialize(agent_result), "task": _serialize(task) if task else None, "error": None,
                }
        except Exception as exc:
            audit_service.record("agent_react_task_failed", "Agent ReAct runtime failed.", {"error": str(exc)})

    if selected_action in {"triage_close", "triage_dispose"} and agent_service.is_configured() and agent_available:
        try:
            workflow_definition = load_agent_workflow(WORKFLOW_ROOT, task.workflow_name)
            agent_result = await agent_workflow_runner.run_alert_workflow(workflow_definition, alert, selected_action)
            if bool(agent_result.get("success")):
                task = dispatch_service.finalize_task(task.task_id, selected_action, True, _serialize(agent_result), None)
                return {
                    "action": selected_action, "success": True,
                    "task_id": task.task_id if task else "",
                    "event_ids": str(agent_result.get("event_ids", "")).strip(),
                    "data": _serialize(agent_result), "task": _serialize(task) if task else None, "error": None,
                }
        except FileNotFoundError:
            try:
                agent_result = await agent_service.run_alert(alert, selected_action)
                if bool(agent_result.get("success")):
                    task = dispatch_service.finalize_task(task.task_id, selected_action, True, _serialize(agent_result), None)
                    return {
                        "action": selected_action, "success": True,
                        "task_id": task.task_id if task else "",
                        "event_ids": str(agent_result.get("event_ids", "")).strip(),
                        "data": _serialize(agent_result), "task": _serialize(task) if task else None, "error": None,
                    }
            except Exception as exc:
                audit_service.record("agent_task_failed", f"Agent runtime failed during {selected_action}.", {"error": str(exc)})
        except Exception as exc:
            audit_service.record("agent_workflow_task_failed", f"Workflow failed during {selected_action}.", {"error": str(exc)})

    task = dispatch_service.finalize_task(task.task_id, selected_action, False, {}, "当前任务没有可用的 Agent Workflow，且主 Agent 处理未成功。")
    return {
        "action": selected_action, "success": False,
        "task_id": task.task_id if task else "",
        "event_ids": str(alert.get("eventIds", "")).strip(),
        "data": {}, "task": _serialize(task) if task else None,
        "error": "当前任务没有可用的 Agent Workflow，且主 Agent 处理未成功。",
    }



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
            results.append(await _run_task(queued_task))
        return {
            "action": payload.action,
            "success": all(item.get("success", False) for item in results) if results else True,
            "task_id": "",
            "event_ids": "",
            "data": {"results": results, "count": len(results)},
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
        return await _run_task(task)

    if not alert:
        return {"action": payload.action, "success": False, "error": "未提供可处理的告警上下文。"}

    if task:
        return await _run_task(task, payload.action)

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

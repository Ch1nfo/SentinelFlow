from __future__ import annotations

from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def serialize_graph_state(state: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in state.items():
        if key == "cancel_event":
            continue
        if key == "messages":
            payload[key] = _serialize_messages(value)
            continue
        payload[key] = _json_safe(value)
    return payload


def deserialize_graph_state(payload: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "messages":
            state[key] = _deserialize_messages(value)
            continue
        state[key] = value
    return state


def _serialize_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    try:
        from langchain_core.messages import messages_to_dict
    except ModuleNotFoundError:
        return []
    return messages_to_dict(messages)


def _deserialize_messages(payload: Any) -> list[Any]:
    if not isinstance(payload, list):
        return []
    try:
        from langchain_core.messages import messages_from_dict
    except ModuleNotFoundError:
        return []
    return messages_from_dict(payload)

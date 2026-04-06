from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AuditEvent:
    event_type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AuditService:
    """Collects runtime audit events for SentinelFlow operations."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            message=message,
            payload=payload or {},
        )
        self._events.append(event)
        return event

    def list_events(self) -> list[AuditEvent]:
        return list(self._events)

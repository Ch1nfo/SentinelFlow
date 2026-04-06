from __future__ import annotations

from sentinelflow.domain.errors import PolicyViolationError


def enforce_event_id_guard(context: dict) -> None:
    """Protect authoritative event identifiers during alert handling."""
    alert_data = context.get("alert_data") or {}
    authoritative = str(alert_data.get("eventIds", "")).strip()
    ref_value = str(context.get("event_id_ref", "")).strip()
    if ref_value and authoritative and ref_value != authoritative:
        raise PolicyViolationError(
            f"eventIds mismatch detected: event_id_ref={ref_value!r}, alert_data.eventIds={authoritative!r}"
        )


def append_manual_review_suffix(memo: str) -> str:
    suffix = " [Agent处置，请人工复核]"
    if suffix.strip() in memo:
        return memo
    return memo.rstrip() + suffix

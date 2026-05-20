"""High-level intervals.icu queries."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from tp_icu_sync.icu.client import IcuApiError, IcuClient
from tp_icu_sync.icu.models import IcuActivity, IcuEvent


def list_events(client: IcuClient, start: date, end: date) -> list[IcuEvent]:
    """Return all calendar events between start and end (inclusive)."""
    raw = client.get(
        f"/athlete/{client.athlete_id}/events",
        params={"oldest": start.isoformat(), "newest": end.isoformat()},
    )
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise IcuApiError(f"Unexpected icu events payload: {type(raw).__name__}")
    out: list[IcuEvent] = []
    for entry in raw:
        try:
            out.append(IcuEvent.model_validate(entry))
        except ValidationError as exc:
            raise IcuApiError(f"Failed to parse icu event {entry.get('id')}: {exc}") from exc
    return out


def create_event(client: IcuClient, payload: dict[str, Any]) -> IcuEvent:
    raw = client.post(f"/athlete/{client.athlete_id}/events", json=payload)
    if raw is None:
        raise IcuApiError("icu create_event returned no body.")
    return IcuEvent.model_validate(raw)


def update_event(client: IcuClient, event_id: int, payload: dict[str, Any]) -> IcuEvent:
    raw = client.put(f"/athlete/{client.athlete_id}/events/{event_id}", json=payload)
    if raw is None:
        # icu sometimes returns 204 on update; refetch.
        raw = client.get(f"/athlete/{client.athlete_id}/events/{event_id}")
    if raw is None:
        raise IcuApiError(f"icu update_event {event_id} returned no body.")
    return IcuEvent.model_validate(raw)


def delete_event(client: IcuClient, event_id: int) -> None:
    client.delete(f"/athlete/{client.athlete_id}/events/{event_id}")


def list_activities(client: IcuClient, start: date, end: date) -> list[IcuActivity]:
    """Return all activities between start and end."""
    raw = client.get(
        f"/athlete/{client.athlete_id}/activities",
        params={"oldest": start.isoformat(), "newest": end.isoformat()},
    )
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise IcuApiError(f"Unexpected icu activities payload: {type(raw).__name__}")
    out: list[IcuActivity] = []
    for entry in raw:
        try:
            out.append(IcuActivity.model_validate(entry))
        except ValidationError as exc:
            raise IcuApiError(f"Failed to parse icu activity {entry.get('id')}: {exc}") from exc
    return out


def update_activity(client: IcuClient, activity_id: str, payload: dict[str, Any]) -> None:
    """PUT a partial activity update."""
    client.put(f"/activity/{activity_id}", json=payload)

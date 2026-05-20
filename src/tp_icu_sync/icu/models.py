"""intervals.icu domain models (subset we use)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class IcuEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    start_date_local: str  # "2026-05-17T00:00:00"
    type: str | None = None  # "Ride", "Run", "Swim", "Workout", ...
    category: str | None = None  # "WORKOUT", "RACE", "NOTE", ...
    name: str | None = None
    description: str | None = None
    external_id: str | None = None
    moving_time: int | None = None  # seconds
    distance: float | None = None  # metres
    icu_training_load: float | None = None
    icu_intensity: float | None = None
    workout_doc: dict[str, Any] | None = None
    paired_activity_id: str | None = None


class IcuActivity(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str  # "i149818035"
    start_date_local: str
    type: str | None = None
    name: str | None = None
    description: str | None = None
    paired_event_id: int | None = None

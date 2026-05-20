"""High-level TP queries."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from tp_icu_sync.tp.client import TPApiError, TPClient
from tp_icu_sync.tp.models import TPWorkout


def list_planned_workouts(
    client: TPClient, start: date, end: date
) -> list[TPWorkout]:
    """Return planned (not completed) workouts in [start, end], inclusive."""
    athlete_id = client.athlete_id()
    endpoint = (
        f"/fitness/v6/athletes/{athlete_id}"
        f"/workouts/{start.isoformat()}/{end.isoformat()}"
    )
    raw = client.get(endpoint)
    if raw is None:
        return []
    items = raw["workouts"] if isinstance(raw, dict) and "workouts" in raw else raw
    if not isinstance(items, list):
        raise TPApiError(f"Unexpected TP workouts payload: {type(items).__name__}")

    result: list[TPWorkout] = []
    for entry in items:
        try:
            w = TPWorkout.model_validate(entry)
        except ValidationError as exc:
            raise TPApiError(f"Failed to parse TP workout {entry.get('workoutId')}: {exc}") from exc
        # Skip completed workouts — those become activities, owned by Garmin/Rouvy.
        if w.completed is True:
            continue
        result.append(w)
    return result

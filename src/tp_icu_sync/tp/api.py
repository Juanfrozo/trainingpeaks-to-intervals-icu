"""High-level TP queries."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from tp_icu_sync.tp.client import TPApiError, TPClient
from tp_icu_sync.tp.models import TPWorkout


def list_workouts(client: TPClient, start: date, end: date) -> list[TPWorkout]:
    """Return non-completed workouts in [start, end] inclusive.

    Includes everything TrainingPeaks gave us that isn't already marked as
    completed: planned sessions, Day-Off entries, races, notes — the caller
    decides what to do with each via classification.
    """
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
        # Completed workouts become activities, owned by Garmin/Rouvy.
        if w.completed is True:
            continue
        result.append(w)
    return result

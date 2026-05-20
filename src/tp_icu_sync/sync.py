"""Sync orchestration: diff TP planned workouts against icu events, then apply."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from tp_icu_sync.config import Config
from tp_icu_sync.icu.api import (
    create_event,
    delete_event,
    list_activities,
    list_events,
    update_activity,
    update_event,
)
from tp_icu_sync.icu.client import IcuApiError, IcuClient
from tp_icu_sync.icu.models import IcuEvent
from tp_icu_sync.mapping.sport import tp_sport_to_icu_type
from tp_icu_sync.mapping.structure import render_workout_doc, render_workout_text
from tp_icu_sync.tp.api import list_planned_workouts
from tp_icu_sync.tp.client import AthleteThresholds, TPClient
from tp_icu_sync.tp.models import TPWorkout

logger = logging.getLogger(__name__)

EXTERNAL_ID_PREFIX = "tp:"
HASH_TAG_RE = re.compile(r"\[tp-sync hash=([0-9a-f]{12})\]")


@dataclass
class SyncResult:
    created: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    deleted: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)
    activity_updates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated) + len(self.deleted) + len(self.unchanged)


def build_icu_payload(
    w: TPWorkout, thresholds: AthleteThresholds | None = None
) -> dict[str, Any]:
    """Translate a TP planned workout into an icu Event POST/PUT body."""
    sport_type = tp_sport_to_icu_type(w.workoutTypeValueId)
    workout_doc = render_workout_doc(w.structure, sport_type, thresholds)

    body_lines: list[str] = []
    if w.description:
        body_lines.append(w.description.strip())
    workout_text = render_workout_text(w.structure, sport_type, thresholds)
    if workout_text:
        if body_lines:
            body_lines.append("")
        body_lines.append(workout_text)
    if w.tssPlanned or w.ifPlanned:
        body_lines.append("")
        if w.tssPlanned:
            body_lines.append(f"Planned TSS: {w.tssPlanned:.0f}")
        if w.ifPlanned:
            body_lines.append(f"Planned IF: {w.ifPlanned:.2f}")

    description = "\n".join(body_lines).rstrip()
    h = _content_hash(w, description, sport_type, workout_doc)
    description = f"{description}\n\n[tp-sync hash={h}]".strip()

    # Use planned start time if set, otherwise midnight of the workout day.
    if w.startTimePlanned:
        start_local = w.startTimePlanned
    else:
        start_local = f"{w.day.isoformat()}T00:00:00"

    payload: dict[str, Any] = {
        "category": "WORKOUT",
        "type": sport_type,
        "start_date_local": start_local,
        "name": w.title or "(untitled)",
        "description": description,
        "external_id": f"{EXTERNAL_ID_PREFIX}{w.workoutId}",
        "indoor": sport_type.startswith("Virtual"),
    }
    if workout_doc is not None:
        payload["workout_doc"] = workout_doc
    if w.duration_seconds:
        payload["moving_time"] = w.duration_seconds
    if w.distancePlanned:
        payload["distance"] = w.distancePlanned
    if w.tssPlanned:
        payload["icu_training_load"] = w.tssPlanned
    if w.ifPlanned:
        payload["icu_intensity"] = w.ifPlanned
    return payload


def _content_hash(
    w: TPWorkout,
    description: str,
    sport_type: str,
    workout_doc: dict[str, Any] | None,
) -> str:
    """Stable 12-char hash of the fields we mirror to icu.

    Excludes the [tp-sync hash=...] footer itself so a re-hash of the body produces
    the same digest.
    """
    body_only = re.sub(r"\n*\[tp-sync hash=[0-9a-f]+\]\s*$", "", description).rstrip()
    raw = {
        "wid": w.workoutId,
        "day": w.day.isoformat(),
        "start": w.startTimePlanned,
        "title": w.title or "",
        "type": sport_type,
        "duration": w.duration_seconds,
        "distance": w.distancePlanned,
        "tss": w.tssPlanned,
        "if": w.ifPlanned,
        "body": body_only,
        "workout_doc": workout_doc,
    }
    blob = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def extract_hash(event: IcuEvent) -> str | None:
    if not event.description:
        return None
    m = HASH_TAG_RE.search(event.description)
    return m.group(1) if m else None


def is_ours(event: IcuEvent) -> bool:
    return bool(event.external_id and event.external_id.startswith(EXTERNAL_ID_PREFIX))


def tp_id_from(event: IcuEvent) -> int | None:
    if not is_ours(event):
        return None
    try:
        return int(event.external_id.split(":", 1)[1])  # type: ignore[union-attr]
    except (ValueError, IndexError):
        return None


def run_sync(
    cfg: Config,
    *,
    days: int = 14,
    activity_lookback: int = 14,
    dry_run: bool = False,
) -> SyncResult:
    """Pull TP planned workouts for the next `days` days, mirror to icu.

    Also propagates the TP description into paired icu activities for the past
    `activity_lookback` days, so completed workouts on icu carry the coach's
    notes from TP. Activity descriptions are overwritten on every sync.
    """
    today = date.today()
    end = today + timedelta(days=days)
    activity_start = today - timedelta(days=activity_lookback)
    result = SyncResult()

    with TPClient(cfg.tp_cookie) as tp, IcuClient(cfg.icu_api_key, cfg.icu_athlete_id) as icu:
        logger.info("Fetching athlete thresholds")
        thresholds = tp.thresholds()
        logger.info(
            "  thresholds: FTP=%s W, LTHR=%s bpm, run_pace=%s s/km, swim_pace=%s s/100m",
            int(thresholds.ftp) if thresholds.ftp else None,
            int(thresholds.threshold_hr) if thresholds.threshold_hr else None,
            int(1000 / thresholds.threshold_velocity_mps) if thresholds.threshold_velocity_mps else None,
            int(100 / thresholds.swim_threshold_velocity_mps) if thresholds.swim_threshold_velocity_mps else None,
        )

        # Plan-sync window: today..end. Activity sync also covers the lookback.
        logger.info("Fetching TP planned workouts %s..%s", today, end)
        tp_workouts = list_planned_workouts(tp, today, end)
        logger.info("  TP returned %d planned workout(s)", len(tp_workouts))

        # Past TP workouts (for activity description lookup). These are completed
        # in TP but we still need their description to push into the paired
        # icu activity.
        if activity_lookback > 0:
            logger.info(
                "Fetching TP workouts in lookback window %s..%s for activity sync",
                activity_start,
                today - timedelta(days=1),
            )
            past_tp = list_planned_workouts(tp, activity_start, today - timedelta(days=1))
            logger.info("  TP returned %d workout(s) in lookback", len(past_tp))
        else:
            past_tp = []

        logger.info("Fetching icu events %s..%s", today, end)
        icu_events = list_events(icu, today, end)
        ours = {tp_id_from(e): e for e in icu_events if is_ours(e)}
        ours.pop(None, None)
        logger.info(
            "  icu returned %d total event(s), %d previously synced by us",
            len(icu_events),
            len(ours),
        )

        tp_by_id = {w.workoutId: w for w in tp_workouts}
        tp_all_by_id = {**{w.workoutId: w for w in past_tp}, **tp_by_id}

        # CREATE / UPDATE
        for wid, w in tp_by_id.items():
            payload = build_icu_payload(w, thresholds)
            new_hash = _content_hash(
                w, payload["description"], payload["type"], payload.get("workout_doc")
            )
            existing = ours.get(wid)
            if existing is None:
                logger.info("+ create %s [%s] %s", w.day, payload["type"], payload["name"])
                if not dry_run:
                    try:
                        created = create_event(icu, payload)
                        result.created.append(created.id or 0)
                    except IcuApiError as exc:
                        result.errors.append(f"create wid={wid}: {exc}")
                else:
                    result.created.append(0)
                continue

            old_hash = extract_hash(existing)
            if old_hash == new_hash:
                logger.debug(". unchanged %s %s", w.day, payload["name"])
                result.unchanged.append(existing.id or 0)
                continue

            logger.info("~ update %s [%s] %s", w.day, payload["type"], payload["name"])
            if not dry_run:
                try:
                    update_event(icu, existing.id, payload)  # type: ignore[arg-type]
                    result.updated.append(existing.id or 0)
                except IcuApiError as exc:
                    result.errors.append(f"update id={existing.id} wid={wid}: {exc}")
            else:
                result.updated.append(existing.id or 0)

        # DELETE: events we own but no longer in TP
        stale_ids = [wid for wid in ours.keys() if wid not in tp_by_id]
        for wid in stale_ids:
            ev = ours[wid]
            logger.info("- delete %s [%s] %s", ev.start_date_local[:10], ev.type, ev.name)
            if not dry_run:
                try:
                    delete_event(icu, ev.id)  # type: ignore[arg-type]
                    result.deleted.append(ev.id or 0)
                except IcuApiError as exc:
                    result.errors.append(f"delete id={ev.id} wid={wid}: {exc}")
            else:
                result.deleted.append(ev.id or 0)

        # ACTIVITY DESCRIPTIONS: propagate TP description to paired icu activities.
        if activity_lookback > 0:
            _sync_activity_descriptions(
                icu=icu,
                start=activity_start,
                end=end,
                tp_by_id=tp_all_by_id,
                ours_in_plan_window=ours,
                dry_run=dry_run,
                result=result,
            )

    return result


def _sync_activity_descriptions(
    *,
    icu: IcuClient,
    start: date,
    end: date,
    tp_by_id: dict[int, TPWorkout],
    ours_in_plan_window: dict[int | None, IcuEvent],
    dry_run: bool,
    result: SyncResult,
) -> None:
    """Push TP description into paired icu activity.description (overwrite).

    Resolves activity.paired_event_id -> event.external_id -> tp workoutId -> tp.description.
    Skips activities that are not paired with one of our tp-synced events.
    """
    logger.info("Fetching icu activities %s..%s for description sync", start, end)
    activities = list_activities(icu, start, end)
    logger.info("  icu returned %d activity(ies) in lookback window", len(activities))
    if not activities:
        return

    # Need the events in the lookback window too (not just plan window) so we
    # can resolve paired_event_id -> tp workoutId for past events.
    past_events = list_events(icu, start, end)
    events_by_id: dict[int, IcuEvent] = {}
    for e in past_events:
        if e.id is not None and is_ours(e):
            events_by_id[e.id] = e
    for e in ours_in_plan_window.values():
        if e.id is not None:
            events_by_id[e.id] = e

    for act in activities:
        if act.paired_event_id is None:
            continue
        ev = events_by_id.get(act.paired_event_id)
        if ev is None:
            continue
        wid = tp_id_from(ev)
        if wid is None:
            continue
        w = tp_by_id.get(wid)
        if w is None:
            continue
        desired = (w.description or "").strip()
        current = (act.description or "").strip()
        if desired == current:
            continue

        logger.info(
            "+ activity desc %s [%s] %s (id=%s)",
            act.start_date_local[:10],
            act.type,
            act.name,
            act.id,
        )
        if not dry_run:
            try:
                update_activity(icu, act.id, {"description": desired})
                result.activity_updates.append(act.id)
            except IcuApiError as exc:
                result.errors.append(f"activity update id={act.id} wid={wid}: {exc}")
        else:
            result.activity_updates.append(act.id)

"""Sync orchestration: diff TP planned workouts against icu events, then apply."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
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
from tp_icu_sync.icu.models import IcuActivity, IcuEvent
from tp_icu_sync.mapping.sport import tp_sport_to_icu_type
from tp_icu_sync.mapping.structure import render_workout_doc, render_workout_text
from tp_icu_sync.tp.api import list_workouts
from tp_icu_sync.tp.client import AthleteThresholds, TPClient
from tp_icu_sync.tp.models import TPWorkout

logger = logging.getLogger(__name__)

EXTERNAL_ID_PREFIX = "tp:"
HASH_TAG_RE = re.compile(r"\[tp-sync hash=([0-9a-f]{12})\]")
HASH_FOOTER_RE = re.compile(r"\n*\[tp-sync hash=[0-9a-f]+\]\s*$")

# TP workoutTypeValueId values that need special handling.
TP_TYPE_RACE = 6
TP_TYPE_DAY_OFF = 7


# ---------------------------------------------------------------------------
# Classification: which icu category + sport type does this TP workout become?
# ---------------------------------------------------------------------------


def _classify(w: TPWorkout) -> tuple[str, str | None]:
    """Pick (icu_category, icu_type) for a TP workout.

    - Day Off (7) -> NOTE without sport
    - Race (6)   -> RACE_A, sport from workoutSubTypeId (default Run)
    - No content (no duration / distance / structure / tss) -> NOTE
    - Anything else -> WORKOUT + sport mapping
    """
    if w.workoutTypeValueId == TP_TYPE_DAY_OFF:
        return ("NOTE", None)
    if w.workoutTypeValueId == TP_TYPE_RACE:
        sport = tp_sport_to_icu_type(None, w.workoutSubTypeId)
        if sport == "Workout":
            sport = "Run"
        return ("RACE_A", sport)

    has_content = bool(
        w.totalTimePlanned or w.distancePlanned or w.structure or w.tssPlanned
    )
    if not has_content:
        return ("NOTE", None)

    return ("WORKOUT", tp_sport_to_icu_type(w.workoutTypeValueId, w.workoutSubTypeId))


# ---------------------------------------------------------------------------
# Description body building
# ---------------------------------------------------------------------------


def _format_comments(comments: list[dict[str, Any]]) -> str:
    """Render TP workoutComments thread as a bullet list."""
    lines: list[str] = []
    for c in comments:
        text = (c.get("comment") or "").strip()
        if not text:
            continue
        author = (
            c.get("commentByPersonName")
            or c.get("commentByName")
            or c.get("authorName")
            or "Comment"
        )
        when = c.get("dateAdded") or c.get("commentDate") or ""
        when_short = when[:10] if isinstance(when, str) else ""
        prefix = f"{author} ({when_short})" if when_short else author
        lines.append(f"- {prefix}: {text}")
    return "\n".join(lines)


def _build_description(
    w: TPWorkout,
    sport_type: str | None,
    is_note: bool,
    thresholds: AthleteThresholds | None,
) -> str:
    """Build the human-readable description body (without the [tp-sync hash=...] footer)."""
    sections: list[str] = []

    if w.description and w.description.strip():
        sections.append(w.description.strip())

    if w.coachComments and w.coachComments.strip():
        sections.append("Coach:\n" + w.coachComments.strip())

    if w.workoutComments:
        comments = _format_comments(w.workoutComments)
        if comments:
            sections.append("Comments:\n" + comments)

    if not is_note:
        text = render_workout_text(w.structure, sport_type or "", thresholds)
        if text:
            sections.append(text)

        meta: list[str] = []
        if w.tssPlanned:
            meta.append(f"Planned TSS: {w.tssPlanned:.0f}")
        if w.ifPlanned:
            meta.append(f"Planned IF: {w.ifPlanned:.2f}")
        if meta:
            sections.append("\n".join(meta))

    return "\n\n".join(sections)


def build_icu_payload(
    w: TPWorkout, thresholds: AthleteThresholds | None = None
) -> dict[str, Any]:
    """Translate a TP planned workout into an icu Event POST/PUT body."""
    category, sport_type = _classify(w)
    is_note = category == "NOTE"
    workout_doc = (
        None if is_note else render_workout_doc(w.structure, sport_type or "", thresholds)
    )

    body = _build_description(w, sport_type, is_note, thresholds)
    h = _content_hash(w, body, category, sport_type, workout_doc)
    description = f"{body}\n\n[tp-sync hash={h}]".lstrip()

    start_local = w.startTimePlanned or f"{w.day.isoformat()}T00:00:00"

    payload: dict[str, Any] = {
        "category": category,
        "start_date_local": start_local,
        "name": w.title or ("(note)" if is_note else "(untitled)"),
        "description": description,
        "external_id": f"{EXTERNAL_ID_PREFIX}{w.workoutId}",
    }
    if sport_type is not None:
        payload["type"] = sport_type
        payload["indoor"] = sport_type.startswith("Virtual")
    if workout_doc is not None:
        payload["workout_doc"] = workout_doc
    if not is_note:
        if w.duration_seconds:
            payload["moving_time"] = w.duration_seconds
        if w.distancePlanned:
            payload["distance"] = w.distancePlanned
        if w.tssPlanned:
            payload["icu_training_load"] = w.tssPlanned
        if w.ifPlanned:
            payload["icu_intensity"] = w.ifPlanned
    return payload


# ---------------------------------------------------------------------------
# Content hashing — drives idempotent diffs
# ---------------------------------------------------------------------------


def _content_hash(
    w: TPWorkout,
    description: str,
    category: str,
    sport_type: str | None,
    workout_doc: dict[str, Any] | None,
) -> str:
    """Stable 12-char hash of fields we mirror to icu (without the hash footer)."""
    body_only = HASH_FOOTER_RE.sub("", description).rstrip()
    raw = {
        "wid": w.workoutId,
        "day": w.day.isoformat(),
        "start": w.startTimePlanned,
        "title": w.title or "",
        "category": category,
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


def _extract_hash(event: IcuEvent) -> str | None:
    if not event.description:
        return None
    m = HASH_TAG_RE.search(event.description)
    return m.group(1) if m else None


def _is_ours(event: IcuEvent) -> bool:
    return bool(event.external_id and event.external_id.startswith(EXTERNAL_ID_PREFIX))


def _tp_id_from(event: IcuEvent) -> int | None:
    if not _is_ours(event) or not event.external_id:
        return None
    try:
        return int(event.external_id.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    activity_updates: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_sync(
    cfg: Config,
    *,
    days: int = 14,
    activity_lookback: int = 14,
    dry_run: bool = False,
) -> SyncResult:
    """Pull TP planned workouts for the next `days` days, mirror to icu.

    Also propagates the TP description into paired icu activities for the past
    `activity_lookback` days. Activity descriptions are overwritten on every sync.
    """
    today = date.today()
    plan_end = today + timedelta(days=days)
    lookback_start = today - timedelta(days=activity_lookback)
    fetch_start = lookback_start if activity_lookback > 0 else today

    result = SyncResult()

    with TPClient(cfg.tp_cookie) as tp, IcuClient(cfg.icu_api_key, cfg.icu_athlete_id) as icu:
        thresholds = tp.thresholds()
        _log_thresholds(thresholds)

        # Single TP fetch covering both the plan window and the lookback window.
        logger.info("Fetching TP workouts %s..%s", fetch_start, plan_end)
        tp_all = list_workouts(tp, fetch_start, plan_end)
        logger.info("  TP returned %d workout(s)", len(tp_all))

        # Single icu events fetch covering the same range.
        logger.info("Fetching icu events %s..%s", fetch_start, plan_end)
        icu_events = list_events(icu, fetch_start, plan_end)
        ours_all = {
            wid: e
            for e in icu_events
            if (wid := _tp_id_from(e)) is not None
        }
        logger.info(
            "  icu returned %d event(s), %d previously synced by us",
            len(icu_events),
            len(ours_all),
        )

        # Partition TP workouts into in-plan-window vs lookback-only.
        tp_in_plan = {
            w.workoutId: w for w in tp_all if today <= w.day <= plan_end
        }
        tp_all_by_id = {w.workoutId: w for w in tp_all}

        # Only events that fall inside the plan window are eligible for diff.
        ours_in_plan = {
            wid: e
            for wid, e in ours_all.items()
            if today.isoformat() <= e.start_date_local[:10] <= plan_end.isoformat()
        }

        _sync_events(
            tp_in_plan=tp_in_plan,
            ours_in_plan=ours_in_plan,
            thresholds=thresholds,
            icu=icu,
            dry_run=dry_run,
            result=result,
        )

        if activity_lookback > 0:
            _sync_activity_descriptions(
                icu=icu,
                start=lookback_start,
                end=plan_end,
                tp_by_id=tp_all_by_id,
                events_by_id={e.id: e for e in icu_events if e.id is not None and _is_ours(e)},
                dry_run=dry_run,
                result=result,
            )

    return result


def _log_thresholds(t: AthleteThresholds) -> None:
    logger.info(
        "Thresholds: FTP=%s W, LTHR=%s bpm, run_pace=%s s/km, swim_pace=%s s/100m",
        int(t.ftp) if t.ftp else None,
        int(t.threshold_hr) if t.threshold_hr else None,
        int(1000 / t.threshold_velocity_mps) if t.threshold_velocity_mps else None,
        int(100 / t.swim_threshold_velocity_mps) if t.swim_threshold_velocity_mps else None,
    )


def _sync_events(
    *,
    tp_in_plan: dict[int, TPWorkout],
    ours_in_plan: dict[int, IcuEvent],
    thresholds: AthleteThresholds | None,
    icu: IcuClient,
    dry_run: bool,
    result: SyncResult,
) -> None:
    """Diff & apply: create / update / delete events for the plan window."""

    # CREATE / UPDATE
    for wid, w in tp_in_plan.items():
        payload = build_icu_payload(w, thresholds)
        label = payload.get("type") or payload["category"]
        new_hash = _content_hash(
            w,
            payload["description"],
            payload["category"],
            payload.get("type"),
            payload.get("workout_doc"),
        )

        existing = ours_in_plan.get(wid)
        if existing is None:
            logger.info("+ create %s [%s] %s", w.day, label, payload["name"])
            if dry_run:
                result.created += 1
                continue
            try:
                create_event(icu, payload)
                result.created += 1
            except IcuApiError as exc:
                msg = f"create wid={wid}: {exc}"
                logger.error("  %s", msg)
                result.errors.append(msg)
            continue

        if _extract_hash(existing) == new_hash:
            result.unchanged += 1
            continue

        logger.info("~ update %s [%s] %s", w.day, label, payload["name"])
        if dry_run:
            result.updated += 1
            continue
        try:
            update_event(icu, existing.id, payload)  # type: ignore[arg-type]
            result.updated += 1
        except IcuApiError as exc:
            msg = f"update id={existing.id} wid={wid}: {exc}"
            logger.error("  %s", msg)
            result.errors.append(msg)

    # DELETE: events we own in the plan window but TP no longer has
    stale = [wid for wid in ours_in_plan if wid not in tp_in_plan]
    for wid in stale:
        ev = ours_in_plan[wid]
        logger.info(
            "- delete %s [%s] %s", ev.start_date_local[:10], ev.type, ev.name
        )
        if dry_run:
            result.deleted += 1
            continue
        try:
            delete_event(icu, ev.id)  # type: ignore[arg-type]
            result.deleted += 1
        except IcuApiError as exc:
            msg = f"delete id={ev.id} wid={wid}: {exc}"
            logger.error("  %s", msg)
            result.errors.append(msg)


def _sync_activity_descriptions(
    *,
    icu: IcuClient,
    start: date,
    end: date,
    tp_by_id: dict[int, TPWorkout],
    events_by_id: dict[int, IcuEvent],
    dry_run: bool,
    result: SyncResult,
) -> None:
    """Overwrite paired icu activity.description with the TP description."""
    logger.info("Fetching icu activities %s..%s", start, end)
    activities = list_activities(icu, start, end)
    logger.info("  icu returned %d activity(ies)", len(activities))
    if not activities:
        return

    for act in activities:
        update = _activity_desc_update(act, events_by_id, tp_by_id)
        if update is None:
            continue
        desired = update
        logger.info(
            "+ activity desc %s [%s] %s (id=%s)",
            act.start_date_local[:10],
            act.type,
            act.name,
            act.id,
        )
        if dry_run:
            result.activity_updates += 1
            continue
        try:
            update_activity(icu, act.id, {"description": desired})
            result.activity_updates += 1
        except IcuApiError as exc:
            msg = f"activity update id={act.id}: {exc}"
            logger.error("  %s", msg)
            result.errors.append(msg)


def _activity_desc_update(
    act: IcuActivity,
    events_by_id: dict[int, IcuEvent],
    tp_by_id: dict[int, TPWorkout],
) -> str | None:
    """Return the description the activity SHOULD have, or None if no change needed."""
    if act.paired_event_id is None:
        return None
    ev = events_by_id.get(act.paired_event_id)
    if ev is None:
        return None
    wid = _tp_id_from(ev)
    if wid is None:
        return None
    w = tp_by_id.get(wid)
    if w is None:
        return None
    desired = (w.description or "").strip()
    current = (act.description or "").strip()
    return desired if desired != current else None

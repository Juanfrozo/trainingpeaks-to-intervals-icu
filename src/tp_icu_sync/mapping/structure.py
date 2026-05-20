"""Translate a TrainingPeaks structure into intervals.icu workout_doc + a
human-readable text rendering.

When an `AthleteThresholds` object is provided, percent-of-threshold targets
are converted into absolute values:

  percentOfFtp           x%  ->  power.value = x * ftp / 100  W           (units="w")
  percentOfThresholdHr   x%  ->  hr.value    = x * thr_hr / 100 bpm       (units="bpm")
  percentOfThresholdPace x%  ->  pace.value  = 1000 / (v_thr * x/100) s/km (units="s/km")

This matters because icu does not always have the athlete's threshold pace
configured per sport, so a "%pace" target would not be converted on display
and would not be pushed to Garmin/Wahoo as a real pace target.

If no threshold is available we fall back to keeping the percent units.
"""

from __future__ import annotations

from typing import Any

from tp_icu_sync.tp.client import AthleteThresholds
from tp_icu_sync.tp.models import TPStructure, TPStructureStep

POWER_SPORTS = {"Ride", "VirtualRide", "MountainBikeRide"}
PACE_SPORTS = {"Run", "VirtualRun", "Walk", "Hike", "Swim", "Rowing"}

CLASS_LABEL: dict[str, str] = {
    "warmup": "Warm up",
    "warm_up": "Warm up",
    "cooldown": "Cool down",
    "cool_down": "Cool down",
    "active": "",
    "rest": "Recovery",
    "recovery": "Recovery",
}


def _seconds(length: dict[str, Any] | None) -> int | None:
    if not length:
        return None
    unit = (length.get("unit") or "").lower()
    val = length.get("value")
    if val is None:
        return None
    if unit == "second":
        return int(round(float(val)))
    if unit == "minute":
        return int(round(float(val) * 60))
    if unit == "hour":
        return int(round(float(val) * 3600))
    return None


def _metres(length: dict[str, Any] | None) -> int | None:
    if not length:
        return None
    unit = (length.get("unit") or "").lower()
    val = length.get("value")
    if val is None:
        return None
    if unit in {"metre", "meter"}:
        return int(round(float(val)))
    if unit in {"kilometre", "kilometer"}:
        return int(round(float(val) * 1000))
    if unit == "mile":
        return int(round(float(val) * 1609.344))
    return None


def _build_target(
    targets: list[dict[str, Any]],
    metric: str,
    icu_type: str,
    thresholds: AthleteThresholds | None,
) -> dict[str, dict[str, Any]] | None:
    if not targets:
        return None
    t = targets[0]
    lo = t.get("minValue")
    hi = t.get("maxValue")
    if lo is None and hi is None:
        return None

    metric = (metric or "").lower()
    key, units = _metric_to_icu(metric, icu_type)
    if key is None:
        return None

    # Try to convert percent-of-threshold to absolute, sport-aware.
    abs_units, abs_pair = _convert_to_absolute(key, units, lo, hi, icu_type, thresholds)
    if abs_pair is not None:
        a_lo, a_hi = abs_pair
        target: dict[str, Any] = {"units": abs_units}
        if a_lo is not None and a_hi is not None and a_lo != a_hi:
            target["value"] = a_lo
            target["max_value"] = a_hi
        elif a_lo is not None:
            target["value"] = a_lo
        else:
            target["value"] = a_hi
        return {key: target}

    # Fall through: keep percent units.
    target = {"units": units}
    if lo is not None and hi is not None and lo != hi:
        target["value"] = _num(lo)
        target["max_value"] = _num(hi)
    elif lo is not None:
        target["value"] = _num(lo)
        if hi is not None:
            target["max_value"] = _num(hi)
    else:
        target["value"] = _num(hi)
    return {key: target}


def _convert_to_absolute(
    key: str,
    units: str,
    lo: float | None,
    hi: float | None,
    icu_type: str,
    thresholds: AthleteThresholds | None,
) -> tuple[str, tuple[float | None, float | None] | None]:
    """Convert percent-of-threshold (lo, hi) to absolute (value, max_value).

    Returns (new_units, (low_abs, high_abs)) or (units, None) when no conversion is
    possible/applicable.
    """
    if thresholds is None:
        return units, None

    # Power: %ftp -> watts
    if key == "power" and units == "%ftp" and thresholds.ftp:
        ftp = thresholds.ftp
        a_lo = round(lo * ftp / 100) if lo is not None else None
        a_hi = round(hi * ftp / 100) if hi is not None else None
        return "w", (a_lo, a_hi)

    # HR: %lthr -> bpm
    if key == "hr" and units == "%lthr" and thresholds.threshold_hr:
        thr = thresholds.threshold_hr
        a_lo = round(lo * thr / 100) if lo is not None else None
        a_hi = round(hi * thr / 100) if hi is not None else None
        return "bpm", (a_lo, a_hi)

    # Pace: %pace -> s/km (or s/100m for swim)
    if key == "pace" and units == "%pace":
        is_swim = icu_type == "Swim"
        v_thr = thresholds.swim_threshold_velocity_mps if is_swim else thresholds.threshold_velocity_mps
        if v_thr:
            # value = pct of threshold velocity. Lower velocity = slower pace = higher s.
            distance_m = 100 if is_swim else 1000
            pace_unit = "s/100m" if is_swim else "s/km"
            # lo (%): slower bound  -> slower pace (larger s)
            # hi (%): faster bound  -> faster pace (smaller s)
            slow_pace = round(distance_m / (v_thr * lo / 100)) if lo is not None else None
            fast_pace = round(distance_m / (v_thr * hi / 100)) if hi is not None else None
            # icu convention: value = fast (low s), max_value = slow (high s).
            # Use whichever bound is available; if both, present (fast, slow).
            a_lo = fast_pace if fast_pace is not None else slow_pace
            a_hi = slow_pace if (fast_pace is not None and slow_pace is not None) else None
            return pace_unit, (a_lo, a_hi)

    return units, None


def _metric_to_icu(metric: str, icu_type: str) -> tuple[str | None, str]:
    """Map TP intensity metric to icu (key, units). Remaps to sport-appropriate key."""
    if metric in {"percentofftp"}:
        if icu_type in POWER_SPORTS:
            return ("power", "%ftp")
        if icu_type in {"Run", "VirtualRun"}:
            return ("pace", "%pace")  # TP coaches sometimes mis-tag
        return ("hr", "%lthr")
    if metric in {"watts", "power"}:
        return ("power", "w")
    if metric in {"percentofthresholdhr"}:
        return ("hr", "%lthr")
    if metric in {"percentofmaxhr"}:
        return ("hr", "%hr")
    if metric in {"heartrate", "bpm"}:
        return ("hr", "bpm")
    if metric in {"percentofthresholdpace"}:
        if icu_type in PACE_SPORTS:
            return ("pace", "%pace")
        return ("hr", "%lthr")  # weird mix, fall back
    if metric in {"pace", "speed"}:
        return ("pace", "/km")
    return (None, "")


def _num(value: float | int) -> int | float:
    f = float(value)
    return int(f) if f.is_integer() else round(f, 2)


def _render_step(
    step: TPStructureStep,
    metric: str,
    icu_type: str,
    thresholds: AthleteThresholds | None,
) -> dict[str, Any] | None:
    secs = _seconds(step.length)
    metres = _metres(step.length)
    if secs is None and metres is None:
        return None

    out: dict[str, Any] = {}
    if secs is not None:
        out["duration"] = secs
    if metres is not None:
        out["distance"] = metres

    target = _build_target(step.targets, metric, icu_type, thresholds)
    if target:
        out.update(target)

    cls = (step.intensityClass or "").lower()
    label = CLASS_LABEL.get(cls)
    if step.name and step.name.lower() not in {"active", "rest"}:
        out["text"] = step.name
    elif label:
        out["text"] = label

    return out


def render_workout_doc(
    structure: TPStructure | dict[str, Any] | None,
    icu_type: str,
    thresholds: AthleteThresholds | None = None,
) -> dict[str, Any] | None:
    """Build an icu workout_doc dict from a TP structure. Returns None when empty."""
    if structure is None:
        return None
    if isinstance(structure, dict):
        structure = TPStructure.model_validate(structure)
    if not structure.structure:
        return None

    metric = (structure.primaryIntensityMetric or "").lower()
    steps: list[dict[str, Any]] = []
    total_seconds = 0
    total_metres = 0

    for block in structure.structure:
        reps = 1
        if block.length and (block.length.get("unit") or "").lower() == "repetition":
            reps = int(block.length.get("value") or 1)

        rendered = [
            s
            for s in (_render_step(st, metric, icu_type, thresholds) for st in block.steps)
            if s
        ]
        if not rendered:
            continue

        block_secs = sum(s.get("duration", 0) for s in rendered)
        block_mtrs = sum(s.get("distance", 0) for s in rendered)
        total_seconds += reps * block_secs
        total_metres += reps * block_mtrs

        if reps > 1:
            steps.append({"reps": reps, "steps": rendered})
        else:
            steps.extend(rendered)

    if not steps:
        return None

    doc: dict[str, Any] = {"steps": steps}
    if total_seconds:
        doc["duration"] = total_seconds
    if total_metres:
        doc["distance"] = total_metres
    return doc


def render_workout_text(
    structure: TPStructure | dict[str, Any] | None,
    icu_type: str,
    thresholds: AthleteThresholds | None = None,
) -> str:
    """Plain human-readable summary of the structure for the description body.

    Kept intentionally lossy and free of icu workout-language tokens to avoid
    fighting icu's auto-parser when workout_doc is already set explicitly.
    """
    if structure is None:
        return ""
    if isinstance(structure, dict):
        structure = TPStructure.model_validate(structure)
    if not structure.structure:
        return ""

    metric = (structure.primaryIntensityMetric or "").lower()
    lines: list[str] = []

    for block in structure.structure:
        reps = 1
        if block.length and (block.length.get("unit") or "").lower() == "repetition":
            reps = int(block.length.get("value") or 1)
        rendered = [
            _step_text(s, metric, icu_type, thresholds)
            for s in block.steps
            if _step_text(s, metric, icu_type, thresholds)
        ]
        if not rendered:
            continue
        if reps > 1:
            lines.append(f"{reps}x ({' / '.join(rendered)})")
        else:
            lines.extend(rendered)

    return " | ".join(lines)


def _step_text(
    step: TPStructureStep,
    metric: str,
    icu_type: str,
    thresholds: AthleteThresholds | None,
) -> str:
    secs = _seconds(step.length)
    metres = _metres(step.length)
    parts: list[str] = []
    if secs is not None:
        parts.append(f"{secs // 60}m" if secs >= 60 and secs % 60 == 0 else f"{secs}s")
    elif metres is not None:
        parts.append(f"{metres / 1000:g}km" if metres >= 1000 else f"{metres}m")
    target = _build_target(step.targets, metric, icu_type, thresholds)
    if target:
        key, td = next(iter(target.items()))
        v = td.get("value")
        mx = td.get("max_value")
        u = td.get("units", "")
        # Pace in s/km -> render as mm:ss/km for humans.
        if u in {"s/km", "s/100m"} and isinstance(v, (int, float)):
            v_str = _fmt_pace(v, u)
            mx_str = _fmt_pace(mx, u) if isinstance(mx, (int, float)) else None
            unit_label = ""
            parts.append(f"{v_str}-{mx_str}" if mx_str else v_str)
        else:
            unit_label = {
                "%ftp": "% FTP",
                "%lthr": "% LTHR",
                "%hr": "% MaxHR",
                "%pace": "% Pace",
                "w": "W",
                "bpm": "bpm",
                "/km": "/km",
            }.get(u, u)
            if mx is not None:
                parts.append(f"{v}-{mx}{unit_label}")
            else:
                parts.append(f"{v}{unit_label}")
    cls = (step.intensityClass or "").lower()
    if cls == "warmup":
        parts.insert(0, "WU")
    elif cls == "cooldown":
        parts.insert(0, "CD")
    return " ".join(parts)


def _fmt_pace(secs: float, unit: str) -> str:
    s = int(round(secs))
    suffix = "/km" if unit == "s/km" else "/100m"
    return f"{s // 60}:{s % 60:02d}{suffix}"

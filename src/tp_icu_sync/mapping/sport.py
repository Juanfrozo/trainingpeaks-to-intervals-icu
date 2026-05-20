"""TrainingPeaks sport (workoutTypeValueId) -> intervals.icu event `type` string.

icu event types we use: Ride, VirtualRide, MountainBikeRide, Run, VirtualRun,
TrailRun, Swim, Walk, Hike, WeightTraining, Workout, NordicSki, AlpineSki,
BackcountrySki, Rowing.

TP top-level IDs (from GET /fitness/v6/workouttypes):
  1 Swim, 2 Bike, 3 Run, 4 Brick, 5 Crosstrain, 6 Race, 7 Day Off,
  8 Mountain Bike, 9 Strength, 10 Custom, 11 XC-Ski, 12 Rowing, 13 Walk,
  29 Strength, 100 Other.

TP subtypes that warrant a more specific icu type:
  6  Indoor Bike   -> VirtualRide
  49 Virtual Bike  -> VirtualRide
  13 Indoor Run    -> VirtualRun
  50 Virtual Run   -> VirtualRun
  12 Trail Run     -> TrailRun
  41 Hike          -> Hike
  39 Indoor Rowing -> Rowing
"""

from __future__ import annotations

# Subtype overrides take precedence over the parent.
SUBTYPE_TO_ICU: dict[int, str] = {
    6: "VirtualRide",  # Indoor Bike
    49: "VirtualRide",  # Virtual Bike
    13: "VirtualRun",  # Indoor Run (treadmill)
    50: "VirtualRun",  # Virtual Run
    12: "Run",  # Trail Run (icu has TrailRun; some installs don't, default safe to Run)
    41: "Hike",
    42: "Walk",  # Treadmill Walk
    14: "MountainBikeRide",
    15: "MountainBikeRide",
    16: "MountainBikeRide",
    17: "MountainBikeRide",
    18: "MountainBikeRide",
    19: "MountainBikeRide",
}

PARENT_TO_ICU: dict[int, str] = {
    1: "Swim",
    2: "Ride",
    3: "Run",
    4: "Workout",  # Brick: ambiguous, generic
    5: "Workout",  # Crosstrain
    6: "Race",  # icu also has 'Race' category but we keep type generic
    8: "MountainBikeRide",
    9: "WeightTraining",
    11: "NordicSki",
    12: "Rowing",
    13: "Walk",
    29: "WeightTraining",
    100: "Workout",
}


def tp_sport_to_icu_type(tp_type_id: int | None, tp_subtype_id: int | None = None) -> str:
    """Best-effort mapping. Falls back to 'Workout' for unknown sports."""
    if tp_subtype_id is not None and tp_subtype_id in SUBTYPE_TO_ICU:
        return SUBTYPE_TO_ICU[tp_subtype_id]
    if tp_type_id is not None and tp_type_id in PARENT_TO_ICU:
        return PARENT_TO_ICU[tp_type_id]
    return "Workout"

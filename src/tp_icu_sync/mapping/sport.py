"""TrainingPeaks sport (workoutTypeValueId / workoutSubTypeId) -> intervals.icu
event `type` string.

icu event types we emit: Ride, VirtualRide, MountainBikeRide, Run, VirtualRun,
Swim, Walk, Hike, WeightTraining, Workout, NordicSki, Rowing.

TP top-level IDs (from GET /fitness/v6/workouttypes):
  1 Swim, 2 Bike, 3 Run, 4 Brick, 5 Crosstrain, 6 Race, 7 Day Off,
  8 Mountain Bike, 9 Strength, 10 Custom, 11 XC-Ski, 12 Rowing, 13 Walk,
  29 Strength, 100 Other.

Subtype overrides are applied first (subtype IDs are unique across sports in
TP), then the parent type is consulted as a fallback. Unknown sports map to
"Workout".
"""

from __future__ import annotations

# Subtype overrides take precedence over the parent. Subtype IDs are unique
# across TrainingPeaks (no collisions between sports), so they can be looked
# up independently of the parent ID.
SUBTYPE_TO_ICU: dict[int, str] = {
    # Swim
    1: "Swim",  # Open Water Swim
    2: "Swim",  # Pool Swim
    # Bike
    3: "Ride",  # Road Bike
    4: "Ride",  # Gravel Bike
    5: "Ride",  # Track Bike
    6: "VirtualRide",  # Indoor Bike
    7: "Ride",  # Cyclocross
    8: "Ride",  # E-Bike
    9: "Ride",  # Hand Cycling
    47: "Ride",  # Time Trial
    49: "VirtualRide",  # Virtual Bike
    # Run
    10: "Run",  # Road Run
    11: "Run",  # Track Run
    12: "Run",  # Trail Run
    13: "VirtualRun",  # Indoor Run (treadmill)
    50: "VirtualRun",  # Virtual Run
    # Walk
    41: "Hike",
    42: "Walk",  # Treadmill Walk
    43: "Hike",  # Mountaineering
    44: "Hike",  # Hunting
    # Mountain Bike
    14: "MountainBikeRide",
    15: "MountainBikeRide",
    16: "MountainBikeRide",
    17: "MountainBikeRide",
    18: "MountainBikeRide",
    19: "MountainBikeRide",
    # Rowing
    39: "Rowing",  # Indoor Rowing
    51: "Rowing",  # Virtual Rowing
}

PARENT_TO_ICU: dict[int, str] = {
    1: "Swim",
    2: "Ride",
    3: "Run",
    4: "Workout",  # Brick: ambiguous, generic
    5: "Workout",  # Crosstrain
    # 6 (Race) is handled separately: it's a category, not a sport. Look at subtype.
    8: "MountainBikeRide",
    9: "WeightTraining",
    # 7 (Day Off) and 10 (Custom) are handled as notes when content is empty.
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

"""TrainingPeaks domain models (subset we actually use)."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TPStructureStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    length: dict[str, Any] | None = None
    targets: list[dict[str, Any]] = Field(default_factory=list)
    intensityClass: str | None = None
    openDuration: bool = False


class TPStructureBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    length: dict[str, Any] | None = None
    steps: list[TPStructureStep] = Field(default_factory=list)


class TPStructure(BaseModel):
    model_config = ConfigDict(extra="allow")

    structure: list[TPStructureBlock] = Field(default_factory=list)
    primaryLengthMetric: str | None = None
    primaryIntensityMetric: str | None = None


class TPWorkout(BaseModel):
    model_config = ConfigDict(extra="allow")

    workoutId: int
    workoutDay: str  # "2026-05-17T00:00:00"
    title: str | None = None
    description: str | None = None
    workoutTypeValueId: int | None = None
    workoutSubTypeId: int | None = None
    totalTimePlanned: float | None = None  # hours
    distancePlanned: float | None = None  # metres
    tssPlanned: float | None = None
    ifPlanned: float | None = None
    completed: bool | None = None
    structure: TPStructure | dict[str, Any] | None = None
    startTimePlanned: str | None = None
    coachComments: str | None = None
    workoutComments: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def day(self) -> date:
        return date.fromisoformat(self.workoutDay.split("T")[0])

    @property
    def duration_seconds(self) -> int | None:
        if self.totalTimePlanned is None:
            return None
        return int(round(self.totalTimePlanned * 3600))

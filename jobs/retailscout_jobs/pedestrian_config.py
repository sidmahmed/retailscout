"""Typed loader for jobs/registry/pedestrian_config.yaml.

Dayparts and day-type definitions for the pedestrian baseline
aggregation, kept out of SQL/code (architecture.md invariant 8 / §10.1).
Resolves to plain hour→daypart and isodow→day_type mappings the loader
hands to SQL as arrays. Overlaps fail loudly here at load time.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

PEDESTRIAN_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "registry" / "pedestrian_config.yaml"
)


class Daypart(BaseModel):
    name: str
    start_hour: int
    end_hour: int  # half-open [start_hour, end_hour)

    @model_validator(mode="after")
    def _valid_range(self) -> Daypart:
        if not (0 <= self.start_hour < self.end_hour <= 24):
            raise ValueError(f"daypart '{self.name}' has an invalid hour range")
        return self


class DayType(BaseModel):
    name: str
    isodows: list[int]  # 1=Mon .. 7=Sun


class Interpolation(BaseModel):
    decay_distance_m: float
    max_sensor_distance_m: float
    confidence_high_max_nearest_m: float
    confidence_high_min_sensors: int
    confidence_medium_max_nearest_m: float


class PedestrianConfig(BaseModel):
    version: str
    timezone: str
    trailing_months: int
    dayparts: list[Daypart]
    day_types: list[DayType]
    interpolation: Interpolation

    @model_validator(mode="after")
    def _no_overlaps(self) -> PedestrianConfig:
        # Building the maps here surfaces any overlap as a load-time error.
        self.hour_to_daypart()
        self.isodow_to_daytype()
        return self

    def hour_to_daypart(self) -> dict[int, str]:
        hour_map: dict[int, str] = {}
        for dp in self.dayparts:
            for h in range(dp.start_hour, dp.end_hour):
                if h in hour_map:
                    raise ValueError(
                        f"hour {h} is in both '{hour_map[h]}' and '{dp.name}' dayparts"
                    )
                hour_map[h] = dp.name
        return hour_map

    def isodow_to_daytype(self) -> dict[int, str]:
        dow_map: dict[int, str] = {}
        for dt in self.day_types:
            for d in dt.isodows:
                if not (1 <= d <= 7):
                    raise ValueError(f"day_type '{dt.name}' has invalid isodow {d}")
                if d in dow_map:
                    raise ValueError(
                        f"isodow {d} is in both '{dow_map[d]}' and '{dt.name}' day types"
                    )
                dow_map[d] = dt.name
        return dow_map


def load_pedestrian_config(path: Path = PEDESTRIAN_CONFIG_PATH) -> PedestrianConfig:
    return PedestrianConfig.model_validate(yaml.safe_load(path.read_text()))

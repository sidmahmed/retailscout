"""Typed loader for jobs/registry/development_config.yaml.

Status-probability factors, people-equivalent coefficients and the
catchment decay for the development-pipeline feature (§13), versioned
and kept out of code (invariant 8). Invalid factors fail loudly here at
load time, not mid-build.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

DEVELOPMENT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "registry" / "development_config.yaml"
)


class DistanceDecay(BaseModel):
    radius_m: float

    @model_validator(mode="after")
    def _positive(self) -> DistanceDecay:
        if self.radius_m <= 0:
            raise ValueError("distance_decay.radius_m must be positive")
        return self


class DevelopmentConfig(BaseModel):
    version: str
    status_probability: dict[str, float]
    completed_since_year: int
    people_equivalents: dict[str, float]
    distance_decay: DistanceDecay

    @model_validator(mode="after")
    def _validate(self) -> DevelopmentConfig:
        if not self.status_probability:
            raise ValueError("no status_probability factors defined")
        for status, p in self.status_probability.items():
            if not 0 <= p <= 1:
                raise ValueError(f"status_probability[{status}]={p} outside [0, 1]")
        if not self.people_equivalents:
            raise ValueError("no people_equivalents coefficients defined")
        for field, coeff in self.people_equivalents.items():
            if coeff < 0:
                raise ValueError(f"people_equivalents[{field}]={coeff} is negative")
        return self


def load_development_config(path: Path = DEVELOPMENT_CONFIG_PATH) -> DevelopmentConfig:
    return DevelopmentConfig.model_validate(yaml.safe_load(path.read_text()))

"""Typed loader for jobs/registry/score_profiles.yaml.

Per-profile component weights + confidence-band scores for the scoring
engine (§15), versioned and kept out of code (invariant 8). Weights that
don't sum to 100 fail loudly here at load time.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

SCORE_PROFILES_PATH = Path(__file__).resolve().parent.parent / "registry" / "score_profiles.yaml"

# The five scored components (development is defined but has no feature yet,
# so it is always reweighted out — kept here so profiles can weight it the
# moment a growth-pipeline feature lands).
COMPONENTS = ("foot_traffic", "worker_demand", "competition", "transport", "development")
CONFIDENCE_BANDS = ("high", "medium", "low", "insufficient")


class ProfileWeights(BaseModel):
    foot_traffic: float
    worker_demand: float
    competition: float
    transport: float
    development: float

    @model_validator(mode="after")
    def _sums_to_100(self) -> ProfileWeights:
        total = sum(getattr(self, c) for c in COMPONENTS)
        if abs(total - 100) > 1e-6:
            raise ValueError(f"profile weights sum to {total}, expected 100")
        return self

    def as_dict(self) -> dict[str, float]:
        return {c: getattr(self, c) for c in COMPONENTS}


class ScoreConfig(BaseModel):
    version: str
    profiles: dict[str, ProfileWeights]
    confidence_scores: dict[str, float]

    @model_validator(mode="after")
    def _validate(self) -> ScoreConfig:
        if not self.profiles:
            raise ValueError("no profiles defined")
        missing = set(CONFIDENCE_BANDS) - set(self.confidence_scores)
        if missing:
            raise ValueError(f"confidence_scores missing bands: {sorted(missing)}")
        return self


def load_score_config(path: Path = SCORE_PROFILES_PATH) -> ScoreConfig:
    return ScoreConfig.model_validate(yaml.safe_load(path.read_text()))

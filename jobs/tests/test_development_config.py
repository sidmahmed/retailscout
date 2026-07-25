"""development_config.yaml loader: the committed registry file must be
valid, and invalid factor values must fail at load time, not mid-build."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from retailscout_jobs.development_config import (
    DevelopmentConfig,
    load_development_config,
)

_VALID = {
    "version": "test",
    "status_probability": {"APPLIED": 0.3, "COMPLETED": 1.0},
    "completed_since_year": 2024,
    "people_equivalents": {"resi_dwellings": 1.8},
    "distance_decay": {"radius_m": 800},
}


def test_committed_registry_file_is_valid():
    config = load_development_config()
    # The exact factor values are tunable hypotheses; what must hold is
    # that the statuses observed in the real source are all covered.
    assert {"APPLIED", "APPROVED", "UNDER CONSTRUCTION", "COMPLETED"} <= set(
        config.status_probability
    )
    assert config.distance_decay.radius_m > 0
    assert config.completed_since_year >= 2000


def test_probability_outside_unit_interval_rejected():
    bad = {**_VALID, "status_probability": {"APPLIED": 1.5}}
    with pytest.raises(ValidationError, match="outside"):
        DevelopmentConfig.model_validate(bad)


def test_negative_people_coefficient_rejected():
    bad = {**_VALID, "people_equivalents": {"resi_dwellings": -1}}
    with pytest.raises(ValidationError, match="negative"):
        DevelopmentConfig.model_validate(bad)


def test_nonpositive_radius_rejected():
    bad = {**_VALID, "distance_decay": {"radius_m": 0}}
    with pytest.raises(ValidationError, match="positive"):
        DevelopmentConfig.model_validate(bad)

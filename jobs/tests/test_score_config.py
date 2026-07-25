"""Score profile config resolver — pure unit tests."""

from __future__ import annotations

import pytest

from retailscout_jobs.score_config import COMPONENTS, ScoreConfig, load_score_config


def test_real_config_loads():
    c = load_score_config()
    assert c.version
    assert set(c.profiles) == {"cafe", "retail", "food_truck", "pop_up"}
    for weights in c.profiles.values():
        d = weights.as_dict()
        assert set(d) == set(COMPONENTS)
        assert sum(d.values()) == pytest.approx(100)
    assert set(c.confidence_scores) >= {"high", "medium", "low", "insufficient"}


def test_weights_not_summing_to_100_rejected():
    with pytest.raises(ValueError, match="sum to"):
        ScoreConfig.model_validate(
            {
                "version": "bad",
                "profiles": {
                    "cafe": {
                        "foot_traffic": 50,
                        "worker_demand": 50,
                        "competition": 50,
                        "transport": 0,
                        "development": 0,
                    }
                },
                "confidence_scores": {"high": 85, "medium": 60, "low": 35, "insufficient": 15},
            }
        )


def test_missing_confidence_band_rejected():
    with pytest.raises(ValueError, match="missing bands"):
        ScoreConfig.model_validate(
            {
                "version": "bad",
                "profiles": {
                    "cafe": {
                        "foot_traffic": 20,
                        "worker_demand": 20,
                        "competition": 20,
                        "transport": 20,
                        "development": 20,
                    }
                },
                "confidence_scores": {"high": 85, "medium": 60},
            }
        )

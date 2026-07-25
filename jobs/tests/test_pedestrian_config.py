"""Pedestrian daypart/day-type config resolver — pure unit tests."""

from __future__ import annotations

import pytest

from retailscout_jobs.pedestrian_config import PedestrianConfig, load_pedestrian_config


def test_real_config_resolves():
    c = load_pedestrian_config()
    assert c.version
    assert c.timezone == "Australia/Melbourne"
    assert c.trailing_months == 12
    h = c.hour_to_daypart()
    assert h[12] == "lunch"
    assert 10 not in h  # deliberate gap between morning and lunch
    assert c.isodow_to_daytype()[6] == "saturday"


def test_overlapping_dayparts_rejected():
    with pytest.raises(ValueError, match="both"):
        PedestrianConfig.model_validate(
            {
                "version": "bad",
                "timezone": "UTC",
                "trailing_months": 12,
                "dayparts": [
                    {"name": "a", "start_hour": 6, "end_hour": 12},
                    {"name": "b", "start_hour": 10, "end_hour": 14},
                ],
                "day_types": [{"name": "weekday", "isodows": [1]}],
            }
        )


def test_overlapping_day_types_rejected():
    with pytest.raises(ValueError, match="both"):
        PedestrianConfig.model_validate(
            {
                "version": "bad",
                "timezone": "UTC",
                "trailing_months": 12,
                "dayparts": [{"name": "a", "start_hour": 6, "end_hour": 10}],
                "day_types": [
                    {"name": "x", "isodows": [1, 2]},
                    {"name": "y", "isodows": [2, 3]},
                ],
            }
        )


def test_invalid_hour_range_rejected():
    with pytest.raises(ValueError, match="invalid hour range"):
        PedestrianConfig.model_validate(
            {
                "version": "bad",
                "timezone": "UTC",
                "trailing_months": 12,
                "dayparts": [{"name": "a", "start_hour": 14, "end_hour": 10}],
                "day_types": [{"name": "weekday", "isodows": [1]}],
            }
        )

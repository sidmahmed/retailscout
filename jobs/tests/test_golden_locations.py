"""Golden-location release regression gate (§20.3 / §21.2).

The fixture contract is always checked, including in an empty CI database.
The release regression test needs a built active release, so migration-only
databases skip it cleanly. When release data exists, the test re-runs the real
scorer inside a rolled-back transaction and checks stable cell placement,
qualitative score guardrails, confidence, and relative ordering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h3
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.score_config import load_score_config
from retailscout_jobs.scoring.score import build_scores

GOLDEN_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "golden_locations" / "golden_locations.yaml"
)
CONFIDENCE_BANDS = {"high", "medium", "low", "insufficient"}


def _load_golden_locations() -> dict[str, Any]:
    data = yaml.safe_load(GOLDEN_PATH.read_text())
    assert isinstance(data, dict)
    return data


@pytest.fixture
def db_conn():
    engine = get_engine()
    try:
        conn = engine.connect()
    except OperationalError:
        pytest.skip("no database reachable — start it with `make db-up && make db-migrate`")
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()


def _assert_range(value: float, expected: dict[str, float], label: str) -> None:
    if "min" in expected:
        assert value >= expected["min"], f"{label}: {value} is below {expected['min']}"
    if "max" in expected:
        assert value <= expected["max"], f"{label}: {value} is above {expected['max']}"


def test_golden_location_fixture_is_v1_and_snapped_to_h3_cells():
    golden = _load_golden_locations()

    assert golden["version"] == 1
    resolution = golden["grid_resolution"]
    assert resolution == 10
    assert golden["default_profile"] in load_score_config().profiles

    bands = golden["activity_bands"]
    assert set(bands) == {"very_high", "high", "medium", "low"}

    locations = golden["locations"]
    ids = [location["id"] for location in locations]
    assert len(ids) == len(set(ids))

    rejected = [location for location in locations if location["expectations"].get("rejected")]
    assert [location["id"] for location in rejected] == ["outside_boundary_control"]
    assert rejected[0]["cell_id"] is None

    snapped = [location for location in locations if location not in rejected]
    cell_ids = [location["cell_id"] for location in snapped]
    assert len(cell_ids) == len(set(cell_ids))

    for location in snapped:
        cell_id = location["cell_id"]
        assert h3.is_valid_cell(cell_id), location["id"]
        assert h3.get_resolution(cell_id) == resolution, location["id"]

        expected_lat, expected_lon = h3.cell_to_latlng(cell_id)
        assert location["lat"] == pytest.approx(expected_lat, abs=1e-6), location["id"]
        assert location["lon"] == pytest.approx(expected_lon, abs=1e-6), location["id"]

        expectations = location["expectations"]
        assert expectations["activity_band"] in bands
        assert expectations["confidence_band"] in CONFIDENCE_BANDS
        score_range = expectations["total_score_range"]
        assert set(score_range).issubset({"min", "max"})
        assert score_range["min"] < score_range["max"]

    comparison_ids = [comparison["id"] for comparison in golden["comparisons"]]
    assert len(comparison_ids) == len(set(comparison_ids))
    known_ids = set(ids)
    for comparison in golden["comparisons"]:
        assert set(comparison["higher"]) <= known_ids
        assert set(comparison["lower"]) <= known_ids
        assert comparison["minimum_margin"] >= 0


def test_active_release_holds_golden_location_regressions(db_conn):
    golden = _load_golden_locations()
    release_id = db_conn.execute(
        text("SELECT release_id FROM analytics.active_release WHERE only_one")
    ).scalar_one_or_none()
    if release_id is None:
        pytest.skip("no built active release — fixture contract was still validated")

    baseline_version = db_conn.execute(
        text("""
            SELECT baseline_version
            FROM analytics.cell_pedestrian_daypart
            WHERE release_id = :release_id
            ORDER BY calculated_at DESC
            LIMIT 1
        """),
        {"release_id": release_id},
    ).scalar_one_or_none()
    assert baseline_version is not None, "active release has no pedestrian features"

    config = load_score_config()
    profile = golden["default_profile"]
    build_scores(db_conn, config=config, baseline_version=baseline_version)

    scores: dict[str, float] = {}
    for location in golden["locations"]:
        point_cell = db_conn.execute(
            text("""
                SELECT cell_id
                FROM analytics.analysis_cell
                WHERE release_id = :release_id
                  AND ST_Covers(
                      geom,
                      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                  )
            """),
            {
                "release_id": release_id,
                "lat": location["lat"],
                "lon": location["lon"],
            },
        ).scalar_one_or_none()

        expectations = location["expectations"]
        if expectations.get("rejected"):
            assert point_cell is None, f"{location['id']} unexpectedly resolved to {point_cell}"
            continue

        assert point_cell == location["cell_id"], (
            f"{location['id']} moved from {location['cell_id']} to {point_cell}"
        )

        row = (
            db_conn.execute(
                text("""
                    SELECT total_score, foot_traffic_score, competition_score,
                           confidence_score, explanation
                    FROM analytics.location_score
                    WHERE release_id = :release_id
                      AND cell_id = :cell_id
                      AND business_profile = :profile
                      AND score_version = :score_version
                """),
                {
                    "release_id": release_id,
                    "cell_id": location["cell_id"],
                    "profile": profile,
                    "score_version": config.version,
                },
            )
            .mappings()
            .one()
        )

        total_score = float(row["total_score"])
        scores[location["id"]] = total_score
        _assert_range(
            total_score,
            expectations["total_score_range"],
            f"{location['id']} total score",
        )

        activity = row["foot_traffic_score"]
        activity_band = golden["activity_bands"][expectations["activity_band"]]
        if activity is None:
            assert activity_band.get("allow_missing", False), (
                f"{location['id']} unexpectedly has no pedestrian score"
            )
        else:
            _assert_range(
                float(activity),
                activity_band,
                f"{location['id']} pedestrian activity",
            )

        confidence_band = row["explanation"]["confidence"]["band"]
        assert confidence_band == expectations["confidence_band"], (
            f"{location['id']} confidence changed to {confidence_band}"
        )

        if "competition_score_max" in expectations:
            assert float(row["competition_score"]) <= expectations["competition_score_max"], (
                f"{location['id']} no longer has the expected competition pressure"
            )

    for comparison in golden["comparisons"]:
        for higher_id in comparison["higher"]:
            for lower_id in comparison["lower"]:
                actual_margin = scores[higher_id] - scores[lower_id]
                assert actual_margin >= comparison["minimum_margin"], (
                    f"{comparison['id']}: {higher_id} only beats {lower_id} by {actual_margin:.1f}"
                )

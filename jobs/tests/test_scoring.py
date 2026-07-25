"""Scoring engine, against a real PostGIS database.

Instead of the real 2,317-cell grid, this builds a tiny synthetic
release of 4 hand-chosen cells (A>B>C>D) with controlled feature values,
so the within-city percentile normalisation, the missing-component
reweighting, the per-profile weighting, and the competition inversion all
have exact expected outputs. Everything is created inside the rolled-back
transaction and the fixture release is made active for the duration.

percent_rank over 4 distinct values gives 0, 33.3, 66.7, 100.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.scoring.score import build_scores
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
BV = "test"  # baseline_version used by fixture pedestrian rows


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


def _source_release(db_conn, tmp_path) -> int:
    registry = load_registry()
    source = registry.get("municipal_boundary")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps([{"mccid_gis": 999, "name": "Test"}]))
    snapshot_dir = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url="https://example.test/exports/json",
        data_file=data_file,
        export_format="json",
        fields=source.fields_observed,
        now=FIXED_NOW,
    )
    upsert_dataset(db_conn, registry, source)
    return record_release(db_conn, source, snapshot_dir, raw_root)


def _make_active_release(db_conn, src: int) -> int:
    rel = db_conn.execute(
        text("""
            INSERT INTO analytics.data_release
                (status, grid_resolution, boundary_source_release_id)
            VALUES ('published', 10, :src) RETURNING release_id
        """),
        {"src": src},
    ).scalar_one()
    db_conn.execute(
        text("""
            INSERT INTO analytics.active_release (only_one, release_id) VALUES (true, :rel)
            ON CONFLICT (only_one) DO UPDATE SET release_id = EXCLUDED.release_id
        """),
        {"rel": rel},
    )
    return rel


def _add_cell(db_conn, rel: int, cell_id: str, lon: float, lat: float) -> None:
    db_conn.execute(
        text("""
            INSERT INTO analytics.analysis_cell (release_id, cell_id, geom, centroid)
            VALUES (:rel, :cid,
                ST_SetSRID(ST_MakeEnvelope(:lon-0.001, :lat-0.001, :lon+0.001, :lat+0.001), 4326),
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        """),
        {"rel": rel, "cid": cell_id, "lon": lon, "lat": lat},
    )


def _add_feature(db_conn, rel, cid, jobs_800m, cafe, takeaway, tram, bus, train) -> None:
    db_conn.execute(
        text("""
            INSERT INTO analytics.location_feature
                (release_id, cell_id, feature_version, jobs_800m,
                 cafe_restaurant_400m, takeaway_food_400m,
                 tram_stops_400m, bus_stops_400m, train_stops_800m)
            VALUES (:rel, :cid, 'v1', :jobs, :cafe, :takeaway, :tram, :bus, :train)
        """),
        {
            "rel": rel,
            "cid": cid,
            "jobs": jobs_800m,
            "cafe": cafe,
            "takeaway": takeaway,
            "tram": tram,
            "bus": bus,
            "train": train,
        },
    )


def _add_ped(db_conn, rel, cid, estimate, band) -> None:
    """One weekday/lunch row is enough: the scorer's foot_traffic metric is
    the weekday estimate, and confidence is the weekday/lunch band."""
    db_conn.execute(
        text("""
            INSERT INTO analytics.cell_pedestrian_daypart
                (release_id, cell_id, day_type, daypart, baseline_version,
                 pedestrian_estimate, n_sensors, nearest_sensor_m, foot_traffic_confidence)
            VALUES (:rel, :cid, 'weekday', 'lunch', :bv, :est, 3, 100, :band)
        """),
        {"rel": rel, "cid": cid, "est": estimate, "bv": BV, "band": band},
    )


def _score(db_conn, rel, cid, profile="cafe"):
    return (
        db_conn.execute(
            text("""
            SELECT total_score, foot_traffic_score, worker_demand_score, competition_score,
                   transport_score, development_score, confidence_score, explanation
            FROM analytics.location_score
            WHERE release_id = :rel AND cell_id = :cid AND business_profile = :p
        """),
            {"rel": rel, "cid": cid, "p": profile},
        )
        .mappings()
        .one()
    )


def _setup_four_cells(db_conn, tmp_path) -> int:
    src = _source_release(db_conn, tmp_path)
    rel = _make_active_release(db_conn, src)
    # A best .. D worst. jobs, saturation, transit all descend A->D.
    _add_cell(db_conn, rel, "A", 144.960, -37.810)
    _add_cell(db_conn, rel, "B", 144.962, -37.810)
    _add_cell(db_conn, rel, "C", 144.964, -37.810)
    _add_cell(db_conn, rel, "D", 144.966, -37.810)
    #             jobs  cafe takeaway tram bus train
    _add_feature(db_conn, rel, "A", 400, 0, 0, 20, 20, 0)  # saturation 0, transit 40
    _add_feature(db_conn, rel, "B", 300, 5, 5, 15, 15, 0)  # saturation 10, transit 30
    _add_feature(db_conn, rel, "C", 200, 10, 10, 10, 10, 0)  # saturation 20, transit 20
    _add_feature(db_conn, rel, "D", 100, 20, 20, 5, 5, 0)  # saturation 40, transit 10
    _add_ped(db_conn, rel, "A", 1000, "high")
    _add_ped(db_conn, rel, "B", 500, "medium")
    # C: NO pedestrian row -> insufficient
    _add_ped(db_conn, rel, "D", 100, "low")
    return rel


def test_component_percentiles_and_competition_inversion(db_conn, tmp_path):
    rel = _setup_four_cells(db_conn, tmp_path)
    build_scores(db_conn, baseline_version=BV)

    a, d = _score(db_conn, rel, "A"), _score(db_conn, rel, "D")
    # Best cell tops every component; worst bottoms out.
    assert float(a["worker_demand_score"]) == pytest.approx(100)
    assert float(a["transport_score"]) == pytest.approx(100)
    assert float(d["worker_demand_score"]) == pytest.approx(0)
    # Competition is INVERTED: A has 0 competitors -> 100; D is most saturated -> 0.
    assert float(a["competition_score"]) == pytest.approx(100)
    assert float(d["competition_score"]) == pytest.approx(0)


def test_all_max_cell_scores_100(db_conn, tmp_path):
    rel = _setup_four_cells(db_conn, tmp_path)
    build_scores(db_conn, baseline_version=BV)
    a = _score(db_conn, rel, "A")
    assert float(a["total_score"]) == pytest.approx(100)
    assert float(a["confidence_score"]) == 85  # 'high' band
    assert a["development_score"] is None  # no growth-pipeline feature


def test_missing_foot_traffic_is_reweighted_not_zeroed(db_conn, tmp_path):
    rel = _setup_four_cells(db_conn, tmp_path)
    build_scores(db_conn, baseline_version=BV)
    c = _score(db_conn, rel, "C")
    # C has no pedestrian estimate; its worker/comp/transport are all the
    # 33.3 percentile. Total = weighted mean over just those three (foot and
    # development reweighted out) = 33.3, NOT dragged toward 0 by a missing
    # foot_traffic treated as 0.
    assert c["foot_traffic_score"] is None
    assert float(c["total_score"]) == pytest.approx(33.3, abs=0.2)
    assert float(c["confidence_score"]) == 15  # insufficient


def test_profiles_weight_differently(db_conn, tmp_path):
    rel = _setup_four_cells(db_conn, tmp_path)
    build_scores(db_conn, baseline_version=BV)
    # Cell B has an uneven component mix (foot 50 vs others 66.7), so the
    # café and food-truck profiles (different foot weights) diverge.
    cafe = float(_score(db_conn, rel, "B", "cafe")["total_score"])
    truck = float(_score(db_conn, rel, "B", "food_truck")["total_score"])
    assert cafe != truck


def test_explanation_shape_is_api_ready(db_conn, tmp_path):
    rel = _setup_four_cells(db_conn, tmp_path)
    build_scores(db_conn, baseline_version=BV)
    exp = _score(db_conn, rel, "A")["explanation"]
    keys = {comp["key"] for comp in exp["components"]}
    assert keys == {
        "pedestrian_demand",
        "worker_demand",
        "competition",
        "transport",
        "development",
    }
    assert exp["confidence"]["band"] == "high"
    assert exp["confidence"]["score"] == 85
    # Every component carries its weight and evidence for the API.
    assert all("weight" in comp and "evidence" in comp for comp in exp["components"])


def test_totals_within_bounds_for_all_rows(db_conn, tmp_path):
    rel = _setup_four_cells(db_conn, tmp_path)
    build_scores(db_conn, baseline_version=BV)
    bad = db_conn.execute(
        text("""
            SELECT count(*) FROM analytics.location_score
            WHERE release_id = :rel AND (total_score < 0 OR total_score > 100)
        """),
        {"rel": rel},
    ).scalar_one()
    assert bad == 0
    n = db_conn.execute(
        text("SELECT count(*) FROM analytics.location_score WHERE release_id = :rel"),
        {"rel": rel},
    ).scalar_one()
    assert n == 16  # 4 cells × 4 profiles

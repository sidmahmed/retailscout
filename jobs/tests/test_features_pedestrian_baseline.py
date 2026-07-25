"""Per-sensor pedestrian daypart baseline loader, against real PostGIS.

Isolation: fixture observations use a fictional sensor_id and are dated
in 2099. Because the trailing window is measured back from
max(observed_at), inserting 2099 rows moves the window to 2098-2099,
which EXCLUDES the real 2024-2026 observations — so only the fixtures
aggregate. Rolled back after.

Local-time correctness is tested directly: observations are inserted at
known Melbourne local wall-clock times (converted to the UTC instant the
column stores), and we assert they land in the expected daypart/day-type.
"""

from __future__ import annotations

import datetime as dt
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from retailscout_jobs.db import get_engine
from retailscout_jobs.features.pedestrian_baseline import build_sensor_baselines
from retailscout_jobs.provenance import record_release, upsert_dataset
from retailscout_jobs.registry import load_registry
from retailscout_jobs.snapshot import write_snapshot

FIXED_NOW = dt.datetime(2099, 1, 1, 3, 0, 0, tzinfo=dt.UTC)
MEL = ZoneInfo("Australia/Melbourne")
SENSOR = 999001


def _first_weekday_and_saturday_of_2099():
    monday = date(2099, 1, 1)
    while monday.isoweekday() != 1:
        monday += timedelta(days=1)
    saturday = date(2099, 1, 1)
    while saturday.isoweekday() != 6:
        saturday += timedelta(days=1)
    return monday, saturday


def _utc(d: date, local_hour: int) -> datetime:
    """The UTC instant for local Melbourne (d, local_hour:00)."""
    return datetime(d.year, d.month, d.day, local_hour, 0, tzinfo=MEL).astimezone(dt.UTC)


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


def _fake_release(db_conn, tmp_path) -> int:
    registry = load_registry()
    source = registry.get("pedestrian_hourly")
    raw_root = tmp_path / "raw"
    data_file = tmp_path / "data.csv"
    data_file.write_text("placeholder")
    snapshot_dir = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url="https://example.test/exports/csv",
        data_file=data_file,
        export_format="csv",
        fields=source.fields_observed,
        now=FIXED_NOW,
    )
    upsert_dataset(db_conn, registry, source)
    return record_release(db_conn, source, snapshot_dir, raw_root)


def _add_obs(db_conn, src: int, observed_at_utc: datetime, count: int) -> None:
    db_conn.execute(
        text("""
            INSERT INTO core.pedestrian_observation
                (sensor_id, observed_at, pedestrian_count, source_release_id)
            VALUES (:sid, :at, :count, :src)
        """),
        {"sid": SENSOR, "at": observed_at_utc, "count": count, "src": src},
    )


def _baseline(db_conn, day_type: str, daypart: str):
    return db_conn.execute(
        text("""
            SELECT median_count, mean_count, p25_count, p75_count, n_observations, n_days
            FROM analytics.sensor_daypart_baseline
            WHERE sensor_id = :s AND day_type = :dt AND daypart = :dp AND baseline_version = 'v1'
        """),
        {"s": SENSOR, "dt": day_type, "dp": daypart},
    ).one_or_none()


def test_aggregates_by_local_daypart_and_day_type(db_conn, tmp_path):
    src = _fake_release(db_conn, tmp_path)
    monday, saturday = _first_weekday_and_saturday_of_2099()

    # Three weekday-lunch observations (local 12:00) on distinct weekdays.
    for i, count in enumerate((100, 200, 300)):
        _add_obs(db_conn, src, _utc(monday + timedelta(days=7 * i), 12), count)
    # One weekday observation at local 10:00 — a daypart GAP, must be excluded.
    _add_obs(db_conn, src, _utc(monday, 10), 9999)
    # One Saturday-morning observation (local 08:00).
    _add_obs(db_conn, src, _utc(saturday, 8), 50)

    build_sensor_baselines(db_conn)

    wl = _baseline(db_conn, "weekday", "lunch")
    assert float(wl.median_count) == 200
    assert float(wl.mean_count) == 200
    assert float(wl.p25_count) == 150
    assert float(wl.p75_count) == 250
    assert wl.n_observations == 3
    assert wl.n_days == 3

    sm = _baseline(db_conn, "saturday", "morning")
    assert float(sm.median_count) == 50
    assert sm.n_observations == 1

    # The 10:00 gap observation created no weekday baseline at all.
    assert _baseline(db_conn, "weekday", "morning") is None
    assert _baseline(db_conn, "weekday", "afternoon") is None


def test_is_idempotent(db_conn, tmp_path):
    src = _fake_release(db_conn, tmp_path)
    monday, _ = _first_weekday_and_saturday_of_2099()
    _add_obs(db_conn, src, _utc(monday, 12), 100)

    build_sensor_baselines(db_conn)
    build_sensor_baselines(db_conn)

    rows = db_conn.execute(
        text(
            "SELECT count(*) FROM analytics.sensor_daypart_baseline "
            "WHERE sensor_id = :s AND baseline_version = 'v1'"
        ),
        {"s": SENSOR},
    ).scalar_one()
    assert rows == 1  # single weekday/lunch row, not duplicated
    assert float(_baseline(db_conn, "weekday", "lunch").median_count) == 100


def test_raises_on_empty_observations(db_conn, tmp_path):
    _fake_release(db_conn, tmp_path)
    db_conn.execute(text("DELETE FROM core.pedestrian_observation"))
    with pytest.raises(ValueError, match="pedestrian_observation is empty"):
        build_sensor_baselines(db_conn)

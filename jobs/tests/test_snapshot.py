"""Snapshot layout and manifest integrity, without touching the network."""

import datetime as dt
import json
from pathlib import Path

import pytest

from retailscout_jobs.snapshot import (
    adopt_snapshot,
    schema_fingerprint,
    sha256_file,
    write_snapshot,
)

FIXED_NOW = dt.datetime(2026, 7, 25, 3, 0, 0, tzinfo=dt.UTC)


def _write_source_file(
    tmp_path: Path, name: str = "download.csv", content: bytes = b"a,b\n1,2\n"
) -> Path:
    f = tmp_path / name
    f.write_bytes(content)
    return f


def test_snapshot_layout_and_manifest(tmp_path):
    raw_root = tmp_path / "raw"
    data = _write_source_file(tmp_path)

    target = write_snapshot(
        raw_root=raw_root,
        provider="city_of_melbourne",
        source_id="example_source",
        remote_dataset_id="example-dataset",
        source_url="https://example.test/exports/csv",
        data_file=data,
        export_format="csv",
        fields=["b", "a"],
        now=FIXED_NOW,
    )

    assert target == raw_root / "city_of_melbourne" / "example_source" / "retrieved_date=2026-07-25"
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["retrieval_mode"] == "api_export"
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["name"] == "data.csv"
    assert manifest["files"][0]["sha256"] == sha256_file(target / "data.csv")
    assert manifest["retrieved_at_utc"] == FIXED_NOW.isoformat()
    # fingerprint is order-insensitive: registry field order must not matter
    assert manifest["schema_fingerprint"] == schema_fingerprint(["a", "b"])
    # the temp download was moved, not copied — no stray bytes left behind
    assert not data.exists()


def test_same_day_rerun_replaces_snapshot_wholesale(tmp_path):
    raw_root = tmp_path / "raw"
    first = _write_source_file(tmp_path, content=b"old")
    write_snapshot(
        raw_root=raw_root,
        provider="p",
        source_id="s",
        remote_dataset_id="d",
        source_url="u",
        data_file=first,
        export_format="csv",
        fields=None,
        now=FIXED_NOW,
    )
    second = _write_source_file(tmp_path, content=b"new")
    target = write_snapshot(
        raw_root=raw_root,
        provider="p",
        source_id="s",
        remote_dataset_id="d",
        source_url="u",
        data_file=second,
        export_format="csv",
        fields=None,
        now=FIXED_NOW,
    )
    assert (target / "data.csv").read_bytes() == b"new"
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["schema_fingerprint"] is None


def test_adopt_copies_files_and_keeps_originals(tmp_path):
    raw_root = tmp_path / "raw"
    zips = [
        _write_source_file(tmp_path, "Archive_2023.zip", b"year-2023"),
        _write_source_file(tmp_path, "Archive_2024.zip", b"year-2024"),
    ]

    target = adopt_snapshot(
        raw_root=raw_root,
        provider="city_of_melbourne",
        source_id="transport_activity",
        remote_dataset_id="transport-activity-counts",
        source_files=zips,
        export_format="csv",
        fields=["from", "to", "class", "count"],
        note="Operator download from portal attachments",
        retrieved_date=dt.date(2026, 5, 11),
        now=FIXED_NOW,
    )

    # directory reflects when the operator OBTAINED the data, not today
    assert target.name == "retrieved_date=2026-05-11"
    # originals untouched; copies keep their names
    for z in zips:
        assert z.exists()
        assert (target / z.name).read_bytes() == z.read_bytes()

    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["retrieval_mode"] == "manual_adopt"
    assert manifest["source_url"] == "manual-adopt"
    assert manifest["note"] == "Operator download from portal attachments"
    names = {f["name"] for f in manifest["files"]}
    assert names == {"Archive_2023.zip", "Archive_2024.zip"}
    for entry in manifest["files"]:
        assert entry["sha256"] == sha256_file(target / entry["name"])


def test_adopt_refuses_missing_or_empty_inputs(tmp_path):
    kwargs = dict(
        raw_root=tmp_path / "raw",
        provider="p",
        source_id="s",
        remote_dataset_id="d",
        export_format="csv",
        fields=None,
        note="n",
        retrieved_date=dt.date(2026, 5, 11),
    )
    with pytest.raises(ValueError):
        adopt_snapshot(source_files=[], **kwargs)
    with pytest.raises(FileNotFoundError):
        adopt_snapshot(source_files=[tmp_path / "nope.zip"], **kwargs)

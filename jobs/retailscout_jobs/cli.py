"""Data-worker CLI.

    python -m retailscout_jobs.cli list
    python -m retailscout_jobs.cli ingest <source_id>
    python -m retailscout_jobs.cli adopt <source_id> --retrieved-date YYYY-MM-DD \
        --note "where these files came from" FILE [FILE...]
    python -m retailscout_jobs.cli load <source_id>
    python -m retailscout_jobs.cli freshness <source_id>

`ingest` downloads a full export and writes an immutable raw snapshot
under RAW_DATA_DIR. `adopt` does the same for operator-provided files
when a source's upstream feed is unusable (status: manual). Both then
record provenance (source.dataset / source.dataset_release /
source.ingestion_run — see db/migrations/versions/0002) via
DATABASE_DIRECT_URL. Neither parses file contents.

`load` reads the most recent source.dataset_release for a source and
upserts it into its core.* table via the registered loader in
transform/ (see db/migrations/versions/0003). It requires `ingest`/
`adopt` to have run first — "copy the bytes", "record what was
copied", and "interpret the bytes" are independently re-runnable
pipeline stages by design.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from .opendatasoft import OpenDataSoftClient
from .registry import SourceDefinition, SourceRegistry, SourceStatus, load_registry


def _raw_root() -> Path:
    return Path(os.environ.get("RAW_DATA_DIR", "../data/raw")).resolve()


def _record_provenance(
    registry: SourceRegistry, source: SourceDefinition, snapshot_dir: Path, raw_root: Path
) -> None:
    from .db import get_engine
    from .provenance import record_release, upsert_dataset

    engine = get_engine()
    try:
        with engine.begin() as conn:
            upsert_dataset(conn, registry, source)
            release_id = record_release(conn, source, snapshot_dir, raw_root)
    finally:
        engine.dispose()
    print(f"Provenance recorded: source.dataset_release#{release_id}")


def cmd_list() -> int:
    registry = load_registry()
    for s in registry.sources:
        print(f"{s.id:28} {s.status.value:12} {s.fetch_mode:8} {s.remote_dataset_id}")
    return 0


def cmd_ingest(source_id: str) -> int:
    registry = load_registry()
    source = registry.get(source_id)
    defaults = registry.provider_defaults

    if source.status == SourceStatus.BLOCKED:
        print(f"REFUSING: '{source_id}' is blocked: {source.notes.strip()}", file=sys.stderr)
        return 2
    if source.status == SourceStatus.MANUAL:
        print(
            f"REFUSING: '{source_id}' is a manual source — its API feed is unusable. "
            "Use `adopt` with operator-provided files instead.",
            file=sys.stderr,
        )
        return 2
    if source.status == SourceStatus.DEFERRED:
        print(
            f"REFUSING: '{source_id}' is deferred: {source.notes.strip()}",
            file=sys.stderr,
        )
        return 2
    if source.status == SourceStatus.UNVALIDATED:
        print(
            f"WARNING: '{source_id}' is unvalidated — profile fields after this run "
            "and update sources.yaml.",
            file=sys.stderr,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{source.export_format}") as tmp:
        tmp_path = Path(tmp.name)

    if source.fetch_mode == "http_file":
        assert source.download_url is not None  # guaranteed by registry validator
        url = source.download_url
        print(f"Fetching {url}")
        _download_file(url, tmp_path)
    else:
        url = (
            f"{defaults.base_url}/catalog/datasets/{source.remote_dataset_id}"
            f"/exports/{source.export_format}"
        )
        print(f"Fetching {url}")
        with OpenDataSoftClient(base_url=defaults.base_url) as client:
            client.export(source.remote_dataset_id, source.export_format, tmp_path)

    from .snapshot import write_snapshot

    raw_root = _raw_root()
    target = write_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_url=url,
        data_file=tmp_path,
        export_format=source.export_format,
        fields=source.fields_observed,
        retrieval_mode="http_download" if source.fetch_mode == "http_file" else "api_export",
    )
    print(f"Snapshot written: {target}")
    _record_provenance(registry, source, target, raw_root)
    return 0


def _download_file(url: str, destination: Path, timeout: float = 600.0) -> None:
    """Stream a plain HTTP(S) file (e.g. the PTV GTFS zip) to disk."""
    import httpx

    with (
        httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response,
        open(destination, "wb") as f,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes():
            f.write(chunk)


def cmd_adopt(source_id: str, files: list[str], retrieved_date: str, note: str) -> int:
    import datetime as dt

    from .snapshot import adopt_snapshot

    registry = load_registry()
    source = registry.get(source_id)

    if source.status != SourceStatus.MANUAL:
        print(
            f"REFUSING: '{source_id}' has status '{source.status.value}', not 'manual'. "
            "adopt is only for sources whose upstream feed is unusable — "
            "use `ingest`, or change the status in sources.yaml deliberately.",
            file=sys.stderr,
        )
        return 2

    raw_root = _raw_root()
    target = adopt_snapshot(
        raw_root=raw_root,
        provider=registry.provider_for(source),
        source_id=source.id,
        remote_dataset_id=source.remote_dataset_id,
        source_files=[Path(f) for f in files],
        export_format=source.export_format,
        fields=source.fields_observed,
        note=note,
        retrieved_date=dt.date.fromisoformat(retrieved_date),
    )
    print(f"Snapshot written: {target}")
    _record_provenance(registry, source, target, raw_root)
    return 0


def cmd_load(source_id: str) -> int:
    from .transform import LOADERS

    loader = LOADERS.get(source_id)
    if loader is None:
        known = ", ".join(sorted(LOADERS)) or "(none yet)"
        print(
            f"REFUSING: no core-schema loader implemented for '{source_id}' yet. "
            f"Implemented: {known}",
            file=sys.stderr,
        )
        return 2

    from .db import get_engine

    raw_root = _raw_root()
    engine = get_engine()
    try:
        with engine.begin() as conn:
            release = conn.execute(
                text(
                    "SELECT release_id, object_path FROM source.dataset_release "
                    "WHERE dataset_id = :id ORDER BY retrieved_at DESC LIMIT 1"
                ),
                {"id": source_id},
            ).one_or_none()
            if release is None:
                print(
                    f"REFUSING: no source.dataset_release for '{source_id}' — "
                    "run `ingest` or `adopt` first.",
                    file=sys.stderr,
                )
                return 2
            snapshot_dir = raw_root / release.object_path
            row_count = loader(conn, snapshot_dir, release.release_id)
    finally:
        engine.dispose()

    print(f"Loaded {row_count} row(s) into core from {source_id} release#{release.release_id}")
    return 0


def cmd_build_grid(resolution: int, notes: str | None, activate: bool) -> int:
    from .db import get_engine
    from .features.grid import build_grid

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = build_grid(conn, resolution=resolution, notes=notes, activate=activate)
    finally:
        engine.dispose()

    print(
        f"Built analytics.data_release#{result.release_id}: "
        f"{result.cell_count} cells at H3 res {result.resolution} "
        f"({'activated' if result.activated else 'NOT activated'})"
    )
    return 0


def cmd_build_features(feature_version: str) -> int:
    from .db import get_engine
    from .features.business_features import build_business_features

    engine = get_engine()
    try:
        with engine.begin() as conn:
            result = build_business_features(conn, feature_version=feature_version)
    finally:
        engine.dispose()

    print(
        f"Built business features for release#{result.release_id} "
        f"(feature_version={result.feature_version}, census_year={result.census_year}, "
        f"{result.catchment_metres}m): {result.cells_written} cells"
    )
    return 0


def cmd_freshness(source_id: str) -> int:
    registry = load_registry()
    source = registry.get(source_id)

    if source.freshness.strategy == "http_header":
        import httpx

        assert source.download_url is not None
        response = httpx.head(source.download_url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        print(f"{source_id}: Last-Modified = {response.headers.get('last-modified')}")
        return 0

    with OpenDataSoftClient(base_url=registry.provider_defaults.base_url) as client:
        if source.freshness.strategy == "max_field":
            assert source.freshness.field is not None
            value = client.max_field_value(source.remote_dataset_id, source.freshness.field)
            print(f"{source_id}: max({source.freshness.field}) = {value}")
        else:
            meta = client.dataset_metadata(source.remote_dataset_id)
            modified = meta.get("metas", {}).get("default", {}).get("modified")
            print(f"{source_id}: metas.modified = {modified} (treat with suspicion)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retailscout-jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List registered sources")
    p_ingest = sub.add_parser("ingest", help="Snapshot one source to RAW_DATA_DIR")
    p_ingest.add_argument("source_id")
    p_adopt = sub.add_parser(
        "adopt", help="Snapshot operator-provided files for a status:manual source"
    )
    p_adopt.add_argument("source_id")
    p_adopt.add_argument("files", nargs="+", help="Local files to adopt (copied, not moved)")
    p_adopt.add_argument(
        "--retrieved-date",
        required=True,
        help="ISO date the operator obtained the files (data provenance, not today)",
    )
    p_adopt.add_argument("--note", required=True, help="Where the files came from")
    p_load = sub.add_parser(
        "load", help="Load the most recent raw snapshot for a source into its core.* table"
    )
    p_load.add_argument("source_id")
    p_grid = sub.add_parser(
        "build-grid",
        help="Build the hex analysis grid (analytics.analysis_cell) from core.municipal_boundary",
    )
    from .features.grid import DEFAULT_RESOLUTION

    p_grid.add_argument(
        "--resolution", type=int, default=DEFAULT_RESOLUTION, help="H3 resolution (default: 10)"
    )
    p_grid.add_argument("--notes", default=None, help="Free-text note stored on the data_release")
    p_grid.add_argument(
        "--no-activate",
        action="store_true",
        help="Build the release but do NOT flip active_release to it",
    )
    p_feat = sub.add_parser(
        "build-features",
        help="Compute business/competition features into analytics.location_feature",
    )
    p_feat.add_argument(
        "--feature-version", default="v1", help="feature_version tag for the rows (default: v1)"
    )
    p_fresh = sub.add_parser("freshness", help="Probe upstream freshness for one source")
    p_fresh.add_argument("source_id")

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "ingest":
        return cmd_ingest(args.source_id)
    if args.command == "adopt":
        return cmd_adopt(args.source_id, args.files, args.retrieved_date, args.note)
    if args.command == "load":
        return cmd_load(args.source_id)
    if args.command == "build-grid":
        return cmd_build_grid(args.resolution, args.notes, not args.no_activate)
    if args.command == "build-features":
        return cmd_build_features(args.feature_version)
    if args.command == "freshness":
        return cmd_freshness(args.source_id)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Immutable raw snapshot writer.

Layout (architecture.md §8.2), rooted at RAW_DATA_DIR (locally
data/raw/; object storage in deployed environments):

    raw/{provider}/{source_id}/retrieved_date=YYYY-MM-DD/
        <one or more data files>
        manifest.json

Two entry points:
- write_snapshot()  — API export path: one downloaded temp file, moved
                      in and renamed data.{format}.
- adopt_snapshot()  — manual path: operator-provided files (e.g. bulk
                      archives for a source whose API feed is dead) are
                      COPIED in under their original names; originals
                      are left untouched.

Manifests make every downstream row traceable to the exact bytes that
produced it. A snapshot directory is never modified after writing —
re-running on the same day overwrites the whole directory atomically
(delete + rewrite), never patches files in place.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

SOFTWARE_VERSION = "0.1.0"


@dataclass(frozen=True)
class FileEntry:
    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Manifest:
    source_id: str
    provider: str
    remote_dataset_id: str
    source_url: str
    retrieval_mode: str  # "api_export" | "http_download" | "manual_adopt"
    retrieved_at_utc: str
    files: list[FileEntry]
    export_format: str
    schema_fingerprint: str | None  # sha256 of sorted field names, if known
    ingestion_software_version: str
    note: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_fingerprint(field_names: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(field_names)).encode()).hexdigest()


def snapshot_dir(raw_root: Path, provider: str, source_id: str, retrieved: dt.date) -> Path:
    return raw_root / provider / source_id / f"retrieved_date={retrieved.isoformat()}"


def _fresh_dir(raw_root: Path, provider: str, source_id: str, retrieved: dt.date) -> Path:
    target = snapshot_dir(raw_root, provider, source_id, retrieved)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target


def _write_manifest(target: Path, manifest: Manifest) -> None:
    with open(target / "manifest.json", "w") as f:
        json.dump(asdict(manifest), f, indent=2)


def _entry(path: Path) -> FileEntry:
    return FileEntry(name=path.name, sha256=sha256_file(path), size_bytes=path.stat().st_size)


def write_snapshot(
    raw_root: Path,
    provider: str,
    source_id: str,
    remote_dataset_id: str,
    source_url: str,
    data_file: Path,
    export_format: str,
    fields: list[str] | None,
    now: dt.datetime | None = None,
    retrieval_mode: str = "api_export",
) -> Path:
    """Move a downloaded export into the snapshot layout and write its manifest.

    Returns the snapshot directory. Overwrites any same-day snapshot
    wholesale (idempotent re-runs).
    """
    now = now or dt.datetime.now(dt.UTC)
    target = _fresh_dir(raw_root, provider, source_id, now.date())

    data_dest = target / f"data.{export_format}"
    shutil.move(str(data_file), data_dest)

    _write_manifest(
        target,
        Manifest(
            source_id=source_id,
            provider=provider,
            remote_dataset_id=remote_dataset_id,
            source_url=source_url,
            retrieval_mode=retrieval_mode,
            retrieved_at_utc=now.isoformat(),
            files=[_entry(data_dest)],
            export_format=export_format,
            schema_fingerprint=schema_fingerprint(fields) if fields else None,
            ingestion_software_version=SOFTWARE_VERSION,
        ),
    )
    return target


def adopt_snapshot(
    raw_root: Path,
    provider: str,
    source_id: str,
    remote_dataset_id: str,
    source_files: list[Path],
    export_format: str,
    fields: list[str] | None,
    note: str,
    retrieved_date: dt.date,
    now: dt.datetime | None = None,
) -> Path:
    """Copy operator-provided files into the snapshot layout.

    For sources whose upstream feed is unusable (status: manual).
    Files keep their original names; originals are not touched.
    `retrieved_date` is when the OPERATOR obtained the files (not
    today) so the snapshot directory reflects data provenance; `note`
    must say where the files came from.
    """
    if not source_files:
        raise ValueError("adopt_snapshot requires at least one file")
    for path in source_files:
        if not path.is_file():
            raise FileNotFoundError(path)

    now = now or dt.datetime.now(dt.UTC)
    target = _fresh_dir(raw_root, provider, source_id, retrieved_date)

    entries: list[FileEntry] = []
    for path in source_files:
        dest = target / path.name
        shutil.copy2(path, dest)
        entries.append(_entry(dest))

    _write_manifest(
        target,
        Manifest(
            source_id=source_id,
            provider=provider,
            remote_dataset_id=remote_dataset_id,
            source_url="manual-adopt",
            retrieval_mode="manual_adopt",
            retrieved_at_utc=now.isoformat(),
            files=entries,
            export_format=export_format,
            schema_fingerprint=schema_fingerprint(fields) if fields else None,
            ingestion_software_version=SOFTWARE_VERSION,
            note=note,
        ),
    )
    return target

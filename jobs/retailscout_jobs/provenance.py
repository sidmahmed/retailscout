"""Records raw-snapshot provenance into the `source` schema (migration 0002).

Reads the manifest.json that snapshot.write_snapshot()/adopt_snapshot()
already wrote to disk — the manifest file is the single source of truth
for what a snapshot contains, so this module never re-derives it.

Scope: this records SUCCESSFUL ingest/adopt runs only. Failed or
refused runs (blocked/manual/deferred sources, network errors) are not
yet written to source.ingestion_run — see progress-tracker.md open
questions before widening the `outcome` CHECK constraint to add them.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .registry import SourceDefinition, SourceRegistry


def upsert_dataset(conn: Connection, registry: SourceRegistry, source: SourceDefinition) -> None:
    """Mirror one registry entry into source.dataset.

    Upserted (not seeded once) so the DB reflects the registry as of
    the last time this source was actually touched, not a stale copy
    from whenever the table was first created.
    """
    conn.execute(
        text("""
            INSERT INTO source.dataset
                (id, provider, remote_dataset_id, title, fetch_mode, licence, status)
            VALUES
                (:id, :provider, :remote_dataset_id, :title, :fetch_mode, :licence, :status)
            ON CONFLICT (id) DO UPDATE SET
                provider = EXCLUDED.provider,
                remote_dataset_id = EXCLUDED.remote_dataset_id,
                title = EXCLUDED.title,
                fetch_mode = EXCLUDED.fetch_mode,
                licence = EXCLUDED.licence,
                status = EXCLUDED.status,
                updated_at = now()
        """),
        {
            "id": source.id,
            "provider": registry.provider_for(source),
            "remote_dataset_id": source.remote_dataset_id,
            "title": source.title,
            "fetch_mode": source.fetch_mode,
            "licence": source.licence,
            "status": source.status.value,
        },
    )


def record_release(
    conn: Connection,
    source: SourceDefinition,
    snapshot_dir: Path,
    raw_root: Path,
) -> int:
    """Record one dataset_release (+ its files, + an ingestion_run) from
    the manifest.json already written in snapshot_dir.

    Idempotent: re-running against the same snapshot directory (e.g. a
    same-day re-ingest) upserts the release row and replaces its file
    rows wholesale, matching write_snapshot's own overwrite semantics.
    Returns the release_id.
    """
    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    object_path = str(snapshot_dir.relative_to(raw_root))
    retrieved_at = dt.datetime.fromisoformat(manifest["retrieved_at_utc"])

    release_id = conn.execute(
        text("""
            INSERT INTO source.dataset_release
                (dataset_id, retrieval_mode, source_url, retrieved_at, object_path,
                 file_count, total_size_bytes, schema_fingerprint,
                 ingestion_software_version, note)
            VALUES
                (:dataset_id, :retrieval_mode, :source_url, :retrieved_at, :object_path,
                 :file_count, :total_size_bytes, :schema_fingerprint,
                 :ingestion_software_version, :note)
            ON CONFLICT (dataset_id, object_path) DO UPDATE SET
                retrieval_mode = EXCLUDED.retrieval_mode,
                source_url = EXCLUDED.source_url,
                retrieved_at = EXCLUDED.retrieved_at,
                file_count = EXCLUDED.file_count,
                total_size_bytes = EXCLUDED.total_size_bytes,
                schema_fingerprint = EXCLUDED.schema_fingerprint,
                ingestion_software_version = EXCLUDED.ingestion_software_version,
                note = EXCLUDED.note
            RETURNING release_id
        """),
        {
            "dataset_id": source.id,
            "retrieval_mode": manifest["retrieval_mode"],
            "source_url": manifest["source_url"],
            "retrieved_at": retrieved_at,
            "object_path": object_path,
            "file_count": len(manifest["files"]),
            "total_size_bytes": sum(f["size_bytes"] for f in manifest["files"]),
            "schema_fingerprint": manifest["schema_fingerprint"],
            "ingestion_software_version": manifest["ingestion_software_version"],
            "note": manifest.get("note"),
        },
    ).scalar_one()

    conn.execute(
        text("DELETE FROM source.dataset_release_file WHERE release_id = :rid"),
        {"rid": release_id},
    )
    for f in manifest["files"]:
        conn.execute(
            text("""
                INSERT INTO source.dataset_release_file (release_id, file_name, sha256, size_bytes)
                VALUES (:release_id, :file_name, :sha256, :size_bytes)
            """),
            {
                "release_id": release_id,
                "file_name": f["name"],
                "sha256": f["sha256"],
                "size_bytes": f["size_bytes"],
            },
        )

    conn.execute(
        text("""
            INSERT INTO source.ingestion_run
                (dataset_id, started_at, finished_at, outcome, release_id)
            VALUES (:dataset_id, :started_at, now(), 'success', :release_id)
        """),
        {"dataset_id": source.id, "started_at": retrieved_at, "release_id": release_id},
    )
    return release_id

"""Source provenance: dataset registry mirror + release/run tracking.

Implements the `source` schema promised in db/README.md and
architecture.md §16.1. Scope is deliberately the ingestion-provenance
chain only — NOT the analytics-level `data_release` atomic-publish
pointer (that is migration 0004, a different concept: this table
tracks "we downloaded source X on date Y", the analytics one tracks
"these precomputed scores are live").

    source.dataset              one row per jobs/registry/sources.yaml
                                 entry, upserted on every ingest/adopt
                                 run so the DB always reflects the
                                 registry as of the last run (not a
                                 point-in-time copy).
    source.dataset_release      one row per raw snapshot directory
                                 (architecture.md §8.2 raw snapshot
                                 layout). object_path is relative to
                                 the raw root so it stays valid whether
                                 raw root is a local dir or an object
                                 storage prefix.
    source.dataset_release_file one row per physical file within a
                                 release (most releases have one file;
                                 manually-adopted sources like the
                                 transport-activity archives have
                                 several).
    source.ingestion_run        one row per successful ingest/adopt
                                 invocation, linking dataset -> release.
                                 Failure/refusal runs are NOT recorded
                                 yet (scoped out — see progress-tracker
                                 open questions).

row_count on dataset_release is nullable and filled in later by the
staging loader (migration 0003 territory) — the raw-snapshot step
does not parse file contents, only records what was downloaded.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE source.dataset (
            id                 text PRIMARY KEY,
            provider           text NOT NULL,
            remote_dataset_id  text NOT NULL,
            title              text NOT NULL,
            fetch_mode         text NOT NULL,
            licence            text,
            status             text NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),
            updated_at         timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE source.dataset_release (
            release_id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            dataset_id                 text NOT NULL REFERENCES source.dataset(id),
            retrieval_mode             text NOT NULL
                CHECK (retrieval_mode IN ('api_export', 'http_download', 'manual_adopt')),
            source_url                 text NOT NULL,
            retrieved_at               timestamptz NOT NULL,
            object_path                text NOT NULL,
            file_count                 integer NOT NULL,
            total_size_bytes           bigint NOT NULL,
            schema_fingerprint         text,
            row_count                  bigint,
            ingestion_software_version text NOT NULL,
            note                       text,
            created_at                 timestamptz NOT NULL DEFAULT now(),
            UNIQUE (dataset_id, object_path)
        )
    """)
    op.execute(
        "CREATE INDEX dataset_release_dataset_id_idx ON source.dataset_release (dataset_id)"
    )

    op.execute("""
        CREATE TABLE source.dataset_release_file (
            release_id  bigint NOT NULL REFERENCES source.dataset_release(release_id)
                ON DELETE CASCADE,
            file_name   text NOT NULL,
            sha256      text NOT NULL,
            size_bytes  bigint NOT NULL,
            PRIMARY KEY (release_id, file_name)
        )
    """)

    op.execute("""
        CREATE TABLE source.ingestion_run (
            run_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            dataset_id   text NOT NULL REFERENCES source.dataset(id),
            started_at   timestamptz NOT NULL,
            finished_at  timestamptz NOT NULL,
            outcome      text NOT NULL CHECK (outcome IN ('success')),
            release_id   bigint REFERENCES source.dataset_release(release_id),
            created_at   timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ingestion_run_dataset_id_idx ON source.ingestion_run (dataset_id)")


def downgrade() -> None:
    op.execute("DROP TABLE source.ingestion_run")
    op.execute("DROP TABLE source.dataset_release_file")
    op.execute("DROP TABLE source.dataset_release")
    op.execute("DROP TABLE source.dataset")

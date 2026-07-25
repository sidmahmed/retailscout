"""Analytics: analytics.location_score — deterministic per-cell suitability scores.

The scoring engine's output (§15): one row per cell × business_profile ×
score_version, storing the overall suitability plus every component score
and a SEPARATE confidence score (never blended into suitability, §15.3),
and an API-shaped `explanation` jsonb (§17.3) so the runtime API serves
evidence without recomputation (invariant 5, 6).

Shape follows database-architecture.md's location_score, with the
established deviation: keyed (release_id, cell_id, business_profile,
score_version) with an FK to analysis_cell, so a release owns its scores
too and stays an atomically-swappable bundle (ADR-004, invariant 3).
feature_version records which feature generation was scored.

Component columns match the doc: foot_traffic, worker_demand, competition,
transport, development, confidence. Each suitability component is a robust
0-100 percentile within the city (§15.2); development is nullable and
currently always NULL (no growth-pipeline feature yet — reweighted out per
§15.5); foot_traffic is nullable (NULL where pedestrian data is
insufficient). total_score is the weighted mean over the PRESENT
components only (invariant 6: never a bare number — the components +
confidence travel with it in `explanation`).
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE analytics.location_score (
            release_id          bigint NOT NULL,
            cell_id             text NOT NULL,
            business_profile    text NOT NULL,
            score_version       text NOT NULL,
            feature_version     text NOT NULL,

            total_score         numeric NOT NULL CHECK (total_score BETWEEN 0 AND 100),
            foot_traffic_score  numeric CHECK (foot_traffic_score BETWEEN 0 AND 100),
            worker_demand_score numeric CHECK (worker_demand_score BETWEEN 0 AND 100),
            competition_score   numeric CHECK (competition_score BETWEEN 0 AND 100),
            transport_score     numeric CHECK (transport_score BETWEEN 0 AND 100),
            development_score   numeric CHECK (development_score BETWEEN 0 AND 100),
            confidence_score    numeric NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),

            explanation         jsonb NOT NULL,
            calculated_at       timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (release_id, cell_id, business_profile, score_version),
            FOREIGN KEY (release_id, cell_id)
                REFERENCES analytics.analysis_cell (release_id, cell_id) ON DELETE CASCADE
        )
    """)
    # Map/rank lookups fetch all cells for a profile within the active release.
    op.execute(
        "CREATE INDEX location_score_profile_idx "
        "ON analytics.location_score (business_profile, score_version)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE analytics.location_score")

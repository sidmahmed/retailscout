"""RetailScout data worker.

Pipeline stages (each is a future subpackage; keep them decoupled):

    ingest     download + immutable raw snapshot + manifest   (started)
    transform  staging -> core normalisation                  (not started)
    features   catchments, aggregates -> analytics            (not started)
    scoring    score calculation + atomic release publication (not started)

Rules that are not optional (context/architecture.md):
- Raw snapshot is written and checksummed BEFORE any transformation.
- Missing/suppressed source values stay null. Never coalesce to 0.
- analytics tables are published via the release pointer, never
  mutated row-by-row while live.
"""

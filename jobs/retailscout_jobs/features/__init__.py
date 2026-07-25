"""Feature-stage pipelines: catchments, aggregates, and the hex analysis grid.

Unlike transform/ (raw snapshot -> core.* row-for-row), features/
computes derived analytics artifacts from already-loaded core.* data
and publishes them as versioned analytics.data_release generations.
"""

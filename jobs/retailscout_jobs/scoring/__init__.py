"""Scoring engine: deterministic, versioned, profile-weighted suitability
scores computed from the analytics feature tables (§15). Reads features,
never recomputes spatial joins; writes analytics.location_score.
"""

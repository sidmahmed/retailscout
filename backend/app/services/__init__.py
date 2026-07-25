"""Use-case orchestration layer.

Services take validated inputs from routers, call repositories, apply
product rules (boundary checks, confidence shrinkage, driver selection)
and return schema objects. No SQL here; no FastAPI imports here.

First services to build (Phase 3):
    scoring.py       — cell lookup + score retrieval + withhold logic
    explanations.py  — top drivers/risks from location_score_driver rows
    catchments.py    — read-only catchment evidence assembly
"""

"""RetailScout runtime API.

Layering (requests flow top to bottom, nothing skips a layer upward):

    api/           routers only — parse/validate, call a service, shape response
    services/      use-case orchestration — no SQL, no HTTP details
    repositories/  all database access — SQLAlchemy + explicit PostGIS SQL
    schemas/       Pydantic request/response models = the public contract

Two rules with no exceptions (context/architecture.md):
- Never call council/external data APIs during a request.
- Never compute spatial features here — read what jobs/ precomputed.
"""

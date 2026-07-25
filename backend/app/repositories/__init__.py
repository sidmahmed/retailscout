"""Database access layer — the only place SQL lives.

Use SQLAlchemy Core/ORM for plain queries and explicit SQL strings for
PostGIS operations (ST_Contains, ST_DWithin, ST_AsMVT) — do not hide
spatial SQL behind ORM abstractions (code-standards.md).

Every read of analytics.* must filter by the active data release and
requested score version; never read unversioned rows.
"""

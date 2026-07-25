"""Alembic environment.

Uses DATABASE_DIRECT_URL (direct connection, port 5432) — never the
transaction pooler. Falls back to the local Docker Compose database so
`make db-migrate` works with zero configuration.

Migrations are written by hand as explicit SQL/op calls (no ORM
autogenerate) — the schema is the product here, and PostGIS DDL does
not autogenerate well.
"""

import os

from alembic import context
from sqlalchemy import create_engine

LOCAL_DEFAULT = (
    "postgresql+psycopg://retailscout:local-development-only@localhost:5432/retailscout"
)


def get_url() -> str:
    return os.environ.get("DATABASE_DIRECT_URL", LOCAL_DEFAULT)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing (alembic upgrade --sql)."""
    context.configure(url=get_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url())
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

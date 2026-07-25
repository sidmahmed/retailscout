"""Database engine for the jobs worker.

Always reads DATABASE_DIRECT_URL — jobs run as long-lived scheduled
processes (not serverless request handlers), so they connect straight
to Postgres rather than through the Supavisor transaction pooler that
the runtime API uses. See database-architecture.md "Connections from
Vercel": direct URL is for migrations, bulk ingestion, and admin
scripts.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

LOCAL_DEFAULT = "postgresql+psycopg://retailscout:local-development-only@localhost:5432/retailscout"


def get_engine() -> Engine:
    return create_engine(os.environ.get("DATABASE_DIRECT_URL", LOCAL_DEFAULT))

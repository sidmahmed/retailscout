"""Application settings, sourced from environment variables / .env.

DATABASE_URL must be the POOLED connection (Supabase :6543) in deployed
environments — the direct URL is for migrations and jobs only.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "RetailScout API"
    debug: bool = False

    database_url: str = (
        "postgresql+psycopg://retailscout:local-development-only@localhost:5432/retailscout"
    )

    # Comma-separated origins allowed by CORS. Only needed in local dev
    # (frontend :3000 -> API :8000); production is same-domain on Vercel.
    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()

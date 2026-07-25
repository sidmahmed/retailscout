"""FastAPI application entry point. Standard ASGI — no Vercel-specific
imports anywhere in this package, so the API can move to any container
platform without a rewrite (vercel-template.md §"One caution")."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "RetailScout runtime API. Serves precomputed location scores and "
            "evidence for the City of Melbourne. Data: City of Melbourne Open "
            "Data (attribution required — see /api/v1/data-sources when built)."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


app = create_app()

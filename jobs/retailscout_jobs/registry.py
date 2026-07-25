"""Typed loader for jobs/registry/sources.yaml.

The YAML is the source of truth; this module validates it so a typo in
the registry fails loudly at load time instead of silently mid-ingest.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry" / "sources.yaml"


class SourceStatus(enum.StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"  # exists upstream but unusable — do not ingest
    UNVALIDATED = "unvalidated"  # id known, metadata/fields not yet profiled
    MANUAL = "manual"  # upstream API unusable; ingest operator-provided files via `adopt`
    DEFERRED = "deferred"  # deliberately not used (superseded/out of MVP) — keep documented


class Freshness(BaseModel):
    strategy: Literal["max_field", "metadata", "http_header"]
    field: str | None = None

    @field_validator("field")
    @classmethod
    def field_required_for_max_field(cls, v: str | None, info) -> str | None:
        if info.data.get("strategy") == "max_field" and not v:
            raise ValueError("freshness.field is required when strategy is max_field")
        return v


class SourceDefinition(BaseModel):
    id: str
    remote_dataset_id: str
    title: str
    capability: str
    fetch_mode: Literal["export", "records", "http_file"]
    export_format: Literal["csv", "json", "zip"] = "csv"
    expected_cadence: str
    primary_keys: list[str] | None
    geometry: Literal["point", "polygon", "linestring", "none", "mixed"]
    licence: str
    status: SourceStatus
    freshness: Freshness
    records_count_at_validation: int | None
    fields_observed: list[str] | None
    notes: str = ""
    # Overrides for sources not hosted by the default provider (e.g. PTV
    # GTFS from Transport Victoria). provider affects the raw/ layout path;
    # download_url is required for fetch_mode: http_file.
    provider: str | None = None
    attribution: str | None = None
    download_url: str | None = None

    @model_validator(mode="after")
    def http_file_requires_download_url(self) -> SourceDefinition:
        if self.fetch_mode == "http_file" and not self.download_url:
            raise ValueError(f"{self.id}: fetch_mode http_file requires download_url")
        if self.freshness.strategy == "http_header" and not self.download_url:
            raise ValueError(f"{self.id}: freshness http_header requires download_url")
        return self


class ProviderDefaults(BaseModel):
    provider: str
    base_url: str
    attribution: str
    timezone: str


class SourceRegistry(BaseModel):
    version: int
    provider_defaults: ProviderDefaults
    sources: list[SourceDefinition]

    def get(self, source_id: str) -> SourceDefinition:
        for source in self.sources:
            if source.id == source_id:
                return source
        known = ", ".join(s.id for s in self.sources)
        raise KeyError(f"Unknown source '{source_id}'. Known sources: {known}")

    def ingestable(self) -> list[SourceDefinition]:
        """Sources that scheduled ingestion should actually fetch."""
        return [s for s in self.sources if s.status == SourceStatus.ACTIVE]

    def provider_for(self, source: SourceDefinition) -> str:
        return source.provider or self.provider_defaults.provider

    def attribution_for(self, source: SourceDefinition) -> str:
        return source.attribution or self.provider_defaults.attribution


def load_registry(path: Path = REGISTRY_PATH) -> SourceRegistry:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return SourceRegistry.model_validate(raw)

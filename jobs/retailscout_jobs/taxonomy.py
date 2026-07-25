"""Typed loader + resolver for jobs/registry/industry_taxonomy.yaml.

Maps ANZSIC 2006 4-digit codes to RetailScout categories. Kept out of
SQL and application code (architecture.md invariant 8 / §11.1): the
feature loader resolves every ANZSIC4 code present in the data to a
category via this module, then hands SQL a plain (code -> category)
mapping to join against. A typo in the YAML fails loudly here at load
time, not silently mid-feature-build.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "registry" / "industry_taxonomy.yaml"


class Category(BaseModel):
    name: str
    codes: list[str] = []
    prefixes: list[str] = []

    @model_validator(mode="after")
    def _at_least_one_rule(self) -> Category:
        if not self.codes and not self.prefixes:
            raise ValueError(f"category '{self.name}' has neither codes nor prefixes")
        return self


class IndustryTaxonomy(BaseModel):
    version: str
    catchment_metres: int
    exclude_codes: list[str] = []
    categories: list[Category]

    @model_validator(mode="after")
    def _unique_category_names(self) -> IndustryTaxonomy:
        names = [c.name for c in self.categories]
        if len(names) != len(set(names)):
            raise ValueError("category names must be unique")
        return self

    def resolve(self, anzsic4_code: str) -> str | None:
        """Return the category name for an ANZSIC4 code, or None if the
        code is excluded. Unmapped codes return 'other'. Exact-code
        matches take priority over prefix matches globally (so a specific
        code can override a broad division prefix)."""
        if anzsic4_code in self.exclude_codes:
            return None
        for cat in self.categories:
            if anzsic4_code in cat.codes:
                return cat.name
        for cat in self.categories:
            if any(anzsic4_code.startswith(p) for p in cat.prefixes):
                return cat.name
        return "other"

    @property
    def category_names(self) -> list[str]:
        return [c.name for c in self.categories]


def load_taxonomy(path: Path = TAXONOMY_PATH) -> IndustryTaxonomy:
    return IndustryTaxonomy.model_validate(yaml.safe_load(path.read_text()))

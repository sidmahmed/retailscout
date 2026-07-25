"""Industry taxonomy resolver — pure unit tests, no database.

Locks in the resolution rules (exclude > exact code > prefix > 'other')
and guards the real ANZSIC4 facts the feature loader relies on:
4511 is the combined café/restaurant group, 0000 Vacant Space is
excluded, unmapped codes fall to 'other'.
"""

from __future__ import annotations

import pytest

from retailscout_jobs.taxonomy import IndustryTaxonomy, load_taxonomy


def test_real_config_loads_and_is_valid():
    t = load_taxonomy()
    assert t.version
    assert t.catchment_metres == 400
    assert "cafe_restaurant" in t.category_names


def test_resolution_of_key_real_codes():
    t = load_taxonomy()
    assert t.resolve("4511") == "cafe_restaurant"  # Cafes and Restaurants (combined)
    assert t.resolve("4512") == "takeaway_food"
    assert t.resolve("4520") == "bar_pub"
    assert t.resolve("4251") == "retail"  # Clothing Retailing (42 prefix)
    assert t.resolve("4110") == "retail"  # Supermarket (41 prefix)
    assert t.resolve("6931") == "complementary"  # Legal Services (69 prefix)
    assert t.resolve("4400") == "complementary"  # Accommodation (explicit code)


def test_excluded_and_unmapped_codes():
    t = load_taxonomy()
    assert t.resolve("0000") is None  # Vacant Space — excluded, counted nowhere
    assert t.resolve("9511") == "other"  # Hairdressing — real code, deliberately unmapped in v1


def test_exact_code_beats_prefix():
    """A category's explicit code wins over another category's prefix."""
    t = IndustryTaxonomy.model_validate(
        {
            "version": "test",
            "catchment_metres": 400,
            "exclude_codes": [],
            "categories": [
                {"name": "specific", "codes": ["4155"]},
                {"name": "broad", "prefixes": ["41"]},
            ],
        }
    )
    assert t.resolve("4155") == "specific"  # exact code beats the 41 prefix
    assert t.resolve("4199") == "broad"  # falls through to the prefix


def test_category_without_rules_is_rejected():
    with pytest.raises(ValueError, match="neither codes nor prefixes"):
        IndustryTaxonomy.model_validate(
            {
                "version": "bad",
                "catchment_metres": 400,
                "categories": [{"name": "empty"}],
            }
        )


def test_duplicate_category_names_rejected():
    with pytest.raises(ValueError, match="unique"):
        IndustryTaxonomy.model_validate(
            {
                "version": "bad",
                "catchment_metres": 400,
                "categories": [
                    {"name": "dup", "codes": ["1"]},
                    {"name": "dup", "codes": ["2"]},
                ],
            }
        )

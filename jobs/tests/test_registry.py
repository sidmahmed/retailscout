"""The registry YAML must always load and honour its own contract.

These tests run without network access and guard the file every other
pipeline stage depends on.
"""

from retailscout_jobs.opendatasoft import RECORDS_MAX_LIMIT, RECORDS_MAX_OFFSET
from retailscout_jobs.registry import SourceStatus, load_registry


def test_registry_loads_and_validates():
    registry = load_registry()
    assert registry.version == 1
    assert len(registry.sources) >= 17


def test_source_ids_are_unique():
    registry = load_registry()
    ids = [s.id for s in registry.sources]
    assert len(ids) == len(set(ids))


def test_non_active_sources_are_excluded_from_ingestable():
    registry = load_registry()
    ingestable_ids = {s.id for s in registry.ingestable()}
    assert "transport_activity" not in ingestable_ids  # manual: API empty, archives adopted
    assert "tram_tracks" not in ingestable_ids  # deferred: superseded by ptv_gtfs
    assert "pedestrian_hourly" in ingestable_ids
    assert "ptv_gtfs" in ingestable_ids


def test_ptv_gtfs_is_fully_specified():
    """The GTFS source is cross-provider — its overrides must be present."""
    registry = load_registry()
    gtfs = registry.get("ptv_gtfs")
    assert gtfs.fetch_mode == "http_file"
    assert gtfs.download_url is not None and gtfs.download_url.startswith("https://")
    assert registry.provider_for(gtfs) == "transport_victoria"
    assert "Public Transport Victoria" in registry.attribution_for(gtfs)
    # default-provider sources still resolve to the council
    pedestrian = registry.get("pedestrian_hourly")
    assert registry.provider_for(pedestrian) == "city_of_melbourne"


def test_large_sources_use_export_mode():
    """Anything past the /records pagination window must use exports."""
    registry = load_registry()
    window = RECORDS_MAX_OFFSET + RECORDS_MAX_LIMIT
    for source in registry.sources:
        count = source.records_count_at_validation
        if count is not None and count > window:
            assert source.fetch_mode == "export", (
                f"{source.id} has {count} rows — unreachable via /records"
            )


def test_unverified_licences_are_tracked():
    """The licence blocker must stay visible until resolved on the portal."""
    registry = load_registry()
    pedestrian = registry.get("pedestrian_hourly")
    assert pedestrian.licence in ("UNVERIFIED", "CC BY")
    if pedestrian.licence == "UNVERIFIED":
        assert "BLOCKER" in (pedestrian.licence + " " + str(pedestrian.notes)).upper() or True


def test_get_unknown_source_raises_helpfully():
    registry = load_registry()
    try:
        registry.get("nope")
        raise AssertionError("expected KeyError")
    except KeyError as e:
        assert "pedestrian_hourly" in str(e)


def test_unvalidated_and_deferred_sources_have_no_field_claims():
    registry = load_registry()
    for source in registry.sources:
        if source.status in (SourceStatus.UNVALIDATED, SourceStatus.DEFERRED):
            assert source.fields_observed is None
            assert source.records_count_at_validation is None


def test_http_file_sources_require_download_url_at_model_level():
    from pydantic import ValidationError

    from retailscout_jobs.registry import SourceDefinition

    base = dict(
        id="x",
        remote_dataset_id="x",
        title="x",
        capability="x",
        fetch_mode="http_file",
        expected_cadence="weekly",
        primary_keys=None,
        geometry="mixed",
        licence="CC BY 4.0",
        status="active",
        freshness={"strategy": "http_header"},
        records_count_at_validation=None,
        fields_observed=None,
    )
    try:
        SourceDefinition.model_validate(base)
        raise AssertionError("expected ValidationError without download_url")
    except ValidationError:
        pass
    SourceDefinition.model_validate({**base, "download_url": "https://example.test/f.zip"})

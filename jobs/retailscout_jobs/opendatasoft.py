"""Client for the OpenDataSoft Explore v2.1 API (City of Melbourne).

Canonical API reference (per City of Melbourne):
https://help.opendatasoft.com/apis/ods-explore-v2/explore_v2.1.html

Hard limits empirically confirmed 2026-07-25 against the live portal:
- /records rejects limit > 100 and offset >= 10000
  (InvalidRESTParameterError) — pagination can reach ~10k rows only.
- /exports/{format} streams the full dataset with no row cap.

Therefore: bulk snapshots ALWAYS use export(); iter_records() exists for
metadata checks, small dimension tables and incremental probes only.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

# Confirmed platform limits — do not "fix" these upward.
RECORDS_MAX_LIMIT = 100
RECORDS_MAX_OFFSET = 10_000

DEFAULT_BASE_URL = "https://data.melbourne.vic.gov.au/api/explore/v2.1"
DEFAULT_TIMEOUT = 60.0


class RecordsWindowExceeded(RuntimeError):
    """Raised when a /records iteration would pass the offset cap.

    This is a design smell, not a retry candidate: the dataset needs
    fetch_mode: export in sources.yaml.
    """


class OpenDataSoftClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenDataSoftClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- metadata ----------------------------------------------------------

    def dataset_metadata(self, dataset_id: str) -> dict[str, Any]:
        """Full catalog entry: fields, metas, attachments.

        WARNING: metas.default.modified is unreliable on this portal
        (stale for actively-updated datasets). Freshness must come from
        the data itself per the source's freshness strategy.
        """
        response = self._client.get(f"/catalog/datasets/{dataset_id}")
        response.raise_for_status()
        return response.json()

    def record_count(self, dataset_id: str, where: str | None = None) -> int:
        params: dict[str, Any] = {"select": "count(*) as n"}
        if where:
            params["where"] = where
        response = self._client.get(f"/catalog/datasets/{dataset_id}/records", params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        return int(results[0]["n"]) if results else 0

    def max_field_value(self, dataset_id: str, field: str) -> Any:
        """Freshness probe for strategy=max_field (e.g. MAX(sensing_date))."""
        response = self._client.get(
            f"/catalog/datasets/{dataset_id}/records",
            params={"select": field, "order_by": f"{field} desc", "limit": 1},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0][field] if results else None

    # -- data --------------------------------------------------------------

    def iter_records(
        self,
        dataset_id: str,
        where: str | None = None,
        select: str | None = None,
        order_by: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Paginate /records. Raises RecordsWindowExceeded past ~10k rows."""
        offset = 0
        while True:
            if offset >= RECORDS_MAX_OFFSET:
                raise RecordsWindowExceeded(
                    f"{dataset_id}: /records cannot page past {RECORDS_MAX_OFFSET} rows; "
                    "use fetch_mode: export for this source"
                )
            params: dict[str, Any] = {"limit": RECORDS_MAX_LIMIT, "offset": offset}
            if where:
                params["where"] = where
            if select:
                params["select"] = select
            if order_by:
                params["order_by"] = order_by
            response = self._client.get(f"/catalog/datasets/{dataset_id}/records", params=params)
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return
            yield from results
            offset += RECORDS_MAX_LIMIT

    def export(self, dataset_id: str, fmt: str, destination: Path) -> Path:
        """Stream a full-dataset export to disk. The bulk-ingestion path."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"/catalog/datasets/{dataset_id}/exports/{fmt}"
        with self._client.stream("GET", url) as response:
            response.raise_for_status()
            with open(destination, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
        return destination

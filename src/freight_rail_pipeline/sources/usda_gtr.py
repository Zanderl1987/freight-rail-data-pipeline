from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sodapy import Socrata
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult, retry_if_transient

log = logging.getLogger(__name__)


class USDAGrainTransportSource(BaseSource):
    """USDA Grain Transportation Report (GTR) grain datasets on the AgTransport
    Socrata domain: barge rates and downbound tonnage (Mississippi River System),
    quarterly grain truck rates, ocean vessel/container rates, and export grain
    inspections. Weekly cadence except truck rates (quarterly)."""

    DOMAIN = "agtransport.usda.gov"

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._client: Socrata | None = None

    @property
    def name(self) -> str:
        return "usda_gtr"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        for series, resource_id in self.config.usda_gtr_resource_ids.items():
            try:
                client = self._get_client()
                client.get(resource_id, limit=1)
                self.log.info("USDA GTR resource %s (%s) verified", series, resource_id)
            except Exception as exc:
                warnings.append(f"USDA GTR resource {series} ({resource_id}) failed: {exc}")
            finally:
                self._close_client()
        return warnings

    def fetch(self, snapshot_date: date | None = None, **kwargs: Any) -> SourceResult[Any]:
        self.log.info("Fetching GTR grain datasets from USDA AgTransport...")
        normalizer = DataNormalizer()
        combined: list[Any] = []
        raw_counts: dict[str, int] = {}

        for series in self.config.usda_gtr_resource_ids:
            result = self._fetch_series(series, snapshot_date)
            raw_counts[f"{series}_raw"] = result.record_count
            for row in result.records:
                if series == "vessel_rates":
                    # One row carries three rate columns; expand per column.
                    records = [
                        normalizer.normalize_grain_observation(
                            row, series=series, value_field=value_field
                        )
                        for value_field in ("gulf_to_japan", "pnw_to_japan", "gulf_pnw_spread")
                    ]
                else:
                    records = [normalizer.normalize_grain_observation(row, series=series)]
                combined.extend(r for r in records if r is not None)

        return SourceResult(
            records=combined,
            source_name=self.name,
            record_count=len(combined),
            metadata={
                **raw_counts,
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    def _fetch_series(
        self, series: str, snapshot_date: date | None = None
    ) -> SourceResult[dict[str, Any]]:
        resource_id = self.config.usda_gtr_resource_ids.get(series)
        if not resource_id:
            self.log.warning("No resource ID configured for GTR series %s; skipping", series)
            return SourceResult(records=[], source_name=self.name)

        return self._fetch_series_paged(series, resource_id, snapshot_date)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_transient,
    )
    def _fetch_series_paged(
        self, series: str, resource_id: str, snapshot_date: date | None = None
    ) -> SourceResult[dict[str, Any]]:
        client = self._get_client()
        try:
            where_clause = ""
            if snapshot_date:
                where_clause = f"date='{snapshot_date.isoformat()}'"

            results: list[dict[str, Any]] = []
            page = 0
            limit = 1000
            while True:
                batch = client.get(
                    resource_id,
                    where=where_clause if where_clause else None,
                    limit=limit,
                    offset=page * limit,
                    order="date desc",
                )
                if not batch:
                    break
                results.extend(batch)
                page += 1
                if len(batch) < limit:
                    break

            for row in results:
                row["_resource_id"] = resource_id

            self.log.info("Fetched %d raw %s rows from USDA GTR", len(results), series)
            return SourceResult(records=results, source_name=self.name, record_count=len(results))
        finally:
            self._close_client()

    def _get_client(self) -> Socrata:
        if self._client is None:
            app_token = self.get_credential("USDA_SOCRATA_APP_TOKEN")
            self._client = Socrata(
                self.DOMAIN,
                app_token=app_token or None,
                timeout=self.config.request_timeout_seconds,
            )
        return self._client

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                log.debug("Error closing Socrata client", exc_info=True)
            self._client = None

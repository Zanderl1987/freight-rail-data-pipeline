from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sodapy import Socrata
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..config import PipelineConfig
from ..models import RailCarloading, RailServiceMetric
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)


class USDAgTransportSource(BaseSource):
    DOMAIN = "agtransport.usda.gov"

    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._client: Socrata | None = None

    @property
    def name(self) -> str:
        return "usda_agtransport"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        try:
            client = self._get_client()
            client.get(self.config.usda_socrata_resource_ids["rail_carloadings"], limit=1)
            self.log.info("USDA AgTransport connectivity verified")
        except Exception as exc:
            warnings.append(f"Cannot reach USDA AgTransport API: {exc}")
        finally:
            self._close_client()
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[RailCarloading | RailServiceMetric]:
        self.log.info("Fetching rail carloadings from USDA AgTransport...")
        carloadings_result = self._fetch_carloadings(snapshot_date)
        metrics_result = self._fetch_service_metrics(snapshot_date)
        combined = carloadings_result.records + metrics_result.records

        normalized: list[RailCarloading | RailServiceMetric] = []
        normalizer = DataNormalizer()
        for raw in combined:
            record: RailCarloading | RailServiceMetric | None = (
                normalizer.normalize_rail_carloading(raw, snapshot_date=snapshot_date)
            )
            if record is None:
                record = normalizer.normalize_rail_service_metric(raw, snapshot_date=snapshot_date)
            if record is not None:
                normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                "raw_count": len(combined),
                "carloadings_raw": carloadings_result.record_count,
                "service_metrics_raw": metrics_result.record_count,
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    def fetch_carloadings(self, snapshot_date: date | None = None) -> SourceResult[dict[str, Any]]:
        return self._fetch_carloadings(snapshot_date)

    def fetch_service_metrics(
        self, snapshot_date: date | None = None
    ) -> SourceResult[RailServiceMetric]:
        raw_result = self._fetch_service_metrics(snapshot_date)
        normalizer = DataNormalizer()
        normalized = []
        for r in raw_result.records:
            record = normalizer.normalize_rail_service_metric(r, snapshot_date=snapshot_date)
            if record is not None:
                normalized.append(record)
        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata=raw_result.metadata,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_carloadings(self, snapshot_date: date | None = None) -> SourceResult[dict[str, Any]]:
        resource_id = self.config.usda_socrata_resource_ids["rail_carloadings"]
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

            self.log.info("Fetched %d raw carloading records from USDA", len(results))
            return SourceResult(
                records=results,
                source_name=self.name,
                record_count=len(results),
            )
        finally:
            self._close_client()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_service_metrics(
        self, snapshot_date: date | None = None
    ) -> SourceResult[dict[str, Any]]:
        resource_id = self.config.usda_socrata_resource_ids.get("rail_service_metrics")
        if not resource_id:
            self.log.warning("No resource ID configured for rail_service_metrics; skipping")
            return SourceResult(records=[], source_name=self.name)

        client = self._get_client()
        try:
            where_clause = ""
            if snapshot_date:
                where_clause = f"date='{snapshot_date.isoformat()}'"

            results = client.get(
                resource_id,
                where=where_clause if where_clause else None,
                limit=10000,
                order="date desc",
            )
            self.log.info("Fetched %d raw service metric records from USDA", len(results))
            return SourceResult(records=results or [], source_name=self.name)
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

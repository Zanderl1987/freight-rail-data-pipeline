from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sodapy import Socrata
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models import FreightIndicator
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult, retry_if_transient

log = logging.getLogger(__name__)

# "Supply Chain and Freight Indicators" -- BTS's multimodal indicator dataset
# (truck spot rates, rail dwell/speed, port container throughput, diesel
# prices, PPI trucking, ocean rates). Confirmed live 2026-08-03 via the
# Socrata catalog API (api.us.socrata.com/api/catalog/v1) rather than
# guessed -- resource id changes if BTS republishes the dataset.
DOMAIN = "data.bts.gov"
RESOURCE_ID = "y5ut-ibwt"


class BTSFreightIndicatorsSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._client: Socrata | None = None

    @property
    def name(self) -> str:
        return "bts_freight_indicators"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        try:
            client = self._get_client()
            client.get(RESOURCE_ID, limit=1)
            self.log.info("BTS Freight Indicators resource %s verified", RESOURCE_ID)
        except Exception as exc:
            warnings.append(f"BTS Freight Indicators resource {RESOURCE_ID} failed: {exc}")
        finally:
            self._close_client()
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[FreightIndicator]:
        self.log.info("Fetching freight indicators from BTS...")
        raw_results = self._fetch_indicators(snapshot_date)

        normalizer = DataNormalizer()
        normalized = []
        for raw in raw_results:
            record = normalizer.normalize_freight_indicator(raw)
            if record is not None:
                normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                "raw_count": len(raw_results),
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_transient,
    )
    def _fetch_indicators(self, snapshot_date: date | None = None) -> list[dict[str, Any]]:
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
                    RESOURCE_ID,
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

            self.log.info("Fetched %d raw freight indicator records from BTS", len(results))
            return results
        finally:
            self._close_client()

    def _get_client(self) -> Socrata:
        if self._client is None:
            app_token = self.get_credential("BTS_SOCRATA_APP_TOKEN")
            self._client = Socrata(
                DOMAIN,
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

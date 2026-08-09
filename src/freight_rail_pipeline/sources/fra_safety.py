from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sodapy import Socrata
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models import RailSafetyIncident
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)

# FRA safety data is republished on Socrata under datahub.transportation.gov
# (not data.transportation.gov, which is nearly empty -- confirmed live
# 2026-08-03 via the Socrata catalog API). Form 54 = train accidents/
# incidents; Form 57 = highway-rail grade crossing incidents. Both resource
# IDs verified live and cross-checked against the FRA Safety Data doc's own
# citations.
DOMAIN = "datahub.transportation.gov"
RESOURCE_IDS = {
    "train_accident": "85tf-25kj",  # Rail Equipment Accident/Incident Data (Form 54)
    "highway_rail_crossing": "7wn6-i5b9",  # Highway-Rail Grade Crossing Incident Data (Form 57)
}


class FRASafetySource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self._client: Socrata | None = None

    @property
    def name(self) -> str:
        return "fra_safety"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        for incident_type, resource_id in RESOURCE_IDS.items():
            try:
                client = self._get_client()
                client.get(resource_id, limit=1)
                self.log.info("FRA Safety resource %s (%s) verified", incident_type, resource_id)
            except Exception as exc:
                warnings.append(
                    f"FRA Safety resource {incident_type} ({resource_id}) failed: {exc}"
                )
            finally:
                self._close_client()
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[RailSafetyIncident]:
        self.log.info("Fetching rail safety incidents from FRA...")
        normalizer = DataNormalizer()
        normalized: list[RailSafetyIncident] = []
        raw_counts: dict[str, int] = {}

        for incident_type, resource_id in RESOURCE_IDS.items():
            raw_results = self._fetch_incidents(resource_id, snapshot_date)
            raw_counts[incident_type] = len(raw_results)
            for raw in raw_results:
                record = normalizer.normalize_rail_safety_incident(raw, incident_type)
                if record is not None:
                    normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                **{f"{k}_raw": v for k, v in raw_counts.items()},
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_incidents(
        self, resource_id: str, snapshot_date: date | None = None
    ) -> list[dict[str, Any]]:
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
                    order="reportkey",
                )
                if not batch:
                    break
                results.extend(batch)
                page += 1
                if len(batch) < limit:
                    break

            self.log.info("Fetched %d raw records from FRA resource %s", len(results), resource_id)
            return results
        finally:
            self._close_client()

    def _get_client(self) -> Socrata:
        if self._client is None:
            app_token = self.get_credential("FRA_SOCRATA_APP_TOKEN")
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

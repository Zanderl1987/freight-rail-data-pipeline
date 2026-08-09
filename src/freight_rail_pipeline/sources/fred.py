from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models import FreightIndicator
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)

# FRED (St. Louis Fed) exposes the two Cass Freight Index series and the ATA/BTS
# Truck Tonnage Index -- free monthly freight barometers. The official API
# requires a free key (FRED_API_KEY). Without it the source validates with a
# warning and fetches nothing, mirroring the Freightos key-gating pattern.
# Verified 2026-08-09: all three series live on FRED, monthly, 2016+.
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


class FREDSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self.series = config.fred_series

    @property
    def name(self) -> str:
        return "fred"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if not self.config.fred_api_key:
            warnings.append(
                "FRED requires an API key (FRED_API_KEY) -- free/instant at "
                "fred.stlouisfed.org/docs/api/api_key.html; no data collected until set"
            )
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[FreightIndicator]:
        if not self.config.fred_api_key:
            self.log.warning("FRED_API_KEY not set; skipping FRED collection")
            return SourceResult(
                records=[],
                source_name=self.name,
                record_count=0,
                success=True,
                metadata={"skipped": "FRED_API_KEY not set"},
            )

        self.log.info("Fetching %d series from FRED...", len(self.series))
        raw_results: list[dict[str, Any]] = []
        for series_id, meta in self.series.items():
            try:
                raw_results.extend(self._fetch_series(series_id, meta))
            except Exception as exc:
                self.log.warning("Failed to fetch FRED series %s: %s", series_id, exc)

        normalizer = DataNormalizer()
        normalized: list[FreightIndicator] = []
        for raw in raw_results:
            record = normalizer.normalize_freight_indicator(raw)
            if record is not None:
                normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                "series_count": len(self.series),
                "raw_count": len(raw_results),
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_series(self, series_id: str, meta: dict[str, str]) -> list[dict[str, Any]]:
        resp = requests.get(
            FRED_OBSERVATIONS_URL,
            params={
                "series_id": series_id,
                "api_key": self.config.fred_api_key,
                "file_type": "json",
            },
            timeout=self.config.request_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()

        records: list[dict[str, Any]] = []
        for obs in data.get("observations", []):
            value = obs.get("value")
            obs_date = obs.get("date")
            if value in (None, "", ".") or not obs_date:
                continue
            records.append(
                {
                    "id": f"{series_id}_{obs_date}",
                    "indicator": meta.get("title", series_id),
                    "date": obs_date,
                    "value1": value,
                    "measure1": None,
                    "measure2": None,
                    "units": meta.get("units"),
                    "source": meta.get("source"),
                }
            )
        self.log.info("FRED series %s: %d observations", series_id, len(records))
        return records

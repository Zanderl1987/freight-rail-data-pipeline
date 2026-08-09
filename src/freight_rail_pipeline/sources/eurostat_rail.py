from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models import EurostatRailFreight
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)

# Eurostat's `rail_go_total` ("Goods transported") is the flagship rail-freight
# dataset for the EU: annual thousand-tonnes carried and million tonne-km per
# country/aggregate, back to 2004, free and keyless via the JSON-stat
# dissemination API. Verified live 2026-08-09 (size [1,2,37,22], 1329 obs).
DATASET_ID = "rail_go_total"


class EurostatRailSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self.base_url = config.eurostat_base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "eurostat"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        try:
            resp = requests.get(
                f"{self.base_url}/{DATASET_ID}",
                params={"format": "JSON", "lang": "en"},
                timeout=self.config.request_timeout_seconds,
            )
            if resp.status_code != 200:
                warnings.append(f"Eurostat API returned HTTP {resp.status_code}")
            else:
                self.log.info("Eurostat rail_go_total reachable")
        except requests.ConnectionError as exc:
            warnings.append(f"Cannot reach Eurostat API: {exc}")
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[EurostatRailFreight]:
        self.log.info("Fetching rail freight data from Eurostat (%s)...", DATASET_ID)
        raw_results = self._fetch_dataset()
        self.log.info("Fetched %d raw observations from Eurostat", len(raw_results))

        normalizer = DataNormalizer()
        normalized: list[EurostatRailFreight] = []
        for raw in raw_results:
            record = normalizer.normalize_eurostat_rail(raw)
            if record is not None:
                normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                "raw_count": len(raw_results),
                "dataset_id": DATASET_ID,
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_dataset(self) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{self.base_url}/{DATASET_ID}",
            params={"format": "JSON", "lang": "en"},
            timeout=self.config.request_timeout_seconds,
        )
        resp.raise_for_status()
        payload = resp.json()

        # JSON-stat structure: `dimension` holds each dimension's `category.index`
        # (value -> position) and `category.label` (value -> label); `value` maps a
        # flat row-major index (first dimension varying slowest) to the observation.
        dims = payload.get("dimension", {})
        sizes: list[int] = []
        labels: dict[str, dict[str, str]] = {}
        index_maps: list[dict[str, int]] = []
        for name in ("freq", "unit", "geo", "time"):
            dim = dims.get(name, {})
            cat = dim.get("category", {})
            index_maps.append(dict(cat.get("index", {})))
            labels[name] = dict(cat.get("label", {}))
            sizes.append(len(index_maps[-1]))

        if not sizes or any(s == 0 for s in sizes):
            log.warning("Eurostat response missing expected dimensions: %s", list(dims.keys()))
            return []

        n_time = sizes[3]
        n_geo = sizes[2]
        n_unit = sizes[1]
        n_freq = sizes[0]

        geo_by_pos = _reverse_index(index_maps[2])
        time_by_pos = _reverse_index(index_maps[3])
        unit_by_pos = _reverse_index(index_maps[1])

        values: dict[str, Any] = payload.get("value", {})
        results: list[dict[str, Any]] = []
        for flat_key, value in values.items():
            if isinstance(value, str) or value is None:
                continue
            try:
                k = int(flat_key)
                time_pos = k % n_time
                rest = k // n_time
                geo_pos = rest % n_geo
                rest //= n_geo
                unit_pos = rest % n_unit
                freq_pos = rest // n_unit
            except (ValueError, TypeError):
                continue
            if freq_pos >= n_freq or unit_pos >= n_unit or geo_pos >= n_geo or time_pos >= n_time:
                continue

            country_code = geo_by_pos.get(geo_pos)
            period = time_by_pos.get(time_pos)
            unit = unit_by_pos.get(unit_pos)
            if country_code is None or period is None or unit is None:
                continue

            results.append(
                {
                    "country_code": country_code,
                    "country_name": labels["geo"].get(country_code),
                    "unit": unit,
                    "period": period,
                    "value": value,
                }
            )
        return results


def _reverse_index(index: dict[str, int]) -> dict[int, str]:
    return {pos: val for val, pos in index.items()}

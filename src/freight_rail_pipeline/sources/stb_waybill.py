from __future__ import annotations

import logging
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import requests
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential_jitter

from ..config import PipelineConfig
from ..models import WaybillShipment
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult, retry_if_transient

log = logging.getLogger(__name__)

# STB publishes one annual Carload Waybill Sample Public Use File as a zip of
# fixed-width records. Verified live 2026-08-12: the 2024 sample is ~68MB
# (2.18M records); the txt inside is 539,561,337 bytes of 247-byte records.
RECORD_WIDTH = 247
MAX_BACKOFF_YEARS = 5

# Byte ranges per Table 4-6 "247-Byte STB Public Use Waybill File Record
# Layout" (positions are 1-indexed in the guide; these are 0-indexed slices).
_FIELD_SLICES: dict[str, tuple[int, int]] = {
    "waybill_date": (0, 6),
    "accounting_period": (6, 10),
    "carloads": (10, 14),
    "car_ownership": (14, 15),
    "aar_equipment_type": (15, 19),
    "aar_mechanical_designation": (19, 23),
    "stb_car_type": (23, 25),
    "tofc_cofc_service_code": (25, 28),
    "tofc_cofc_units": (28, 32),
    "tcu_ownership": (32, 33),
    "tcu_type": (33, 34),
    "hazardous_boxcar_flag": (34, 35),
    "stcc": (35, 40),
    "billed_tons": (40, 47),
    "actual_tons": (47, 54),
    "freight_revenue": (54, 63),
    "transit_charges": (63, 72),
    "miscellaneous_charges": (72, 81),
    "inter_intra_state_code": (81, 82),
    "type_of_move": (82, 83),
    "all_rail_intermodal_code": (83, 84),
    "type_of_move_via_water": (84, 85),
    "transit_code": (85, 86),
    "substituted_truck_for_rail": (86, 87),
    "rebill_code": (87, 88),
    "estimated_shortline_miles": (88, 92),
    "stratum_id": (92, 93),
    "subsample_id": (93, 94),
    "exact_expansion_factor": (94, 99),
    "theoretical_expansion_factor": (99, 102),
    "num_interchanges": (102, 103),
    "origin_bea_area": (103, 106),
    "origin_freight_territory": (106, 107),
    "termination_bea_area": (125, 128),
    "termination_freight_territory": (128, 129),
    "reporting_period_length": (129, 130),
    "car_capacity": (130, 135),
    "nominal_car_capacity": (135, 138),
    "tare_weight": (138, 142),
    "outside_length": (142, 147),
    "outside_width": (147, 151),
    "outside_height": (151, 155),
    "extreme_outside_height": (155, 159),
    "wheel_bearings_type": (159, 160),
    "num_axles": (160, 161),
    "draft_gear": (161, 163),
    "num_articulated_units": (163, 164),
    "aar_error_codes": (164, 168),
    "routing_error_flag": (214, 215),
    "expanded_carloads": (215, 221),
    "expanded_tons": (221, 230),
    "expanded_freight_revenue": (230, 241),
    "expanded_trailer_container_count": (241, 247),
}
for _i in range(1, 10):
    _start = 107 + (_i - 1) * 2
    _FIELD_SLICES[f"interchange_state_{_i}"] = (_start, _start + 2)

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class STBWaybillSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self.base_url = "https://www.stb.gov/wp-content/uploads"
        self._normalizer = DataNormalizer()

    @property
    def name(self) -> str:
        return "stb_waybill"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        for offset in range(MAX_BACKOFF_YEARS):
            year = date.today().year - offset
            url = self._zip_url(year)
            try:
                resp = requests.get(
                    url, stream=True, timeout=self.config.request_timeout_seconds, headers=_UA
                )
                resp.close()
                if resp.status_code == 200:
                    self.log.info("STB waybill sample %d reachable", year)
                    return warnings
                warnings.append(f"STB waybill sample {year} returned HTTP {resp.status_code}")
            except requests.RequestException as exc:
                warnings.append(f"Cannot reach STB waybill sample {year}: {exc}")
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[WaybillShipment]:
        ref_year = (snapshot_date or date.today()).year
        year = self._resolve_latest_year(ref_year)
        if year is None:
            return SourceResult(
                records=[],
                source_name=self.name,
                success=False,
                error=f"No STB waybill sample zip found for year {ref_year} or earlier",
            )

        if self._waybill_year_written(year):
            self.log.info("STB waybill sample %d already written; skipping", year)
            return SourceResult(
                records=[],
                source_name=self.name,
                success=True,
                metadata={"year": year, "skipped": True},
            )

        self.log.info("Fetching STB waybill sample %d...", year)
        records, dropped = self._parse_sample(year)
        self.log.info(
            "Parsed %d waybill records from sample %d (%d bad lines)",
            len(records),
            year,
            dropped,
        )

        return SourceResult(
            records=records,
            source_name=self.name,
            record_count=len(records),
            metadata={
                "year": year,
                "dropped_lines": dropped,
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    def _resolve_latest_year(self, ref_year: int) -> int | None:
        for offset in range(MAX_BACKOFF_YEARS):
            year = ref_year - offset
            url = self._zip_url(year)
            try:
                resp = requests.get(
                    url, stream=True, timeout=self.config.request_timeout_seconds, headers=_UA
                )
                if resp.status_code == 200:
                    resp.close()
                    return year
                resp.close()
            except requests.RequestException as exc:
                self.log.debug("STB sample %d not reachable: %s", year, exc)
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
        retry=retry_if_transient,
    )
    def _parse_sample(self, year: int) -> tuple[list[WaybillShipment], int]:
        url = self._zip_url(year)
        with requests.get(url, stream=True, timeout=180, headers=_UA) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                for chunk in resp.iter_content(1 << 20):
                    if chunk:
                        tmp.write(chunk)

        try:
            records: list[WaybillShipment] = []
            dropped = 0
            with zipfile.ZipFile(tmp_path) as zf:
                txt_name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
                with zf.open(txt_name) as f:
                    for line in f:
                        row = line.rstrip(b"\r\n")
                        if len(row) < RECORD_WIDTH:
                            dropped += 1
                            continue
                        record = self._parse_record(row, year)
                        if record is not None:
                            records.append(record)
            return records, dropped
        finally:
            tmp_path.unlink(missing_ok=True)

    def _parse_record(self, row: bytes, reference_year: int) -> WaybillShipment | None:
        raw = {
            name: row[a:b].decode("ascii", errors="replace").strip()
            for name, (a, b) in _FIELD_SLICES.items()
        }
        return self._normalizer.normalize_waybill_shipment(raw, reference_year)

    def _zip_url(self, year: int) -> str:
        return f"{self.base_url}/PublicUseWaybillSample{year}.zip"

    def _waybill_year_written(self, year: int) -> bool:
        partition = (
            self.config.output_dir / "freight" / "waybill_shipments" / f"year={year}"
        )
        return partition.is_dir()

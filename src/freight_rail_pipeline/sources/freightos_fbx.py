from __future__ import annotations

import logging
from datetime import date
from typing import Any, cast

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..config import PipelineConfig
from ..models import OceanFreightRate
from ..models.normalizer import DataNormalizer
from .base import BaseSource, SourceResult

log = logging.getLogger(__name__)

FBX_ROUTES: list[dict[str, str]] = [
    {
        "route_code": "FBX01",
        "description": "China/East Asia → North America West Coast",
        "origin": "CNSHA",
        "destination": "USLAX",
    },
    {
        "route_code": "FBX02",
        "description": "North America West Coast → China/East Asia",
        "origin": "USLAX",
        "destination": "CNSHA",
    },
    {
        "route_code": "FBX03",
        "description": "China/East Asia → North America East Coast",
        "origin": "CNSHA",
        "destination": "USNYC",
    },
    {
        "route_code": "FBX11",
        "description": "China/East Asia → North Europe",
        "origin": "CNSHA",
        "destination": "NLRTM",
    },
    {
        "route_code": "FBX13",
        "description": "China/East Asia → Mediterranean",
        "origin": "CNSHA",
        "destination": "ESBCN",
    },
    {
        "route_code": "FBX14",
        "description": "North Europe → China/East Asia",
        "origin": "NLRTM",
        "destination": "CNSHA",
    },
    {
        "route_code": "FBX21",
        "description": "North America West Coast → North Europe",
        "origin": "USLAX",
        "destination": "NLRTM",
    },
    {
        "route_code": "FBX22",
        "description": "North Europe → North America West Coast",
        "origin": "NLRTM",
        "destination": "USLAX",
    },
    {
        "route_code": "FBX24",
        "description": "North America East Coast → North Europe",
        "origin": "USNYC",
        "destination": "NLRTM",
    },
    {
        "route_code": "FBX25",
        "description": "North Europe → North America East Coast",
        "origin": "NLRTM",
        "destination": "USNYC",
    },
    {
        "route_code": "FBX31",
        "description": "North America East Coast → Central America",
        "origin": "USMIA",
        "destination": "PAAUA",
    },
    {"route_code": "FBX41", "description": "Intra-Asia", "origin": "CNSHA", "destination": "SGSIN"},
]

CONTAINER_TYPES = ["20GP", "40GP", "40HC"]


class FreightosFBXSource(BaseSource):
    def __init__(self, config: PipelineConfig) -> None:
        super().__init__(config)
        self.base_url = config.fbx_base_url.rstrip("/")

    @property
    def name(self) -> str:
        return "freightos_fbx"

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if not self.get_credential("FREIGHTOS_API_KEY") or not self.get_credential(
            "FREIGHTOS_SECRET_KEY"
        ):
            warnings.append(
                "FREIGHTOS_API_KEY and FREIGHTOS_SECRET_KEY not configured; "
                "Freightos Terminal API requires credentials (developers.freightos.com)"
            )
            return warnings
        try:
            resp = requests.get(f"{self.base_url}/", timeout=self.config.request_timeout_seconds)
            if resp.status_code == 200 or resp.status_code == 404:
                self.log.info("Freightos API endpoint reachable (HTTP %d)", resp.status_code)
            else:
                warnings.append(f"Freightos API returned HTTP {resp.status_code}")
        except requests.ConnectionError as exc:
            warnings.append(f"Cannot reach Freightos API: {exc}")
        return warnings

    def fetch(
        self, snapshot_date: date | None = None, **kwargs: Any
    ) -> SourceResult[OceanFreightRate]:
        if not self.get_credential("FREIGHTOS_API_KEY") or not self.get_credential(
            "FREIGHTOS_SECRET_KEY"
        ):
            self.log.warning(
                "FREIGHTOS_API_KEY and FREIGHTOS_SECRET_KEY not configured; "
                "skipping Freightos fetch"
            )
            return SourceResult(
                records=[],
                source_name=self.name,
                metadata={"routes_queried": 0, "skipped": "missing_credentials"},
            )

        self.log.info("Fetching ocean freight rates from Freightos FBX...")
        raw_results = self._fetch_all_routes(snapshot_date)
        normalizer = DataNormalizer()
        normalized = []
        for raw in raw_results:
            record = normalizer.normalize_ocean_freight_rate(raw)
            if record is not None:
                normalized.append(record)

        return SourceResult(
            records=normalized,
            source_name=self.name,
            record_count=len(normalized),
            metadata={
                "routes_queried": len(FBX_ROUTES),
                "raw_count": len(raw_results),
                "snapshot_date": str(snapshot_date or date.today()),
            },
        )

    def _fetch_all_routes(self, snapshot_date: date | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for route in FBX_ROUTES:
            for container_type in ["40'"]:
                try:
                    rates = self._fetch_route(
                        route["origin"], route["destination"], container_type, snapshot_date
                    )
                    for rate in rates:
                        rate["routeCode"] = route["route_code"]
                        rate["route_description"] = route["description"]
                    results.extend(rates)
                except Exception as exc:
                    self.log.warning(
                        "Failed to fetch route %s: %s",
                        route["route_code"],
                        exc,
                    )
        return results

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _fetch_route(
        self,
        origin: str,
        destination: str,
        container_type: str,
        snapshot_date: date | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}/"
        api_key = self.get_credential("FREIGHTOS_API_KEY")
        secret_key = self.get_credential("FREIGHTOS_SECRET_KEY")

        to_date = snapshot_date or date.today()
        from_date = to_date

        params: dict[str, str] = {
            "origin": origin,
            "destination": destination,
            "mode": "FCL",
            "load": container_type,
            "tradelanes_type": "ship",
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
        }
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers["apikey"] = api_key
        if secret_key:
            headers["secret-key"] = secret_key

        self.log.debug("GET %s params=%s", url, params)
        resp = requests.get(
            url,
            params=params,
            timeout=self.config.request_timeout_seconds,
            headers=headers,
        )

        if resp.status_code == 401:
            raise PermissionError(
                "Freightos API returned 401 — configure FREIGHTOS_API_KEY and "
                "FREIGHTOS_SECRET_KEY (developers.freightos.com)"
            )

        if resp.status_code == 404:
            self.log.debug("No rate data for %s → %s (%s)", origin, destination, container_type)
            return []

        if resp.status_code == 429:
            self.log.warning("Rate limited on FBX API; backing off")
            raise OSError("Rate limited by Freightos API")

        resp.raise_for_status()

        data = resp.json()
        records: list[Any] = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = cast(list[Any], data.get("data", data.get("results", [])))

        for rec in records:
            rec["originPort"] = origin
            rec["destinationPort"] = destination
            rec["containerType"] = container_type

        return records

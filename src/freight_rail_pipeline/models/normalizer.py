from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from .schemas import (
    OceanFreightRate,
    RailCarloading,
    RailServiceMetric,
)

log = logging.getLogger(__name__)


class DataNormalizer:
    @staticmethod
    def normalize_rail_carloading(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> RailCarloading | None:
        try:
            carloads_raw = raw.get("carloads") or raw.get("volume") or raw.get("count")
            if carloads_raw is None:
                return None

            return RailCarloading(
                snapshot_date=snapshot_date or date.today(),
                railroad=str(raw.get("railroad", raw.get("carrier", "unknown"))),
                commodity=str(raw.get("commodity", raw.get("commodity_desc", "unknown"))),
                carloads=int(carloads_raw),
                carload_type=raw.get("type"),
                units=raw.get("units", "carloads"),
                origin_region=raw.get("origin", raw.get("origin_region")),
                destination_region=raw.get("destination", raw.get("destination_region")),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize rail carloading record: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def normalize_rail_service_metric(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> RailServiceMetric | None:
        try:
            metric_name = (
                raw.get("metric_name")
                or raw.get("metric")
                or raw.get("indicator")
                or raw.get("measure")
            )
            metric_value = raw.get("metric_value") or raw.get("value")
            railroad = raw.get("railroad") or raw.get("carrier") or raw.get("reporting_railroad")

            if not metric_name or metric_value is None or not railroad:
                return None

            unit = str(raw.get("unit", "unknown"))
            if unit == "unknown" and isinstance(metric_name, str):
                match = re.search(r"\(([^)]+)\)\s*$", metric_name)
                if match:
                    unit = match.group(1).strip().lower()

            return RailServiceMetric(
                snapshot_date=snapshot_date or date.today(),
                railroad=str(railroad),
                metric_name=str(metric_name).lower().replace(" ", "_"),
                metric_value=float(metric_value),
                unit=unit,
                region=raw.get("region"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize rail service metric: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def normalize_ocean_freight_rate(raw: dict[str, Any]) -> OceanFreightRate | None:
        try:
            rate_usd = (
                raw.get("rateUsd")
                or raw.get("rate_usd")
                or raw.get("rate")
                or raw.get("median_price")
                or raw.get("average_price")
            )
            if rate_usd is None:
                return None

            published = raw.get("publishedDate") or raw.get("published_date") or raw.get("date")
            parsed_date = date.today()
            if published:
                if isinstance(published, str):
                    parsed_date = datetime.fromisoformat(published.replace("Z", "+00:00")).date()

            return OceanFreightRate(
                snapshot_date=parsed_date,
                route_code=str(raw.get("routeCode", raw.get("route_code", "unknown"))),
                route_description=str(raw.get("route", raw.get("route_description", ""))),
                origin_port=str(raw.get("originPort", raw.get("origin_port", "unknown"))),
                destination_port=str(
                    raw.get("destinationPort", raw.get("destination_port", "unknown"))
                ),
                trade_lane=str(raw.get("tradeRoute", raw.get("trade_lane", "unknown"))),
                container_type=str(raw.get("containerType", raw.get("container_type", "40GP"))),
                rate_usd=int(rate_usd),
                region=raw.get("region"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize ocean freight rate: %s | raw=%s", exc, raw)
            return None

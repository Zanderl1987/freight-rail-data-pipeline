from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from .schemas import (
    FreightIndicator,
    OceanFreightRate,
    RailCarloading,
    RailServiceMetric,
)

log = logging.getLogger(__name__)


def _extract_unit(metric_name: str) -> str:
    """Extract a unit from a measure label like '... (Hours)' or '... (mph)'."""
    if "(" in metric_name and metric_name.rstrip().endswith(")"):
        inner = metric_name.split("(", 1)[1].rstrip(")").strip()
        if inner:
            return inner.lower()
    return "unknown"


class DataNormalizer:
    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                return None
        return None

    @staticmethod
    def normalize_rail_carloading(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> RailCarloading | None:
        try:
            carloads_raw = raw.get("carloads") or raw.get("volume") or raw.get("count")
            if carloads_raw is None:
                return None

            record_date = DataNormalizer._parse_date(raw.get("date"))
            reported = record_date or snapshot_date or date.today()

            return RailCarloading(
                snapshot_date=reported,
                railroad=str(raw.get("railroad", raw.get("carrier", "unknown"))),
                commodity=str(raw.get("commodity", raw.get("commodity_desc", "unknown"))),
                traffic_type=raw.get("type") or raw.get("traffic_type"),
                carloads=float(carloads_raw),
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
                raw.get("measure")
                or raw.get("metric_name")
                or raw.get("metric")
                or raw.get("indicator")
            )
            metric_value = raw.get("value") or raw.get("metric_value")
            railroad = raw.get("railroad") or raw.get("carrier") or raw.get("reporting_railroad")

            if not metric_name or metric_value is None or not railroad:
                return None

            record_date = DataNormalizer._parse_date(raw.get("date"))
            reported = record_date or snapshot_date or date.today()

            unit = raw.get("unit") or _extract_unit(str(metric_name))

            return RailServiceMetric(
                snapshot_date=reported,
                railroad=str(railroad),
                metric_name=str(metric_name).lower().replace(" ", "_"),
                metric_value=float(metric_value),
                unit=str(unit),
                region=raw.get("region"),
                segment=raw.get("variable") or raw.get("segment"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize rail service metric: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def normalize_freight_indicator(raw: dict[str, Any]) -> FreightIndicator | None:
        try:
            external_id = raw.get("id")
            indicator = raw.get("indicator")
            value_raw = raw.get("value1")
            if external_id is None or indicator is None or value_raw is None:
                return None

            record_date = DataNormalizer._parse_date(raw.get("date"))
            if record_date is None:
                return None

            return FreightIndicator(
                external_id=str(external_id),
                snapshot_date=record_date,
                indicator=str(indicator),
                measure1=raw.get("measure1"),
                measure2=raw.get("measure2"),
                value=float(value_raw),
                units=raw.get("units"),
                underlying_source=raw.get("source"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize freight indicator: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def normalize_ocean_freight_rate(raw: dict[str, Any]) -> OceanFreightRate | None:
        try:
            rate_usd = raw.get("rateUsd") or raw.get("rate_usd") or raw.get("rate")
            if rate_usd is None:
                return None

            published = raw.get("publishedDate") or raw.get("published_date")
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
                rate_usd=float(rate_usd),
                region=raw.get("region"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize ocean freight rate: %s | raw=%s", exc, raw)
            return None

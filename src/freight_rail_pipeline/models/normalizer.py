from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .schemas import (
    FreightIndicator,
    OceanFreightRate,
    RailCarloading,
    RailSafetyIncident,
    RailServiceMetric,
    RailTariffRate,
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
    def normalize_grain_rail_carload(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> RailCarloading | None:
        """USDA AgTransport's grain-specific weekly car counts (resource 27k8-utc2)
        report one row per railroad/state/week with `all`/`dedicated_or_shuttle`/`other`
        car counts rather than the generic carloadings feed's `carloads` field."""
        try:
            railroad = raw.get("railroad")
            total_cars = raw.get("all")
            if not railroad or total_cars is None:
                return None

            record_date = DataNormalizer._parse_date(raw.get("date"))
            reported = record_date or snapshot_date or date.today()

            return RailCarloading(
                snapshot_date=reported,
                railroad=str(railroad),
                commodity="Grain",
                traffic_type=None,
                carloads=float(total_cars),
                units="cars",
                origin_region=raw.get("state"),
                destination_region=None,
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize grain rail carload record: %s | raw=%s", exc, raw)
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
    def _safe_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_decimal(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @staticmethod
    def _parse_fra_date(raw: dict[str, Any]) -> date | None:
        """FRA's `date` field is null on many older records (mostly pre-1990s) even
        though year/month/day are populated -- fall back to reconstructing it. Form 54
        uses `accidentmonth`; Form 57 has a plain `month` field."""
        parsed = DataNormalizer._parse_date(raw.get("date"))
        if parsed is not None:
            return parsed
        year = raw.get("year")
        month = raw.get("month") or raw.get("accidentmonth")
        day = raw.get("day")
        if year and month and day:
            try:
                return date(int(year), int(month), int(day))
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def normalize_rail_safety_incident(
        raw: dict[str, Any], incident_type: str
    ) -> RailSafetyIncident | None:
        """incident_type: 'train_accident' (Form 54) or 'highway_rail_crossing' (Form 57) --
        the two forms share most fields but use different names for casualty/cost totals
        and even for the reporting railroad's own code/name."""
        try:
            external_id = raw.get("reportkey")
            record_date = DataNormalizer._parse_fra_date(raw)
            if external_id is None or record_date is None:
                return None

            if incident_type == "train_accident":
                killed = raw.get("totalkilledform54")
                injured = raw.get("totalinjuredform54")
                damage = raw.get("totaldamagecost")
                category = raw.get("accidenttype")
            else:
                killed = raw.get("totalkilledform57")
                injured = raw.get("totalinjuredform57")
                damage = raw.get("vehicledamagecost")
                category = raw.get("equipmentinvolved")

            return RailSafetyIncident(
                external_id=str(external_id),
                incident_type=incident_type,
                incident_date=record_date,
                railroad_code=raw.get("reportingrailroadcode") or raw.get("railroadcode"),
                railroad_name=raw.get("reportingrailroadname") or raw.get("railroadname"),
                state=raw.get("statename"),
                county=raw.get("countyname"),
                category=category,
                total_killed=DataNormalizer._safe_int(killed),
                total_injured=DataNormalizer._safe_int(injured),
                damage_cost_usd=DataNormalizer._safe_float(damage),
                latitude=DataNormalizer._safe_float(raw.get("latitude")),
                longitude=DataNormalizer._safe_float(raw.get("longitude")),
                narrative=raw.get("narrative"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize rail safety incident: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def normalize_rail_tariff_rate(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> RailTariffRate | None:
        """USDA AgTransport's Historical U.S. Rail Tariff Rates for Grain and Soybeans
        (resource idbx-qf4w): monthly published tariffs by railroad/origin/destination."""
        try:
            railroad = raw.get("railroad")
            commodity = raw.get("commodity")
            origin_city = raw.get("origin_city")
            origin_state = raw.get("origin_state")
            destination_city = raw.get("destination_city")
            destination_state = raw.get("destination_state")
            if not railroad or not commodity or not origin_city or not destination_city:
                return None

            record_date = DataNormalizer._parse_date(raw.get("date"))
            reported = record_date or snapshot_date or date.today()

            origin = f"{origin_city}, {origin_state}" if origin_state else str(origin_city)
            destination = (
                f"{destination_city}, {destination_state}"
                if destination_state
                else str(destination_city)
            )

            return RailTariffRate(
                snapshot_date=reported,
                railroad=str(railroad),
                commodity=str(commodity),
                origin=origin,
                destination=destination,
                rate_per_car=DataNormalizer._safe_decimal(raw.get("tariff_car")),
                fuel_surcharge=DataNormalizer._safe_decimal(raw.get("fsc_car")),
                movement_type=raw.get("train_type"),
                raw_record=raw,
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize rail tariff rate record: %s | raw=%s", exc, raw)
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

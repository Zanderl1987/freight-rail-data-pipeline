from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .schemas import (
    EurostatRailFreight,
    FreightIndicator,
    MotorCarrierCensus,
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
    def _first_not_none(raw: dict[str, Any], *keys: str) -> Any:
        """Return the first present value across `keys`.

        Uses `is not None` rather than truthiness so a legitimate `0` is
        treated as a value, not as a missing field.
        """
        for key in keys:
            value = raw.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def normalize_rail_carloading(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> RailCarloading | None:
        try:
            carloads_raw = DataNormalizer._first_not_none(raw, "carloads", "volume", "count")
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
            metric_value = DataNormalizer._first_not_none(raw, "value", "metric_value")
            railroad = raw.get("railroad") or raw.get("carrier") or raw.get("reporting_railroad")

            if not metric_name or metric_value is None or not railroad:
                return None

            record_date = DataNormalizer._parse_date(raw.get("date"))
            reported = record_date or snapshot_date or date.today()

            unit = raw.get("unit") or _extract_unit(str(metric_name))

            # Strip the unit parenthetical (e.g. "Average Train Speed (mph)")
            # out of the metric label before slugifying it.
            metric_label = str(metric_name)
            if "(" in metric_label:
                metric_label = metric_label[: metric_label.index("(")].strip()

            return RailServiceMetric(
                snapshot_date=reported,
                railroad=str(railroad),
                metric_name=metric_label.lower().replace(" ", "_"),
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
    def normalize_eurostat_rail(
        raw: dict[str, Any],
    ) -> EurostatRailFreight | None:
        """Normalize one decoded Eurostat `rail_go_total` observation. `raw` is a
        flat dict built by the Eurostat source with fields: country_code,
        country_name, unit, period, value. Missing/blank values are dropped by the
        source before this is called, so a non-numeric value here is unexpected."""
        try:
            country_code = raw.get("country_code")
            period = raw.get("period")
            unit = raw.get("unit")
            value = raw.get("value")
            if not country_code or not period or not unit or value is None:
                return None

            try:
                year = int(period)
                snapshot_date = date(year, 12, 31)
            except (ValueError, TypeError):
                log.warning("Failed to parse Eurostat period %r; record dropped", raw.get("period"))
                return None

            metric = "rail_goods_tonnes" if unit == "THS_T" else "rail_goods_tonne_km"

            return EurostatRailFreight(
                snapshot_date=snapshot_date,
                period=str(period),
                country_code=str(country_code),
                country_name=raw.get("country_name"),
                unit=str(unit),
                metric=metric,
                value=float(value),
                raw_record=raw,
            )
        except (ValueError, TypeError) as exc:
            log.warning("Failed to normalize Eurostat rail record: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def _parse_fmcsa_date(value: Any) -> date | None:
        """FMCSA's mcs150_date is 'DD-MON-YY' (e.g. '20-OCT-23'), not ISO."""
        if not value or not isinstance(value, str):
            return None
        try:
            return datetime.strptime(value, "%d-%b-%y").date()
        except ValueError:
            return None

    @staticmethod
    def normalize_motor_carrier_census(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> MotorCarrierCensus | None:
        """`raw` must already be PII-stripped -- the FMCSA source only ever
        selects non-identity columns from Socrata (see fmcsa_carrier_census.py),
        so no name/address/email/phone fields exist here to accidentally keep."""
        try:
            dot_number = raw.get("dot_number")
            if not dot_number:
                return None

            record_date = DataNormalizer._parse_fmcsa_date(raw.get("mcs150_date"))
            reported = record_date or snapshot_date or date.today()

            return MotorCarrierCensus(
                snapshot_date=reported,
                dot_number=str(dot_number),
                carrier_operation=raw.get("carrier_operation"),
                state=raw.get("phy_state"),
                power_units=DataNormalizer._safe_int(raw.get("nbr_power_unit")),
                driver_count=DataNormalizer._safe_int(raw.get("driver_total")),
                mileage=DataNormalizer._safe_int(raw.get("recent_mileage")),
                mileage_year=DataNormalizer._safe_int(raw.get("recent_mileage_year")),
            )
        except (ValueError, TypeError, KeyError) as exc:
            log.warning("Failed to normalize motor carrier census record: %s | raw=%s", exc, raw)
            return None

    @staticmethod
    def normalize_ocean_freight_rate(
        raw: dict[str, Any],
        snapshot_date: date | None = None,
    ) -> OceanFreightRate | None:
        try:
            rate_usd = DataNormalizer._first_not_none(raw, "rateUsd", "rate_usd", "rate")
            if rate_usd is None:
                return None

            published = DataNormalizer._first_not_none(raw, "publishedDate", "published_date")
            # Fall back to the run's snapshot date (or today) for missing or
            # malformed dates instead of dropping the record.
            parsed_date = DataNormalizer._parse_date(published) or snapshot_date or date.today()

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

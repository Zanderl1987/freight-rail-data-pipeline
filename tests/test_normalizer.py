from __future__ import annotations

from datetime import date
from decimal import Decimal

from freight_rail_pipeline.models.normalizer import DataNormalizer


class TestRailCarloadingNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "date": "2026-07-25T00:00:00.000",
            "railroad": "BNSF",
            "commodity": "Grain",
            "type": "Originated",
            "carloads": "1500",
        }
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is not None
        assert result.railroad == "BNSF"
        assert result.commodity == "Grain"
        assert result.carloads == 1500
        assert result.traffic_type == "Originated"
        assert result.snapshot_date == date(2026, 7, 25)
        assert result.source == "usda_agtransport"

    def test_alternative_field_names(self) -> None:
        raw = {"carrier": "UP", "commodity_desc": "Coal", "volume": "5000"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is not None
        assert result.railroad == "UP"
        assert result.commodity == "Coal"
        assert result.carloads == 5000

    def test_snapshot_date_fallback(self) -> None:
        raw = {"railroad": "CSX", "commodity": "Chemicals", "carloads": 400}
        result = DataNormalizer.normalize_rail_carloading(raw, snapshot_date=date(2026, 7, 15))
        assert result is not None
        assert result.snapshot_date == date(2026, 7, 15)

    def test_fractional_carloads(self) -> None:
        # Real USDA data reports fractional carloads (e.g. prorated across a
        # mixed-commodity car) -- confirmed live 2026-08-03, was silently
        # dropping the record when carloads was typed int.
        raw = {"railroad": "CPKC", "commodity": "Pulp, Paper and Allied Products", "carloads": "811.5"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is not None
        assert result.carloads == 811.5

    def test_missing_carloads_returns_none(self) -> None:
        raw = {"railroad": "CSX", "commodity": "Chemicals"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is None

    def test_empty_record(self) -> None:
        result = DataNormalizer.normalize_rail_carloading({})
        assert result is None


class TestGrainRailCarloadNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "date": "2026-07-24T00:00:00.000",
            "railroad": "BNSF",
            "state": "AZ",
            "all": "2",
            "dedicated_or_shuttle": "0",
            "other": "2",
        }
        result = DataNormalizer.normalize_grain_rail_carload(raw)
        assert result is not None
        assert result.railroad == "BNSF"
        assert result.commodity == "Grain"
        assert result.carloads == 2.0
        assert result.units == "cars"
        assert result.origin_region == "AZ"
        assert result.snapshot_date == date(2026, 7, 24)

    def test_missing_railroad_returns_none(self) -> None:
        raw = {"date": "2026-07-24T00:00:00.000", "state": "AZ", "all": "2"}
        assert DataNormalizer.normalize_grain_rail_carload(raw) is None

    def test_missing_all_returns_none(self) -> None:
        raw = {"date": "2026-07-24T00:00:00.000", "railroad": "BNSF", "state": "AZ"}
        assert DataNormalizer.normalize_grain_rail_carload(raw) is None

    def test_zero_cars_is_valid(self) -> None:
        # `all` of "0" is a legitimate zero-cars week, not a missing value.
        raw = {"date": "2026-07-24T00:00:00.000", "railroad": "BNSF", "state": "AZ", "all": "0"}
        result = DataNormalizer.normalize_grain_rail_carload(raw)
        assert result is not None
        assert result.carloads == 0.0


class TestRailTariffRateNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "date": "2025-04-15T00:00:00.000",
            "commodity": "Soybeans",
            "origin_city": "Grand Island",
            "origin_state": "NE",
            "destination_city": "Portland",
            "destination_state": "OR",
            "train_type": "shuttle",
            "railroad": "UP",
            "tariff_car": "6185",
            "fsc_car": "523.84",
        }
        result = DataNormalizer.normalize_rail_tariff_rate(raw)
        assert result is not None
        assert result.railroad == "UP"
        assert result.commodity == "Soybeans"
        assert result.origin == "Grand Island, NE"
        assert result.destination == "Portland, OR"
        assert result.rate_per_car == Decimal("6185.00")
        assert result.fuel_surcharge == Decimal("523.84")
        assert result.movement_type == "shuttle"
        assert result.snapshot_date == date(2025, 4, 15)

    def test_missing_state_falls_back_to_city_only(self) -> None:
        raw = {
            "date": "2025-04-15T00:00:00.000",
            "commodity": "Wheat",
            "origin_city": "Chicago",
            "destination_city": "Albany",
            "railroad": "CSX",
            "tariff_car": "7413",
        }
        result = DataNormalizer.normalize_rail_tariff_rate(raw)
        assert result is not None
        assert result.origin == "Chicago"
        assert result.destination == "Albany"

    def test_missing_commodity_returns_none(self) -> None:
        raw = {
            "date": "2025-04-15T00:00:00.000",
            "origin_city": "Chicago",
            "destination_city": "Albany",
            "railroad": "CSX",
        }
        assert DataNormalizer.normalize_rail_tariff_rate(raw) is None

    def test_missing_railroad_returns_none(self) -> None:
        raw = {
            "date": "2025-04-15T00:00:00.000",
            "commodity": "Wheat",
            "origin_city": "Chicago",
            "destination_city": "Albany",
        }
        assert DataNormalizer.normalize_rail_tariff_rate(raw) is None


class TestRailServiceMetricNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "measure": "Average Train Speed (mph)",
            "date": "2026-07-24T00:00:00.000",
            "railroad": "BNSF",
            "variable": "Automotive",
            "value": "24.7",
        }
        result = DataNormalizer.normalize_rail_service_metric(raw)
        assert result is not None
        assert result.railroad == "BNSF"
        assert result.metric_name == "average_train_speed_(mph)"
        assert result.metric_value == 24.7
        assert result.unit == "mph"
        assert result.segment == "Automotive"
        assert result.snapshot_date == date(2026, 7, 24)

    def test_alternative_field_names(self) -> None:
        raw = {"reporting_railroad": "UP", "indicator": "terminal dwell", "value": "12.3"}
        result = DataNormalizer.normalize_rail_service_metric(raw)
        assert result is not None
        assert result.railroad == "UP"
        assert result.metric_name == "terminal_dwell"
        assert result.metric_value == 12.3

    def test_missing_required_fields(self) -> None:
        assert DataNormalizer.normalize_rail_service_metric({}) is None
        assert DataNormalizer.normalize_rail_service_metric({"railroad": "BNSF"}) is None
        assert DataNormalizer.normalize_rail_service_metric({"metric_name": "speed"}) is None


class TestOceanFreightRateNormalizer:
    def test_valid_fbx_record(self) -> None:
        raw = {
            "routeCode": "FBX01",
            "originPort": "CNSHA",
            "destinationPort": "USLAX",
            "containerType": "40GP",
            "rateUsd": 4500,
            "tradeLane": "Trans-Pacific Eastbound",
            "publishedDate": "2026-07-28",
        }
        result = DataNormalizer.normalize_ocean_freight_rate(raw)
        assert result is not None
        assert result.route_code == "FBX01"
        assert result.origin_port == "CNSHA"
        assert result.destination_port == "USLAX"
        assert result.container_type == "40GP"
        assert result.rate_usd == 4500
        assert result.snapshot_date == date(2026, 7, 28)

    def test_alternative_field_names(self) -> None:
        raw = {
            "route_code": "FBX03",
            "origin_port": "CNSHA",
            "destination_port": "USNYC",
            "container_type": "40HC",
            "rate_usd": "5800",
            "trade_lane": "Trans-Pacific Eastbound",
        }
        result = DataNormalizer.normalize_ocean_freight_rate(raw)
        assert result is not None
        assert result.rate_usd == 5800
        assert result.container_type == "40HC"

    def test_fractional_rate(self) -> None:
        raw = {"routeCode": "FBX01", "originPort": "CNSHA", "destinationPort": "USLAX",
               "containerType": "40GP", "rateUsd": 4521.75, "tradeLane": "Trans-Pacific Eastbound"}
        result = DataNormalizer.normalize_ocean_freight_rate(raw)
        assert result is not None
        assert result.rate_usd == 4521.75

    def test_missing_rate_returns_none(self) -> None:
        raw = {"routeCode": "FBX01", "originPort": "CNSHA"}
        result = DataNormalizer.normalize_ocean_freight_rate(raw)
        assert result is None


class TestFreightIndicatorNormalizer:
    def test_valid_record_with_measures(self) -> None:
        raw = {
            "id": "59_2026_07_18_Memphis, TN_BNSF",
            "date": "2026-07-18T00:00:00.000",
            "indicator": "Average Dwell Time at Class I Railroad Terminals",
            "measure1": "Memphis, TN",
            "measure2": "BNSF",
            "value1": "18.9",
            "units": "Hours",
            "source": "Surface Transportation Board (STB)",
        }
        result = DataNormalizer.normalize_freight_indicator(raw)
        assert result is not None
        assert result.external_id == "59_2026_07_18_Memphis, TN_BNSF"
        assert result.value == 18.9
        assert result.measure1 == "Memphis, TN"
        assert result.underlying_source == "Surface Transportation Board (STB)"

    def test_valid_record_no_measures(self) -> None:
        raw = {
            "id": "20_2026_07_18",
            "date": "2026-07-18T00:00:00.000",
            "indicator": "U.S. Class I Total Rail Non-Intermodal Carloads",
            "value1": "256117",
            "units": "Carloads",
        }
        result = DataNormalizer.normalize_freight_indicator(raw)
        assert result is not None
        assert result.measure1 is None
        assert result.value == 256117.0

    def test_missing_value_returns_none(self) -> None:
        raw = {"id": "x", "date": "2026-07-18T00:00:00.000", "indicator": "foo"}
        result = DataNormalizer.normalize_freight_indicator(raw)
        assert result is None


class TestRailSafetyIncidentNormalizer:
    def test_train_accident_form54(self) -> None:
        raw = {
            "reportkey": "BNSFMT0526112202605",
            "reportingrailroadcode": "BNSF",
            "reportingrailroadname": "BNSF Railway Company",
            "date": "2026-05-31T00:00:00.000",
            "statename": "NORTH DAKOTA",
            "countyname": "STARK",
            "accidenttype": "Derailment",
            "totalkilledform54": "0",
            "totalinjuredform54": "0",
            "totaldamagecost": "44623",
            "latitude": "46.876573",
            "longitude": "-102.809469",
        }
        result = DataNormalizer.normalize_rail_safety_incident(raw, "train_accident")
        assert result is not None
        assert result.railroad_code == "BNSF"
        assert result.category == "Derailment"
        assert result.total_killed == 0
        assert result.damage_cost_usd == 44623.0
        assert result.latitude == 46.876573

    def test_highway_rail_crossing_form57_uses_different_railroad_fields(self) -> None:
        # Form 57 uses railroadcode/railroadname, NOT reportingrailroadcode/name
        # like Form 54 -- real bug found live 2026-08-03.
        raw = {
            "reportkey": "AA15197503",
            "railroadcode": "AA",
            "railroadname": "Ann Arbor Railroad",
            "date": "1975-03-17T00:00:00.000",
            "equipmentinvolved": "Train (units pulling)",
            "totalkilledform57": "0",
            "totalinjuredform57": "1",
            "vehicledamagecost": "500",
        }
        result = DataNormalizer.normalize_rail_safety_incident(raw, "highway_rail_crossing")
        assert result is not None
        assert result.railroad_code == "AA"
        assert result.total_injured == 1
        assert result.damage_cost_usd == 500.0

    def test_null_date_falls_back_to_year_month_day(self) -> None:
        # Real data quality issue found live: many pre-1990s records have a
        # null `date` field even though year/month/day are populated, and
        # Socrata's `order=date desc` sorts those nulls first.
        raw = {
            "reportkey": "AA15197503",
            "date": None,
            "year": "1975",
            "month": "03",
            "day": "17",
            "totalkilledform57": "0",
            "totalinjuredform57": "0",
            "vehicledamagecost": "0",
        }
        result = DataNormalizer.normalize_rail_safety_incident(raw, "highway_rail_crossing")
        assert result is not None
        assert result.incident_date == date(1975, 3, 17)

    def test_missing_reportkey_returns_none(self) -> None:
        raw = {"date": "2026-01-01T00:00:00.000"}
        result = DataNormalizer.normalize_rail_safety_incident(raw, "train_accident")
        assert result is None

    def test_no_date_and_no_year_month_day_returns_none(self) -> None:
        raw = {"reportkey": "x", "date": None}
        result = DataNormalizer.normalize_rail_safety_incident(raw, "train_accident")
        assert result is None

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
        raw = {
            "railroad": "CPKC",
            "commodity": "Pulp, Paper and Allied Products",
            "carloads": "811.5",
        }
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is not None
        assert result.carloads == 811.5

    def test_missing_carloads_returns_none(self) -> None:
        raw = {"railroad": "CSX", "commodity": "Chemicals"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is None

    def test_zero_carloads_is_valid(self) -> None:
        # I1: a reported 0 carloads is a real value, not a missing field --
        # falsy-zero `or` chains used to drop it.
        raw = {"railroad": "CSX", "commodity": "Chemicals", "carloads": "0"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is not None
        assert result.carloads == 0

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


class TestMotorCarrierCensusNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "dot_number": "1000000",
            "carrier_operation": "A",
            "phy_state": "AL",
            "nbr_power_unit": "2",
            "driver_total": "2",
            "recent_mileage": "24227",
            "recent_mileage_year": "2025",
            "mcs150_date": "21-APR-26",
        }
        result = DataNormalizer.normalize_motor_carrier_census(raw)
        assert result is not None
        assert result.dot_number == "1000000"
        assert result.carrier_operation == "A"
        assert result.state == "AL"
        assert result.power_units == 2
        assert result.driver_count == 2
        assert result.mileage == 24227
        assert result.mileage_year == 2025
        assert result.snapshot_date == date(2026, 4, 21)

    def test_no_pii_fields_in_output(self) -> None:
        # Even if a legal_name/email somehow ended up in raw (shouldn't happen
        # since the source only ever selects non-identity columns), the model
        # itself has no field to carry it -- confirms the schema-level guard.
        raw = {
            "dot_number": "42",
            "legal_name": "SHOULD NOT APPEAR",
            "email_address": "should-not-appear@example.com",
        }
        result = DataNormalizer.normalize_motor_carrier_census(raw)
        assert result is not None
        assert "legal_name" not in result.model_dump()
        assert "email_address" not in result.model_dump()
        assert not hasattr(result, "raw_record")

    def test_missing_dot_number_returns_none(self) -> None:
        raw = {"carrier_operation": "A", "mcs150_date": "21-APR-26"}
        assert DataNormalizer.normalize_motor_carrier_census(raw) is None

    def test_null_date_falls_back_to_snapshot_date(self) -> None:
        raw = {"dot_number": "42", "mcs150_date": None}
        result = DataNormalizer.normalize_motor_carrier_census(raw, snapshot_date=date(2026, 1, 1))
        assert result is not None
        assert result.snapshot_date == date(2026, 1, 1)

    def test_zero_mileage_is_valid_not_missing(self) -> None:
        raw = {
            "dot_number": "42",
            "recent_mileage": "0",
            "recent_mileage_year": "0",
            "mcs150_date": "30-APR-22",
        }
        result = DataNormalizer.normalize_motor_carrier_census(raw)
        assert result is not None
        assert result.mileage == 0
        assert result.mileage_year == 0


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
        assert result.metric_name == "average_train_speed"
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

    def test_zero_metric_value_is_valid(self) -> None:
        # I1: a legitimate 0 (e.g. zero dwell hours) must not be treated as missing.
        raw = {
            "measure": "Terminal Dwell Time",
            "date": "2026-07-24T00:00:00.000",
            "railroad": "BNSF",
            "value": "0",
        }
        result = DataNormalizer.normalize_rail_service_metric(raw)
        assert result is not None
        assert result.metric_value == 0


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

    def test_zero_rate_is_valid(self) -> None:
        # I1: a 0 rate must be kept, not dropped as "missing".
        raw = {
            "routeCode": "FBX01",
            "originPort": "CNSHA",
            "destinationPort": "USLAX",
            "containerType": "40GP",
            "rateUsd": 0,
            "tradeLane": "Trans-Pacific Eastbound",
            "publishedDate": "2026-07-28",
        }
        result = DataNormalizer.normalize_ocean_freight_rate(raw)
        assert result is not None
        assert result.rate_usd == 0

    def test_malformed_date_falls_back_to_snapshot_date(self) -> None:
        # I5: an unparseable publishedDate must not silently stamp today nor
        # drop the record -- fall back to the run's snapshot date.
        raw = {
            "routeCode": "FBX01",
            "originPort": "CNSHA",
            "destinationPort": "USLAX",
            "containerType": "40GP",
            "rateUsd": 4500,
            "publishedDate": "not-a-date",
        }
        result = DataNormalizer.normalize_ocean_freight_rate(
            raw, snapshot_date=date(2026, 7, 1)
        )
        assert result is not None
        assert result.snapshot_date == date(2026, 7, 1)

    def test_missing_date_falls_back_to_snapshot_date(self) -> None:
        raw = {
            "routeCode": "FBX01",
            "originPort": "CNSHA",
            "destinationPort": "USLAX",
            "containerType": "40GP",
            "rateUsd": 4500,
        }
        result = DataNormalizer.normalize_ocean_freight_rate(
            raw, snapshot_date=date(2026, 7, 1)
        )
        assert result is not None
        assert result.snapshot_date == date(2026, 7, 1)


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

class TestWaybillShipmentNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "waybill_date": "041118",
            "accounting_period": "0324",
            "carloads": "0001",
            "car_ownership": "P",
            "aar_equipment_type": "T106",
            "stb_car_type": "51",
            "stcc": "48110",
            "billed_tons": "00100",
            "actual_tons": "00100",
            "freight_revenue": "000023475",
            "transit_charges": "000000000",
            "miscellaneous_charges": "000000000",
            "exact_expansion_factor": "00500",
            "theoretical_expansion_factor": "005",
            "expanded_carloads": "000005",
            "expanded_tons": "000000500",
            "expanded_freight_revenue": "000000117375",
            "interchange_state_1": "ND",
        }
        result = DataNormalizer.normalize_waybill_shipment(raw, reference_year=2024)
        assert result is not None
        assert result.snapshot_date == date(2018, 4, 11)
        assert result.accounting_period == "03/24"
        assert result.carloads == 1
        assert result.stcc == "48110"
        assert result.freight_revenue == 23475.0
        assert result.expanded_carloads == 5
        assert result.interchange_states == "ND"

    def test_century_inference_prefers_nearest_to_reference_year(self) -> None:
        # A 2024 sample can contain waybills dated a few years earlier; the
        # century must resolve to the 2000s, never 1900s.
        assert DataNormalizer._parse_waybill_date("041118", 2024) == date(2018, 4, 11)
        assert DataNormalizer._parse_waybill_date("123124", 2024) == date(2024, 12, 31)
        assert DataNormalizer._parse_waybill_date("010125", 2024) == date(2025, 1, 1)

    def test_blank_stcc_returns_none(self) -> None:
        raw = {"carloads": "0001", "stcc": "     "}
        result = DataNormalizer.normalize_waybill_shipment(raw, reference_year=2024)
        assert result is None

    def test_missing_carloads_returns_none(self) -> None:
        raw = {"stcc": "48110"}
        result = DataNormalizer.normalize_waybill_shipment(raw, reference_year=2024)
        assert result is None

    def test_invalid_date_returns_none(self) -> None:
        raw = {"carloads": "0001", "stcc": "48110", "waybill_date": "023024"}
        result = DataNormalizer.normalize_waybill_shipment(raw, reference_year=2024)
        assert result is None


class TestTransBorderFreightNormalizer:
    def test_valid_truck_row_dot1(self) -> None:
        raw = {
            "TRDTYPE": "1",
            "USASTATE": "AK",
            "DEPE": "0901",
            "DISAGMOT": "5",
            "MEXSTATE": "",
            "CANPROV": "XY",
            "COUNTRY": "1220",
            "VALUE": "42199",
            "SHIPWT": "0",
            "FREIGHT_CHARGES": "62",
            "DF": "1",
            "CONTCODE": "1",
            "MONTH": "01",
            "YEAR": "2026",
        }
        result = DataNormalizer.normalize_transborder_freight(raw, source_file="dot1")
        assert result is not None
        assert result.snapshot_date == date(2026, 1, 31)
        assert result.trade_type == "import"
        assert result.country == "CA"
        assert result.mode == "truck"
        assert result.value_usd == 42199.0
        assert result.containerized is True
        assert result.us_state == "AK"
        assert result.source_file == "dot1"

    def test_mexico_export_maps_country_code(self) -> None:
        raw = {
            "TRDTYPE": "2",
            "DISAGMOT": "6",
            "COUNTRY": "2010",
            "VALUE": "1000",
            "MONTH": "02",
            "YEAR": "2025",
        }
        result = DataNormalizer.normalize_transborder_freight(raw)
        assert result is not None
        assert result.country == "MX"
        assert result.mode == "rail"
        assert result.trade_type == "export"
        assert result.disagg_mode == 6
        assert result.containerized is False

    def test_rail_row_dot2_keeps_commodity(self) -> None:
        raw = {
            "TRDTYPE": "1",
            "USASTATE": "WA",
            "COMMODITY2": "10",
            "DISAGMOT": "6",
            "COUNTRY": "1220",
            "VALUE": "50000",
            "SHIPWT": "12000",
            "FREIGHT_CHARGES": "800",
            "DF": "",
            "CONTCODE": "X",
            "MONTH": "01",
            "YEAR": "2026",
        }
        result = DataNormalizer.normalize_transborder_freight(raw, source_file="dot2")
        assert result is not None
        assert result.commodity_2digit == "10"
        assert result.containerized is False

    def test_missing_value_returns_none(self) -> None:
        raw = {"TRDTYPE": "1", "COUNTRY": "1220", "MONTH": "01", "YEAR": "2026"}
        result = DataNormalizer.normalize_transborder_freight(raw)
        assert result is None


class TestAARWeeklyNormalizer:
    def test_valid_row(self) -> None:
        raw = {
            "region": "US",
            "week_number": "31",
            "year": "2026",
            "week_end_date": "2026-08-08",
            "category": "Coal",
            "this_week_cars": "57976",
            "this_week_yoy_pct": "-6.1%",
            "ytd_cars": "1761694",
            "ytd_avg_week_cars": "56829",
            "ytd_yoy_pct": "-1.8%",
        }
        result = DataNormalizer.normalize_aar_weekly(raw)
        assert result is not None
        assert result.snapshot_date == date(2026, 8, 8)
        assert result.region == "US"
        assert result.week_number == 31
        assert result.year == 2026
        assert result.category == "Coal"
        assert result.this_week_cars == 57976
        assert result.this_week_yoy_pct == -6.1
        assert result.ytd_cars == 1761694
        assert result.ytd_yoy_pct == -1.8

    def test_missing_required_fields_returns_none(self) -> None:
        raw = {"region": "US", "category": "Coal"}
        result = DataNormalizer.normalize_aar_weekly(raw)
        assert result is None


class TestGrainObservationNormalizer:
    def test_barge_rate_per_ton(self) -> None:
        raw = {
            "date": "2026-08-18T00:00:00.000",
            "river_system_location": "La Crosse - Minneapolis",
            "price_per_ton": "47.3535",
        }
        result = DataNormalizer.normalize_grain_observation(raw, "mississippi_barge_rates")
        assert result is not None
        assert result.metric == "barge_rate_per_ton"
        assert result.value == 47.3535
        assert result.location == "La Crosse - Minneapolis"
        assert result.units == "$ per ton"
        assert result.snapshot_date == date(2026, 8, 18)
        assert result.source == "usda_gtr"

    def test_barge_rate_pct_of_benchmark_keeps_week(self) -> None:
        raw = {"date": "2026-08-18T00:00:00.000", "location": "Twin Cities", "rate": "765"}
        result = DataNormalizer.normalize_grain_observation(raw, "downbound_grain_barge_rates")
        assert result is not None
        assert result.metric == "barge_rate_pct_of_benchmark"
        assert result.units == "% of benchmark"
        assert result.week_number is None

        raw["week"] = "33"
        with_week = DataNormalizer.normalize_grain_observation(
            raw, "downbound_grain_barge_rates"
        )
        assert with_week is not None
        assert with_week.week_number == 33

    def test_container_ocean_freight_route_fields(self) -> None:
        raw = {
            "date": "2026-07-01T00:00:00.000",
            "container_size": "20ft container",
            "origin": "U.S. Mid West (Chicago)",
            "destination_country": "Shanghai",
            "rate": "1551",
        }
        result = DataNormalizer.normalize_grain_observation(
            raw, "container_ocean_freight_rates"
        )
        assert result is not None
        assert result.origin == "U.S. Mid West (Chicago)"
        assert result.destination == "Shanghai"
        assert result.container_type == "20ft container"
        assert result.units == "$ per container"

    def test_vessel_rate_requires_known_value_field(self) -> None:
        raw = {"date": "2026-07-01T00:00:00.000", "gulf_to_japan": "68.95"}
        assert DataNormalizer.normalize_grain_observation(raw, "vessel_rates") is None
        bad = DataNormalizer.normalize_grain_observation(
            raw, "vessel_rates", value_field="not_a_column"
        )
        assert bad is None
        good = DataNormalizer.normalize_grain_observation(
            raw, "vessel_rates", value_field="gulf_to_japan"
        )
        assert good is not None
        assert good.location == "Gulf to Japan"
        assert good.value == 68.95

    def test_truck_rate_quarter_label(self) -> None:
        raw = {
            "yearquarter": "2026Q1",
            "region": "National",
            "rate_mile_trukload": "6.83",
        }
        result = DataNormalizer.normalize_grain_observation(raw, "quarterly_grain_truck_rates")
        assert result is not None
        assert result.quarter == "2026Q1"
        assert result.location == "National"
        assert result.units == "$ per mile"

    def test_barge_movements_tons(self) -> None:
        raw = {
            "date": "2026-08-15T00:00:00.000",
            "commodity": "Corn",
            "lock": "IL La Grange",
            "tons": "133600",
        }
        result = DataNormalizer.normalize_grain_observation(
            raw, "downbound_barge_grain_movements"
        )
        assert result is not None
        assert result.metric == "downbound_grain_barge_tons"
        assert result.commodity == "Corn"
        assert result.location == "IL La Grange"

    def test_inspection_metric_tons(self) -> None:
        raw = {
            "date": "2026-08-20T00:00:00.000",
            "port": "New Orleans",
            "grain": "Corn",
            "mt": "12345.6",
        }
        result = DataNormalizer.normalize_grain_observation(raw, "grain_inspections")
        assert result is not None
        assert result.metric == "grain_inspected"
        assert result.units == "metric tons"

    def test_missing_value_returns_none(self) -> None:
        raw = {"river_system_location": "La Crosse - Minneapolis"}
        assert (
            DataNormalizer.normalize_grain_observation(raw, "mississippi_barge_rates") is None
        )

    def test_unknown_series_returns_none(self) -> None:
        assert DataNormalizer.normalize_grain_observation({"value": "1"}, "nope") is None


class TestFMCContainerNormalizer:
    PORT_ROW = {
        "Quarter, Year": "Q1 2024",
        "Port Name": "Anchorage, Alaska",
        "Laden Exports": 3548,
        "Empty Exports": 132,
        "Laden Imports": 12,
        "Empty Imports": 5928,
        "Export Tonnage": 49266,
        "Import Tonnage": 5963,
    }

    def test_port_row_full(self) -> None:
        result = DataNormalizer.normalize_fmc_container(self.PORT_ROW, "port")
        assert result is not None
        assert result.snapshot_date == date(2024, 3, 31)
        assert result.quarter_label == "Q1 2024"
        assert result.year == 2024
        assert result.quarter == 1
        assert result.entity_type == "port"
        assert result.entity_name == "Anchorage, Alaska"
        assert result.laden_export_teu == 3548
        assert result.empty_import_teu == 5928
        assert result.export_tonnage == 49266.0

    def test_quarter_end_dates(self) -> None:
        row = dict(self.PORT_ROW, **{"Quarter, Year": "Q4 2025"})
        result = DataNormalizer.normalize_fmc_container(row, "port")
        assert result is not None
        assert result.snapshot_date == date(2025, 12, 31)

    def test_carrier_entity_name_column(self) -> None:
        row = {
            "Quarter, Year": "Q1 2024",
            "Carrier Name": "CMACGM",
            "Laden Exports": 456525,
        }
        result = DataNormalizer.normalize_fmc_container(row, "carrier")
        assert result is not None
        assert result.entity_name == "CMACGM"
        assert result.laden_import_teu is None

    def test_blank_teus_with_tonnage_kept(self) -> None:
        row = {
            "Quarter, Year": "Q2 2024",
            "Port Name": "Boston, Massachusetts",
            "Export Tonnage": 172132,
        }
        result = DataNormalizer.normalize_fmc_container(row, "port")
        assert result is not None
        assert result.laden_export_teu is None
        assert result.export_tonnage == 172132.0

    def test_all_measures_blank_returns_none(self) -> None:
        row = {"Quarter, Year": "Q2 2024", "Port Name": "Nowhere"}
        assert DataNormalizer.normalize_fmc_container(row, "port") is None

    def test_bad_quarter_label_returns_none(self) -> None:
        row = dict(self.PORT_ROW, **{"Quarter, Year": "early 2024"})
        assert DataNormalizer.normalize_fmc_container(row, "port") is None

    def test_missing_entity_name_returns_none(self) -> None:
        row = {"Quarter, Year": "Q1 2024"}
        assert DataNormalizer.normalize_fmc_container(row, "carrier") is None

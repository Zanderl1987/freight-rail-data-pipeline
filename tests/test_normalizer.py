from __future__ import annotations

from datetime import date

from freight_rail_pipeline.models.normalizer import DataNormalizer


class TestRailCarloadingNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "railroad": "BNSF",
            "commodity": "Grain",
            "carloads": 1500,
            "origin": "ND",
            "destination": "TX",
        }
        result = DataNormalizer.normalize_rail_carloading(raw, snapshot_date=date(2026, 7, 15))
        assert result is not None
        assert result.railroad == "BNSF"
        assert result.commodity == "Grain"
        assert result.carloads == 1500
        assert result.origin_region == "ND"
        assert result.destination_region == "TX"
        assert result.snapshot_date == date(2026, 7, 15)
        assert result.source == "usda_agtransport"

    def test_alternative_field_names(self) -> None:
        raw = {"carrier": "UP", "commodity_desc": "Coal", "volume": "5000"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is not None
        assert result.railroad == "UP"
        assert result.commodity == "Coal"
        assert result.carloads == 5000

    def test_preserves_carload_type(self) -> None:
        raw = {
            "railroad": "BNSF",
            "commodity": "Grain",
            "type": "Received",
            "carloads": 900,
        }
        result = DataNormalizer.normalize_rail_carloading(raw, snapshot_date=date(2026, 7, 15))
        assert result is not None
        assert result.carload_type == "Received"

    def test_missing_carloads_returns_none(self) -> None:
        raw = {"railroad": "CSX", "commodity": "Chemicals"}
        result = DataNormalizer.normalize_rail_carloading(raw)
        assert result is None

    def test_empty_record(self) -> None:
        result = DataNormalizer.normalize_rail_carloading({})
        assert result is None


class TestRailServiceMetricNormalizer:
    def test_valid_record(self) -> None:
        raw = {
            "railroad": "NS",
            "metric_name": "Train Speed",
            "metric_value": 22.5,
            "unit": "mph",
            "region": "East",
        }
        result = DataNormalizer.normalize_rail_service_metric(raw, snapshot_date=date(2026, 7, 15))
        assert result is not None
        assert result.railroad == "NS"
        assert result.metric_name == "train_speed"
        assert result.metric_value == 22.5
        assert result.unit == "mph"
        assert result.region == "East"

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

    def test_missing_rate_returns_none(self) -> None:
        raw = {"routeCode": "FBX01", "originPort": "CNSHA"}
        result = DataNormalizer.normalize_ocean_freight_rate(raw)
        assert result is None

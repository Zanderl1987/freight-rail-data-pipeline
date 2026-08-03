from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import responses

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.sources.bts_freight_indicators import BTSFreightIndicatorsSource
from freight_rail_pipeline.sources.fmcsa_carrier_census import (
    SELECT_COLUMNS,
    FMCSACarrierCensusSource,
)
from freight_rail_pipeline.sources.fra_safety import FRASafetySource
from freight_rail_pipeline.sources.freightos_fbx import FBX_ROUTES, FreightosFBXSource
from freight_rail_pipeline.sources.usda_agtransport import USDAgTransportSource


class TestUSDAgTransportSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> USDAgTransportSource:
        return USDAgTransportSource(config)

    @patch("freight_rail_pipeline.sources.usda_agtransport.Socrata")
    def test_fetch_carloadings_returns_records(self, mock_socrata: MagicMock, source: USDAgTransportSource) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = [
            {
                "date": "2026-07-25T00:00:00.000",
                "railroad": "BNSF",
                "commodity": "Grain",
                "type": "Originated",
                "carloads": "1500",
            },
            {
                "date": "2026-07-25T00:00:00.000",
                "railroad": "UP",
                "commodity": "Coal",
                "type": "Received",
                "carloads": "3200",
            },
        ]

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 2
        assert result.source_name == "usda_agtransport"
        assert all(isinstance(r.traffic_type, str) for r in result.records)

    @patch("freight_rail_pipeline.sources.usda_agtransport.Socrata")
    def test_fetch_service_metrics(self, mock_socrata: MagicMock, source: USDAgTransportSource) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = [
            {
                "measure": "Average Train Speed (mph)",
                "date": "2026-07-24T00:00:00.000",
                "railroad": "BNSF",
                "variable": "Automotive",
                "value": "24.7",
            }
        ]

        result = source.fetch_service_metrics(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 1
        metric = result.records[0]
        assert metric.metric_value == 24.7
        assert metric.unit == "mph"
        assert metric.segment == "Automotive"

    @patch("freight_rail_pipeline.sources.usda_agtransport.Socrata")
    def test_fetch_handles_empty_response(self, mock_socrata: MagicMock, source: USDAgTransportSource) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = []

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 0

    @patch("freight_rail_pipeline.sources.usda_agtransport.Socrata")
    def test_fetch_grain_rail_carloads_and_tariffs_via_full_fetch(
        self, mock_socrata: MagicMock, source: USDAgTransportSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client

        fixtures = {
            source.config.usda_socrata_resource_ids["rail_carloadings"]: [],
            source.config.usda_socrata_resource_ids["rail_service_metrics"]: [],
            source.config.usda_socrata_resource_ids["grain_rail_carloads"]: [
                {
                    "date": "2026-07-24T00:00:00.000",
                    "railroad": "BNSF",
                    "state": "AZ",
                    "all": "2",
                    "dedicated_or_shuttle": "0",
                    "other": "2",
                }
            ],
            source.config.usda_socrata_resource_ids["grain_rail_tariff_rates"]: [
                {
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
            ],
        }

        def get_side_effect(resource_id: str, **kwargs: object) -> list[dict[str, object]]:
            if kwargs.get("offset", 0):
                return []
            return fixtures.get(resource_id, [])

        mock_client.get.side_effect = get_side_effect

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 2
        assert result.metadata["grain_rail_carloads_raw"] == 1
        assert result.metadata["grain_rail_tariff_rates_raw"] == 1

        carload = next(r for r in result.records if type(r).__name__ == "RailCarloading")
        assert carload.commodity == "Grain"
        assert carload.carloads == 2.0
        assert carload.origin_region == "AZ"

        tariff = next(r for r in result.records if type(r).__name__ == "RailTariffRate")
        assert tariff.origin == "Grand Island, NE"
        assert tariff.destination == "Portland, OR"
        assert tariff.rate_per_car == Decimal("6185.00")
        assert tariff.fuel_surcharge == Decimal("523.84")

    @patch("freight_rail_pipeline.sources.usda_agtransport.Socrata")
    def test_validate_connectivity(self, mock_socrata: MagicMock, source: USDAgTransportSource) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = [{"date": "2026-07-25T00:00:00.000"}]

        warnings = source.validate()
        assert isinstance(warnings, list)
        assert warnings == []
        assert mock_client.get.call_count == len(source.config.usda_socrata_resource_ids)


class TestBTSFreightIndicatorsSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> BTSFreightIndicatorsSource:
        return BTSFreightIndicatorsSource(config)

    @patch("freight_rail_pipeline.sources.bts_freight_indicators.Socrata")
    def test_fetch_returns_normalized_records(
        self, mock_socrata: MagicMock, source: BTSFreightIndicatorsSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        # Real shape confirmed live 2026-08-03 against data.bts.gov/resource/y5ut-ibwt.json
        mock_client.get.return_value = [
            {
                "id": "59_2026_07_18_Memphis, TN_BNSF",
                "date": "2026-07-18T00:00:00.000",
                "year": "2026",
                "indicator": "Average Dwell Time at Class I Railroad Terminals",
                "measure1": "Memphis, TN",
                "measure2": "BNSF",
                "measure1_description": "Terminal",
                "measure2_description": "Railroad name",
                "value1": "18.9",
                "units": "Hours",
                "source": "Surface Transportation Board (STB)",
            }
        ]

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 1
        assert result.source_name == "bts_freight_indicators"

        rec = result.records[0]
        assert rec.external_id == "59_2026_07_18_Memphis, TN_BNSF"
        assert rec.indicator == "Average Dwell Time at Class I Railroad Terminals"
        assert rec.measure1 == "Memphis, TN"
        assert rec.measure2 == "BNSF"
        assert rec.value == 18.9
        assert rec.units == "Hours"
        assert rec.underlying_source == "Surface Transportation Board (STB)"

    @patch("freight_rail_pipeline.sources.bts_freight_indicators.Socrata")
    def test_fetch_handles_empty_response(
        self, mock_socrata: MagicMock, source: BTSFreightIndicatorsSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = []

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 0

    @patch("freight_rail_pipeline.sources.bts_freight_indicators.Socrata")
    def test_validate_connectivity(
        self, mock_socrata: MagicMock, source: BTSFreightIndicatorsSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = [{"date": "2026-07-18T00:00:00.000"}]

        warnings = source.validate()
        assert warnings == []


class TestFRASafetySource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> FRASafetySource:
        return FRASafetySource(config)

    @patch("freight_rail_pipeline.sources.fra_safety.Socrata")
    def test_fetch_returns_normalized_records_for_both_forms(
        self, mock_socrata: MagicMock, source: FRASafetySource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        # Real shapes confirmed live 2026-08-03 against datahub.transportation.gov
        # resources 85tf-25kj (Form 54) and 7wn6-i5b9 (Form 57).
        form54_row = {
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
            "narrative": "LIGHT POWER RAN THROUGH A SWITCH...",
        }
        # Older record with a null `date` field but populated year/month/day --
        # real data quality issue found live; must still normalize via fallback.
        form57_row = {
            "reportkey": "AA15197503",
            "railroadcode": "AA",
            "railroadname": "Ann Arbor Railroad",
            "date": None,
            "year": "1975",
            "month": "03",
            "day": "17",
            "statename": "MICHIGAN",
            "countyname": "WASHTENAW",
            "equipmentinvolved": "Train (units pulling)",
            "totalkilledform57": "0",
            "totalinjuredform57": "1",
            "vehicledamagecost": "0",
        }
        mock_client.get.side_effect = [[form54_row], [form57_row]]

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 2
        assert result.source_name == "fra_safety"

        by_type = {r.incident_type: r for r in result.records}
        train = by_type["train_accident"]
        assert train.external_id == "BNSFMT0526112202605"
        assert train.railroad_code == "BNSF"
        assert train.category == "Derailment"
        assert train.damage_cost_usd == 44623.0

        crossing = by_type["highway_rail_crossing"]
        assert crossing.external_id == "AA15197503"
        assert crossing.incident_date.isoformat() == "1975-03-17"
        assert crossing.railroad_code == "AA"
        assert crossing.total_injured == 1

    @patch("freight_rail_pipeline.sources.fra_safety.Socrata")
    def test_fetch_handles_empty_response(
        self, mock_socrata: MagicMock, source: FRASafetySource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = []

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 0

    @patch("freight_rail_pipeline.sources.fra_safety.Socrata")
    def test_validate_connectivity(
        self, mock_socrata: MagicMock, source: FRASafetySource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = [{"reportkey": "x", "date": "2026-01-01T00:00:00.000"}]

        warnings = source.validate()
        assert warnings == []

    @patch("freight_rail_pipeline.sources.fra_safety.Socrata")
    def test_backfill_uses_null_date_aware_where_clause(
        self, mock_socrata: MagicMock, source: FRASafetySource
    ) -> None:
        # I3: backfilling by date used to filter `where="date='X'"`, which can
        # never match the many pre-1990 records whose `date` is null. The where
        # clause must also cover the reconstructed year/month/day parts, using
        # each form's month column (accidentmonth for Form 54, month for Form 57).
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = []

        source.fetch(snapshot_date=date(1975, 3, 17))

        where_calls = [call.kwargs.get("where") for call in mock_client.get.call_args_list]
        assert len(where_calls) == 2
        for where in where_calls:
            assert where is not None
            assert "date='1975-03-17'" in where
            assert "year='1975'" in where
            assert "day='17'" in where
        assert "accidentmonth='3'" in where_calls[0] or "accidentmonth='03'" in where_calls[0]
        assert "month='3'" in where_calls[1] or "month='03'" in where_calls[1]


class TestFMCSACarrierCensusSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> FMCSACarrierCensusSource:
        return FMCSACarrierCensusSource(config)

    @patch("freight_rail_pipeline.sources.fmcsa_carrier_census.Socrata")
    def test_fetch_returns_normalized_records_and_requests_only_safe_columns(
        self, mock_socrata: MagicMock, source: FMCSACarrierCensusSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        # Real shape confirmed live 2026-08-03 against datahub.transportation.gov
        # resource kjg3-diqy, already restricted to non-identity columns.
        mock_client.get.return_value = [
            {
                "dot_number": "1000000",
                "carrier_operation": "A",
                "phy_state": "AL",
                "nbr_power_unit": "2",
                "driver_total": "2",
                "recent_mileage": "24227",
                "recent_mileage_year": "2025",
                "mcs150_date": "21-APR-26",
            }
        ]

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 1
        assert result.source_name == "fmcsa_carrier_census"

        record = result.records[0]
        assert record.dot_number == "1000000"
        assert record.state == "AL"
        assert record.power_units == 2

        # PII-safety contract: the source must only ever request the
        # non-identity column list, never name/address/email/phone fields.
        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs["select"] == SELECT_COLUMNS
        for pii_field in ("legal_name", "dba_name", "phy_street", "email_address", "telephone"):
            assert pii_field not in call_kwargs["select"]

    @patch("freight_rail_pipeline.sources.fmcsa_carrier_census.Socrata")
    def test_fetch_handles_empty_response(
        self, mock_socrata: MagicMock, source: FMCSACarrierCensusSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = []

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 0

    @patch("freight_rail_pipeline.sources.fmcsa_carrier_census.Socrata")
    def test_validate_connectivity(
        self, mock_socrata: MagicMock, source: FMCSACarrierCensusSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = [{"dot_number": "1"}]

        warnings = source.validate()
        assert warnings == []


class TestFreightosFBXSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> FreightosFBXSource:
        return FreightosFBXSource(config)

    @responses.activate
    def test_fetch_returns_normalized_records(self, source: FreightosFBXSource) -> None:
        base = source.config.fbx_base_url

        sample_response = [
            {
                "routeCode": "FBX01",
                "originPort": "CNSHA",
                "destinationPort": "USLAX",
                "containerType": "40GP",
                "rateUsd": 4200,
                "tradeLane": "Trans-Pacific Eastbound",
                "publishedDate": "2026-07-28",
            }
        ]

        responses.add(
            responses.GET,
            f"{base}/",
            json=sample_response,
            status=200,
        )

        result = source.fetch()
        assert result.success is True
        assert result.record_count > 0

        rate = result.records[0]
        assert rate.source == "freightos_fbx"
        assert rate.rate_usd == 4200

    @responses.activate
    def test_fetch_handles_404_gracefully(self, source: FreightosFBXSource) -> None:
        base = source.config.fbx_base_url
        responses.add(responses.GET, f"{base}/", status=404)

        result = source.fetch()
        assert result.records == []

    @responses.activate
    def test_fetch_retries_on_429(self, source: FreightosFBXSource) -> None:
        base = source.config.fbx_base_url

        responses.add(
            responses.GET, f"{base}/",
            status=429,
            body="Rate limit exceeded",
        )

        with pytest.raises(IOError, match="Rate limited"):
            source._fetch_route("CNSHA", "USLAX", "40GP")

    def test_validate(self, source: FreightosFBXSource) -> None:
        warnings = source.validate()
        assert isinstance(warnings, list)

    @responses.activate
    def test_all_routes_fail_raises(self, source: FreightosFBXSource) -> None:
        # C2: every route rejecting the API key used to produce a green run
        # with zero records -- now it must raise.
        base = source.config.fbx_base_url
        for _route in FBX_ROUTES:
            responses.add(
                responses.GET,
                re.compile(rf"{re.escape(base)}.*"),
                status=401,
            )

        with pytest.raises(RuntimeError, match="all routes"):
            source.fetch()

    @responses.activate
    def test_partial_route_failure_still_returns_other_routes(
        self, source: FreightosFBXSource
    ) -> None:
        base = source.config.fbx_base_url
        # One route rejects the key; every other route succeeds. The run should
        # still return data for the healthy routes (and not raise).
        first_route = FBX_ROUTES[0]

        def route_callback(request: responses.PreparedRequest) -> tuple[int, dict[str, str], str]:
            if first_route["origin"] in request.url:
                return 401, {}, '{"error": "unauthorized"}'
            return (
                200,
                {},
                json.dumps(
                    [
                        {
                            "routeCode": "FBX01",
                            "originPort": "CNSHA",
                            "destinationPort": "USLAX",
                            "containerType": "40GP",
                            "rateUsd": 4200,
                            "tradeLane": "Trans-Pacific Eastbound",
                            "publishedDate": "2026-07-28",
                        }
                    ]
                ),
            )

        responses.add_callback(
            responses.GET,
            re.compile(rf"{re.escape(base)}.*"),
            callback=route_callback,
        )

        result = source.fetch()
        assert result.success is True
        assert result.record_count > 0

    @responses.activate
    def test_validate_401_returns_warning(self, source: FreightosFBXSource) -> None:
        keyed_source = FreightosFBXSource(
            PipelineConfig(output_dir="tests/_test_output", fbx_api_key="test-key")
        )
        base = keyed_source.config.fbx_base_url
        responses.add(responses.GET, re.compile(rf"{re.escape(base)}.*"), status=401)
        warnings = keyed_source.validate()
        assert any("401" in w for w in warnings)

    @responses.activate
    def test_validate_200_returns_no_warning(self, source: FreightosFBXSource) -> None:
        keyed_source = FreightosFBXSource(
            PipelineConfig(output_dir="tests/_test_output", fbx_api_key="test-key")
        )
        base = keyed_source.config.fbx_base_url
        responses.add(responses.GET, re.compile(rf"{re.escape(base)}.*"), status=200, json=[])
        warnings = keyed_source.validate()
        assert warnings == []

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import responses

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.sources.bts_freight_indicators import BTSFreightIndicatorsSource
from freight_rail_pipeline.sources.fra_safety import FRASafetySource
from freight_rail_pipeline.sources.freightos_fbx import FreightosFBXSource
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

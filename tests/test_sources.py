from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import responses

from freight_rail_pipeline.config import PipelineConfig
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

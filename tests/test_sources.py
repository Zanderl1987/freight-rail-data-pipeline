from __future__ import annotations

from datetime import date
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
    def test_fetch_carloadings_returns_records(
        self, mock_socrata: MagicMock, source: USDAgTransportSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.side_effect = lambda resource_id, **kwargs: (
            [
                {"railroad": "BNSF", "commodity": "Grain", "carloads": "1500"},
                {"railroad": "UP", "commodity": "Coal", "carloads": "3200"},
            ]
            if resource_id == "tb7q-kn5i"
            else [
                {"railroad": "BNSF", "measure": "Cars On Line (Count)", "value": "30000"},
            ]
        )

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == 3
        assert result.source_name == "usda_agtransport"
        assert any(type(r).__name__ == "RailServiceMetric" for r in result.records)

    @patch("freight_rail_pipeline.sources.usda_agtransport.Socrata")
    def test_fetch_handles_empty_response(self, mock_socrata: MagicMock, source: USDAgTransportSource) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        mock_client.get.return_value = []

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 0

    def test_validate_connectivity(self, source: USDAgTransportSource) -> None:
        warnings = source.validate()
        assert isinstance(warnings, list)


class TestFreightosFBXSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> FreightosFBXSource:
        return FreightosFBXSource(config)

    @responses.activate
    def test_fetch_returns_normalized_records(
        self, source: FreightosFBXSource, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FREIGHTOS_API_KEY", "test-key")
        monkeypatch.setenv("FREIGHTOS_SECRET_KEY", "test-secret")
        base = source.config.fbx_base_url

        sample_response = {
            "license": "https://www.freightos.com/freightos-data-terms-conditions/",
            "metadata": {"units": {"currency": "USD"}},
            "data": [
                {
                    "date": "2026-07-28",
                    "route_name": "CNSHA||USLAX||FCL||40'",
                    "median_price": 4200,
                    "average_price": 4300,
                    "confidence_level": "High",
                }
            ],
        }

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
        assert rate.route_code == "FBX01"
        assert rate.snapshot_date == date(2026, 7, 28)

    def test_fetch_skips_without_credentials(self, source: FreightosFBXSource) -> None:
        result = source.fetch()
        assert result.records == []
        assert result.metadata["skipped"] == "missing_credentials"

    def test_validate_warns_without_credentials(self, source: FreightosFBXSource) -> None:
        warnings = source.validate()
        assert any("FREIGHTOS_API_KEY" in w for w in warnings)

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

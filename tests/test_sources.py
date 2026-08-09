from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import responses

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.sources.bts_freight_indicators import BTSFreightIndicatorsSource
from freight_rail_pipeline.sources.eurostat_rail import DATASET_ID, EurostatRailSource
from freight_rail_pipeline.sources.fmcsa_carrier_census import (
    SELECT_COLUMNS,
    FMCSACarrierCensusSource,
)
from freight_rail_pipeline.sources.fra_safety import FRASafetySource
from freight_rail_pipeline.sources.fred import FREDSource
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


class TestEurostatRailSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> EurostatRailSource:
        return EurostatRailSource(config)

    @staticmethod
    def _jsonstat_payload() -> dict[str, object]:
        # Shape mirrors the real rail_go_total response (size [1,2,37,22]),
        # trimmed to 1 freq x 2 units x 2 geos x 2 years for a compact fixture.
        return {
            "label": "Goods transported",
            "dimension": {
                "freq": {"category": {"index": {"A": 0}, "label": {"A": "Annual"}}},
                "unit": {
                    "category": {
                        "index": {"THS_T": 0, "MIO_TKM": 1},
                        "label": {"THS_T": "Thousand tonnes", "MIO_TKM": "Million tonne-km"},
                    }
                },
                "geo": {
                    "category": {
                        "index": {"DE": 0, "EU27_2020": 1},
                        "label": {"DE": "Germany", "EU27_2020": "European Union - 27 countries (from 2020)"},
                    }
                },
                "time": {
                    "category": {
                        "index": {"2004": 0, "2005": 1},
                        "label": {"2004": "2004", "2005": "2005"},
                    }
                },
            },
            "size": [1, 2, 2, 2],
            # flat row-major: A/THS_T/DE/2004, A/THS_T/DE/2005, A/THS_T/EU/2004, ...
            "value": {"0": 123.5, "1": 130.1, "2": 900.0, "3": 910.5, "4": 18757, "5": 19000, "6": 100000, "7": 101000},
        }

    @responses.activate
    def test_fetch_returns_normalized_records(self, source: EurostatRailSource) -> None:
        responses.add(
            responses.GET,
            f"{source.config.eurostat_base_url}/{DATASET_ID}",
            json=self._jsonstat_payload(),
            status=200,
        )

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 8
        assert result.source_name == "eurostat"
        assert result.metadata["dataset_id"] == "rail_go_total"

        de_tonnes = [r for r in result.records if r.country_code == "DE" and r.unit == "THS_T"]
        assert len(de_tonnes) == 2
        assert de_tonnes[0].period == "2004"
        assert de_tonnes[0].value == 123.5
        assert de_tonnes[0].snapshot_date == date(2004, 12, 31)
        assert de_tonnes[0].metric == "rail_goods_tonnes"
        assert de_tonnes[0].country_name == "Germany"

        eu_tkm = [r for r in result.records if r.country_code == "EU27_2020" and r.unit == "MIO_TKM"]
        assert eu_tkm[0].value == 100000.0
        assert eu_tkm[0].metric == "rail_goods_tonne_km"

    @responses.activate
    def test_fetch_skips_missing_string_values(self, source: EurostatRailSource) -> None:
        payload = self._jsonstat_payload()
        payload["value"] = {"0": 123.5, "1": ":", "2": 900.0, "4": 18757}  # type: ignore[assignment]

        responses.add(
            responses.GET,
            f"{source.config.eurostat_base_url}/{DATASET_ID}",
            json=payload,
            status=200,
        )

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 3
        assert all(r.value > 0 for r in result.records)

    @responses.activate
    def test_fetch_handles_malformed_dimensions(self, source: EurostatRailSource) -> None:
        responses.add(
            responses.GET,
            f"{source.config.eurostat_base_url}/{DATASET_ID}",
            json={"label": "unexpected", "value": {}},
            status=200,
        )

        result = source.fetch()
        assert result.success is True
        assert result.records == []

    @responses.activate
    def test_validate_reports_http_error(self, source: EurostatRailSource) -> None:
        responses.add(responses.GET, f"{source.config.eurostat_base_url}/{DATASET_ID}", status=503)

        warnings = source.validate()
        assert any("HTTP 503" in w for w in warnings)


class TestFREDSource:
    @pytest.fixture
    def config(self) -> PipelineConfig:
        return PipelineConfig(output_dir="tests/_test_output", log_dir="tests/_test_output/logs")

    @pytest.fixture
    def source(self, config: PipelineConfig) -> FREDSource:
        return FREDSource(config)

    def test_validate_warns_without_key(self, source: FREDSource) -> None:
        warnings = source.validate()
        assert any("FRED_API_KEY" in w for w in warnings)

    def test_fetch_skips_without_key(self, source: FREDSource) -> None:
        result = source.fetch()
        assert result.success is True
        assert result.records == []
        assert result.metadata.get("skipped") is not None

    @responses.activate
    def test_fetch_returns_normalized_records_with_key(self, source: FREDSource) -> None:
        config = PipelineConfig(
            output_dir="tests/_test_output",
            log_dir="tests/_test_output/logs",
            fred_api_key="test-key",
        )
        source = FREDSource(config)

        series_id = "FRGSHPUSM649NCIS"
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            "?series_id=FRGSHPUSM649NCIS&api_key=test-key&file_type=json"
        )
        responses.add(
            responses.GET,
            url,
            match_querystring=True,
            json={
                "realtime_start": "2026-06-29",
                "observations": [
                    {"date": "2026-01-01", "value": "1.009"},
                    {"date": "2026-02-01", "value": "."},
                    {"date": "2026-03-01", "value": "1.054"},
                ],
            },
            status=200,
        )

        result = source.fetch()
        assert result.success is True
        assert result.record_count == 2

        rec = result.records[0]
        assert rec.external_id == "FRGSHPUSM649NCIS_2026-01-01"
        assert rec.indicator == "Cass Freight Index: Shipments"
        assert rec.value == 1.009
        assert rec.snapshot_date == date(2026, 1, 1)
        assert rec.underlying_source == "Cass Information Systems"

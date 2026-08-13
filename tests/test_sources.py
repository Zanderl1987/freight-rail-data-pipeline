from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses

from freight_rail_pipeline.config import PipelineConfig
from freight_rail_pipeline.sources.aar_weekly import (
    AARWeeklyTrafficSource,
    parse_aar_page,
)
from freight_rail_pipeline.sources.bts_freight_indicators import BTSFreightIndicatorsSource
from freight_rail_pipeline.sources.bts_transborder import BTSTransBorderSource
from freight_rail_pipeline.sources.eurostat_rail import DATASET_ID, EurostatRailSource
from freight_rail_pipeline.sources.fmcsa_carrier_census import (
    SELECT_COLUMNS,
    FMCSACarrierCensusSource,
)
from freight_rail_pipeline.sources.fra_safety import FRASafetySource
from freight_rail_pipeline.sources.fred import FREDSource
from freight_rail_pipeline.sources.freightos_fbx import FBX_ROUTES, FreightosFBXSource
from freight_rail_pipeline.sources.stb_waybill import (
    _FIELD_SLICES,
    STBWaybillSource,
)
from freight_rail_pipeline.sources.usda_agtransport import USDAgTransportSource

FIXTURES = Path(__file__).parent / "fixtures"


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
    def test_fetch_service_metrics(
        self, mock_socrata: MagicMock, source: USDAgTransportSource
    ) -> None:
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
    def test_fetch_handles_empty_response(
        self, mock_socrata: MagicMock, source: USDAgTransportSource
    ) -> None:
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
    def test_validate_connectivity(
        self, mock_socrata: MagicMock, source: USDAgTransportSource
    ) -> None:
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

    @patch("freight_rail_pipeline.sources.fmcsa_carrier_census.Socrata")
    def test_fetch_paginates_through_full_census(
        self, mock_socrata: MagicMock, source: FMCSACarrierCensusSource
    ) -> None:
        mock_client = MagicMock()
        mock_socrata.return_value = mock_client
        # The real dataset is 2M+ rows; the loop walks pages of `limit` until a
        # short final page. Full first page (exactly `limit`) forces another
        # call, then a 1-row page terminates the loop.
        limit = 5000
        full_page = [
            {"dot_number": str(i), "phy_state": "AL", "mcs150_date": "21-APR-26"}
            for i in range(limit)
        ]
        last_page = [{"dot_number": "5000", "phy_state": "AL", "mcs150_date": "21-APR-26"}]
        mock_client.get.side_effect = [full_page, last_page]

        result = source.fetch(snapshot_date=None)
        assert result.success is True
        assert result.record_count == limit + 1

        offsets = [call.kwargs["offset"] for call in mock_client.get.call_args_list]
        assert offsets == [0, limit]


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
                        "label": {
                            "DE": "Germany",
                            "EU27_2020": "European Union - 27 countries (from 2020)",
                        },
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
            "value": {
                "0": 123.5,
                "1": 130.1,
                "2": 900.0,
                "3": 910.5,
                "4": 18757,
                "5": 19000,
                "6": 100000,
                "7": 101000,
            },
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

        eu_tkm = [
            r
            for r in result.records
            if r.country_code == "EU27_2020" and r.unit == "MIO_TKM"
        ]
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


def _build_waybill_line(**fields: str) -> bytes:
    buf = bytearray(b" " * 247)
    for name, value in fields.items():
        start, end = _FIELD_SLICES[name]
        encoded = value.encode("ascii")
        width = end - start
        if len(encoded) > width:
            raise ValueError(f"value for {name} longer than field width {width}")
        buf[start:end] = encoded + b" " * (width - len(encoded))
    return bytes(buf)


class TestSTBWaybillSource:
    @pytest.fixture
    def config(self, tmp_path: Path) -> PipelineConfig:
        return PipelineConfig(output_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))

    @pytest.fixture
    def source(self, config: PipelineConfig) -> STBWaybillSource:
        return STBWaybillSource(config)

    def test_parse_record_full_width(self, source: STBWaybillSource) -> None:
        line = _build_waybill_line(
            waybill_date="041118",
            accounting_period="0324",
            carloads="0001",
            car_ownership="P",
            aar_equipment_type="T106",
            stb_car_type="51",
            stcc="48110",
            billed_tons="00100",
            actual_tons="00100",
            freight_revenue="000023475",
            expanded_carloads="000005",
            expanded_freight_revenue="00000117375",
            interchange_state_1="ND",
        )
        assert len(line) == 247
        rec = source._parse_record(line, reference_year=2024)
        assert rec is not None
        assert rec.snapshot_date == date(2018, 4, 11)
        assert rec.stcc == "48110"
        assert rec.freight_revenue == 23475.0
        assert rec.expanded_carloads == 5
        assert rec.interchange_states == "ND"

    def test_parse_record_too_short_returns_none(self, source: STBWaybillSource) -> None:
        assert source._parse_record(b"short", reference_year=2024) is None

    def test_waybill_year_written(self, config: PipelineConfig) -> None:
        source = STBWaybillSource(config)
        assert source._waybill_year_written(2024) is False
        (config.output_dir / "freight" / "waybill_shipments" / "year=2024").mkdir(parents=True)
        assert source._waybill_year_written(2024) is True

    @responses.activate
    def test_resolve_latest_year_backs_off(self, source: STBWaybillSource) -> None:
        responses.add(
            responses.GET,
            "https://www.stb.gov/wp-content/uploads/PublicUseWaybillSample2026.zip",
            status=404,
            body="not found",
        )
        responses.add(
            responses.GET,
            "https://www.stb.gov/wp-content/uploads/PublicUseWaybillSample2025.zip",
            status=200,
            body=b"PK",
        )
        assert source._resolve_latest_year(2026) == 2025

    @responses.activate
    def test_fetch_skips_when_year_already_written(self, config: PipelineConfig) -> None:
        source = STBWaybillSource(config)
        (config.output_dir / "freight" / "waybill_shipments" / "year=2025").mkdir(parents=True)
        responses.add(
            responses.GET,
            "https://www.stb.gov/wp-content/uploads/PublicUseWaybillSample2025.zip",
            status=200,
            body=b"PK",
        )
        result = source.fetch(snapshot_date=date(2025, 6, 1))
        assert result.success is True
        assert result.records == []
        assert result.metadata.get("skipped") is True

    @responses.activate
    def test_fetch_parses_zip(self, config: PipelineConfig) -> None:
        source = STBWaybillSource(config)
        line = _build_waybill_line(
            waybill_date="071524",
            accounting_period="0724",
            carloads="0002",
            car_ownership="R",
            stcc="01122",
            freight_revenue="000050000",
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("PublicUseWaybillSample2025.txt", b"firstbadline\n" + line + b"\n")
        zip_bytes = buf.getvalue()

        responses.add(
            responses.GET,
            "https://www.stb.gov/wp-content/uploads/PublicUseWaybillSample2025.zip",
            status=200,
            body=zip_bytes,
        )
        responses.add(
            responses.GET,
            "https://www.stb.gov/wp-content/uploads/PublicUseWaybillSample2025.zip",
            status=200,
            body=zip_bytes,
        )
        result = source.fetch(snapshot_date=date(2025, 6, 1))
        assert result.success is True
        assert result.record_count == 1
        rec = result.records[0]
        assert rec.snapshot_date == date(2024, 7, 15)
        assert rec.carloads == 2
        assert rec.freight_revenue == 50000.0


class TestBTSTransBorderSource:
    @pytest.fixture
    def config(self, tmp_path: Path) -> PipelineConfig:
        return PipelineConfig(output_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))

    @pytest.fixture
    def source(self, config: PipelineConfig) -> BTSTransBorderSource:
        return BTSTransBorderSource(config)

    def test_parse_month_year(self, source: BTSTransBorderSource) -> None:
        raw = "/sites/bts.dot.gov/files/transborder-raw/{}/{}.zip"
        assert source._parse_month_year(raw.format(2026, "January2026")) == (2026, 1)
        assert source._parse_month_year(raw.format(2024, "Jan2024")) == (2024, 1)
        assert source._parse_month_year(raw.format(2025, "December2025")) == (2025, 12)
        assert source._parse_month_year("/sites/bts.dot.gov/files/other/file.zip") is None

    def test_select_zip_newest_without_date(self, source: BTSTransBorderSource) -> None:
        links = [(2024, 12, "dec"), (2025, 5, "may"), (2026, 1, "jan")]
        assert source._select_zip(links, None) == (2026, 1, "jan")

    def test_select_zip_respects_snapshot_date(self, source: BTSTransBorderSource) -> None:
        links = [(2025, 12, "dec"), (2026, 1, "jan"), (2026, 2, "feb")]
        assert source._select_zip(links, date(2026, 2, 10)) == (2026, 2, "feb")
        assert source._select_zip(links, date(2026, 1, 20)) == (2026, 1, "jan")
        # No published zip predates the snapshot: fetching newer data would
        # violate snapshot semantics.
        assert source._select_zip(links, date(2025, 10, 1)) is None

    @responses.activate
    def test_fetch_parses_three_files(self, source: BTSTransBorderSource) -> None:
        page_html = (
            '<a href="/sites/bts.dot.gov/files/transborder-raw/2026/January2026.zip">Jan 2026</a>'
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "dot1_0126.csv",
                "TRDTYPE,USASTATE,DEPE,DISAGMOT,MEXSTATE,CANPROV,COUNTRY,VALUE,SHIPWT,"
                "FREIGHT_CHARGES,DF,CONTCODE,MONTH,YEAR\n"
                "1,AK,0901,5,,XY,1220,42199,0,62,1,1,01,2026\n",
            )
            zf.writestr(
                "dot2_0126.csv",
                "TRDTYPE,USASTATE,COMMODITY2,DISAGMOT,MEXSTATE,CANPROV,COUNTRY,VALUE,SHIPWT,"
                "FREIGHT_CHARGES,DF,CONTCODE,MONTH,YEAR\n"
                "1,WA,10,6,,,1220,50000,12000,800,,X,01,2026\n",
            )
            zf.writestr(
                "dot3_0126.csv",
                "TRDTYPE,DEPE,COMMODITY2,DISAGMOT,COUNTRY,VALUE,SHIPWT,"
                "FREIGHT_CHARGES,DF,CONTCODE,MONTH,YEAR\n"
                "2,0910,28,1,2010,22052,0,10,1,1,01,2026\n",
            )
        zip_bytes = buf.getvalue()

        responses.add(
            responses.GET,
            "https://www.bts.gov/topics/transborder-raw-data",
            status=200,
            body=page_html,
        )
        responses.add(
            responses.GET,
            "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2026/January2026.zip",
            status=200,
            body=zip_bytes,
        )
        result = source.fetch()
        assert result.success is True
        assert result.record_count == 3
        by_file = {r.source_file: r for r in result.records}
        assert by_file["dot1"].mode == "truck"
        assert by_file["dot2"].commodity_2digit == "10"
        assert by_file["dot3"].trade_type == "export"
        assert by_file["dot1"].country == "CA"
        assert all(r.snapshot_date == date(2026, 1, 31) for r in result.records)

    @responses.activate
    def test_fetch_fails_cleanly_without_links(self, source: BTSTransBorderSource) -> None:
        responses.add(
            responses.GET,
            "https://www.bts.gov/topics/transborder-raw-data",
            status=200,
            body="<html>no zips here</html>",
        )
        result = source.fetch()
        assert result.success is False
        assert result.error is not None


class TestAARWeeklyTrafficSource:
    @pytest.fixture
    def config(self, tmp_path: Path) -> PipelineConfig:
        return PipelineConfig(output_dir=str(tmp_path), log_dir=str(tmp_path / "logs"))

    @pytest.fixture
    def source(self, config: PipelineConfig) -> AARWeeklyTrafficSource:
        return AARWeeklyTrafficSource(config)

    def test_parse_aar_page_text(self) -> None:
        text = (
            "U.S. Rail Traffic1\n"
            "Week 31, 2026 \u2013 Ended August 8, 2026\n"
            "This Week\nYear-To-Date\nCars\nvs 2025\nCumulative\nAvg/wk2\nvs 2025\n"
            "Total Carloads\n231,268\n1.8%\n7,042,764\n227,186\n2.7%\n"
            "Coal\n57,976\n-6.1%\n1,761,694\n56,829\n-1.8%\n"
            "Total Traffic\n526,624\n3.0%\n15,756,335\n508,269\n3.3%\n"
            "1 Excludes U.S. operations of CPKC, CN and GMXT.\n"
            "2 Average per week figures may not sum to totals "
            "as a result of independent rounding.\n"
            "Trends, 2026 vs 2025\n"
        )
        rows = parse_aar_page(text)
        assert len(rows) == 3
        assert rows[0]["region"] == "US"
        assert rows[0]["category"] == "Total Carloads"
        assert rows[0]["this_week_cars"] == "231268"
        assert rows[0]["this_week_yoy_pct"] == "1.8%"
        assert rows[1]["category"] == "Coal"
        assert rows[1]["this_week_cars"] == "57976"
        assert rows[1]["ytd_yoy_pct"] == "-1.8%"

    def test_parse_aar_page_rejects_garbage(self) -> None:
        assert parse_aar_page("no title or rows here") == []

    def test_fixture_pdf_parses_all_four_regions(self) -> None:
        import fitz

        with fitz.open(FIXTURES / "aar_weekly_2026_08_12.pdf") as doc:
            rows: list[dict] = []
            for page in doc:
                if page.number >= 4:
                    break
                rows += parse_aar_page(page.get_text())
        assert len(rows) == 52
        regions = {r["region"] for r in rows}
        assert regions == {"US", "Canada", "Mexico", "North America"}

    @responses.activate
    def test_fetch_parses_live_shape(self, source: AARWeeklyTrafficSource) -> None:
        feed = (
            "<rss><channel>"
            "<item><title>Weekly Rail Traffic for the Week Ending August 8, 2026</title>"
            "<link>https://www.aar.org/news/aar-reports-weekly-rail-traffic-for-the-week-ending-august-8-2026/</link>"
            "</item>"
            "</channel></rss>"
        )
        release_html = (
            '<html><a href="https://www.aar.org/wp-content/uploads/2026/08/2026-08-12-railtraffic.pdf">'
            "download</a></html>"
        )
        pdf_bytes = (FIXTURES / "aar_weekly_2026_08_12.pdf").read_bytes()

        responses.add(
            responses.GET,
            "https://www.aar.org/aar_news/weekly-rail-traffic-data/feed/",
            status=200,
            body=feed,
        )
        responses.add(
            responses.GET,
            "https://www.aar.org/news/aar-reports-weekly-rail-traffic-for-the-week-ending-august-8-2026/",
            status=200,
            body=release_html,
        )
        responses.add(
            responses.GET,
            "https://www.aar.org/wp-content/uploads/2026/08/2026-08-12-railtraffic.pdf",
            status=200,
            body=pdf_bytes,
        )
        result = source.fetch()
        assert result.success is True
        assert result.record_count == 52
        assert result.metadata["pdf_url"].endswith("railtraffic.pdf")
        assert all(r.snapshot_date == date(2026, 8, 8) for r in result.records)

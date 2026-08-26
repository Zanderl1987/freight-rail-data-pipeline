from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from freight_rail_pipeline.models.schemas import (
    FMCContainerStats,
    FMCContainerStatsBatch,
    GrainTransportObservation,
    GrainTransportObservationBatch,
    OceanFreightRate,
    OceanFreightRateBatch,
    RailCarloading,
    RailCarloadingBatch,
    RailServiceMetric,
    RailTariffRate,
)


class TestRailCarloading:
    def test_minimal_valid(self) -> None:
        r = RailCarloading(
            snapshot_date=date(2026, 7, 15), railroad="BNSF", commodity="Grain", carloads=100
        )
        assert r.railroad == "BNSF"
        assert r.carloads == 100
        assert r.source == "usda_agtransport"
        assert isinstance(r.ingested_at, datetime)

    def test_negative_carloads_raises(self) -> None:
        with pytest.raises(ValidationError):
            RailCarloading(
                snapshot_date=date(2026, 7, 15), railroad="BNSF", commodity="Grain", carloads=-1
            )

    def test_batch(self) -> None:
        batch = RailCarloadingBatch(records=[
            RailCarloading(
                snapshot_date=date(2026, 7, 15), railroad="BNSF", commodity="Grain", carloads=100
            ),
        ])
        assert batch.count == 1
        assert batch.source == "usda_agtransport"


class TestRailServiceMetric:
    def test_valid(self) -> None:
        m = RailServiceMetric(
            snapshot_date=date(2026, 7, 15),
            railroad="NS",
            metric_name="train_speed",
            metric_value=22.5,
            unit="mph",
        )
        assert m.metric_value == 22.5
        assert m.metric_name == "train_speed"


class TestOceanFreightRate:
    def test_valid(self) -> None:
        r = OceanFreightRate(
            snapshot_date=date(2026, 7, 28),
            route_code="FBX01",
            route_description="China → USWC",
            origin_port="CNSHA",
            destination_port="USLAX",
            trade_lane="Trans-Pacific",
            container_type="40GP",
            rate_usd=4500,
        )
        assert r.rate_usd == 4500
        assert r.source == "freightos_fbx"
        assert r.currency == "USD"

    def test_negative_rate_raises(self) -> None:
        with pytest.raises(ValidationError):
            OceanFreightRate(
                snapshot_date=date(2026, 7, 28),
                route_code="FBX01",
                route_description="China → USWC",
                origin_port="CNSHA",
                destination_port="USLAX",
                trade_lane="Trans-Pacific",
                container_type="40GP",
                rate_usd=-100,
            )

    def test_batch(self) -> None:
        batch = OceanFreightRateBatch(records=[
            OceanFreightRate(
                snapshot_date=date(2026, 7, 28),
                route_code="FBX01",
                route_description="Test",
                origin_port="A",
                destination_port="B",
                trade_lane="Lane",
                container_type="40GP",
                rate_usd=1000,
            ),
        ])
        assert batch.count == 1
        assert batch.source == "freightos_fbx"


class TestRailTariffRate:
    def test_valid(self) -> None:
        t = RailTariffRate(
            snapshot_date=date(2026, 7, 15),
            railroad="BNSF",
            commodity="Corn",
            origin="ND",
            destination="TX",
            rate_per_car=2500.00,
            fuel_surcharge=350.00,
        )
        assert t.rate_per_car == 2500.00
        assert t.fuel_surcharge == 350.00
        assert t.currency == "USD"
        assert t.source == "usda_agtransport"


class TestGrainTransportObservation:
    def test_minimal_valid(self) -> None:
        g = GrainTransportObservation(
            snapshot_date=date(2026, 8, 18),
            series="downbound_grain_barge_rates",
            resource_id="deqi-uken",
            metric="barge_rate_pct_of_benchmark",
            value=765.0,
        )
        assert g.source == "usda_gtr"
        assert isinstance(g.ingested_at, datetime)

    def test_negative_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            GrainTransportObservation(
                snapshot_date=date(2026, 8, 18),
                series="mississippi_barge_rates",
                resource_id="7spn-fbua",
                metric="barge_rate_per_ton",
                value=-1.0,
            )

    def test_batch(self) -> None:
        batch = GrainTransportObservationBatch(
            records=[
                GrainTransportObservation(
                    snapshot_date=date(2026, 8, 18),
                    series="grain_inspections",
                    resource_id="sruw-w49i",
                    metric="grain_inspected",
                    value=1.0,
                )
            ]
        )
        assert batch.count == 1
        assert batch.source == "usda_gtr"


class TestFMCContainerStats:
    def test_minimal_valid(self) -> None:
        f = FMCContainerStats(
            snapshot_date=date(2024, 3, 31),
            quarter_label="Q1 2024",
            year=2024,
            quarter=1,
            entity_type="port",
            entity_name="Anchorage, Alaska",
        )
        assert f.source == "fmc"
        assert isinstance(f.ingested_at, datetime)

    def test_quarter_bounds_enforced(self) -> None:
        with pytest.raises(ValidationError):
            FMCContainerStats(
                snapshot_date=date(2024, 3, 31),
                quarter_label="Q5 2024",
                year=2024,
                quarter=5,
                entity_type="port",
                entity_name="Nowhere",
            )

    def test_negative_teu_raises(self) -> None:
        with pytest.raises(ValidationError):
            FMCContainerStats(
                snapshot_date=date(2024, 3, 31),
                quarter_label="Q1 2024",
                year=2024,
                quarter=1,
                entity_type="carrier",
                entity_name="CMACGM",
                laden_export_teu=-5,
            )

    def test_batch(self) -> None:
        batch = FMCContainerStatsBatch(
            records=[
                FMCContainerStats(
                    snapshot_date=date(2024, 3, 31),
                    quarter_label="Q1 2024",
                    year=2024,
                    quarter=1,
                    entity_type="carrier",
                    entity_name="CMACGM",
                )
            ]
        )
        assert batch.count == 1
        assert batch.source == "fmc"

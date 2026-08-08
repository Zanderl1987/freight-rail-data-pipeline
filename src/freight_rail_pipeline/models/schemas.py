from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RailCarloading(BaseModel):
    source: str = Field(default="usda_agtransport", description="Source system identifier")
    snapshot_date: date = Field(..., description="Date of the reported data")
    railroad: str = Field(..., description="Railroad or carrier name")
    commodity: str = Field(..., description="Commodity group / STCC description")
    carloads: int = Field(..., ge=0, description="Number of carloads")
    carload_type: str | None = Field(
        default=None, description="Direction of traffic: Originated or Received"
    )
    units: str | None = Field(default="carloads", description="Unit of measurement")
    origin_region: str | None = Field(default=None, description="Origin region / BEA")
    destination_region: str | None = Field(default=None, description="Destination region / BEA")
    raw_record: dict[str, Any] | None = Field(default=None, description="Original source record")
    ingested_at: datetime = Field(
        default_factory=_utcnow, description="Pipeline ingestion timestamp"
    )


class RailCarloadingBatch(BaseModel):
    records: list[RailCarloading]
    source: str = "usda_agtransport"

    @property
    def count(self) -> int:
        return len(self.records)


class RailServiceMetric(BaseModel):
    source: str = Field(default="usda_agtransport")
    snapshot_date: date = Field(..., description="Date of the reported data")
    railroad: str = Field(..., description="Class I railroad name")
    metric_name: str = Field(..., description="Metric: train_speed, terminal_dwell, cars_on_line")
    metric_value: float = Field(..., description="Numeric value of the metric")
    unit: str = Field(..., description="Unit: mph, hours, cars")
    region: str | None = Field(default=None, description="Geographic region if applicable")
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class RailServiceMetricBatch(BaseModel):
    records: list[RailServiceMetric]
    source: str = "usda_agtransport"

    @property
    def count(self) -> int:
        return len(self.records)


class RailTariffRate(BaseModel):
    source: str = Field(default="usda_agtransport")
    snapshot_date: date = Field(..., description="Rate effective date")
    railroad: str = Field(..., description="Railroad publishing the tariff")
    commodity: str = Field(..., description="Commodity (grain, corn, wheat, etc.)")
    origin: str = Field(..., description="Origin location (state/region)")
    destination: str = Field(..., description="Destination location (state/region)")
    rate_per_car: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    fuel_surcharge: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    currency: str = Field(default="USD")
    movement_type: str | None = Field(default=None, description="Shuttle, unit-train, single-car")
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class RailTariffRateBatch(BaseModel):
    records: list[RailTariffRate]
    source: str = "usda_agtransport"

    @property
    def count(self) -> int:
        return len(self.records)


class OceanFreightRate(BaseModel):
    source: str = Field(default="freightos_fbx")
    snapshot_date: date = Field(..., description="Date the rate was published")
    route_code: str = Field(..., description="FBX route code (e.g. FBX01)")
    route_description: str = Field(..., description="Human-readable route name")
    origin_port: str = Field(..., description="Origin port code or name")
    destination_port: str = Field(..., description="Destination port code or name")
    trade_lane: str = Field(..., description="Trade corridor name")
    container_type: str = Field(..., description="20GP, 40GP, 40HC")
    rate_usd: int | None = Field(default=None, ge=0, description="Spot rate in USD per container")
    currency: str = Field(default="USD")
    rate_unit: str = Field(default="per_container")
    region: str | None = Field(default=None, description="Geographic corridor")
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class OceanFreightRateBatch(BaseModel):
    records: list[OceanFreightRate]
    source: str = "freightos_fbx"

    @property
    def count(self) -> int:
        return len(self.records)


class PipelineRunSummary(BaseModel):
    run_id: str = Field(..., description="Unique run identifier (timestamp-based)")
    started_at: datetime = Field(...)
    finished_at: datetime | None = Field(default=None)
    success: bool = Field(default=False)
    sources_attempted: list[str] = Field(default_factory=list)
    sources_succeeded: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
    total_records_written: int = Field(default=0)
    errors: list[str] = Field(default_factory=list)
    output_paths: list[str] = Field(default_factory=list)

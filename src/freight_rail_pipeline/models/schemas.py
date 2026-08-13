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
    traffic_type: str | None = Field(default=None, description="Originated or Received")
    carloads: float = Field(..., ge=0, description="Number of carloads")
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
    segment: str | None = Field(
        default=None, description="Commodity/segment (e.g. Automotive, Coal)"
    )
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
    rate_usd: float | None = Field(default=None, ge=0, description="Spot rate in USD per container")
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


class FreightIndicator(BaseModel):
    """A single dated observation from BTS's Supply Chain and Freight Indicators
    dataset -- a multimodal series (truck spot rates, rail dwell/speed, port
    container throughput, diesel prices, PPI trucking, etc.), one row per
    indicator/date/breakdown combination rather than a fixed rail-only shape."""

    source: str = Field(default="bts_freight_indicators")
    external_id: str = Field(
        ..., description="BTS's own row id, e.g. '59_2026_07_18_Memphis, TN_BNSF'"
    )
    snapshot_date: date = Field(..., description="Date of the reported observation")
    indicator: str = Field(
        ..., description="Indicator name, e.g. 'Truck Spot Rates in $ per Mile by Truck Type'"
    )
    measure1: str | None = Field(
        default=None, description="Primary breakdown dimension, e.g. terminal or truck type"
    )
    measure2: str | None = Field(
        default=None, description="Secondary breakdown dimension, e.g. railroad name"
    )
    value: float = Field(..., description="Observed value")
    units: str | None = Field(
        default=None, description="Unit of the value, e.g. 'Hours', 'Dollars per mile'"
    )
    underlying_source: str | None = Field(
        default=None, description="BTS's cited data provider, e.g. 'DAT Freight and Analytics'"
    )
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class FreightIndicatorBatch(BaseModel):
    records: list[FreightIndicator]
    source: str = "bts_freight_indicators"

    @property
    def count(self) -> int:
        return len(self.records)


class RailSafetyIncident(BaseModel):
    """A single FRA safety event -- either a Form 54 train accident/incident
    or a Form 57 highway-rail grade crossing incident. The two forms share a
    common shape (railroad, date, location, casualties, damage cost) but have
    different field names for casualty/cost totals, so `incident_type`
    disambiguates which form this record came from."""

    source: str = Field(default="fra_safety")
    external_id: str = Field(..., description="FRA's reportkey/incidentkey, unique per event")
    incident_type: str = Field(
        ..., description="'train_accident' (Form 54) or 'highway_rail_crossing' (Form 57)"
    )
    incident_date: date = Field(..., description="Date the incident occurred")
    railroad_code: str | None = Field(default=None, description="Reporting railroad's FRA code")
    railroad_name: str | None = Field(default=None, description="Reporting railroad name")
    state: str | None = Field(default=None, description="State name")
    county: str | None = Field(default=None, description="County name")
    category: str | None = Field(
        default=None, description="Accident type (e.g. Derailment) or equipment involved"
    )
    total_killed: int | None = Field(default=None, ge=0)
    total_injured: int | None = Field(default=None, ge=0)
    damage_cost_usd: float | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    narrative: str | None = Field(default=None)
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class RailSafetyIncidentBatch(BaseModel):
    records: list[RailSafetyIncident]
    source: str = "fra_safety"

    @property
    def count(self) -> int:
        return len(self.records)


class MotorCarrierCensus(BaseModel):
    """A snapshot of one FMCSA-registered motor carrier's fleet-size profile.

    Deliberately excludes `raw_record` (unlike every other model here) and the
    source query never selects name/address/email/phone columns in the first
    place -- FMCSA's carrier census is per-individual PII (2M+ carriers, many
    sole proprietors), not aggregate freight data. User decision 2026-08-03:
    keep only fleet-size/operational fields, strip identity fields entirely,
    server-side, before any data is fetched. Do not add raw_record back."""

    source: str = Field(default="fmcsa_carrier_census")
    snapshot_date: date = Field(..., description="MCS-150 census filing date")
    dot_number: str = Field(..., description="FMCSA DOT number (carrier's public registration ID)")
    carrier_operation: str | None = Field(
        default=None, description="Interstate/intrastate operation code"
    )
    state: str | None = Field(default=None, description="Physical location state")
    power_units: int | None = Field(
        default=None, ge=0, description="Number of power units (trucks/tractors)"
    )
    driver_count: int | None = Field(default=None, ge=0, description="Total drivers")
    mileage: int | None = Field(default=None, ge=0, description="Most recent annual mileage")
    mileage_year: int | None = Field(default=None, description="Year the mileage figure applies to")
    ingested_at: datetime = Field(default_factory=_utcnow)


class MotorCarrierCensusBatch(BaseModel):
    records: list[MotorCarrierCensus]
    source: str = "fmcsa_carrier_census"

    @property
    def count(self) -> int:
        return len(self.records)


class EurostatRailFreight(BaseModel):
    """A single annual rail-freight observation for one country/aggregate from
    Eurostat's `rail_go_total` dataset ("Goods transported" by rail).

    The dataset reports two complementary units per country/year -- thousand
    tonnes of goods carried (THS_T) and million tonne-kilometres of freight
    traffic (MIO_TKM) -- which land as separate rows so each observation has a
    single unit/value. `metric` gives the friendly label for the unit."""

    source: str = Field(default="eurostat")
    snapshot_date: date = Field(..., description="Period-end date of the annual observation")
    period: str = Field(..., description="Annual period, e.g. '2024'")
    country_code: str = Field(..., description="Eurostat geo code, e.g. 'DE', 'EU27_2020'")
    country_name: str | None = Field(default=None, description="Eurostat geo label, e.g. 'Germany'")
    unit: str = Field(..., description="Eurostat unit code: THS_T or MIO_TKM")
    metric: str = Field(
        ..., description="rail_goods_tonnes (THS_T) or rail_goods_tonne_km (MIO_TKM)"
    )
    value: float = Field(..., description="Observed value")
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class EurostatRailFreightBatch(BaseModel):
    records: list[EurostatRailFreight]
    source: str = "eurostat"

    @property
    def count(self) -> int:
        return len(self.records)


class WaybillShipment(BaseModel):
    """One waybill from the STB Carload Waybill Sample Public Use File.

    The PUF is a confidentiality-scrubbed 247-byte fixed-width record per
    waybill (see the STB reference guide, "247-Byte Public Use Waybill Record
    Layout"). Weights are short tons, revenue/charges are dollars, expansion
    factors scale a sampled waybill up to the population. `raw_record` is
    deliberately omitted -- retaining 247 chars of raw text for ~2M rows would
    roughly double the store's footprint without adding analytic value."""

    source: str = Field(default="stb_waybill")
    snapshot_date: date = Field(..., description="Waybill date")
    accounting_period: str = Field(..., description="Accounting period MM/YY")
    carloads: int = Field(..., ge=0, description="Number of carloads on the waybill")
    car_ownership: str | None = Field(
        default=None, description="Car ownership code: P=private, R=railroad, T=TTX"
    )
    aar_equipment_type: str | None = Field(default=None, description="AAR equipment type code")
    aar_mechanical_designation: str | None = Field(default=None)
    stb_car_type: str | None = Field(default=None, description="STB Form 710 car type line")
    tofc_cofc_service_code: str | None = Field(default=None)
    tofc_cofc_units: int | None = Field(default=None, description="Number of TOFC/COFC units")
    tcu_ownership: str | None = Field(default=None)
    tcu_type: str | None = Field(default=None)
    hazardous_boxcar_flag: str | None = Field(default=None)
    stcc: str = Field(..., description="5-digit STCC commodity code")
    billed_tons: float | None = Field(default=None)
    actual_tons: float | None = Field(default=None)
    freight_revenue: float | None = Field(default=None, ge=0)
    transit_charges: float | None = Field(default=None, ge=0)
    miscellaneous_charges: float | None = Field(default=None, ge=0)
    inter_intra_state_code: str | None = Field(default=None)
    type_of_move: str | None = Field(default=None)
    all_rail_intermodal_code: str | None = Field(default=None)
    type_of_move_via_water: str | None = Field(default=None)
    transit_code: str | None = Field(default=None)
    substituted_truck_for_rail: str | None = Field(default=None)
    rebill_code: str | None = Field(default=None)
    estimated_shortline_miles: int | None = Field(default=None, ge=0)
    stratum_id: int | None = Field(default=None)
    subsample_id: int | None = Field(default=None)
    exact_expansion_factor: float | None = Field(default=None, ge=0)
    theoretical_expansion_factor: int | None = Field(default=None, ge=0)
    num_interchanges: int | None = Field(default=None, ge=0)
    origin_bea_area: int | None = Field(default=None, description="Origin Business Economic Area")
    origin_freight_territory: str | None = Field(default=None)
    interchange_states: str | None = Field(
        default=None, description="Comma-joined state codes at each interchange (1-9)"
    )
    termination_bea_area: int | None = Field(default=None)
    termination_freight_territory: str | None = Field(default=None)
    reporting_period_length: str | None = Field(default=None)
    car_capacity: int | None = Field(default=None, ge=0)
    nominal_car_capacity: int | None = Field(default=None, ge=0)
    tare_weight: int | None = Field(default=None, ge=0)
    outside_length: int | None = Field(default=None, ge=0)
    outside_width: int | None = Field(default=None, ge=0)
    outside_height: int | None = Field(default=None, ge=0)
    extreme_outside_height: int | None = Field(default=None, ge=0)
    wheel_bearings_type: str | None = Field(default=None)
    num_axles: int | None = Field(default=None, ge=0)
    draft_gear: str | None = Field(default=None)
    num_articulated_units: int | None = Field(default=None, ge=0)
    aar_error_codes: str | None = Field(default=None)
    routing_error_flag: str | None = Field(default=None)
    expanded_carloads: int | None = Field(default=None, ge=0)
    expanded_tons: int | None = Field(default=None, ge=0)
    expanded_freight_revenue: float | None = Field(default=None, ge=0)
    expanded_trailer_container_count: int | None = Field(default=None, ge=0)
    ingested_at: datetime = Field(default_factory=_utcnow)


class WaybillShipmentBatch(BaseModel):
    records: list[WaybillShipment]
    source: str = "stb_waybill"

    @property
    def count(self) -> int:
        return len(self.records)


class TransBorderFreight(BaseModel):
    """One monthly TransBorder raw-data line: U.S. trade with Canada/Mexico by
    mode, port, and (for rail/other modes) 2-digit commodity. BTS publishes
    three CSV files per month -- dot1 (state+port detail), dot2 (state+
    commodity detail), dot3 (port+commodity detail) -- whose column sets
    differ, so the mode-specific geography/commodity fields are nullable and
    each row is tagged with the file it came from. The three views overlap
    (a shipment can appear in more than one), so rows must not be summed
    across `source_file` blindly. Value/freight are USD; SHIPWT is kilograms;
    COUNTRY is mapped from Census numeric codes (1220=CA, 2010=MX)."""

    source: str = Field(default="bts_transborder")
    snapshot_date: date = Field(..., description="Month-end date of the statistical period")
    trade_type: str = Field(..., description="'import' or 'export' (TRDTYPE)")
    country: str = Field(..., description="Trading partner: CA or MX")
    year: int = Field(...)
    month: int = Field(...)
    mode: str = Field(..., description="Mode label, e.g. 'rail'")
    disagg_mode: int | None = Field(default=None, description="Raw DISAGMOT code")
    source_file: str | None = Field(
        default=None, description="Source CSV in the monthly zip: dot1/dot2/dot3"
    )
    us_state: str | None = Field(default=None, description="USASTATE (origin for exports)")
    district_port: str | None = Field(default=None, description="DEPE customs district/port code")
    commodity_2digit: str | None = Field(
        default=None, description="COMMODITY2 two-digit HTS code (rail/other only)"
    )
    canada_province: str | None = Field(default=None, description="CANPROV code (see doc table)")
    mexico_state: str | None = Field(default=None, description="MEXSTATE code (exports only)")
    value_usd: float = Field(..., ge=0)
    ship_weight_kg: float | None = Field(default=None, ge=0)
    freight_charges_usd: float | None = Field(default=None, ge=0)
    containerized: bool | None = Field(
        default=None, description="CONTCODE: 1 = containerized, 0/X/blank = not"
    )
    distribution_flag: str | None = Field(default=None, description="BTS 'DF' raw flag")
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class TransBorderFreightBatch(BaseModel):
    records: list[TransBorderFreight]
    source: str = "bts_transborder"

    @property
    def count(self) -> int:
        return len(self.records)


class AARWeeklyTraffic(BaseModel):
    """One row from an AAR weekly rail-traffic press-release PDF: a category
    (Total Carloads, a commodity group, Total Intermodal Units, or Total
    Traffic) for one region (US/Canada/Mexico/North America) for one week.
    Cars are carloads (or intermodal units/traffic for the totals rows) and
    the four %s are year-over-year changes vs the prior year's week/YTD."""

    source: str = Field(default="aar_weekly")
    snapshot_date: date = Field(..., description="Week end date (Saturday)")
    region: str = Field(..., description="US, Canada, Mexico, or North America")
    week_number: int = Field(..., ge=1, le=53)
    year: int = Field(...)
    category: str = Field(..., description="Commodity group / totals label")
    this_week_cars: int = Field(..., ge=0)
    this_week_yoy_pct: float | None = Field(default=None)
    ytd_cars: int = Field(..., ge=0)
    ytd_avg_week_cars: int | None = Field(default=None, ge=0)
    ytd_yoy_pct: float | None = Field(default=None)
    raw_record: dict[str, Any] | None = Field(default=None)
    ingested_at: datetime = Field(default_factory=_utcnow)


class AARWeeklyTrafficBatch(BaseModel):
    records: list[AARWeeklyTraffic]
    source: str = "aar_weekly"

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

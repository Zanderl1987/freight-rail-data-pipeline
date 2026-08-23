from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

from .config import PipelineConfig
from .models.schemas import (
    AARWeeklyTrafficBatch,
    EurostatRailFreightBatch,
    FreightIndicatorBatch,
    MotorCarrierCensusBatch,
    OceanFreightRateBatch,
    PipelineRunSummary,
    RailCarloadingBatch,
    RailSafetyIncidentBatch,
    RailServiceMetricBatch,
    RailTariffRateBatch,
    TransBorderFreightBatch,
    TransBorderLegacyBatch,
    WaybillShipmentBatch,
)

log = logging.getLogger(__name__)


def _partition_path(
    base: Path, source: str, table: str, dt: date, granularity: str = "day"
) -> Path:
    if granularity == "year":
        return base / source / table / f"year={dt.year}"
    return base / source / table / f"year={dt.year}" / f"month={dt.month:02d}" / f"day={dt.day:02d}"


def _schema_for_model(table_name: str) -> pa.Schema:
    schemas: dict[str, pa.Schema] = {
        "rail_carloadings": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("railroad", pa.utf8()),
                pa.field("commodity", pa.utf8()),
                pa.field("traffic_type", pa.utf8(), nullable=True),
                pa.field("carloads", pa.float64()),
                pa.field("units", pa.utf8()),
                pa.field("origin_region", pa.utf8(), nullable=True),
                pa.field("destination_region", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "rail_service_metrics": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("railroad", pa.utf8()),
                pa.field("metric_name", pa.utf8()),
                pa.field("metric_value", pa.float64()),
                pa.field("unit", pa.utf8()),
                pa.field("region", pa.utf8(), nullable=True),
                pa.field("segment", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "ocean_freight_rates": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("route_code", pa.utf8()),
                pa.field("route_description", pa.utf8()),
                pa.field("origin_port", pa.utf8()),
                pa.field("destination_port", pa.utf8()),
                pa.field("trade_lane", pa.utf8()),
                pa.field("container_type", pa.utf8()),
                pa.field("rate_usd", pa.float64(), nullable=True),
                pa.field("currency", pa.utf8()),
                pa.field("rate_unit", pa.utf8()),
                pa.field("region", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "freight_indicators": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("external_id", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("indicator", pa.utf8()),
                pa.field("measure1", pa.utf8(), nullable=True),
                pa.field("measure2", pa.utf8(), nullable=True),
                pa.field("value", pa.float64()),
                pa.field("units", pa.utf8(), nullable=True),
                pa.field("underlying_source", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "rail_tariff_rates": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("railroad", pa.utf8()),
                pa.field("commodity", pa.utf8()),
                pa.field("origin", pa.utf8()),
                pa.field("destination", pa.utf8()),
                pa.field("rate_per_car", pa.decimal128(12, 2), nullable=True),
                pa.field("fuel_surcharge", pa.decimal128(10, 2), nullable=True),
                pa.field("currency", pa.utf8()),
                pa.field("movement_type", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "motor_carrier_census": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("dot_number", pa.utf8()),
                pa.field("carrier_operation", pa.utf8(), nullable=True),
                pa.field("state", pa.utf8(), nullable=True),
                pa.field("power_units", pa.int64(), nullable=True),
                pa.field("driver_count", pa.int64(), nullable=True),
                pa.field("mileage", pa.int64(), nullable=True),
                pa.field("mileage_year", pa.int64(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "rail_safety_incidents": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("external_id", pa.utf8()),
                pa.field("incident_type", pa.utf8()),
                pa.field("incident_date", pa.date32()),
                pa.field("railroad_code", pa.utf8(), nullable=True),
                pa.field("railroad_name", pa.utf8(), nullable=True),
                pa.field("state", pa.utf8(), nullable=True),
                pa.field("county", pa.utf8(), nullable=True),
                pa.field("category", pa.utf8(), nullable=True),
                pa.field("total_killed", pa.int64(), nullable=True),
                pa.field("total_injured", pa.int64(), nullable=True),
                pa.field("damage_cost_usd", pa.float64(), nullable=True),
                pa.field("latitude", pa.float64(), nullable=True),
                pa.field("longitude", pa.float64(), nullable=True),
                pa.field("narrative", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "rail_eurostat_freight": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("period", pa.utf8()),
                pa.field("country_code", pa.utf8()),
                pa.field("country_name", pa.utf8(), nullable=True),
                pa.field("unit", pa.utf8()),
                pa.field("metric", pa.utf8()),
                pa.field("value", pa.float64()),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "waybill_shipments": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("accounting_period", pa.utf8()),
                pa.field("carloads", pa.int64()),
                pa.field("car_ownership", pa.utf8(), nullable=True),
                pa.field("aar_equipment_type", pa.utf8(), nullable=True),
                pa.field("aar_mechanical_designation", pa.utf8(), nullable=True),
                pa.field("stb_car_type", pa.utf8(), nullable=True),
                pa.field("tofc_cofc_service_code", pa.utf8(), nullable=True),
                pa.field("tofc_cofc_units", pa.int64(), nullable=True),
                pa.field("tcu_ownership", pa.utf8(), nullable=True),
                pa.field("tcu_type", pa.utf8(), nullable=True),
                pa.field("hazardous_boxcar_flag", pa.utf8(), nullable=True),
                pa.field("stcc", pa.utf8()),
                pa.field("billed_tons", pa.float64(), nullable=True),
                pa.field("actual_tons", pa.float64(), nullable=True),
                pa.field("freight_revenue", pa.float64(), nullable=True),
                pa.field("transit_charges", pa.float64(), nullable=True),
                pa.field("miscellaneous_charges", pa.float64(), nullable=True),
                pa.field("inter_intra_state_code", pa.utf8(), nullable=True),
                pa.field("type_of_move", pa.utf8(), nullable=True),
                pa.field("all_rail_intermodal_code", pa.utf8(), nullable=True),
                pa.field("type_of_move_via_water", pa.utf8(), nullable=True),
                pa.field("transit_code", pa.utf8(), nullable=True),
                pa.field("substituted_truck_for_rail", pa.utf8(), nullable=True),
                pa.field("rebill_code", pa.utf8(), nullable=True),
                pa.field("estimated_shortline_miles", pa.int64(), nullable=True),
                pa.field("stratum_id", pa.int64(), nullable=True),
                pa.field("subsample_id", pa.int64(), nullable=True),
                pa.field("exact_expansion_factor", pa.float64(), nullable=True),
                pa.field("theoretical_expansion_factor", pa.int64(), nullable=True),
                pa.field("num_interchanges", pa.int64(), nullable=True),
                pa.field("origin_bea_area", pa.int64(), nullable=True),
                pa.field("origin_freight_territory", pa.utf8(), nullable=True),
                pa.field("interchange_states", pa.utf8(), nullable=True),
                pa.field("termination_bea_area", pa.int64(), nullable=True),
                pa.field("termination_freight_territory", pa.utf8(), nullable=True),
                pa.field("reporting_period_length", pa.utf8(), nullable=True),
                pa.field("car_capacity", pa.int64(), nullable=True),
                pa.field("nominal_car_capacity", pa.int64(), nullable=True),
                pa.field("tare_weight", pa.int64(), nullable=True),
                pa.field("outside_length", pa.int64(), nullable=True),
                pa.field("outside_width", pa.int64(), nullable=True),
                pa.field("outside_height", pa.int64(), nullable=True),
                pa.field("extreme_outside_height", pa.int64(), nullable=True),
                pa.field("wheel_bearings_type", pa.utf8(), nullable=True),
                pa.field("num_axles", pa.int64(), nullable=True),
                pa.field("draft_gear", pa.utf8(), nullable=True),
                pa.field("num_articulated_units", pa.int64(), nullable=True),
                pa.field("aar_error_codes", pa.utf8(), nullable=True),
                pa.field("routing_error_flag", pa.utf8(), nullable=True),
                pa.field("expanded_carloads", pa.int64(), nullable=True),
                pa.field("expanded_tons", pa.int64(), nullable=True),
                pa.field("expanded_freight_revenue", pa.float64(), nullable=True),
                pa.field("expanded_trailer_container_count", pa.int64(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "transborder_freight": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("trade_type", pa.utf8()),
                pa.field("country", pa.utf8()),
                pa.field("year", pa.int64()),
                pa.field("month", pa.int64()),
                pa.field("mode", pa.utf8()),
                pa.field("disagg_mode", pa.int64(), nullable=True),
                pa.field("source_file", pa.utf8(), nullable=True),
                pa.field("us_state", pa.utf8(), nullable=True),
                pa.field("district_port", pa.utf8(), nullable=True),
                pa.field("commodity_2digit", pa.utf8(), nullable=True),
                pa.field("canada_province", pa.utf8(), nullable=True),
                pa.field("mexico_state", pa.utf8(), nullable=True),
                pa.field("value_usd", pa.float64()),
                pa.field("ship_weight_kg", pa.float64(), nullable=True),
                pa.field("freight_charges_usd", pa.float64(), nullable=True),
                pa.field("containerized", pa.bool_(), nullable=True),
                pa.field("distribution_flag", pa.utf8(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "transborder_legacy_1993_2006": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("year", pa.int64()),
                pa.field("month", pa.int64()),
                pa.field("direction", pa.utf8()),
                pa.field("partner", pa.utf8()),
                pa.field("emphasis", pa.utf8()),
                pa.field("source_table", pa.utf8()),
                pa.field("source_file", pa.utf8()),
                pa.field("statmoyr", pa.utf8()),
                pa.field("disagg_mode", pa.int64(), nullable=True),
                pa.field("mode", pa.utf8()),
                pa.field("country", pa.utf8(), nullable=True),
                pa.field("value_usd", pa.float64(), nullable=True),
                pa.field("charges_usd", pa.float64(), nullable=True),
                pa.field("freight_usd", pa.float64(), nullable=True),
                pa.field("ship_weight", pa.float64(), nullable=True),
                pa.field("aggregate_count", pa.int64(), nullable=True),
                pa.field("us_state", pa.utf8(), nullable=True),
                pa.field("mexico_state", pa.utf8(), nullable=True),
                pa.field("canada_province", pa.utf8(), nullable=True),
                pa.field("district_port", pa.utf8(), nullable=True),
                pa.field("commodity_code", pa.utf8(), nullable=True),
                pa.field("distribution_flag", pa.utf8(), nullable=True),
                pa.field("ntar", pa.utf8(), nullable=True),
                pa.field("contcode", pa.utf8(), nullable=True),
                pa.field("mexregion", pa.utf8(), nullable=True),
                pa.field("usregion", pa.utf8(), nullable=True),
                pa.field("distgroup", pa.utf8(), nullable=True),
                pa.field("revision", pa.bool_()),
                pa.field("supplement", pa.bool_()),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
        "aar_weekly_traffic": pa.schema(
            [
                pa.field("source", pa.utf8()),
                pa.field("snapshot_date", pa.date32()),
                pa.field("region", pa.utf8()),
                pa.field("week_number", pa.int64()),
                pa.field("year", pa.int64()),
                pa.field("category", pa.utf8()),
                pa.field("this_week_cars", pa.int64()),
                pa.field("this_week_yoy_pct", pa.float64(), nullable=True),
                pa.field("ytd_cars", pa.int64()),
                pa.field("ytd_avg_week_cars", pa.int64(), nullable=True),
                pa.field("ytd_yoy_pct", pa.float64(), nullable=True),
                pa.field("raw_record", pa.string(), nullable=True),
                pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
            ]
        ),
    }
    try:
        return schemas[table_name]
    except KeyError as exc:
        # An unknown table would write a silently-empty Parquet while logging
        # success -- fail instead of corrupting the store.
        raise ValueError(f"Unknown table: {table_name}") from exc


class StorageWriter:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir
        self.written_paths: list[str] = []

    def write_carloadings(
        self,
        batch: RailCarloadingBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_carloadings", batch.records, dt)

    def write_service_metrics(
        self,
        batch: RailServiceMetricBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_service_metrics", batch.records, dt)

    def write_ocean_rates(
        self,
        batch: OceanFreightRateBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("ocean_freight_rates", batch.records, dt)

    def write_freight_indicators(
        self,
        batch: FreightIndicatorBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("freight_indicators", batch.records, dt)

    def write_rail_tariff_rates(
        self,
        batch: RailTariffRateBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_tariff_rates", batch.records, dt)

    def write_motor_carrier_census(
        self,
        batch: MotorCarrierCensusBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("motor_carrier_census", batch.records, dt)

    def write_rail_safety_incidents(
        self,
        batch: RailSafetyIncidentBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_safety_incidents", batch.records, dt)

    def write_rail_eurostat_freight(
        self,
        batch: EurostatRailFreightBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_eurostat_freight", batch.records, dt)

    def write_waybills(
        self,
        batch: WaybillShipmentBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        # Annual dataset (~2M rows): partition by year, skip the CSV fallback
        # (a ~300MB text dump per year adds nothing over the parquet).
        return self._write_table(
            "waybill_shipments", batch.records, dt, partition="year", write_csv=False
        )

    def write_transborder_freight(
        self,
        batch: TransBorderFreightBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("transborder_freight", batch.records, dt)

    def write_transborder_legacy(
        self,
        batch: TransBorderLegacyBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        # 168 month partitions from the DBF backfill, each re-serializing the
        # full JSON raw_record column: an uncompressed CSV twin per month
        # roughly doubles the store for no query benefit (cf. write_waybills).
        return self._write_table(
            "transborder_legacy_1993_2006", batch.records, dt, write_csv=False
        )

    def write_aar_weekly(
        self,
        batch: AARWeeklyTrafficBatch,
        dt: date | None = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("aar_weekly_traffic", batch.records, dt)

    def _write_table(
        self,
        table_name: str,
        records: Sequence[BaseModel],
        dt: date | None = None,
        partition: str = "day",
        write_csv: bool = True,
    ) -> int:
        if not records:
            return 0

        schema = _schema_for_model(table_name)

        # Partition per record's own snapshot_date. This supersedes DECISION-002
        # (partition everything on the ingestion date): both were answers to the
        # same bug -- keying a whole batch on records[0].snapshot_date mislabels
        # years of data when a run fetches full history -- but per-record
        # partitioning is what the live store is physically laid out with, so
        # switching to ingestion-date would require repartitioning everything.
        def partition_date(record: BaseModel) -> date:
            snapshot = getattr(record, "snapshot_date", None)
            if not isinstance(snapshot, date):
                snapshot = dt or date.today()
            return snapshot if isinstance(snapshot, date) else dt or date.today()

        # Group by the physical partition key. Day partitions are unique per
        # snapshot date; year partitions must MERGE every snapshot that falls in
        # the same year into one file -- otherwise each group rewrites the same
        # `year=YYYY/<table>.parquet` and only the last one survives.
        key_fn = (lambda s: s.year) if partition == "year" else (lambda s: (s.year, s.month, s.day))
        by_key: dict[int | tuple[int, int, int], list[BaseModel]] = {}
        for record in records:
            by_key.setdefault(key_fn(partition_date(record)), []).append(record)

        written = 0
        for key, day_records in sorted(by_key.items()):
            if isinstance(key, int):
                partition_dir = _partition_path(
                    self.output_dir, "freight", table_name, date(key, 1, 1), "year"
                )
            else:
                year, month, day = key
                partition_dir = _partition_path(
                    self.output_dir, "freight", table_name, date(year, month, day)
                )
            partition_dir.mkdir(parents=True, exist_ok=True)

            # Serialize raw_record to JSON string for parquet compatibility
            serialized = []
            for r in day_records:
                d = r.model_dump(mode="python")
                if d.get("raw_record") is not None:
                    import json

                    d["raw_record"] = json.dumps(d["raw_record"], default=str)
                d["ingested_at"] = d.get("ingested_at", pd.Timestamp.now("UTC"))
                serialized.append(d)

            df = pd.DataFrame(serialized)

            file_path = partition_dir / f"{table_name}.parquet"

            # Year partitions accumulate across runs: every STB sample year
            # contributes records to overlapping waybill years, so a backfill
            # run must MERGE with what is already on disk instead of silently
            # replacing it -- the same overwrite hazard the within-run group
            # merge fixed, one level up. Day partitions keep overwrite
            # semantics (each fetch returns full history for a day) and dedup
            # happens at export.
            if partition == "year" and file_path.exists():
                existing = pd.read_parquet(file_path)
                if not existing.empty:
                    identity_cols = [c for c in existing.columns if c != "ingested_at"]
                    if identity_cols:
                        df = (
                            pd.concat([existing, df], ignore_index=True)
                            .sort_values("ingested_at")
                            .drop_duplicates(subset=identity_cols, keep="last")
                            .reset_index(drop=True)
                        )
                    log.info(
                        "Merged %d existing + %d new records into %s",
                        len(existing),
                        len(day_records),
                        file_path,
                    )

            # Ensure date-ish fields
            if "snapshot_date" in df.columns:
                df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
            if "incident_date" in df.columns:
                df["incident_date"] = pd.to_datetime(df["incident_date"]).dt.date
            if "ingested_at" in df.columns:
                df["ingested_at"] = pd.to_datetime(df["ingested_at"])

            # Write Parquet
            pa_table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
            pq.write_table(pa_table, file_path, compression="zstd")  # type: ignore[no-untyped-call]
            log.info("Wrote %d records to %s", len(day_records), file_path)
            self.written_paths.append(str(file_path))

            # Write CSV as fallback (skipped for very large annual tables)
            if write_csv:
                csv_path = partition_dir / f"{table_name}.csv"
                df.to_csv(csv_path, index=False)
                log.info("Wrote %d records to %s", len(day_records), csv_path)

            written += len(day_records)

        return written

    def write_summary(self, summary: PipelineRunSummary) -> None:
        summary_file = self.output_dir / "pipeline_runs" / f"{summary.run_id}.json"
        summary_file.parent.mkdir(parents=True, exist_ok=True)

        with open(summary_file, "w") as f:
            f.write(summary.model_dump_json(indent=2))
        log.info("Wrote pipeline summary to %s", summary_file)
        self.written_paths.append(str(summary_file))

    def list_written(self) -> list[str]:
        return list(self.written_paths)

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import PipelineConfig
from .models.schemas import (
    OceanFreightRate,
    OceanFreightRateBatch,
    PipelineRunSummary,
    RailCarloading,
    RailCarloadingBatch,
    RailServiceMetric,
    RailServiceMetricBatch,
    RailTariffRateBatch,
)

log = logging.getLogger(__name__)


def _partition_path(base: Path, source: str, table: str, dt: date) -> Path:
    return base / source / table / f"year={dt.year}" / f"month={dt.month:02d}" / f"day={dt.day:02d}"


def _pydantic_to_pyarrow(
    records: list,
    schema: pa.Schema,
) -> pa.Table:
    data: list[dict] = [r.model_dump(mode="python") for r in records]
    df = pd.DataFrame(data)

    for field in schema:
        if field.name in df.columns:
            if pa.types.is_timestamp(field.type):
                df[field.name] = pd.to_datetime(df[field.name])
            elif pa.types.is_date(field.type):
                df[field.name] = pd.to_datetime(df[field.name]).dt.date

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    return table


def _schema_for_model(table_name: str) -> pa.Schema:
    schemas: dict[str, pa.Schema] = {
        "rail_carloadings": pa.schema([
            pa.field("source", pa.utf8()),
            pa.field("snapshot_date", pa.date32()),
            pa.field("railroad", pa.utf8()),
            pa.field("commodity", pa.utf8()),
            pa.field("carloads", pa.int64()),
            pa.field("units", pa.utf8()),
            pa.field("origin_region", pa.utf8(), nullable=True),
            pa.field("destination_region", pa.utf8(), nullable=True),
            pa.field("raw_record", pa.string(), nullable=True),
            pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
        ]),
        "rail_service_metrics": pa.schema([
            pa.field("source", pa.utf8()),
            pa.field("snapshot_date", pa.date32()),
            pa.field("railroad", pa.utf8()),
            pa.field("metric_name", pa.utf8()),
            pa.field("metric_value", pa.float64()),
            pa.field("unit", pa.utf8()),
            pa.field("region", pa.utf8(), nullable=True),
            pa.field("raw_record", pa.string(), nullable=True),
            pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
        ]),
        "ocean_freight_rates": pa.schema([
            pa.field("source", pa.utf8()),
            pa.field("snapshot_date", pa.date32()),
            pa.field("route_code", pa.utf8()),
            pa.field("route_description", pa.utf8()),
            pa.field("origin_port", pa.utf8()),
            pa.field("destination_port", pa.utf8()),
            pa.field("trade_lane", pa.utf8()),
            pa.field("container_type", pa.utf8()),
            pa.field("rate_usd", pa.int64(), nullable=True),
            pa.field("currency", pa.utf8()),
            pa.field("rate_unit", pa.utf8()),
            pa.field("region", pa.utf8(), nullable=True),
            pa.field("raw_record", pa.string(), nullable=True),
            pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
        ]),
    }
    return schemas.get(table_name, pa.schema([]))


def _json_serialize_raw(records: list) -> list:
    import json

    result = []
    for r in records:
        d = r.model_dump(mode="python")
        if d.get("raw_record") is not None:
            d["raw_record"] = json.dumps(d["raw_record"], default=str)
        result.append(d)
    return result


class StorageWriter:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir
        self.written_paths: list[str] = []

    def write_carloadings(
        self,
        batch: RailCarloadingBatch,
        dt: Optional[date] = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_carloadings", batch.records, dt)

    def write_service_metrics(
        self,
        batch: RailServiceMetricBatch,
        dt: Optional[date] = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("rail_service_metrics", batch.records, dt)

    def write_ocean_rates(
        self,
        batch: OceanFreightRateBatch,
        dt: Optional[date] = None,
    ) -> int:
        if not batch.records:
            return 0
        return self._write_table("ocean_freight_rates", batch.records, dt)

    def _write_table(
        self,
        table_name: str,
        records: list,
        dt: Optional[date] = None,
    ) -> int:
        if not records:
            return 0

        snapshot = dt or getattr(records[0], "snapshot_date", date.today())
        schema = _schema_for_model(table_name)
        partition_dir = _partition_path(self.output_dir, "freight", table_name, snapshot)
        partition_dir.mkdir(parents=True, exist_ok=True)

        # Serialize raw_record to JSON string for parquet compatibility
        serialized = []
        for r in records:
            d = r.model_dump(mode="python")
            if d.get("raw_record") is not None:
                import json
                d["raw_record"] = json.dumps(d["raw_record"], default=str)
            d["ingested_at"] = d.get("ingested_at", pd.Timestamp.utcnow())
            serialized.append(d)

        df = pd.DataFrame(serialized)

        # Ensure date-ish fields
        if "snapshot_date" in df.columns:
            df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
        if "ingested_at" in df.columns:
            df["ingested_at"] = pd.to_datetime(df["ingested_at"])

        # Write Parquet
        pa_table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        file_path = partition_dir / f"{table_name}.parquet"
        pq.write_table(pa_table, file_path, compression="zstd")
        log.info("Wrote %d records to %s", len(records), file_path)
        self.written_paths.append(str(file_path))

        # Write CSV as fallback
        csv_path = partition_dir / f"{table_name}.csv"
        df.to_csv(csv_path, index=False)
        log.info("Wrote %d records to %s", len(records), csv_path)

        return len(records)

    def write_summary(self, summary: PipelineRunSummary) -> None:
        summary_file = self.output_dir / "pipeline_runs" / f"{summary.run_id}.json"
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        import json

        with open(summary_file, "w") as f:
            f.write(summary.model_dump_json(indent=2, default=str))
        log.info("Wrote pipeline summary to %s", summary_file)
        self.written_paths.append(str(summary_file))

    def list_written(self) -> list[str]:
        return list(self.written_paths)

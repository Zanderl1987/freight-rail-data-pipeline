from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from . import sources as src
from .config import PipelineConfig
from .logging_setup import setup_logging
from .models.schemas import (
    OceanFreightRateBatch,
    PipelineRunSummary,
    RailCarloadingBatch,
    RailServiceMetricBatch,
)
from .storage import StorageWriter

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    run_id: str
    success: bool
    total_records: int = 0
    source_results: dict[str, int] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class FreightPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig.from_env()
        self.config.ensure_dirs()
        self.logger = setup_logging(
            log_dir=self.config.log_dir,
            level=self.config.log_level,
            json_format=self.config.log_json,
        )
        self.storage = StorageWriter(self.config)

        self._sources: dict[str, src.BaseSource] = {
            "usda": src.USDAgTransportSource(self.config),
            "fbx": src.FreightosFBXSource(self.config),
        }

    def run(
        self,
        sources: list[str] | None = None,
        snapshot_date: date | None = None,
    ) -> PipelineResult:
        start = time.monotonic()
        run_id = datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S")
        log.info("Pipeline run %s starting — sources=%s", run_id, sources or list(self._sources))

        summary = PipelineRunSummary(
            run_id=run_id,
            started_at=datetime.now(UTC),
        )
        result = PipelineResult(run_id=run_id, success=True)

        selected_sources = self._resolve_sources(sources)
        summary.sources_attempted = list(selected_sources.keys())

        for name, source in selected_sources.items():
            log.info("=== Running source: %s ===", name)
            try:
                source_result = source.fetch(snapshot_date=snapshot_date)
                source_result_written = self._write_source_output(
                    name, source_result, snapshot_date
                )
                result.source_results[name] = source_result_written
                result.total_records += source_result_written
                summary.sources_succeeded.append(name)
                log.info(
                    "Source %s completed: %d records written",
                    name,
                    source_result_written,
                )
            except Exception as exc:
                log.exception("Source %s failed: %s", name, exc)
                summary.sources_failed.append(name)
                result.failed_sources.append(name)
                result.errors.append(f"{name}: {exc}")
                result.success = False
                summary.errors.append(str(exc))

        result.output_paths = self.storage.list_written()
        summary.output_paths = result.output_paths
        summary.total_records_written = result.total_records
        summary.success = result.success
        summary.finished_at = datetime.now(UTC)

        self.storage.write_summary(summary)

        duration = time.monotonic() - start
        result.duration_seconds = duration

        log.info(
            "Pipeline run %s finished — success=%s, records=%d, duration=%.1fs",
            run_id,
            result.success,
            result.total_records,
            duration,
        )
        return result

    def list_sources(self) -> dict[str, str]:
        return {name: type(source).__doc__ or "" for name, source in self._sources.items()}

    def validate_sources(self) -> dict[str, list[str]]:
        return {name: source.validate() for name, source in self._sources.items()}

    def _resolve_sources(self, names: list[str] | None) -> dict[str, src.BaseSource]:
        if not names:
            return dict(self._sources)
        resolved: dict[str, src.BaseSource] = {}
        for name in names:
            if name in self._sources:
                resolved[name] = self._sources[name]
            else:
                log.warning("Unknown source '%s', skipping", name)
        return resolved

    def _write_source_output(
        self,
        source_name: str,
        source_result: src.SourceResult[Any],
        snapshot_date: date | None = None,
    ) -> int:
        records = source_result.records
        if not records:
            return 0

        written = 0

        cl_records = [r for r in records if type(r).__name__ == "RailCarloading"]
        if cl_records:
            written += self.storage.write_carloadings(
                RailCarloadingBatch(records=cl_records),
                dt=snapshot_date,
            )

        sm_records = [r for r in records if type(r).__name__ == "RailServiceMetric"]
        if sm_records:
            written += self.storage.write_service_metrics(
                RailServiceMetricBatch(records=sm_records),
                dt=snapshot_date,
            )

        of_records = [r for r in records if type(r).__name__ == "OceanFreightRate"]
        if of_records:
            written += self.storage.write_ocean_rates(
                OceanFreightRateBatch(records=of_records),
                dt=snapshot_date,
            )

        return written

#!/usr/bin/env python3
"""
Backfill BTS TransBorder monthly zips (2018-present) into local storage.

Walks every month-name zip on the raw-data page (the 1993-2017 annual files
have no month names, so they are naturally excluded -- they are zip-of-zips
bundles in a different schema and are out of scope here), fetches each month
that is not already on disk, and writes it under the monthly day partition.
Runs are idempotent: an existing year=YYYY/month=MM partition skips the fetch,
and day partitions overwrite on re-run.

Usage:
    python scripts/backfill_bts_transborder.py
    python scripts/backfill_bts_transborder.py 2020-07 2021-01   # targeted months
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from freight_rail_pipeline.config import PipelineConfig  # noqa: E402
from freight_rail_pipeline.models import TransBorderFreightBatch  # noqa: E402
from freight_rail_pipeline.pipeline import FreightPipeline  # noqa: E402


def main() -> None:
    targets = {tuple(int(p) for p in a.split("-")) for a in sys.argv[1:]}
    pipeline = FreightPipeline()
    config: PipelineConfig = pipeline.config
    source = pipeline._sources["transborder"]

    links = source._list_zip_links()
    print(f"Found {len(links)} monthly TransBorder zip links on the raw-data page", flush=True)

    written_total = 0
    skipped = 0
    failed = 0
    for year, month, url in links:
        if targets and (year, month) not in targets:
            continue
        month_dir = (
            Path(config.output_dir)
            / "freight"
            / "transborder_freight"
            / f"year={year}"
            / f"month={month:02d}"
        )
        if month_dir.is_dir():
            print(f"  skip {year}-{month:02d}: partition exists", flush=True)
            skipped += 1
            continue
        print(f"  fetch {year}-{month:02d}: {url}", flush=True)
        t0 = time.monotonic()
        try:
            records = source._fetch_month_zip(url)
        except Exception as exc:  # noqa: BLE001 -- report and continue
            print(f"  FAIL {year}-{month:02d}: {exc}", flush=True)
            failed += 1
            continue
        n = len(records)
        written = pipeline.storage.write_transborder_freight(
            TransBorderFreightBatch(records=records)
        )
        dt = time.monotonic() - t0
        written_total += written
        print(f"    {n} records, {written} written ({dt:.0f}s)", flush=True)

    print(
        f"done: {written_total} records written, {skipped} months skipped, {failed} failed",
        flush=True,
    )


if __name__ == "__main__":
    main()

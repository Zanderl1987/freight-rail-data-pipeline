#!/usr/bin/env python3
"""
Backfill STB waybill samples older than the latest one already on disk.

Each STB annual sample covers ~6 years of waybill dates, so backfilling N
sample years deepens coverage of recent waybill years AND extends history
backwards. Runs are idempotent: storage._write_table skips sample years whose
year=YYYY partition already exists, and year partitions merge across runs.

Usage:
    python scripts/backfill_stb_waybill.py 2019 2020 2021 2022 2023
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from freight_rail_pipeline.pipeline import FreightPipeline  # noqa: E402

PACE_SECONDS = 1.0


def main() -> None:
    years = [int(a) for a in sys.argv[1:]]
    if not years:
        raise SystemExit("Pass one or more sample years, e.g. 2019 2020 2021")
    pipeline = FreightPipeline()
    waybill_source = pipeline._sources["stb_waybill"]
    waybill_source.force = True
    for year in years:
        snap = date(year, 12, 31)
        print(f"--- backfilling STB waybill sample {year} (snapshot {snap}) ---", flush=True)
        t0 = time.monotonic()
        result = pipeline.run(sources=["stb_waybill"], snapshot_date=snap)
        dt = time.monotonic() - t0
        n = result.source_results.get("stb_waybill", 0)
        skipped = "skipped" if result.failed_sources == [] and n == 0 else ""
        print(f"    sample {year}: {n} records written {skipped} ({dt:.0f}s)", flush=True)
        if result.failed_sources:
            print(f"    sample {year} FAILED: {result.errors}", flush=True)
        time.sleep(PACE_SECONDS)
    print("done")


if __name__ == "__main__":
    main()

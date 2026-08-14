#!/usr/bin/env python3
"""
Backfill BTS TransBorder modern-schema annual zips (2007-2017) into local storage.

The raw-data page only exposes month-name zips (2018-present). The 2007-2017
annual files are whole-year zip bundles in several layouts, but their per-month
dot1/dot2/dot3 CSVs carry the same modern schema (TRDTYPE/.../YEAR) as the
2018+ monthly files, so they parse with the existing normalizer. Layouts:

  * folders:  {year}/April {year}/dot1_MMYY.csv          -- 2007, 2008, 2014-2016
  * flat:     Revised {year} Public Data/Data Files/...  -- 2009-2013 (Revised)
  * zips:     {year}/{Month} {year}.zip, one per month   -- 2017

Every layout also carries cumulative `dotX_ytd_MMYY.csv` views (and some a
full-year `dotX_YYYY.csv`); the monthly dot files are the raw grain. 2008
bundles a byte-identical "Copy of January 2008" (deduped by basename) and its
March dot2/dot3 files are corrupted in BTS's published zip -- those months are
recovered from the next month's YTD view, which repeats the monthly rows
carrying their own MONTH/YEAR columns. The 1993-2006 annuals are a different,
pre-CSV schema (dBase/DBF) and are out of scope here.

Each annual is downloaded whole to a temp cache (one paced request, avoiding
hundreds of ranged requests against Akamai), parsed, and the cache deleted.
Months whose year=YYYY/month=MM partition already exists are skipped, so runs
are idempotent and resumable.

Usage:
    python scripts/backfill_bts_transborder_annual.py
    python scripts/backfill_bts_transborder_annual.py 2007            # one year
    python scripts/backfill_bts_transborder_annual.py 2007 2010-2013  # years/range
    python scripts/backfill_bts_transborder_annual.py 2017-05         # one month
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from freight_rail_pipeline.config import PipelineConfig  # noqa: E402
from freight_rail_pipeline.models import TransBorderFreightBatch  # noqa: E402
from freight_rail_pipeline.pipeline import FreightPipeline  # noqa: E402
from freight_rail_pipeline.sources.bts_transborder import (  # noqa: E402
    _UA,
    _is_retryable_transborder,
)

log = logging.getLogger(__name__)

ANNUAL_FILES: list[tuple[int, str]] = [
    (2007, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2007/2007.zip"),
    (2008, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2008/2008.zip"),
    (2009, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2009/Revised2009PublicData.zip"),
    (2010, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2010/Revised2010PublicData.zip"),
    (2011, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2011/Revised2011PublicData.zip"),
    (2012, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2012/Revised2012PublicData.zip"),
    (2013, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2013/Revised2013PublicData.zip"),
    (2014, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2014/2014.zip"),
    (2015, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2015/2015.zip"),
    (2016, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2016/2016.zip"),
    (2017, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2017/2017.zip"),
]

_MONTHLY_DOT_RE = re.compile(r"^dot([123])_(0[1-9]|1[0-2])(\d{2})\.csv$", re.I)
_YTD_DOT_RE = re.compile(r"^dot([123])_ytd_(0[1-9]|1[0-2])(\d{2})\.csv$", re.I)
# BTS published 2016-08 under legacy names (TransBorder_3_0816 (N).csv) in
# its "Aug 2016" folder; the (N) suffix does not match the dot number, so the
# view is identified by column set instead.
_LEGACY_MONTHLY_DOT_RE = re.compile(
    r"^TransBorder_\d+_(\d{2})(\d{2})\s*\((\d)\)\.csv$", re.I
)


def _classify_legacy(header: bytes) -> str:
    """Map a legacy TransBorder header to its dot1/dot2/dot3 view."""
    cols = {c.strip().upper() for c in header.decode("utf-8-sig", "replace").split(",")}
    if "COMMODITY2" in cols and "USASTATE" in cols:
        return "dot2"
    if "COMMODITY2" in cols:
        return "dot3"
    return "dot1"

_PACE_SECONDS = 3.0
_last_request_at = 0.0


def _pace() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _PACE_SECONDS:
        time.sleep(_PACE_SECONDS - elapsed)
    _last_request_at = time.monotonic()


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=3, max=60, jitter=3),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
    retry=retry_if_exception(_is_retryable_transborder),
)
def _download_annual(url: str, dest: Path) -> None:
    """Stream one annual zip to disk (single request, paced, retried on 403/429)."""
    _pace()
    with requests.get(url, timeout=1800, headers=_UA, stream=True) as resp:
        resp.raise_for_status()
        if resp.headers.get("Content-Type", "").startswith("text/html"):
            raise requests.HTTPError(
                f"Akamai page returned instead of zip for {url}", response=resp
            )
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)


def _parse_targets(tokens: list[str]) -> set[tuple[int, int]]:
    """Accept bare years ('2007'), inclusive year ranges ('2009-2011'), and
    single months ('2017-05'). Empty means all months of all annuals."""
    if not tokens:
        return set()
    targets: set[tuple[int, int]] = set()
    for tok in tokens:
        parts = [int(p) for p in tok.split("-")]
        if len(parts) == 1:
            targets.update((parts[0], m) for m in range(1, 13))
        elif len(parts) == 2 and parts[1] > 12:
            targets.update((y, m) for y in range(parts[0], parts[1] + 1) for m in range(1, 13))
        else:
            targets.add((parts[0], parts[1]))
    return targets


def _decode_csv(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _filter_month(text: str, year: int, month: int) -> list[dict[str, str]]:
    """Rows of a cumulative YTD view for the given (year, month) only."""
    return [
        dict(row)
        for row in csv.DictReader(io.StringIO(text))
        if str(row.get("YEAR", "")).strip() == str(year)
        and str(row.get("MONTH", "")).strip() == str(month).zfill(2)
    ]


def _month_partition(config: PipelineConfig, year: int, month: int) -> Path:
    return (
        Path(config.output_dir)
        / "freight"
        / "transborder_freight"
        / f"year={year}"
        / f"month={month:02d}"
    )


def _build_registry(zf: zipfile.ZipFile) -> tuple[
    dict[tuple[int, int], dict[str, tuple[str, zipfile.ZipFile]]],
    dict[tuple[int, int], dict[str, tuple[str, zipfile.ZipFile]]],
    list[tuple[int, int, str, str]],
]:
    """Scan one annual zip and register monthly + cumulative-YTD dot members.

    Handles all four BTS layouts (folder, flat, zip-of-zips, and the legacy
    2016-08 `TransBorder_...csv` naming). Returns (monthly, ytd, corrupt).
    Owners are the outer annual (folder/flat) or an inner month zip (2017's
    zip-of-zips). See work-notes/freight-rail-data-pipeline/BUG_FIXES.md for the layout quirks this encodes.
    """
    monthly: dict[tuple[int, int], dict[str, tuple[str, zipfile.ZipFile]]] = {}
    ytd: dict[tuple[int, int], dict[str, tuple[str, zipfile.ZipFile]]] = {}
    corrupt: list[tuple[int, int, str, str]] = []

    def _register(names: list[str], owner: zipfile.ZipFile) -> None:
        for name in names:
            base = name.rsplit("/", 1)[-1]
            m = _MONTHLY_DOT_RE.match(base)
            if m:
                key = (2000 + int(m.group(3)), int(m.group(2)))
                dotkey = f"dot{m.group(1)}"
                prev = monthly.setdefault(key, {}).get(dotkey)
                # 2008 bundles a byte-identical "Copy of January 2008":
                # prefer the shortest path so the copy loses.
                if prev is None or len(name) < len(prev[0]):
                    monthly[key][dotkey] = (name, owner)
                continue
            y = _YTD_DOT_RE.match(base)
            if y:
                key = (2000 + int(y.group(3)), int(y.group(2)))
                ytd.setdefault(key, {})[f"dot{y.group(1)}"] = (name, owner)
                continue
            lg = _LEGACY_MONTHLY_DOT_RE.match(base)
            if lg:
                key = (2000 + int(lg.group(2)), int(lg.group(1)))
                try:
                    dotkey = _classify_legacy(owner.read(name).split(b"\n", 1)[0])
                except Exception:  # noqa: S112 -- skip unreadable member
                    continue
                prev = monthly.setdefault(key, {}).get(dotkey)
                if prev is None or len(name) < len(prev[0]):
                    monthly[key][dotkey] = (name, owner)

    _register(zf.namelist(), zf)
    # Only 2017 is a true zip-of-zips (month bundles as inner zips). The
    # Revised years also carry a "Zip Files" folder of redundant per-view
    # annual bundles (dot1_2011.zip) alongside the flat Data Files CSVs --
    # unwrapping those would double every month, so skip inner zips whenever
    # the outer layout already exposes monthly files directly.
    if not monthly:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".zip"):
                continue
            try:
                inner = zipfile.ZipFile(io.BytesIO(zf.read(info)))
            except zipfile.BadZipFile as exc:
                corrupt.append((0, 0, info.filename, f"inner zip unreadable: {exc}"))
                continue
            _register(inner.namelist(), inner)
    return monthly, ytd, corrupt


def main() -> None:
    targets = _parse_targets(sys.argv[1:])
    pipeline = FreightPipeline()
    config: PipelineConfig = pipeline.config
    source = pipeline._sources["transborder"]

    written_total = 0
    skipped = 0
    failed = 0
    recovered: list[str] = []
    corrupt: list[tuple[int, int, str, str]] = []
    tmp_root = Path(tempfile.mkdtemp(prefix="tbdr_annual_"))
    try:
        for year, url in ANNUAL_FILES:
            missing = {
                (year, m)
                for m in range(1, 13)
                if (not targets or (year, m) in targets)
                and not _month_partition(config, year, m).is_dir()
            }
            if not missing:
                print(f"  skip {year}: all target months present", flush=True)
                skipped += len(missing)
                continue
            print(f"  download {year}: {url}", flush=True)
            t0 = time.monotonic()
            cache = tmp_root / f"{year}.zip"
            try:
                _download_annual(url, cache)
            except Exception as exc:  # noqa: BLE001 -- report and continue
                print(f"  FAIL download {year}: {exc}", flush=True)
                failed += len(missing)
                continue
            print(
                f"    downloaded {cache.stat().st_size / 1e6:.0f}MB "
                f"({time.monotonic() - t0:.0f}s)",
                flush=True,
            )

            with zipfile.ZipFile(cache) as zf:
                monthly, ytd, y_corrupt = _build_registry(zf)
                corrupt.extend(y_corrupt)

                for (fyear, fmonth) in sorted(monthly):
                    if (fyear, fmonth) not in missing:
                        continue
                    if _month_partition(config, fyear, fmonth).is_dir():
                        skipped += 1
                        continue

                    month_records = []
                    for dot in ("dot1", "dot2", "dot3"):
                        entry = monthly[(fyear, fmonth)].get(dot)
                        if entry is None:
                            corrupt.append((fyear, fmonth, dot, "missing monthly member"))
                            continue
                        name, owner = entry
                        try:
                            text = _decode_csv(owner.read(name))
                            rows = csv.DictReader(io.StringIO(text))
                            for row in rows:
                                record = source._normalizer.normalize_transborder_freight(
                                    dict(row), source_file=dot
                                )
                                if record is not None:
                                    month_records.append(record)
                        except Exception as exc:  # noqa: BLE001 -- corrupt member
                            # The BTS-published 2008 zip corrupts the March
                            # dot2/dot3 members. Their rows survive in every
                            # later month's cumulative YTD view, which repeats
                            # the monthly rows carrying MONTH/YEAR columns.
                            fallback = None
                            for (fym, fmm) in sorted(ytd):
                                if fym == fyear and fmm > fmonth:
                                    cand = ytd[(fym, fmm)].get(dot)
                                    if cand is not None:
                                        fallback = cand
                                        break
                            if fallback is not None:
                                fb_name, fb_owner = fallback
                                try:
                                    text = _decode_csv(fb_owner.read(fb_name))
                                    for row in _filter_month(text, fyear, fmonth):
                                        record = source._normalizer.normalize_transborder_freight(
                                            dict(row), source_file=dot
                                        )
                                        if record is not None:
                                            month_records.append(record)
                                    recovered.append(f"{fyear}-{fmonth:02d} {dot} via YTD")
                                    continue
                                except Exception as exc2:  # noqa: BLE001
                                    detail = f"member {name}: {exc}; YTD {fb_name}: {exc2}"
                                    corrupt.append((fyear, fmonth, dot, detail))
                                    continue
                            corrupt.append((fyear, fmonth, dot, f"member {name}: {exc}"))

                    written = pipeline.storage.write_transborder_freight(
                        TransBorderFreightBatch(records=month_records)
                    )
                    written_total += written
                    print(
                        f"    {fyear}-{fmonth:02d}: {len(month_records)} records, "
                        f"{written} written ({time.monotonic() - t0:.0f}s)",
                        flush=True,
                    )
    finally:
        for p in tmp_root.iterdir():
            p.unlink()
        tmp_root.rmdir()

    print(
        f"done: {written_total} records written, {skipped} months skipped, "
        f"{failed} months failed",
        flush=True,
    )
    if recovered:
        print(f"recovered via YTD fallback: {len(recovered)} members")
        for line in recovered:
            print(f"  {line}", flush=True)
    if corrupt:
        print(f"CORRUPT/unrecoverable: {len(corrupt)} members")
        for year, month, dot, detail in corrupt:
            print(f"  {year}-{month:02d} {dot}: {detail}", flush=True)


if __name__ == "__main__":
    main()

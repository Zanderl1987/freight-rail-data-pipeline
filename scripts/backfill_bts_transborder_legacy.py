#!/usr/bin/env python3
"""
Backfill BTS TransBorder pre-CSV annual zips (1993-2006) into local storage.

The 1993-2006 annuals ship per-month dBase (DBF) tables whose grain predates
the modern dot1/dot2/dot3 CSV schema (2007+). Table families encode
direction/partner/emphasis in their name:

  * d03/d3a/d3b  = export MX, commodity
  * d04/d4a/d4b  = export CA, commodity
  * d05/d5a/d5b/d5s = export MX, geography
  * d06/d6a/d6b  = export CA, geography
  * d09/d10      = import MX/CA, commodity
  * d11/d12      = import MX/CA, geography
  * av1-av12     = 2004-2006 air/vessel tables (av1/av2 = export MX/CA
                   commodity; av3-av6 = export geography; av7/av8 = import
                   MX/CA commodity; av9-av12 = import geography)

Layouts:

  * 1993:  outer zip contains `93MM.zip` month zips directly (series starts
           Apr 1993; DBFs flat inside each month zip)
  * 1994-2006: outer zip contains `YY0112.zip` year bundle, which contains
           `YYYYMM.zip` month zips. 2006 also bundles a junk `1701.zip`
           (Jan-2017 modern data) -- skipped because it is not `??0112.zip`.

STATMOYR is authoritative for the period, per row (do not trust zip/file
names, and do not assume a file is period-pure): 4-digit `MMYY` through 1997,
6-digit `YYYYMM` from 1998. Each row is filed under its own STATMOYR, so rows
that land on another month of the same annual are written with that month
(e.g. the 1995 `X*` supplements for Jan-Mar live in the April zip). Rows for a
month outside the annual being processed are reported and dropped -- month
partitions are overwritten rather than merged, so a partial write would
clobber or pre-empt that month's own annual. `r*` files are
revisions that supersede the same-month `D*` file (dropped when a revision
exists for the same source_table+statmoyr); `X*` files are supplements that
add previously unreported rows (always kept). Lookup tables, *.tab/*.txt
files and readmes are skipped. Each month's records are written to the
`transborder_legacy_1993_2006` table (partitioned by month-end snapshot
date); existing month partitions are skipped, so runs are idempotent and
resumable.

Usage:
    python scripts/backfill_bts_transborder_legacy.py
    python scripts/backfill_bts_transborder_legacy.py 1993 1995
    python scripts/backfill_bts_transborder_legacy.py 1993-1996
    python scripts/backfill_bts_transborder_legacy.py 2005-01
"""
from __future__ import annotations

import calendar
import io
import logging
import re
import struct
import sys
import tempfile
import time
import zipfile
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import NamedTuple

import requests
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from freight_rail_pipeline.config import PipelineConfig  # noqa: E402
from freight_rail_pipeline.models import (  # noqa: E402
    TransBorderLegacy,
    TransBorderLegacyBatch,
)
from freight_rail_pipeline.models.normalizer import (  # noqa: E402
    COUNTRY_CODE_MAP,
    DISAGMOT_LABELS,
)
from freight_rail_pipeline.pipeline import FreightPipeline  # noqa: E402
from freight_rail_pipeline.sources.bts_transborder import _UA  # noqa: E402

log = logging.getLogger(__name__)

ANNUAL_FILES: list[tuple[int, str]] = [
    (1993, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1993/tbdrRDzip170406164107.zip"),
    (1994, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1994/tbdrRDzip170406164226.zip"),
    (1995, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1995/tbdrRDzip170406164247.zip"),
    (1996, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1996/tbdrRDzip170406164515.zip"),
    (1997, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1997/tbdrRDzip170406164540.zip"),
    (1998, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1998/tbdrRDzip170406164556.zip"),
    (1999, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/1999/tbdrRDzip170406164612.zip"),
    (2000, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2000/tbdrRDzip170406164722.zip"),
    (2001, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2001/tbdrRDzip170406164747.zip"),
    (2002, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2002/tbdrRDzip170406164806.zip"),
    (2003, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2003/tbdrRDzip170406164823.zip"),
    (2004, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2004/tbdrRDzip170406164852.zip"),
    (2005, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2005/tbdrRDzip170406164931.zip"),
    (2006, "https://www.bts.gov/sites/bts.dot.gov/files/transborder-raw/2006/tbdrRDzip170406164948.zip"),
]

_TABLE = "transborder_legacy_1993_2006"

_YEAR_BUNDLE_RE = re.compile(r"^\d{2}0112\.zip$", re.I)
_MONTH_ZIP_RE = re.compile(r"^\d{6}\.zip$", re.I)
_1993_MONTH_ZIP_RE = re.compile(r"^\d{4}\.zip$", re.I)

_D_FAMILY_RE = re.compile(
    r"^([dD])(\d{1,2})([aAbB])?([a-zA-Z]{3})(\d{2})([sS])?\.dbf$", re.I
)
_R_FAMILY_RE = re.compile(r"^[rR](\d{1,2})([aAbB])?([a-zA-Z]{3})(\d{2})\.dbf$", re.I)
_X_FAMILY_RE = re.compile(r"^[xX](\d{1,2})([aAbB])?([a-zA-Z]{3})(\d{2})\.dbf$", re.I)
_AV_RE = re.compile(r"^av(\d{1,2})(\d{2})(\d{2})\.dbf$", re.I)

# (direction, partner, emphasis)
FAMILY_META: dict[str, tuple[str, str, str]] = {
    "d03": ("export", "MX", "commodity"),
    "d04": ("export", "CA", "commodity"),
    "d05": ("export", "MX", "geography"),
    "d06": ("export", "CA", "geography"),
    "d5s": ("export", "MX", "geography"),
    "d3a": ("export", "MX", "commodity"),
    "d3b": ("export", "MX", "commodity"),
    "d4a": ("export", "CA", "commodity"),
    "d4b": ("export", "CA", "commodity"),
    "d5a": ("export", "MX", "geography"),
    "d5b": ("export", "MX", "geography"),
    "d6a": ("export", "CA", "geography"),
    "d6b": ("export", "CA", "geography"),
    "d09": ("import", "MX", "commodity"),
    "d10": ("import", "CA", "commodity"),
    "d11": ("import", "MX", "geography"),
    "d12": ("import", "CA", "geography"),
    "av1": ("export", "MX", "commodity"),
    "av2": ("export", "CA", "commodity"),
    "av3": ("export", "MX", "geography"),
    "av4": ("export", "MX", "geography"),
    "av5": ("export", "CA", "geography"),
    "av6": ("export", "CA", "geography"),
    "av7": ("import", "MX", "commodity"),
    "av8": ("import", "CA", "commodity"),
    "av9": ("import", "MX", "geography"),
    "av10": ("import", "MX", "geography"),
    "av11": ("import", "CA", "geography"),
    "av12": ("import", "CA", "geography"),
}


_PACE_SECONDS = 3.0
_last_request_at = 0.0


def _pace() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _PACE_SECONDS:
        time.sleep(_PACE_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def _read_dbf(raw: bytes) -> list[dict[str, str]]:
    """Parse a dBase III table into a list of uppercased-key row dicts.

    Quirks this encodes (see work-notes/.../BUG_FIXES.md):
      * field names are uppercased (2006-era files ship lowercase names)
      * the field-descriptor array ends at the 0x0D terminator -- 2004/2005
        av files pad past it, which would otherwise create a phantom column
      * records start at hlen and every record is preceded by a 1-byte
        deletion flag: 0x2A marks a tombstoned record, which is skipped (the
        bytes are still there, so the flag must be read, not just stepped over)
    """
    if len(raw) < 32:
        return []
    nrec = struct.unpack("<L", raw[4:8])[0]
    hlen = struct.unpack("<H", raw[8:10])[0]
    if hlen > len(raw):
        return []
    pos = 32
    fields: list[tuple[str, str, int]] = []
    while pos < hlen - 1 and raw[pos] != 0x0D:
        name = (
            raw[pos : pos + 11]
            .split(b"\x00")[0]
            .decode("ascii", "replace")
            .strip()
            .upper()
        )
        ftype = chr(raw[pos + 11])
        flen = raw[pos + 16]
        if not name or flen == 0:
            break
        fields.append((name, ftype, flen))
        pos += 32
    if not fields:
        return []
    rows: list[dict[str, str]] = []
    p = hlen
    for _ in range(nrec):
        if p >= len(raw):
            break
        deleted = raw[p] == 0x2A  # dBase tombstone; 0x20 means live
        p += 1
        rec: dict[str, str] = {}
        for name, ftype, flen in fields:
            val = raw[p : p + flen].decode("ascii", "replace")
            p += flen
            rec[name] = val.strip() if ftype in "CNIF" else val.rstrip()
        if not deleted:
            rows.append(rec)
    return rows


def _classify_dbf(basename: str) -> tuple[str, bool, bool] | None:
    """Return (source_table, is_revision, is_supplement) for a data DBF, or
    None if the file is not a TransBorder data table (lookups, etc.)."""
    m = _R_FAMILY_RE.match(basename)
    if m:
        return f"d{m.group(1)}{m.group(2) or ''}".lower(), True, False
    m = _X_FAMILY_RE.match(basename)
    if m:
        return f"d{m.group(1)}{m.group(2) or ''}".lower(), False, True
    m = _D_FAMILY_RE.match(basename)
    if m:
        fam = f"d{m.group(2)}{m.group(3) or ''}"
        if m.group(6):
            fam = f"d{m.group(2)}s"
        return fam.lower(), False, False
    m = _AV_RE.match(basename)
    if m:
        fid = int(m.group(1))
        if 1 <= fid <= 12:
            return f"av{fid}", False, False
    return None


def _decode_statmoyr(code: str) -> tuple[int, int] | None:
    """STATMOYR -> (year, month). 4-char = MMYY (1993-2006; d-files use it
    through 1997, av files through 2006); 6-char = YYYYMM (d-files 1998+).
    The 2-digit year is pinned to the series' century (90+ -> 19xx, else
    20xx). Returns None when unparseable/out of range."""
    code = code.strip()
    if not code.isdigit():
        return None
    if len(code) == 4:
        month = int(code[:2])
        yy = int(code[2:])
        year = 1900 + yy if yy >= 90 else 2000 + yy
    elif len(code) == 6:
        year, month = int(code[:4]), int(code[4:])
    else:
        return None
    if 1 <= month <= 12 and 1993 <= year <= 2006:
        return year, month
    return None


_MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _period_from_filename(basename: str) -> tuple[int, int] | None:
    """Fallback period from the DBF filename suffix when the row's STATMOYR
    is blank. 1996-09 ships D4A/D4B/D6A/D6B (CA exports) with the field left
    empty; the filename (e.g. 'D4ASEP96.DBF') still carries the period."""
    m = _D_FAMILY_RE.match(basename)
    if m:
        abbr, yy = m.group(4).upper(), int(m.group(5))
        month = _MONTH_ABBR.get(abbr)
    else:
        m = _AV_RE.match(basename)
        if m:
            month, yy = int(m.group(2)), int(m.group(3))
        else:
            m = _R_FAMILY_RE.match(basename) or _X_FAMILY_RE.match(basename)
            if m:
                abbr, yy = m.group(3).upper(), int(m.group(4))
                month = _MONTH_ABBR.get(abbr)
            else:
                return None
    if month is None:
        return None
    year = 1900 + yy if yy >= 90 else 2000 + yy
    if 1993 <= year <= 2006:
        return year, month
    return None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value or not value.isdigit():
        return None
    return int(value)


def _text(*values: str | None) -> str | None:
    """First non-blank value, stripped, else None.

    `_read_dbf` returns '' for a present-but-blank column and the dict lookup
    returns None for an absent one; both mean "no value", so they must land in
    the column the same way or `IS NULL` filters miss rows. Mirrors the modern
    path (normalizer.py's `str(...).strip() or None`).
    """
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _build_record(
    row: dict[str, str],
    source_table: str,
    source_file: str,
    statmoyr: str,
    revision: bool,
    supplement: bool,
) -> TransBorderLegacy | None:
    period = _decode_statmoyr(statmoyr) or _period_from_filename(source_file)
    if period is None:
        return None
    year, month = period
    direction, partner, emphasis = FAMILY_META[source_table]
    disag_int = _to_int(row.get("DISAGMOT", ""))
    # Derive the label from the parsed int, not the raw string: DISAGMOT_LABELS
    # is keyed on single characters, so a zero-padded '06' would miss and read
    # as "unknown" while disagg_mode resolved to 6.
    mode = (
        DISAGMOT_LABELS.get(str(disag_int), "unknown") if disag_int is not None else "unknown"
    )
    country = COUNTRY_CODE_MAP.get(row.get("COUNTRY", "").strip())

    # A single out-of-range figure (the ge=0 constraints on value/charges/
    # freight/ship_weight) must not abort the year: the exception would unwind
    # past every buffered period and discard the downloaded annual. Mirrors
    # normalizer.py's per-row catch.
    try:
        return TransBorderLegacy(
            snapshot_date=date(year, month, calendar.monthrange(year, month)[1]),
            year=year,
            month=month,
            direction=direction,
            partner=partner,
            emphasis=emphasis,
            source_table=source_table,
            source_file=source_file,
            statmoyr=statmoyr,
            disagg_mode=disag_int,
            mode=mode,
            country=country,
            value_usd=_to_float(row.get("VALUE") or row.get("VALU")),
            charges_usd=_to_float(row.get("CHARGES")),
            freight_usd=_to_float(row.get("FREIGHT")),
            ship_weight=_to_float(row.get("SHIPWT")),
            aggregate_count=_to_int(row.get("COUNT")),
            us_state=_text(
                row.get("DESTATE"), row.get("ORSTATE"), row.get("EXSTATE"), row.get("USSTATE")
            ),
            mexico_state=_text(row.get("MEXSTATE")),
            canada_province=_text(row.get("PROV")),
            district_port=_text(row.get("DEPE")),
            commodity_code=_text(
                row.get("SCH_B"), row.get("TSUSA"), row.get("HTS"),
                row.get("SCH_B_GRP"), row.get("TSUSA_GRP"),
            ),
            distribution_flag=_text(row.get("DF")),
            ntar=_text(row.get("NTAR")),
            contcode=_text(row.get("CONTCODE")),
            mexregion=_text(row.get("MEXREGION")),
            usregion=_text(row.get("USREGION")),
            distgroup=_text(row.get("DISTGROUP")),
            revision=revision,
            supplement=supplement,
            raw_record=dict(row),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        log.warning(
            "Dropping unbuildable %s row from %s: %s", source_table, source_file, exc
        )
        return None


def _parse_targets(tokens: list[str]) -> set[tuple[int, int]]:
    """Accept bare years ('1993'), inclusive year ranges ('1993-1996'), and
    single months ('2005-01'). Empty means all months of all annuals."""
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


def _month_partition(config: PipelineConfig, year: int, month: int) -> Path:
    return (
        Path(config.output_dir)
        / "freight"
        / _TABLE
        / f"year={year}"
        / f"month={month:02d}"
    )


def _basename(member: str) -> str:
    """Zip member name without its directory prefix."""
    return member.rsplit("/", 1)[-1]


class _WritePlan(NamedTuple):
    write: list[tuple[int, int]]
    present: list[tuple[int, int]]
    out_of_scope: list[tuple[int, int]]


def _plan_writes(
    config: PipelineConfig,
    periods: Iterable[tuple[int, int]],
    missing: set[tuple[int, int]],
) -> _WritePlan:
    """Split buffered periods into write / already-present / out-of-scope.

    Out-of-scope means a period this annual is not responsible for -- e.g.
    late-reported Dec-1994 rows riding along in the 1995 zip. Those are not
    written: day partitions overwrite rather than merge, so a partial write
    would either clobber the real 1994 partition or (if 1994 has not run yet)
    pre-empt it. They are returned so the run can report the drop instead of
    swallowing it.
    """
    plan = _WritePlan([], [], [])
    for period in sorted(periods):
        if period not in missing:
            plan.out_of_scope.append(period)
        elif _month_partition(config, *period).is_dir():
            plan.present.append(period)
        else:
            plan.write.append(period)
    return plan


def _mark_empty_months(
    config: PipelineConfig,
    missing: set[tuple[int, int]],
    written: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Create empty partition dirs for target months the annual has no rows for.

    Without this the run never converges: the 1993 series starts in April, so
    (1993, 1..3) can never produce a partition, `missing` is never empty, and
    the annual is re-downloaded and fully re-parsed on every invocation. The
    same trap fires for any month whose rows are all dropped as superseded --
    `write_transborder_legacy` returns 0 without creating a directory. An
    empty `year=/month=` dir records "we looked here and there was nothing".
    """
    marked = []
    for year, month in sorted(missing - written):
        _month_partition(config, year, month).mkdir(parents=True, exist_ok=True)
        marked.append((year, month))
    return marked


def _iter_month_zips(outer: zipfile.ZipFile, year: int):
    """Yield (zip_name, ZipFile) for each monthly bundle of an annual.

    1993 stores `93MM.zip` directly in the outer zip. 1994+ stores a
    `YY0112.zip` year bundle containing `YYYYMM.zip` month zips; the junk
    `1701.zip` bundled in 2006 is skipped because it is not `??0112.zip`.

    Members are matched on their basename, not the full archive path: the DBF
    loop already strips directories off members, so archives do nest, and an
    anchored full-name match would yield nothing and report the year as zero
    rows without raising."""
    if year == 1993:
        for name in outer.namelist():
            if _1993_MONTH_ZIP_RE.match(_basename(name)):
                yield name, zipfile.ZipFile(io.BytesIO(outer.read(name)))
        return
    for name in outer.namelist():
        if _YEAR_BUNDLE_RE.match(_basename(name)):
            bundle = zipfile.ZipFile(io.BytesIO(outer.read(name)))
            for mn in bundle.namelist():
                if _MONTH_ZIP_RE.match(_basename(mn)):
                    yield mn, zipfile.ZipFile(io.BytesIO(bundle.read(mn)))
            return


class _Collected(NamedTuple):
    """Result of the read pass over one annual zip."""

    rows: dict[tuple[int, int], list[tuple[str, str, bool, bool, dict[str, str]]]]
    revised: set[tuple[str, tuple[int, int]]]
    unrecognized: list[str]
    total_rows: int
    read_failures: int


def _collect_rows(outer: zipfile.ZipFile, year: int) -> _Collected:
    """Read every data DBF in an annual zip, bucketing rows by their period.

    Each row is bucketed on its OWN STATMOYR (falling back to the filename
    suffix), not on the file's first row. Files are not period-pure -- a
    Feb-95 table can carry a stray Jan-95 row -- and a batch that mixes
    periods writes a lone record into the other month's day-partition, which
    `_write_table` overwrites rather than merges (storage.py). Bucketing per
    row keeps every batch single-period, so each partition is written exactly
    once from its complete row set.
    """
    buf: dict[tuple[int, int], list[tuple[str, str, bool, bool, dict[str, str]]]] = {}
    revised: set[tuple[str, tuple[int, int]]] = set()
    unrecognized: list[str] = []
    total_rows = 0
    read_failures = 0

    for _month_zip_name, month_zip in _iter_month_zips(outer, year):
        for member in month_zip.namelist():
            base = _basename(member)
            if not base.lower().endswith(".dbf"):
                continue
            classified = _classify_dbf(base)
            if classified is None:
                unrecognized.append(base)
                continue
            source_table, is_revision, is_supplement = classified
            if source_table not in FAMILY_META:
                unrecognized.append(base)
                continue
            try:
                rows = _read_dbf(month_zip.read(member))
            except Exception as exc:  # noqa: BLE001
                print(f"    FAIL read {base}: {exc}", flush=True)
                read_failures += 1
                continue
            if not rows:
                continue
            file_period = _decode_statmoyr(
                rows[0].get("STATMOYR", "").strip()
            ) or _period_from_filename(base)
            if file_period is None:
                statmoyr = rows[0].get("STATMOYR", "").strip()
                unrecognized.append(f"{base} (bad STATMOYR {statmoyr!r})")
                continue
            if is_revision:
                revised.add((source_table, file_period))
            for row in rows:
                period = (
                    _decode_statmoyr(row.get("STATMOYR", "").strip()) or file_period
                )
                buf.setdefault(period, []).append(
                    (source_table, base, is_revision, is_supplement, row)
                )
            total_rows += len(rows)

    return _Collected(buf, revised, unrecognized, total_rows, read_failures)


def main() -> None:
    targets = _parse_targets(sys.argv[1:])
    pipeline = FreightPipeline()
    config: PipelineConfig = pipeline.config

    written_total = 0
    skipped = 0
    failed = 0
    tmp_root = Path(tempfile.mkdtemp(prefix="tbdr_legacy_"))
    try:
        for year, url in ANNUAL_FILES:
            year_targets = {
                (year, m) for m in range(1, 13) if not targets or (year, m) in targets
            }
            if not year_targets:
                continue
            missing = {
                (year, m)
                for (year, m) in year_targets
                if not _month_partition(config, year, m).is_dir()
            }
            if not missing:
                print(f"  skip {year}: all target months present", flush=True)
                skipped += len(year_targets)
                continue
            print(f"  download {year}: {url}", flush=True)
            t0 = time.monotonic()
            cache = tmp_root / f"{year}.zip"
            try:
                _pace()
                with requests.get(url, timeout=1800, headers=_UA, stream=True) as resp:
                    resp.raise_for_status()
                    with open(cache, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1 << 20):
                            f.write(chunk)
            except Exception as exc:  # noqa: BLE001 -- report and continue
                print(f"  FAIL download {year}: {exc}", flush=True)
                failed += len(missing)
                continue
            print(
                f"    downloaded {cache.stat().st_size / 1e6:.0f}MB "
                f"({time.monotonic() - t0:.0f}s)",
                flush=True,
            )

            # ---- single pass: read all data DBFs, buffer raw rows ----------
            with zipfile.ZipFile(cache) as outer:
                collected = _collect_rows(outer, year)
            buf = collected.rows
            revised = collected.revised
            unrecognized = collected.unrecognized
            total_rows = collected.total_rows
            failed += collected.read_failures

            print(
                f"    read {total_rows} rows across {len(buf)} periods; "
                f"revisions supersede {len(revised)} (table, statmoyr) groups",
                flush=True,
            )
            if unrecognized:
                print(f"    skipped {len(unrecognized)} non-data members", flush=True)

            # ---- write per period, dropping superseded d-rows ---------------
            plan = _plan_writes(config, buf, missing)
            skipped += len(plan.present)
            if plan.out_of_scope:
                dropped_rows = sum(len(buf[p]) for p in plan.out_of_scope)
                print(
                    f"    dropped {dropped_rows} rows for "
                    f"{len(plan.out_of_scope)} periods outside this annual "
                    f"({', '.join(f'{y}-{m:02d}' for y, m in plan.out_of_scope)})",
                    flush=True,
                )

            wrote_months: set[tuple[int, int]] = set()
            for (fyear, fmonth) in plan.write:
                records = []
                dropped = 0
                invalid = 0
                for source_table, base, is_revision, is_supplement, row in buf[(fyear, fmonth)]:
                    statmoyr = row.get("STATMOYR", "").strip()
                    row_period = _decode_statmoyr(statmoyr) or _period_from_filename(base)
                    if (
                        not is_revision
                        and not is_supplement
                        and row_period is not None
                        and (source_table, row_period) in revised
                    ):
                        dropped += 1
                        continue
                    record = _build_record(
                        row, source_table, base, statmoyr, is_revision, is_supplement
                    )
                    if record is not None:
                        records.append(record)
                    else:
                        invalid += 1
                written = pipeline.storage.write_transborder_legacy(
                    TransBorderLegacyBatch(records=records)
                )
                written_total += written
                if written:
                    wrote_months.add((fyear, fmonth))
                print(
                    f"    {fyear}-{fmonth:02d}: {len(records)} records written "
                    f"({dropped} superseded, {invalid} unbuildable dropped) "
                    f"({time.monotonic() - t0:.0f}s)",
                    flush=True,
                )

            # Record the target months this annual genuinely has no rows for,
            # so the next run skips the year instead of re-downloading it.
            marked = _mark_empty_months(config, missing, wrote_months)
            if marked:
                print(
                    f"    marked {len(marked)} empty months "
                    f"({', '.join(f'{y}-{m:02d}' for y, m in marked)})",
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


if __name__ == "__main__":
    main()


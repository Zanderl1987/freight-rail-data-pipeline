# Bug Fix Log

Chronological log of bugs fixed in this repo. Each entry captures the symptom,
root cause, fix, and the exact facts needed to re-debug the issue if it ever
regresses. **Update this file every time you fix a bug** (new entry at the top
under "Latest"). Order: newest first.

---

## Latest

---

## Bug 5 — 2016-08 silently missing (legacy `TransBorder_...csv` member names)

**Date:** 2026-08-13
**Where:** `scripts/backfill_bts_transborder_annual.py`

**Symptom:**
- The full 2007-2017 backfill "succeeded" (exit 0, no CORRUPT lines) but the
  store had **no `year=2016/month=08` partition**.
- The run log contained **no `2016-08:` line at all** — the month was neither
  processed nor reported as corrupt/failed. `skipped` stayed 0.

**Root cause:**
- BTS published August 2016 under **legacy member names** in the 2016 annual
  zip. The folder is abbreviated (`2016/Aug 2016/`) and the monthly files are
  `TransBorder_3_0816 (1).csv`, `TransBorder_3_0816 (2).csv`,
  `TransBorder_3_0816 (3).csv` — not `dotN_0816.csv`. (No other month in
  2007-2017 uses this naming; it is a one-off BTS publish quirk.)
- `_MONTHLY_DOT_RE` only matches `dotN_MMYY.csv`, so the members registered
  **nothing**. The month key `(2016, 8)` never entered the `monthly` registry.
- Because the processing loop iterates `sorted(monthly)` keys, an unregistered
  month is **invisible**: no log line, no CORRUPT entry, no failed count.
  This is the single biggest trap in this script — absence in the registry
  reads as success.
- Bonus trap: the `(N)` suffix does **not** map to the dot number. By header:
  `(1)` = dot3, `(2)` = dot1, `(3)` = dot2.

**Fix:**
- Added `_LEGACY_MONTHLY_DOT_RE` matching `TransBorder_<n>_<MM><YY> (k).csv`.
- Added `_classify_legacy(header: bytes) -> str` which maps the file to
  dot1/dot2/dot3 by column set:
  - `COMMODITY2` + `USASTATE` → `dot2`
  - `COMMODITY2` only → `dot3`
  - otherwise → `dot1`
- In `_register`, legacy members are read (just the first line, split on `\n`)
  to sniff the header, then registered under the sniffed dot key. Unreadable
  members are skipped (`# noqa: S112`).

**Verification:**
- `python scripts/backfill_bts_transborder_annual.py 2016-08` wrote 119,624
  records — consistent with neighbors (2016-07: 117,190; 2016-09: 119,043).
- Audit all months (see "Audit query" below) — 2016 now 12/12.

**If it regresses / debugging again:**
1. List members of the annual zip and look for names that don't match
   `dotN_MMYY.csv`:
   `python -c "import zipfile; z=zipfile.ZipFile(r'<annual.zip>'); [print(n) for n in z.namelist() if not n.startswith('__MACOSX')]"`
2. If any `TransBorder_*_(N).csv` exist, check the header line of each to map
   `(N)` → dot (see header rules above) — do NOT trust the suffix.
3. Any month that fails to register is SILENTLY dropped; you must diff the
   store against the zip to find it (audit query below). A month can also be
   missing because the zip names it differently (e.g. "Aug" vs "August"), but
   note that folder names are irrelevant here — only the basename is parsed.

---

## Bug 4 — 2011 crash + double-counting from unwrapping redundant inner zips

**Date:** 2026-08-13
**Where:** `scripts/backfill_bts_transborder_annual.py`

**Symptom:**
- Run crashed right after `download 2011` with exit 1:
  `zipfile.BadZipFile: Bad CRC-32 for file 'Revised 2011 Public Data/Zip Files/dot1_2011.zip'`
- Months 2011-01..12 were never written (store had no 2011 partition).

**Root cause:**
- The rewrite unwrapped **every** `.zip` member of every annual (`inner =
  zipfile.ZipFile(io.BytesIO(zf.read(info)))`). But the Revised-year layouts
  (2009-2013) ship a `Zip Files/` subfolder of **redundant annual per-view
  bundles** (`dot1_2011.zip`, `dot2_2011.zip`, ...) alongside the flat
  `Data Files/` monthly CSVs.
- Two failures from unwrapping them:
  1. `dot1_2011.zip` inside 2011.zip is **CRC-corrupt in BTS's publish**, so
     `zf.read(info)` raised and killed the whole run.
  2. Even intact, the bundles are byte-identical copies of the monthly files
     already in `Data Files/`, so unwrapping them would register every month
     **twice** (double-counted rows).

**Fix:**
- Only unwrap inner zips when the outer layout exposes **no direct monthly
  files** (`if not monthly:`). That is exactly the 2017 zip-of-zips case
  (`2017/<Month> <year>.zip`, one month bundle per inner zip).
- Inner-zip read failures are caught and recorded in `corrupt` instead of
  crashing.

**Verification:**
- 2011-01..12 all wrote ~100-117K records each; 2011 total 1,332,756 rows.
- No month has suspiciously doubled counts (compare totals per year, they are
  monotonic ~1.25M-1.43M across 2007-2017).

**If it regresses / debugging again:**
1. The traceback will name the failing member (e.g. `dot1_2011.zip`) — it is a
   *redundant annual bundle*, not the monthly grain; do not try to repair it.
2. To tell layouts apart: list members and check whether `dotN_MMYY.csv`
   files exist at the top level of the archive (flat/folder) or only inside
   per-month inner zips (2017).
3. Guard: any inner `.zip` unwrap must be conditional on the outer exposing no
   direct monthlies, or Revised-year months get double-counted.

---

## Bug 3 — Registry dot keys `"1"` vs `"dot1"` → every month wrote 0 records

**Date:** 2026-08-13
**Where:** `scripts/backfill_bts_transborder_annual.py`

**Symptom:**
- Backfill runs "succeeded" but printed `2009-01: 0 records, 0 written` …
  `2016-12: 0 records, 0 written` for **every** month of the flat/folder
  layout years (2009-2016). No partitions created, no error, no CORRUPT
  lines.
- 2017 (zip-of-zips) was unaffected because its members register through a
  different path.

**Root cause:**
- In `_register`, the registry stored members keyed by the bare dot digit:
  `monthly[key]["dot" + ...]` was fine, but in the buggy build the key was the
  plain string from the regex group (`"1"`, `"2"`, `"3"`) while the processing
  loop looked them up as `monthly[(year, month)].get("dot1")` (with the `dot`
  prefix). Every lookup returned `None` → every dot was appended to `corrupt`
  as "missing monthly member" → empty month → `write_transborder_freight`
  returned 0 without creating a partition.
- Also note: `write_transborder_freight([])` writes nothing and does **not**
  create the partition directory, which is why re-runs did not skip these
  months and why the store stayed empty.

**Fix:**
- Made the dot key consistent in both places: `dotkey = f"dot{m.group(1)}"`
  in `_register`, looked up as `.get(dotkey)` for `dot in ("dot1","dot2","dot3")`.

**Verification:**
- After the fix, 2009-2016 all wrote ~100-120K records per month (~1.23M-
  1.42M per year). See audit query below.

**If it regresses / debugging again:**
1. Symptom signature is `N records, N written` where N == 0 for a whole layout
   class, or `written < records`.
2. Check `monthly[key]` keys in `_register` vs the lookups in the processing
   loop — they must be byte-identical strings (`"dot1"` etc.).
3. Grep the script for `get("dot` and `f"dot` and make sure the key format
   matches the `_register` storage key.
4. Remember: a 0-record write is a NO-OP on storage (no partition dir), so a
   broken registry is invisible to "did it skip?" logic — you must inspect
   actual row counts.

---

## Bug 2 — Run not resumable / `missing` was a stale list (skipped months re-processed or already-present months treated as missing)

**Date:** 2026-08-13
**Where:** `scripts/backfill_bts_transborder_annual.py`

**Symptom:**
- A partial run (crashed mid-year) that was re-run did not reliably skip
  completed months; month-set bookkeeping and the "skip" decision disagreed,
  causing re-processing (re-download + re-write) or silent no-ops.

**Root cause:**
- The target-month bookkeeping used a plain list derived once at start and the
  "all target months present" skip check compared against it with a `!=`
  length comparison, so the presence check and the processing decision could
  disagree after an interrupted run.

**Fix:**
- Rewrote month bookkeeping as a **set** of `(year, month)` tuples
  (`missing = {(year, m) for m in range(1, 13) if ... and not
  _month_partition(config, year, m).is_dir()}`) computed per-year at run time.
- A year is skipped iff `missing` is empty; per-month partitions are checked
  against the filesystem (`_month_partition(...).is_dir()`) immediately before
  writing, so re-runs skip whatever already exists and only fill gaps.
- The whole backfill is now idempotent and resumable from any point.

**Verification:**
- Re-running the script after partial failures only processed the missing
  months ("skip 2007: all target months present" etc.) and the store ended up
  132/132 months.

**If it regresses / debugging again:**
- If a re-run re-writes months that already have data, the skip predicate is
  broken — check that `_month_partition(config, year, m).is_dir()` is being
  evaluated against the real store path (Hive layout
  `year=YYYY/month=MM/`). If a re-run skips months that are genuinely empty,
  the opposite — the predicate is returning True too early (or a 0-record
  write left a dir behind, which would indicate `write_transborder_freight`
  created a partition for an empty batch — it must not).

---

## Bug 1 — Original script crashed on BTS's corrupt 2008-03 members and had no recovery path

**Date:** 2026-08-13
**Where:** `scripts/backfill_bts_transborder_annual.py`

**Symptom:**
- First full run died mid-2008: `zlib.error` / `BadZipFile` while reading the
  March 2008 `dot2`/`dot3` members. Entire run aborted, months already written
  to the store were the only survivors.

**Root cause:**
- BTS's published `2008.zip` contains **corrupted March dot2 and dot3 CSV
  members** (bad CRC / zlib stream). The original backfill had no per-member
  error handling, so one bad member killed the whole year.
- The affected rows are NOT lost: every later month's cumulative
  `dotX_ytd_MMYY.csv` view repeats the monthly rows, each carrying its own
  `MONTH`/`YEAR` columns, so a corrupt month can be rebuilt from the next
  month's YTD view by filtering `MONTH == that month`.

**Fix:**
- Per-member `try/except` around reading + normalizing.
- On failure, search later `dotX_ytd_MMYY.csv` views of the same year
  (`fmm > fmonth`, in order) for the same dot; `_filter_month(text, year,
  month)` extracts the corrupt month's rows from the cumulative view. The
  recovered member is logged as `recovered via YTD fallback`.
- If no YTD fallback exists, the member is recorded in `corrupt` (printed at
  end of run) rather than crashing.

**Verification:**
- 2008-03 wrote 105,226 records and the run ended with
  `recovered via YTD fallback: 4 members` (2008-03 dot2/dot3 and 2017-03/07
  dot2/dot3 — the 2017 zip also has corrupt members), `CORRUPT/unrecoverable:
  0`.
- 2008 total = 1,270,240 rows, consistent with the surrounding years.

**If it regresses / debugging again:**
1. Any `BadZipFile`/`zlib.error` on a *monthly* `dotN_MMYY.csv` member is the
   2008-03-style corruption — the member is unreadable but recoverable from
   YTD. Do not attempt to repair the member; rely on the fallback.
2. Verify the YTD views actually repeat monthly rows: read a later
   `dotX_ytd_MMYY.csv` and confirm it contains rows with the corrupt month's
   `MONTH`/`YEAR`. If BTS changes the YTD schema (drops MONTH/YEAR), the
   fallback breaks — the script should then surface the month as `corrupt`
   instead of silently writing nothing.
3. A distinct case is the CRC-corrupt **annual bundle** `dot1_2011.zip` (see
   Bug 4) — that is redundant and should be skipped, not recovered.

---

## Supporting facts & reusable checks

### The 2007-2017 annual zip layouts (BTS)
- **folders:** `{year}/April {year}/dot1_MMYY.csv` — 2007, 2008, 2014-2016
- **flat:** `Revised {year} Public Data/Data Files/dotN_MMYY.csv` — 2009-2013
  (plus a `Zip Files/` subfolder of redundant annual `dotN_{year}.zip` bundles —
  **do not unwrap**, see Bug 4)
- **zips:** `{year}/{Month} {year}.zip` one per month — 2017 (unwrap these)
- **legacy month:** 2016-08 is `2016/Aug 2016/TransBorder_3_0816 (N).csv`
  (see Bug 5)
- All layouts also carry cumulative `dotN_ytd_MMYY.csv` views (repeat monthly
  rows with their own MONTH/YEAR columns — used for Bug 1 recovery).
- 2008 bundles a byte-identical "Copy of January 2008"; dedupe by shortest
  path in `_register`.

### Monthly row-count sanity
| year | rows    | | year | rows    |
|------|---------|-|------|---------|
| 2007 | 1,250,289 | | 2013 | 1,367,247 |
| 2008 | 1,270,240 | | 2014 | 1,403,905 |
| 2009 | 1,233,762 | | 2015 | 1,327,031 |
| 2010 | 1,283,440 | | 2016 | 1,415,850 |
| 2011 | 1,332,756 | | 2017 | 1,432,696 |
| 2012 | 1,359,134 | | | |
Total 2007-2017: **14,676,350** rows. Counts grow ~monotonically with trade;
a year that jumps or collapses indicates a registration/parse bug.

### Audit query (months per year + totals)
```python
import collections, duckdb
c = duckdb.connect()
rows = c.execute(
    "SELECT year, month, count(*) FROM read_parquet("
    "'C:/Users/zande/freight-rail-data-pipeline/data/freight/"
    "transborder_freight/year=*/month=*/day=*/transborder_freight.parquet') "
    "WHERE year BETWEEN 2007 AND 2017 GROUP BY 1, 2"
).fetchall()
by_year = collections.defaultdict(dict)
for y, m, n in rows:
    by_year[y][m] = n
for y in range(2007, 2018):
    months = by_year.get(y, {})
    missing = sorted(set(range(1, 13)) - set(months))
    print(y, f"{len(months)}/12", sum(months.values()), missing or "")
```

### Operational rules (learned the hard way)
- **Never run two backfills concurrently.** They share the store and their
  stdout interleaves; concurrent runs produced false "0 records" readings and
  store races that took real debugging to untangle. One run at a time.
- A month **absent from the `monthly` registry is silently dropped** — no log
  line, no error, no CORRUPT entry. Any new annual layout must be validated by
  diffing the store's (year, month) set against the zip's members, not by
  exit code or log greps.
- `write_transborder_freight([])` writes nothing and does not create the
  partition dir — 0-record writes are no-ops, so they never get skipped on
  re-run (which is correct, but makes empty-registry bugs invisible).

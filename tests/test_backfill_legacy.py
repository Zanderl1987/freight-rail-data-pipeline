"""Regression tests for scripts/backfill_bts_transborder_legacy.py.

Encodes the 1993-2006 DBF-era layout facts verified from the live BTS annual
zips: table-family naming (d03/d3a/d3b/d5s, r* revisions, X* supplements,
av1-av12), the 1993 direct-month vs 1994+ YY0112 year-bundle layouts, the
junk 1701.zip bundled in 2006, STATMOYR MMYY/YYYYMM decoding, and the DBF
header quirks (0x0D terminator, lowercase names, per-record deletion flags).
"""
from __future__ import annotations

import importlib.util
import io
import struct
import sys
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "backfill_bts_transborder_legacy.py"
_spec = importlib.util.spec_from_file_location(
    "backfill_bts_transborder_legacy", _SCRIPT
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["backfill_bts_transborder_legacy"] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


def _dbf(
    fields: list[tuple[str, str, int]], rows: list[list[str]], deleted: list[bool] | None = None
) -> bytes:
    """Build a minimal dBase III table. fields = (name, type, length)."""
    if deleted is None:
        deleted = [False] * len(rows)
    nrec = len(rows)
    hlen = 32 + 32 * len(fields) + 1
    rlen = 1 + sum(fld_len for _, _, fld_len in fields)
    header = bytearray(hlen)
    header[0] = 0x03
    header[4:8] = struct.pack("<L", nrec)
    header[8:10] = struct.pack("<H", hlen)
    header[10:12] = struct.pack("<H", rlen)
    for i, (name, ftype, flen) in enumerate(fields):
        off = 32 + 32 * i
        header[off : off + 11] = name.encode()[:11].ljust(11, b"\x00")
        header[off + 11] = ord(ftype)
        header[off + 16] = flen
    header[hlen - 1] = 0x0D
    out = bytes(header)
    for row, is_deleted in zip(rows, deleted):
        out += bytes([0x2A if is_deleted else 0x20])
        for (_, _, flen), val in zip(fields, row):
            out += val.encode().ljust(flen)[:flen]
    return out


def _make_zip(members: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class TestClassifyDbf:
    def test_1993_1994_plain_families(self) -> None:
        for fn, want in [
            ("d03apr93.dbf", "d03"),
            ("D05MAY93.DBF", "d05"),
            ("D09JUL94.DBF", "d09"),
            ("D12AUG94.DBF", "d12"),
            ("d09JAN05.dbf", "d09"),
        ]:
            got = _mod._classify_dbf(fn)
            assert got is not None and got[0] == want and got[1:] == (False, False)

    def test_1993_state_of_origin_suffix(self) -> None:
        for fn in ("d5apr93s.dbf", "D5MAY93S.DBF", "D5JAN94S.DBF"):
            got = _mod._classify_dbf(fn)
            assert got is not None and got[0] == "d5s"

    def test_a_b_variants(self) -> None:
        for fn, want in [
            ("D3AJUL94.DBF", "d3a"),
            ("D3BJUL94.DBF", "d3b"),
            ("D4AJUL94.DBF", "d4a"),
            ("D6BJUL94.DBF", "d6b"),
            ("d3aJAN03.dbf", "d3a"),
        ]:
            got = _mod._classify_dbf(fn)
            assert got is not None and got[0] == want

    def test_revision_and_supplement_prefixes(self) -> None:
        got = _mod._classify_dbf("r3ajan95.dbf")
        assert got == ("d3a", True, False)
        got = _mod._classify_dbf("r09jul95.dbf")
        assert got == ("d09", True, False)
        got = _mod._classify_dbf("X3AFEB95.DBF")
        assert got == ("d3a", False, True)
        got = _mod._classify_dbf("X5BJAN95.DBF")
        assert got == ("d5b", False, True)

    def test_av_ambiguous_ids(self) -> None:
        for fn, want in [
            ("av10105.dbf", "av1"),
            ("av100105.dbf", "av10"),
            ("av120106.dbf", "av12"),
            ("av70406.dbf", "av7"),
            ("av050405.dbf", "av5"),
        ]:
            got = _mod._classify_dbf(fn)
            assert got is not None and got[0] == want

    def test_lookup_tables_return_none(self) -> None:
        for fn in ("provs.dbf", "uregions.dbf", "candepes.dbf", "readme.bat", "693data.tab"):
            assert _mod._classify_dbf(fn) is None


class TestDecodeStatmoyr:
    def test_mmyy_through_1997(self) -> None:
        assert _mod._decode_statmoyr("0493") == (1993, 4)
        assert _mod._decode_statmoyr("0195") == (1995, 1)
        assert _mod._decode_statmoyr("1297") == (1997, 12)

    def test_mmyy_century_pins_av_era(self) -> None:
        # 2006 av files carry MMYY (e.g. '0106') even though 2006 d-files
        # carry YYYYMM; the 2-digit year must pin to 2000-2006.
        assert _mod._decode_statmoyr("0106") == (2006, 1)
        assert _mod._decode_statmoyr("1006") == (2006, 10)
        assert _mod._decode_statmoyr("1206") == (2006, 12)
        assert _mod._decode_statmoyr("0105") == (2005, 1)

    def test_yyyymm_from_1998(self) -> None:
        assert _mod._decode_statmoyr("199801") == (1998, 1)
        assert _mod._decode_statmoyr("200601") == (2006, 1)

    def test_out_of_range_and_garbage(self) -> None:
        assert _mod._decode_statmoyr("1393") is None  # month 13
        assert _mod._decode_statmoyr("0392") is None  # year 1992 predates series
        assert _mod._decode_statmoyr("200713") is None  # month 13, YYYYMM
        assert _mod._decode_statmoyr("abc") is None
        assert _mod._decode_statmoyr("") is None


class TestPeriodFromFilename:
    def test_d_family_month_abbrev(self) -> None:
        assert _mod._period_from_filename("D4ASEP96.DBF") == (1996, 9)
        assert _mod._period_from_filename("D3AJUL94.DBF") == (1994, 7)
        assert _mod._period_from_filename("d09JAN05.dbf") == (2005, 1)

    def test_av_family_mmyy(self) -> None:
        assert _mod._period_from_filename("av10106.dbf") == (2006, 1)
        assert _mod._period_from_filename("av100105.dbf") == (2005, 1)

    def test_revision_and_supplement(self) -> None:
        assert _mod._period_from_filename("r3ajan95.dbf") == (1995, 1)
        assert _mod._period_from_filename("X3AFEB95.DBF") == (1995, 2)

    def test_lookup_or_garbage_returns_none(self) -> None:
        assert _mod._period_from_filename("provs.dbf") is None
        assert _mod._period_from_filename("readme.bat") is None


class TestReadDbf:
    FIELDS = [("DISAGMOT", "C", 1), ("SCH_B", "C", 2), ("VALUE", "N", 8)]

    def test_reads_records_skipping_deletion_flags(self) -> None:
        raw = _dbf(
            self.FIELDS,
            [["4", "90", "24077"], ["5", "11", "  1234"], ["3", "27", "99999"]],
        )
        rows = _mod._read_dbf(raw)
        assert len(rows) == 3
        assert rows[0] == {"DISAGMOT": "4", "SCH_B": "90", "VALUE": "24077"}
        assert rows[2] == {"DISAGMOT": "3", "SCH_B": "27", "VALUE": "99999"}

    def test_records_flagged_deleted_are_dropped(self) -> None:
        # dBase tombstones a record by setting its leading flag byte to 0x2A
        # instead of removing it. Returning those rows double-counts their
        # VALUE/SHIPWT into the month's totals.
        raw = _dbf(
            self.FIELDS,
            [["4", "90", "24077"], ["5", "11", "  1234"], ["3", "27", "99999"]],
            deleted=[False, True, False],
        )
        rows = _mod._read_dbf(raw)
        assert len(rows) == 2
        assert rows[0] == {"DISAGMOT": "4", "SCH_B": "90", "VALUE": "24077"}
        assert rows[1] == {"DISAGMOT": "3", "SCH_B": "27", "VALUE": "99999"}

    def test_header_terminator_stops_at_terminator_byte(self) -> None:
        # Real 2004/2005 av files pad the header PAST the 0x0D terminator. A
        # reader that consumes to hlen parses the space-padding as a phantom
        # descriptor (name = spaces, type ' ', length 56). The 0x0D stop is
        # what keeps the row clean.
        fields = [("DISAGMOT", "C", 1), ("SCH_B", "C", 2), ("VALUE", "N", 8)]
        term = 32 + 32 * len(fields)  # offset of the 0x0D terminator
        hlen = term + 1 + 40  # terminator byte + 40 pad bytes
        header = bytearray(hlen)
        header[0] = 0x03
        header[4:8] = struct.pack("<L", 1)
        header[8:10] = struct.pack("<H", hlen)
        header[10:12] = struct.pack("<H", 1 + 11)
        for i, (name, ftype, flen) in enumerate(fields):
            off = 32 + 32 * i
            header[off : off + 11] = name.encode()[:11]
            header[off + 11] = ord(ftype)
            header[off + 16] = flen
        header[term] = 0x0D
        header[term + 1 :] = b" " * 40  # padding that reads as phantom descriptor
        body = b"\x20" + b"4".ljust(1) + b"90".ljust(2) + b"24077".ljust(8)
        rows = _mod._read_dbf(bytes(header) + body)
        assert rows == [{"DISAGMOT": "4", "SCH_B": "90", "VALUE": "24077"}]

    def test_lowercase_names_uppercased(self) -> None:
        raw = _dbf(
            [("disagmot", "C", 1), ("sch_b", "C", 2)],
            [["4", "90"]],
        )
        rows = _mod._read_dbf(raw)
        assert rows[0] == {"DISAGMOT": "4", "SCH_B": "90"}

    def test_short_input_returns_empty(self) -> None:
        assert _mod._read_dbf(b"") == []


class TestBuildRecord:
    ROW = {
        "DISAGMOT": "4",
        "SCH_B": "90",
        "ORSTATE": "NY",
        "MEXSTATE": "DF",
        "COUNTRY": "2010",
        "VALUE": "24077",
        "STATMOYR": "200601",
    }

    def test_typed_core_fields(self) -> None:
        rec = _mod._build_record(dict(self.ROW), "d3a", "D3AJAN06.DBF", "200601", False, False)
        assert rec is not None
        assert rec.snapshot_date == date(2006, 1, 31)
        assert rec.year == 2006 and rec.month == 1
        assert rec.direction == "export" and rec.partner == "MX"
        assert rec.emphasis == "commodity"
        assert rec.mode == "mail"
        assert rec.country == "MX"
        assert rec.value_usd == 24077.0
        assert rec.us_state == "NY" and rec.mexico_state == "DF"
        assert rec.commodity_code == "90"
        assert rec.statmoyr == "200601"

    def test_zero_padded_disagmot_still_resolves_the_mode(self) -> None:
        # DISAGMOT_LABELS is keyed on single characters. A DBF that stores the
        # code in a 2-wide field ships '06', which must still read as rail --
        # otherwise the whole table is unfilterable for the mode this pipeline
        # exists to track.
        row = {**self.ROW, "DISAGMOT": "06"}
        rec = _mod._build_record(row, "d3a", "D3AJAN06.DBF", "200601", False, False)
        assert rec is not None
        assert rec.disagg_mode == 6
        assert rec.mode == "rail"

    def test_import_family_mapping(self) -> None:
        row = {**self.ROW, "CONTCODE": "01", "CHARGES": "47", "SHIPWT": "1000"}
        rec = _mod._build_record(row, "d09", "D09JAN06.DBF", "200601", False, False)
        assert rec is not None
        assert rec.direction == "import" and rec.partner == "MX"
        assert rec.contcode == "01" and rec.charges_usd == 47.0
        assert rec.ship_weight == 1000.0

    def test_blank_text_fields_become_none_not_empty_string(self) -> None:
        # _read_dbf strips values, so a present-but-blank column arrives as ''
        # while an absent one arrives as None. Storing both in the same column
        # makes `WHERE mexico_state IS NULL` silently miss half the rows.
        row = {
            **self.ROW,
            "MEXSTATE": "   ",
            "PROV": "",
            "DEPE": "",
            "DF": "",
            "NTAR": "",
            "CONTCODE": "",
            "MEXREGION": "",
            "USREGION": "",
            "DISTGROUP": "",
        }
        rec = _mod._build_record(row, "d3a", "D3AJAN06.DBF", "200601", False, False)
        assert rec is not None
        for field in (
            "mexico_state",
            "canada_province",
            "district_port",
            "distribution_flag",
            "ntar",
            "contcode",
            "mexregion",
            "usregion",
            "distgroup",
        ):
            assert getattr(rec, field) is None, field

    def test_blank_last_alternative_in_a_chain_becomes_none(self) -> None:
        row = {**self.ROW, "USSTATE": "", "SCH_B": ""}
        row.pop("ORSTATE")
        rec = _mod._build_record(row, "d3a", "D3AJAN06.DBF", "200601", False, False)
        assert rec is not None
        assert rec.us_state is None
        assert rec.commodity_code is None

    def test_text_fields_are_stripped(self) -> None:
        row = {**self.ROW, "ORSTATE": " NY ", "MEXSTATE": " DF "}
        rec = _mod._build_record(row, "d3a", "D3AJAN06.DBF", "200601", False, False)
        assert rec is not None
        assert rec.us_state == "NY" and rec.mexico_state == "DF"

    def test_revision_and_supplement_flags(self) -> None:
        rec = _mod._build_record(dict(self.ROW), "d3a", "r3ajan95.dbf", "0195", True, False)
        assert rec is not None and rec.revision and not rec.supplement
        rec = _mod._build_record(dict(self.ROW), "d3a", "X3AFEB95.DBF", "0295", False, True)
        assert rec is not None and not rec.revision and rec.supplement

    def test_valu_fallback_for_2004_av(self) -> None:
        row = {**self.ROW, "VALU": "24077"}
        row.pop("VALUE")
        rec = _mod._build_record(row, "av1", "av10104.dbf", "200401", False, False)
        assert rec is not None and rec.value_usd == 24077.0

    def test_invalid_statmoyr_falls_back_to_filename_period(self) -> None:
        # A blank/bad STATMOYR is recovered from the DBF filename suffix
        # (e.g. 1996-09 CA exports ship the field empty).
        row = {**self.ROW, "STATMOYR": ""}
        rec = _mod._build_record(row, "d4a", "D4ASEP96.DBF", "", False, False)
        assert rec is not None
        assert rec.snapshot_date == date(1996, 9, 30)
        assert rec.year == 1996 and rec.month == 9

    def test_schema_violation_drops_the_row_instead_of_raising(self) -> None:
        # value_usd/charges_usd/freight_usd/ship_weight carry ge=0. One
        # negative figure anywhere in 14 years of DBFs must not propagate a
        # ValidationError out of the write loop -- that discards every buffered
        # period for the year along with the downloaded zip.
        row = {**self.ROW, "VALUE": "-500"}
        assert _mod._build_record(row, "d3a", "D3AJAN06.DBF", "200601", False, False) is None

    def test_unrecoverable_statmoyr_returns_none(self) -> None:
        row = {**self.ROW, "STATMOYR": "garbage"}
        assert (
            _mod._build_record(row, "d3a", "lookup_weird.bin", "garbage", False, False)
            is None
        )


class TestIterMonthZips:
    def test_1993_direct_month_zips(self) -> None:
        month = _make_zip({"d03apr93.dbf": _dbf([("DISAGMOT", "C", 1)], [["4"]])})
        outer = _make_zip({"9304.zip": _read_zip_bytes(month), "readme.txt": b"x"})
        names = sorted(n for n, _ in _mod._iter_month_zips(outer, 1993))
        assert names == ["9304.zip"]

    def test_1994_plus_year_bundle(self) -> None:
        month = _make_zip({"D3AJUL94.DBF": _dbf([("DISAGMOT", "C", 1)], [["4"]])})
        bundle = _make_zip({"199407.zip": _read_zip_bytes(month)})
        outer = _make_zip({"940112.zip": _read_zip_bytes(bundle)})
        names = sorted(n for n, _ in _mod._iter_month_zips(outer, 1994))
        assert names == ["199407.zip"]

    def test_nested_1993_month_zips_are_found(self) -> None:
        # The DBF loop already strips directories off members, so archives are
        # known to nest. A directory prefix on the month zip must not make the
        # whole year read as zero rows with no error raised.
        month = _make_zip({"d03apr93.dbf": _dbf([("DISAGMOT", "C", 1)], [["4"]])})
        outer = _make_zip({"1993/9304.zip": _read_zip_bytes(month)})
        names = sorted(n for n, _ in _mod._iter_month_zips(outer, 1993))
        assert names == ["1993/9304.zip"]

    def test_nested_year_bundle_and_month_zips_are_found(self) -> None:
        month = _make_zip({"D3AJUL94.DBF": _dbf([("DISAGMOT", "C", 1)], [["4"]])})
        bundle = _make_zip({"raw/199407.zip": _read_zip_bytes(month)})
        outer = _make_zip({"1994/940112.zip": _read_zip_bytes(bundle)})
        names = sorted(n for n, _ in _mod._iter_month_zips(outer, 1994))
        assert names == ["raw/199407.zip"]

    def test_2006_junk_1701_zip_is_skipped(self) -> None:
        month = _make_zip({"D3AJAN06.DBF": _dbf([("DISAGMOT", "C", 1)], [["4"]])})
        junk = _make_zip({"dot1_0117.csv": b"x"})
        bundle = _make_zip({"200601.zip": _read_zip_bytes(month)})
        outer = _make_zip(
            {"060112.zip": _read_zip_bytes(bundle), "1701.zip": _read_zip_bytes(junk)}
        )
        names = sorted(n for n, _ in _mod._iter_month_zips(outer, 2006))
        assert names == ["200601.zip"]


class TestCollectRows:
    """The read pass buckets rows by period ahead of the write pass."""

    FIELDS = [("STATMOYR", "C", 6), ("DISAGMOT", "C", 1), ("VALUE", "N", 8)]

    @staticmethod
    def _annual(members: dict[str, bytes], bundle_name: str, month_name: str) -> zipfile.ZipFile:
        month = _make_zip(members)
        bundle = _make_zip({month_name: _read_zip_bytes(month)})
        return _make_zip({bundle_name: _read_zip_bytes(bundle)})

    def test_row_buckets_by_its_own_statmoyr_not_the_files(self) -> None:
        # A Feb-95 DBF carrying a stray Jan-95 row must not put that row in the
        # Feb bucket: the Feb batch would then write a lone record into the
        # January day-partition, overwriting the complete January file.
        dbf = _dbf(self.FIELDS, [["0295", "4", "100"], ["0195", "4", "200"]])
        outer = self._annual({"D3AFEB95.DBF": dbf}, "950112.zip", "199502.zip")

        collected = _mod._collect_rows(outer, 1995)

        assert sorted(collected.rows) == [(1995, 1), (1995, 2)]
        assert len(collected.rows[(1995, 1)]) == 1
        assert len(collected.rows[(1995, 2)]) == 1
        assert collected.total_rows == 2

    def test_blank_statmoyr_falls_back_to_the_filename_period(self) -> None:
        dbf = _dbf(self.FIELDS, [["", "4", "100"], ["", "4", "200"]])
        outer = self._annual({"D4ASEP96.DBF": dbf}, "960112.zip", "199609.zip")

        collected = _mod._collect_rows(outer, 1996)

        assert sorted(collected.rows) == [(1996, 9)]
        assert len(collected.rows[(1996, 9)]) == 2

    def test_revisions_are_recorded_by_period(self) -> None:
        dbf = _dbf(self.FIELDS, [["0195", "4", "100"]])
        outer = self._annual({"r3ajan95.dbf": dbf}, "950112.zip", "199501.zip")

        collected = _mod._collect_rows(outer, 1995)

        assert collected.revised == {("d3a", (1995, 1))}

    def test_lookup_tables_are_reported_unrecognized(self) -> None:
        dbf = _dbf(self.FIELDS, [["0195", "4", "100"]])
        outer = self._annual(
            {"d03jan95.dbf": dbf, "provs.dbf": dbf}, "950112.zip", "199501.zip"
        )

        collected = _mod._collect_rows(outer, 1995)

        assert collected.unrecognized == ["provs.dbf"]
        assert collected.total_rows == 1


class TestPlanWrites:
    """Which buffered periods get written, skipped, or dropped."""

    def test_target_month_without_a_partition_is_written(self, tmp_path) -> None:
        config = SimpleNamespace(output_dir=tmp_path)
        plan = _mod._plan_writes(config, [(1995, 4)], {(1995, 4)})
        assert plan.write == [(1995, 4)]
        assert plan.present == [] and plan.out_of_scope == []

    def test_month_already_on_disk_is_skipped(self, tmp_path) -> None:
        config = SimpleNamespace(output_dir=tmp_path)
        _mod._month_partition(config, 1995, 4).mkdir(parents=True)
        plan = _mod._plan_writes(config, [(1995, 4)], {(1995, 4)})
        assert plan.write == [] and plan.present == [(1995, 4)]

    def test_period_outside_this_annual_is_reported_not_silently_dropped(
        self, tmp_path
    ) -> None:
        # Late-reported Dec-1994 rows can appear in the 1995 annual. They are
        # NOT written -- day partitions overwrite, so a partial write here
        # would clobber (or pre-empt) the real 1994 partition -- but the run
        # must say so rather than dropping them without a word.
        config = SimpleNamespace(output_dir=tmp_path)
        plan = _mod._plan_writes(config, [(1994, 12), (1995, 4)], {(1995, 4)})
        assert plan.write == [(1995, 4)]
        assert plan.out_of_scope == [(1994, 12)]


class TestMarkEmptyMonths:
    """Months an annual genuinely has no rows for must stop being retried."""

    def test_months_with_no_rows_are_marked_so_the_run_converges(self, tmp_path) -> None:
        # The 1993 series starts in April, so (1993, 1..3) can never produce a
        # partition. Without a marker `missing` is never empty and the 250MB
        # annual is re-downloaded and re-parsed on every invocation.
        config = SimpleNamespace(output_dir=tmp_path)
        missing = {(1993, m) for m in range(1, 13)}
        written = {(1993, m) for m in range(4, 13)}

        _mod._mark_empty_months(config, missing, written)

        for month in range(1, 4):
            assert _mod._month_partition(config, 1993, month).is_dir()
        assert not _mod._month_partition(config, 1993, 4).is_dir()

    def test_marked_months_are_no_longer_missing(self, tmp_path) -> None:
        config = SimpleNamespace(output_dir=tmp_path)
        _mod._mark_empty_months(config, {(1993, 1)}, set())
        assert _mod._month_partition(config, 1993, 1).is_dir()


def _read_zip_bytes(z: zipfile.ZipFile) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as nz:
        for info in z.infolist():
            nz.writestr(info.filename, z.read(info.filename))
    return out.getvalue()


def test_parse_targets() -> None:
    targets = _mod._parse_targets(["1993", "1995-1996", "2005-01"])
    expected = set()
    expected.update((1993, m) for m in range(1, 13))
    for y in (1995, 1996):
        expected.update((y, m) for m in range(1, 13))
    expected.add((2005, 1))
    assert targets == expected


def test_parse_targets_empty_means_all() -> None:
    assert _mod._parse_targets([]) == set()


"""Regression tests for scripts/backfill_bts_transborder_annual.py.

These encode the layout quirks and registration bugs documented in
work-notes/freight-rail-data-pipeline/BUG_FIXES.md (Bugs 1-5): the four BTS
annual layouts, the "Copy of January 2008" dedup, the dot1/dot2/dot3 key
format, skipping redundant inner zips, tolerating corrupt inner zips, and
the legacy 2016-08 member naming.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "backfill_bts_transborder_annual.py"
_spec = importlib.util.spec_from_file_location(
    "backfill_bts_transborder_annual", _SCRIPT
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["backfill_bts_transborder_annual"] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

DOT1_HEADER = "TRDTYPE,USASTATE,DEPE,DISAGMOT,MEXSTATE,CANPROV,COUNTRY,VALUE,SHIPWT,FREIGHT_CHARGES,DF,CONTCODE,MONTH,YEAR"  # noqa: E501
DOT2_HEADER = "TRDTYPE,USASTATE,COMMODITY2,DISAGMOT,MEXSTATE,CANPROV,COUNTRY,VALUE,SHIPWT,FREIGHT_CHARGES,DF,CONTCODE,MONTH,YEAR"  # noqa: E501
DOT3_HEADER = "TRDTYPE,DEPE,COMMODITY2,DISAGMOT,COUNTRY,VALUE,SHIPWT,FREIGHT_CHARGES,DF,CONTCODE,MONTH,YEAR"  # noqa: E501


def _make_zip(members: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in members.items():
            z.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_folder_layout_registers_monthly_dot_files() -> None:
    z = _make_zip(
        {
            "2008/March 2008/dot1_0308.csv": DOT1_HEADER + "\n",
            "2008/March 2008/dot2_0308.csv": DOT2_HEADER + "\n",
            "2008/March 2008/dot3_0308.csv": DOT3_HEADER + "\n",
        }
    )
    monthly, ytd, corrupt = _mod._build_registry(z)
    assert set(monthly[(2008, 3)]) == {"dot1", "dot2", "dot3"}
    assert monthly[(2008, 3)]["dot1"][0] == "2008/March 2008/dot1_0308.csv"
    assert ytd == {}
    assert corrupt == []


def test_copy_of_january_dedup_prefers_shortest_path() -> None:
    z = _make_zip(
        {
            "2008/January 2008/dot1_0108.csv": DOT1_HEADER + "\n",
            "2008/Copy of January 2008/dot1_0108.csv": DOT1_HEADER + "\n",
        }
    )
    monthly, _, _ = _mod._build_registry(z)
    assert len(monthly[(2008, 1)]) == 1
    assert monthly[(2008, 1)]["dot1"][0] == "2008/January 2008/dot1_0108.csv"


def test_flat_layout_ignores_redundant_annual_bundles() -> None:
    # Revised years ship Data Files CSVs PLUS redundant "Zip Files" annual
    # bundles. Unwrapping the bundles would double-count every month.
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as b:
        b.writestr("dot1_0111.csv", DOT1_HEADER + "\n")
        b.writestr("dot2_0111.csv", DOT2_HEADER + "\n")
        b.writestr("dot3_0111.csv", DOT3_HEADER + "\n")
    z = _make_zip(
        {
            "Revised 2011 Public Data/Data Files/dot1_0111.csv": DOT1_HEADER + "\n",
            "Revised 2011 Public Data/Data Files/dot2_0111.csv": DOT2_HEADER + "\n",
            "Revised 2011 Public Data/Data Files/dot3_0111.csv": DOT3_HEADER + "\n",
            "Revised 2011 Public Data/Zip Files/dot1_2011.zip": bundle.getvalue(),
            "Revised 2011 Public Data/Zip Files/dot2_2011.zip": bundle.getvalue(),
            "Revised 2011 Public Data/Zip Files/dot3_2011.zip": bundle.getvalue(),
            "Revised 2011 Public Data/Zip Files/dot4_2011.zip": bundle.getvalue(),
        }
    )
    monthly, _, corrupt = _mod._build_registry(z)
    assert set(monthly[(2011, 1)]) == {"dot1", "dot2", "dot3"}
    assert monthly[(2011, 1)]["dot1"][0] == (
        "Revised 2011 Public Data/Data Files/dot1_0111.csv"
    )
    assert corrupt == []


def test_zip_of_zips_unwraps_month_bundles() -> None:
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as b:
        b.writestr("dot1_0317.csv", DOT1_HEADER + "\n")
        b.writestr("dot2_0317.csv", DOT2_HEADER + "\n")
        b.writestr("dot3_0317.csv", DOT3_HEADER + "\n")
    z = _make_zip({"2017/March 2017.zip": bundle.getvalue()})
    monthly, _, corrupt = _mod._build_registry(z)
    assert set(monthly[(2017, 3)]) == {"dot1", "dot2", "dot3"}
    assert corrupt == []


def test_corrupt_inner_zip_is_tolerated() -> None:
    z = _make_zip({"2017/March 2017.zip": b"this is not a zip archive"})
    monthly, _, corrupt = _mod._build_registry(z)
    assert monthly == {}
    assert corrupt and corrupt[0][3].startswith("inner zip unreadable")


def test_legacy_2016_aug_mapping_uses_header_not_suffix() -> None:
    # BTS published 2016-08 as TransBorder_3_0816 (N).csv where the (N)
    # suffix does NOT match the dot number: (1)=dot3, (2)=dot1, (3)=dot2.
    z = _make_zip(
        {
            "2016/Aug 2016/TransBorder_3_0816 (1).csv": DOT3_HEADER + "\n",
            "2016/Aug 2016/TransBorder_3_0816 (2).csv": DOT1_HEADER + "\n",
            "2016/Aug 2016/TransBorder_3_0816 (3).csv": DOT2_HEADER + "\n",
        }
    )
    monthly, _, corrupt = _mod._build_registry(z)
    assert set(monthly[(2016, 8)]) == {"dot1", "dot2", "dot3"}
    assert monthly[(2016, 8)]["dot1"][0] == "2016/Aug 2016/TransBorder_3_0816 (2).csv"
    assert monthly[(2016, 8)]["dot2"][0] == "2016/Aug 2016/TransBorder_3_0816 (3).csv"
    assert monthly[(2016, 8)]["dot3"][0] == "2016/Aug 2016/TransBorder_3_0816 (1).csv"
    assert corrupt == []


def test_registry_keys_use_dot_prefix_not_bare_digit() -> None:
    # Bug 3 regression: registry keys must be "dot1"/"dot2"/"dot3", not the
    # bare "1"/"2"/"3" that made every month write 0 records.
    z = _make_zip(
        {
            "2009/Data Files/dot1_0109.csv": DOT1_HEADER + "\n",
            "2009/Data Files/dot2_0109.csv": DOT2_HEADER + "\n",
            "2009/Data Files/dot3_0109.csv": DOT3_HEADER + "\n",
        }
    )
    monthly, _, _ = _mod._build_registry(z)
    assert set(monthly[(2009, 1)]) == {"dot1", "dot2", "dot3"}


def test_filter_month_extracts_target_month_from_ytd() -> None:
    text = (
        DOT1_HEADER
        + "\n"
        + "1,AL,9999,1,MX,BC,CA,100,10,5,X,11,01,2008\n"
        + "1,AL,9999,1,MX,BC,CA,200,20,10,X,11,02,2008\n"
        + "1,AL,9999,1,MX,BC,CA,300,30,15,X,11,03,2008\n"
    )
    rows = _mod._filter_month(text, 2008, 3)
    assert [r["MONTH"] for r in rows] == ["03"]
    assert rows[0]["VALUE"] == "300"


def test_parse_targets() -> None:
    targets = _mod._parse_targets(["2007", "2009-2011", "2017-05"])
    expected = set()
    expected.update((2007, m) for m in range(1, 13))
    for y in (2009, 2010, 2011):
        expected.update((y, m) for m in range(1, 13))
    expected.add((2017, 5))
    assert targets == expected


def test_parse_targets_empty_means_all() -> None:
    assert _mod._parse_targets([]) == set()

"""Regression tests for scripts/forecast_waybill.py.

The panel deliberately drops thin/noisy sample years (2014 and pre-2000), so
the monthly grid is NOT contiguous. These tests pin the two consequences that
silently corrupt results: lag features must not step across the gap, and the
metric helpers must agree with the sample size they are reported against.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "forecast_waybill.py"
_spec = importlib.util.spec_from_file_location("forecast_waybill", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["forecast_waybill"] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


def _panel_with_gap() -> pd.DataFrame:
    """One group, 2012-2013 then 2015-2016 -- 2014 removed, as load_panel does."""
    dates = [
        d
        for d in pd.date_range("2012-01-01", "2016-12-01", freq="MS")
        if d.year != 2014
    ]
    return pd.DataFrame(
        {
            "stcc2": "01",
            "date": dates,
            # value encodes the month index so a wrong lag is unmistakable
            "tons_mt": [float(i) for i in range(len(dates))],
        }
    )


class TestAddLagsAcrossTheDroppedYear:
    def test_lag_1_does_not_reach_across_the_2014_gap(self) -> None:
        # Positional shift(1) hands Jan-2015 the Dec-2013 value -- a 13-month
        # lag mislabeled as a 1-month lag. There is no such observation, so
        # the feature must be NaN.
        out = _mod.add_lags(_panel_with_gap(), "stcc2", "tons_mt", "date", [1])
        jan15 = out.loc[out["date"] == pd.Timestamp("2015-01-01")].iloc[0]
        assert pd.isna(jan15["lag_1"])

    def test_lag_12_does_not_reach_across_the_2014_gap(self) -> None:
        # Every month of 2015 wants its 2014 counterpart, which was dropped.
        out = _mod.add_lags(_panel_with_gap(), "stcc2", "tons_mt", "date", [12])
        y2015 = out.loc[out["date"].dt.year == 2015]
        assert y2015["lag_12"].isna().all()

    def test_lags_inside_a_contiguous_stretch_are_correct(self) -> None:
        out = _mod.add_lags(_panel_with_gap(), "stcc2", "tons_mt", "date", [1, 12])
        dec13 = out.loc[out["date"] == pd.Timestamp("2013-12-01")].iloc[0]
        assert dec13["lag_1"] == 22.0  # Nov-2013
        assert dec13["lag_12"] == 11.0  # Dec-2012
        assert dec13["month_of_year"] == 12 and dec13["year"] == 2013

    def test_lags_are_per_group(self) -> None:
        one = _panel_with_gap()
        two = _panel_with_gap().assign(stcc2="02", tons_mt=lambda d: d["tons_mt"] + 100)
        out = _mod.add_lags(
            pd.concat([one, two], ignore_index=True), "stcc2", "tons_mt", "date", [1]
        )
        feb12 = out.loc[out["date"] == pd.Timestamp("2012-02-01")].set_index("stcc2")
        assert feb12.loc["01", "lag_1"] == 0.0
        assert feb12.loc["02", "lag_1"] == 100.0


class TestBaselinesAcrossTheDroppedYear:
    def test_seasonal_naive_does_not_reach_across_the_gap(self) -> None:
        out = _mod.baseline_predictions(_panel_with_gap())
        y2015 = out.loc[out["date"].dt.year == 2015]
        assert y2015["seasonal_naive"].isna().all()

    def test_persistence_does_not_reach_across_the_gap(self) -> None:
        out = _mod.baseline_predictions(_panel_with_gap())
        jan15 = out.loc[out["date"] == pd.Timestamp("2015-01-01")].iloc[0]
        assert pd.isna(jan15["persistence"])

    def test_baselines_inside_a_contiguous_stretch_are_correct(self) -> None:
        out = _mod.baseline_predictions(_panel_with_gap())
        dec13 = out.loc[out["date"] == pd.Timestamp("2013-12-01")].iloc[0]
        assert dec13["persistence"] == 22.0
        assert dec13["seasonal_naive"] == 11.0


class TestMetricHelpers:
    def test_mape_and_rmse_ignore_non_finite_predictions(self) -> None:
        # A NaN anywhere in a prediction column currently turns rmse into a
        # silent NaN in the output CSV rather than an error.
        actual = np.array([10.0, 20.0, 30.0])
        pred = np.array([10.0, np.nan, 30.0])
        assert _mod.rmse(actual, pred) == 0.0
        assert _mod.mape(actual, pred) == 0.0

    def test_sample_sizes_are_reported_per_metric(self) -> None:
        # mape drops non-positive actuals, rmse keeps them; one shared `n`
        # overstates the MAPE sample.
        actual = np.array([0.0, 10.0, 20.0])
        pred = np.array([1.0, 10.0, 20.0])
        assert _mod.n_used(actual, pred, positive_only=True) == 2
        assert _mod.n_used(actual, pred, positive_only=False) == 3

    def test_metrics_are_nan_when_nothing_is_comparable(self) -> None:
        actual = np.array([np.nan, np.nan])
        pred = np.array([1.0, 2.0])
        assert np.isnan(_mod.mape(actual, pred))
        assert np.isnan(_mod.rmse(actual, pred))
        assert _mod.n_used(actual, pred, positive_only=False) == 0

    def test_mape_and_rmse_on_clean_input(self) -> None:
        actual = np.array([100.0, 200.0])
        pred = np.array([110.0, 180.0])
        assert _mod.mape(actual, pred) == 10.0
        assert _mod.rmse(actual, pred) == np.sqrt((100 + 400) / 2)


class TestPanelQuery:
    def test_dropped_years_come_from_the_constant(self) -> None:
        # The SQL used to hardcode (1996,1997,1998,1999,2014). Removing a year
        # from DROP_YEARS then left the SQL still filtering it out, the grid
        # filled with all-NaN rows, and the run died on the gaps check with a
        # misleading "unexpected gap" message.
        sql = _mod.panel_query({2014, 2020})
        assert "2014" in sql and "2020" in sql
        assert "1996" not in sql

    def test_query_matches_the_module_constant_by_default(self) -> None:
        sql = _mod.panel_query()
        for year in _mod.DROP_YEARS:
            assert str(year) in sql

"""Waybill freight forecast: can ML beat honest baselines for monthly
rail tons by commodity group?

Data: STB Public Use Waybill Sample (stratified annual sample of rail
shipments, 1996-2024). We aggregate the expansion-weighted population
estimate `expanded_tons` to a MONTHLY panel at the STCC-2 commodity-group
grain (30 groups x 24 years of clean monthly coverage, 2000-2013 + 2015-2024).
There is no 2014 sample at all, so the year=2014 partition holds only
backdated spillover from later samples; pre-2000 is thin. Both are dropped,
which means the monthly grid is NOT contiguous -- see `_lag_by_date`.

Task: for each commodity group, forecast NEXT-MONTH tons using only
REFERENCE-PERIOD-prior information: walk-forward, train on every month
strictly before the target month.

WHAT THIS DOES AND DOES NOT MEASURE (per the project's signal-eval
discipline, whose first rule is to join on the date information became
public, not the date it describes):

  The walk-forward split is correct in REFERENCE time and NOT in KNOWLEDGE
  time. The waybill sample is published annually, well after its reference
  year -- the 2020 sample was released 2022-02-02, ~13 months after the year
  ended (stb.gov/news-communications/latest-news/pr-22-06/). So every feature
  for a target month t (lag_1 .. lag_12, and the entire persistence and
  seasonal-naive baselines) is drawn from months whose figures had not been
  published when month t began; the shortfall runs from roughly 13 to 25
  months depending on where t falls in its year.

  Consequently these MAPE/RMSE figures are NOT reproducible by a forecaster
  operating live, and the improvement-vs-baseline numbers must not be read as
  tradeable or operational skill. What they DO measure is a well-posed
  question in its own right: given a complete monthly history of a commodity
  group, how much structure beyond seasonality and persistence is there in
  the next month? A live-realizable version would need an explicit
  availability lag on every feature (data through reference year Y-2 only),
  which is a materially harder and different experiment.

Framing of the comparison itself:
  - Baselines are the bar, not zero: SEASONAL NAIVE (same month last year)
    and PERSISTENCE (last month). Freight volume is seasonal and persistent;
    a model must beat THOSE to be useful, not just beat a mean. Both
    baselines are subject to the same publication lag as the model, so the
    comparison between them is fair even though the level is not live.
  - Expanding-window walk-forward over 2019-2024 (6 test years, 72 test
    months per group): train on every month strictly before the target.
  - Report MAPE and RMSE per group and overall, plus improvement vs the
    better baseline. A null result (ML ~ baseline) is a valid, reportable
    finding.

Caveat: the waybill is a *sample*; `expanded_tons` is a population estimate
with sampling noise. The 2021+ row-count jump is a sample-frame change, not
a tonnage jump (totals stay comparable). Monthly estimates at group grain
are noisier than annual ones — that works against the model, not for it.

Outputs: scripts/output/forecast_results.csv + printed summary.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "freight" / "waybill_shipments"
OUT_DIR = PROJECT_ROOT / "scripts" / "output"

DROP_YEARS = {1996, 1997, 1998, 1999, 2014}  # thin/noisy samples
TEST_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]  # walk-forward test window
LAGS = [1, 2, 3, 6, 12]
MIN_TRAIN_MONTHS = 60  # 5 years of monthly history before first forecast


def panel_query(drop_years: set[int] | None = None) -> str:
    """The monthly-panel aggregation SQL.

    The dropped years are interpolated from DROP_YEARS rather than written as
    literals: a hardcoded list silently diverges from the constant, leaving the
    grid full of all-NaN rows and killing the run on the gaps check with a
    misleading "unexpected gap" message.
    """
    years = sorted(DROP_YEARS if drop_years is None else drop_years)
    drop_list = ", ".join(str(y) for y in years)
    return f"""
        select substr(stcc, 1, 2)                                  as stcc2,
               year                                               as year,
               cast(substr(accounting_period, 1, 2) as integer)   as month,
               sum(expanded_tons) / 1e6                           as tons_mt
        from w
        where year not in ({drop_list})
          and substr(stcc, 1, 2) not in ('00')
          and cast(substr(accounting_period, 1, 2) as integer) between 1 and 12
        group by 1, 2, 3
        """  # noqa: S608 - module constant, not user input


def load_panel() -> pd.DataFrame:
    """Aggregate expanded tons to a monthly (stcc2, date) panel in Mt."""
    files = [str(p).replace("\\", "/") for p in DATA_DIR.glob("year=*/*.parquet")]
    con = duckdb.connect()
    files_join = ", ".join(f"'{f}'" for f in files)
    con.execute(
        f"create view w as select * from read_parquet([{files_join}])"  # noqa: S608 - local glob, not user input
    )
    df = con.execute(panel_query()).df()
    df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=1))
    # Full monthly grid per group, so gaps surface as NaN (they should not
    # exist in the clean years).
    full_dates = pd.DataFrame({"date": pd.date_range("2000-01-01", "2024-12-31", freq="MS")})
    full_dates = full_dates[~full_dates["date"].dt.year.isin(DROP_YEARS)]
    grid = (
        df[["stcc2"]]
        .drop_duplicates()
        .assign(key=1)
        .merge(
            full_dates.assign(key=1),
            on="key",
        )
        .drop(columns="key")
    )
    panel = grid.merge(df.drop(columns=["year", "month"]), on=["stcc2", "date"], how="left")
    panel = panel.sort_values(["stcc2", "date"]).reset_index(drop=True)
    # Keep only groups with complete monthly coverage in the clean years
    # (a partial-coverage group's gaps would otherwise break the lags).
    complete = (
        panel.dropna(subset=["tons_mt"])
        .groupby("stcc2")["date"]
        .count()
        .eq(panel["date"].drop_duplicates().shape[0])
    )
    panel = panel[panel["stcc2"].isin(complete[complete].index)]
    return panel


def _lag_by_date(
    df: pd.DataFrame,
    group_col: str,
    target_col: str,
    date_col: str,
    lag: int,
    name: str,
) -> pd.DataFrame:
    """Join the value from exactly `lag` calendar months earlier.

    A positional `shift(lag)` assumes contiguous months, but DROP_YEARS
    deliberately removes 2014 from the grid, so the panel jumps 2013-12 ->
    2015-01. Shifting there hands Jan-2015 the Dec-2013 value -- a 13-month
    lag mislabeled as a 1-month lag, and 2013 figures presented as the
    seasonal reference for 2015. Matching on the actual date yields NaN when
    the source month is absent, which is the truth: there is no observation.
    """
    src = df[[group_col, date_col, target_col]].rename(columns={target_col: name})
    src = src.assign(**{date_col: src[date_col] + pd.DateOffset(months=lag)})
    return df.merge(src, on=[group_col, date_col], how="left")


def add_lags(
    df: pd.DataFrame, group_col: str, target_col: str, date_col: str, lags: list[int]
) -> pd.DataFrame:
    """Add lag features per group, keyed on calendar date (see _lag_by_date)."""
    out = df.copy()
    for lag in lags:
        out = _lag_by_date(out, group_col, target_col, date_col, lag, f"lag_{lag}")
    out["month_of_year"] = out[date_col].dt.month
    out["year"] = out[date_col].dt.year
    return out


def baseline_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Seasonal-naive (same month, prior year) and persistence (last month).

    Date-keyed for the same reason as the lags: a positional shift would make
    Dec-2013 the "previous month" of Jan-2015.
    """
    out = _lag_by_date(df, "stcc2", "tons_mt", "date", 12, "seasonal_naive")
    return _lag_by_date(out, "stcc2", "tons_mt", "date", 1, "persistence")


def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    """Expanding-window walk-forward: train on all months < target, predict
    next month. Returns one row per (stcc2, date) forecast with the model
    prediction plus both baselines already present."""
    df = add_lags(df, "stcc2", "tons_mt", "date", LAGS)
    df = baseline_predictions(df)

    feat_cols = [f"lag_{lag}" for lag in LAGS] + ["month_of_year", "year"]
    rows = []
    model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=2,
        random_state=0,
    )

    for stcc2, g in df.groupby("stcc2", sort=True):
        g = g.reset_index(drop=True)
        for i in range(len(g)):
            d = g.iloc[i]
            if d["date"].year not in TEST_YEARS:
                continue
            hist = g.iloc[:i]  # strictly before target month
            if len(hist) < MIN_TRAIN_MONTHS:
                continue
            x_tr = hist[feat_cols]
            y_tr = hist["tons_mt"]
            ok = x_tr.notna().all(axis=1) & y_tr.notna()
            if ok.sum() < MIN_TRAIN_MONTHS:
                continue
            x_tr, y_tr = x_tr.loc[ok].astype(float), y_tr.loc[ok].astype(float)
            x_te = d[feat_cols].to_frame().T.astype(float)
            if x_te.isna().any(axis=1).iloc[0]:
                continue  # lag window incomplete at forecast time
            model.fit(x_tr, y_tr)
            pred = float(model.predict(x_te)[0])
            rows.append(
                {
                    "stcc2": stcc2,
                    "date": d["date"],
                    "actual": float(d["tons_mt"]),
                    "pred_xgb": pred,
                    "baseline_seasonal": float(d["seasonal_naive"]),
                    "baseline_persistence": float(d["persistence"]),
                    "n_train": len(x_tr),
                }
            )
    return pd.DataFrame(rows)


def _comparable(actual: np.ndarray, pred: np.ndarray, positive_only: bool) -> np.ndarray:
    """Rows where both series are finite (and the actual is usable as a MAPE
    denominator). Without the finite check a single NaN prediction turns RMSE
    into a silent NaN in the output CSV instead of an error."""
    ok = np.isfinite(actual) & np.isfinite(pred)
    if positive_only:
        ok &= actual > 0
    return ok


def n_used(actual: np.ndarray, pred: np.ndarray, *, positive_only: bool) -> int:
    """Rows a metric actually scored. MAPE and RMSE score different row sets,
    so they must not be reported under one shared `n`."""
    return int(_comparable(actual, pred, positive_only).sum())


def mape(actual: np.ndarray, pred: np.ndarray) -> float:
    ok = _comparable(actual, pred, positive_only=True)
    if not ok.any():
        return float("nan")
    return float(np.mean(np.abs((actual[ok] - pred[ok]) / actual[ok])) * 100)


def rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    ok = _comparable(actual, pred, positive_only=False)
    if not ok.any():
        return float("nan")
    return float(np.sqrt(np.mean((actual[ok] - pred[ok]) ** 2)))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_panel()
    print(
        f"Panel: {len(panel)} monthly (stcc2, date) rows, "
        f"{panel['stcc2'].nunique()} commodity groups, "
        f"{panel['date'].min().date()} -> {panel['date'].max().date()}"
    )
    gaps = int(panel["tons_mt"].isna().sum())
    if gaps:
        raise RuntimeError(f"unexpected gap in clean years: {gaps} rows")
    fc = walk_forward(panel)
    print(
        f"Forecasts: {len(fc)} test-month predictions across "
        f"{TEST_YEARS[0]}-{TEST_YEARS[-1]} ({fc['stcc2'].nunique()} groups)"
    )

    # ---- overall metrics vs baselines ----
    cols = {
        "pred_xgb": "xgboost",
        "baseline_seasonal": "seasonal-naive",
        "baseline_persistence": "persistence",
    }
    metrics = []
    actual = fc["actual"].to_numpy()
    for col, name in cols.items():
        pred = fc[col].to_numpy()
        metrics.append(
            {
                "model": name,
                "mape_pct": mape(actual, pred),
                "rmse_mt": rmse(actual, pred),
                # MAPE drops non-positive actuals, RMSE keeps them, and both
                # drop non-finite rows -- so they are scored over different
                # row sets and cannot share one `n`.
                "n_mape": n_used(actual, pred, positive_only=True),
                "n_rmse": n_used(actual, pred, positive_only=False),
            }
        )
    mdf = pd.DataFrame(metrics).sort_values("mape_pct")
    print("\n=== Overall (pooled across groups & months) ===")
    print(mdf.round(3).to_string(index=False))

    # Per-group, the honest aggregate: mean over groups (each group's MAPE
    # weighted equally, since groups differ hugely in scale).
    print("\n=== Per-group MAPE, mean over groups ===")
    per_group = (
        fc.groupby("stcc2")
        .apply(
            lambda g: pd.Series(
                {
                    "mape_xgb": mape(g["actual"].to_numpy(), g["pred_xgb"].to_numpy()),
                    "mape_seasonal": mape(
                        g["actual"].to_numpy(), g["baseline_seasonal"].to_numpy()
                    ),
                    "mape_persist": mape(
                        g["actual"].to_numpy(), g["baseline_persistence"].to_numpy()
                    ),
                    "n_forecasts": len(g),
                    "n_mape": n_used(
                        g["actual"].to_numpy(),
                        g["pred_xgb"].to_numpy(),
                        positive_only=True,
                    ),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    print(per_group.round(2).to_string(index=False))

    agg = per_group.drop(columns=["stcc2", "n_forecasts", "n_mape"]).mean()
    print("\n=== Mean per-group MAPE (equal-weight across groups) ===")
    print(agg.round(2).to_string())

    # Beat rate: fraction of (group) forecasts where xgb MAPE < seasonal-naive.
    beat_seasonal = (per_group["mape_xgb"] < per_group["mape_seasonal"]).mean()
    beat_persist = (per_group["mape_xgb"] < per_group["mape_persist"]).mean()
    print(
        f"\nxgboost beats seasonal-naive in {beat_seasonal:.0%} of groups, "
        f"beats persistence in {beat_persist:.0%} of groups"
    )

    # Small-scale groups (tiny tons) inflate pooled MAPE via near-zero
    # denominators; report the pooled view excluding them too.
    big = fc[
        fc["stcc2"].isin(
            fc.groupby("stcc2")["actual"]
            .mean()
            .pipe(
                lambda s: s[s > 1.0].index  # >1 Mt/month mean
            )
        )
    ]
    if len(big):
        print(
            f"\n=== Pooled MAPE on large-volume groups only "
            f"(mean >1 Mt/mo, n_groups={big['stcc2'].nunique()}) ==="
        )
        print(f"xgboost       {mape(big['actual'].to_numpy(), big['pred_xgb'].to_numpy()):.1f}%")
        print(
            f"persistence   "
            f"{mape(big['actual'].to_numpy(), big['baseline_persistence'].to_numpy()):.1f}%"
        )
        print(
            f"seasonal-naive "
            f"{mape(big['actual'].to_numpy(), big['baseline_seasonal'].to_numpy()):.1f}%"
        )

    fc.to_csv(OUT_DIR / "forecast_results.csv", index=False)
    per_group.to_csv(OUT_DIR / "forecast_per_group.csv", index=False)
    mdf.to_csv(OUT_DIR / "forecast_summary.csv", index=False)
    print(f"\nWrote outputs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

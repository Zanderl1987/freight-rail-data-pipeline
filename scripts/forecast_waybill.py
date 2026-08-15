"""Waybill freight forecast: can ML beat honest baselines for monthly
rail tons by commodity group?

Data: STB Public Use Waybill Sample (stratified annual sample of rail
shipments, 1996-2024). We aggregate the expansion-weighted population
estimate `expanded_tons` to a MONTHLY panel at the STCC-2 commodity-group
grain (34 groups x 24 years of clean monthly coverage, 2000-2013 + 2015-2024;
2014 and pre-2000 are thin/noisy and dropped).

Task: for each commodity group, forecast NEXT-MONTH tons using only
information available up to the previous month (strict point-in-time:
walk-forward, no look-ahead).

Honest framing (per the project's signal-eval discipline):
  - Baselines are the bar, not zero: SEASONAL NAIVE (same month last year)
    and PERSISTENCE (last month). Freight volume is seasonal and persistent;
    a model must beat THOSE to be useful, not just beat a mean.
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


def load_panel() -> pd.DataFrame:
    """Aggregate expanded tons to a monthly (stcc2, date) panel in Mt."""
    files = [str(p).replace("\\", "/") for p in DATA_DIR.glob("year=*/*.parquet")]
    con = duckdb.connect()
    files_join = ", ".join(f"'{f}'" for f in files)
    con.execute(
        f"create view w as select * from read_parquet([{files_join}])"  # noqa: S608 - local glob, not user input
    )
    df = con.execute(
        """
        select substr(stcc, 1, 2)                                   as stcc2,
               year                                               as year,
               cast(substr(accounting_period, 1, 2) as integer)   as month,
               sum(expanded_tons) / 1e6                           as tons_mt
        from w
        where year not in (1996, 1997, 1998, 1999, 2014)
          and substr(stcc, 1, 2) not in ('00')
          and cast(substr(accounting_period, 1, 2) as integer) between 1 and 12
        group by 1, 2, 3
        """
    ).df()
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


def add_lags(
    df: pd.DataFrame, group_col: str, target_col: str, date_col: str, lags: list[int]
) -> pd.DataFrame:
    """Add lag features per group. Requires rows sorted by (group, date)."""
    out = df.copy()
    for lag in lags:
        out[f"lag_{lag}"] = out.groupby(group_col)[target_col].shift(lag)
    out["month_of_year"] = out[date_col].dt.month
    out["year"] = out[date_col].dt.year
    return out


def baseline_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Seasonal-naive (same month, prior year) and persistence (last month)."""
    g = df.groupby("stcc2", sort=False)["tons_mt"]
    df["seasonal_naive"] = g.shift(12)
    df["persistence"] = g.shift(1)
    return df


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


def mape(actual: np.ndarray, pred: np.ndarray) -> float:
    mask = actual > 0
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


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
    for col, name in cols.items():
        metrics.append(
            {
                "model": name,
                "mape_pct": mape(fc["actual"].to_numpy(), fc[col].to_numpy()),
                "rmse_mt": rmse(fc["actual"].to_numpy(), fc[col].to_numpy()),
                "n": len(fc),
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
                    "n": len(g),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    print(per_group.round(2).to_string(index=False))

    agg = per_group.drop(columns=["stcc2", "n"]).mean()
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

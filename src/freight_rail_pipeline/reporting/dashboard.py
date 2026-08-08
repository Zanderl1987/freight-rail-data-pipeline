from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Freight Rail Data Pipeline — Dashboard",
    page_icon="🚂",
    layout="wide",
    initial_sidebar_state="expanded",
)

log = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("FREIGHT_PIPELINE_DATA_DIR", "data"))


@st.cache_data(ttl=60)
def load_data(table_name: str) -> pd.DataFrame:
    pattern = str(DATA_DIR / "**" / "**" / "**" / f"{table_name}.parquet")
    files = glob.glob(pattern, recursive=True)
    if not files:
        return pd.DataFrame()
    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception:
            log.exception("Failed to read parquet file %s", f)
            continue
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


@st.cache_data(ttl=300)
def list_available_tables() -> list[str]:
    if not DATA_DIR.exists():
        return []
    tables = set()
    for f in DATA_DIR.rglob("*.parquet"):
        tables.add(f.stem)
    return sorted(tables)


@st.cache_data(ttl=300)
def load_pipeline_runs() -> pd.DataFrame:
    runs_dir = DATA_DIR / "pipeline_runs"
    if not runs_dir.exists():
        return pd.DataFrame()
    records = []
    for f in sorted(runs_dir.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            records.append(data)
        except Exception:
            log.exception("Failed to read pipeline run %s", f)
            continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "started_at" in df.columns:
        df["started_at"] = pd.to_datetime(df["started_at"])
    if "finished_at" in df.columns:
        df["finished_at"] = pd.to_datetime(df["finished_at"])
    return df


def main() -> None:
    st.sidebar.title("🚂 Freight Rail Pipeline")
    st.sidebar.markdown(
        "Data pipeline dashboard for freight rail and ocean container shipping rates."
    )

    available = list_available_tables()
    if not available:
        st.warning("No data found. Run the pipeline first: `freight-pipe run`")
        st.info(f"Expected data directory: `{DATA_DIR.resolve()}`")
        return

    page = st.sidebar.radio(
        "View",
        ["Pipeline Runs", "Rail Carloadings", "Ocean Freight Rates", "Raw Data Explorer"],
    )

    if page == "Pipeline Runs":
        show_pipeline_runs()
    elif page == "Rail Carloadings":
        show_rail_carloadings()
    elif page == "Ocean Freight Rates":
        show_ocean_rates()
    elif page == "Raw Data Explorer":
        show_raw_explorer(available)


def show_pipeline_runs() -> None:
    st.header("📊 Pipeline Run History")
    runs = load_pipeline_runs()
    if runs.empty:
        st.info("No pipeline runs recorded yet.")
        return

    cols = st.columns(4)
    total_runs = len(runs)
    successful = runs["success"].sum() if "success" in runs.columns else 0
    total_records = (
        runs["total_records_written"].sum() if "total_records_written" in runs.columns else 0
    )

    with cols[0]:
        st.metric("Total Runs", total_runs)
    with cols[1]:
        st.metric("Successful", int(successful))
    with cols[2]:
        st.metric("Failed", total_runs - int(successful))
    with cols[3]:
        st.metric("Total Records Written", int(total_records))

    if "started_at" in runs.columns:
        run_chart_data = runs.copy()
        run_chart_data["date"] = run_chart_data["started_at"].dt.date
        daily = (
            run_chart_data.groupby("date")
            .agg(
                runs=("run_id", "count"),
                records=("total_records_written", "sum"),
            )
            .reset_index()
        )
        fig = px.bar(
            daily,
            x="date",
            y="records",
            title="Records Written per Day",
            labels={"records": "Records", "date": "Date"},
            color_discrete_sequence=["#2E86AB"],
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Recent Runs")
    display_cols = [
        "run_id",
        "started_at",
        "success",
        "total_records_written",
        "sources_succeeded",
        "sources_failed",
    ]
    available_cols = [c for c in display_cols if c in runs.columns]
    st.dataframe(runs.sort_values("started_at", ascending=False).head(20)[available_cols])


def show_rail_carloadings() -> None:
    st.header("🚂 Rail Carloadings")
    df = load_data("rail_carloadings")
    if df.empty:
        st.info("No rail carloading data available.")
        return

    with st.expander("Filters", expanded=True):
        cols = st.columns(4)
        with cols[0]:
            if "railroad" in df.columns:
                railroads = sorted(df["railroad"].dropna().unique())
                selected_rr = st.multiselect(
                    "Railroad",
                    railroads,
                    default=railroads[:3] if len(railroads) > 3 else railroads,
                )
        with cols[1]:
            if "carload_type" in df.columns:
                types = sorted(df["carload_type"].dropna().unique())
                selected_types = st.multiselect(
                    "Type",
                    types,
                    default=[t for t in ("Originated",) if t in types],
                )
        with cols[2]:
            if "commodity" in df.columns:
                commodities = sorted(df["commodity"].dropna().unique())
                selected_comm = st.multiselect(
                    "Commodity",
                    commodities,
                    default=commodities[:5] if len(commodities) > 5 else commodities,
                )
        with cols[3]:
            if "snapshot_date" in df.columns:
                min_date = df["snapshot_date"].min()
                max_date = df["snapshot_date"].max()
                date_range = st.date_input("Date Range", [min_date, max_date])

    filtered = df.copy()
    if "railroad" in df.columns and selected_rr:
        filtered = filtered[filtered["railroad"].isin(selected_rr)]
    if "carload_type" in df.columns and selected_types:
        filtered = filtered[filtered["carload_type"].isin(selected_types)]
    if "commodity" in df.columns and selected_comm:
        filtered = filtered[filtered["commodity"].isin(selected_comm)]
    if "snapshot_date" in filtered.columns and len(date_range) == 2:
        filtered = filtered[
            (filtered["snapshot_date"] >= pd.Timestamp(date_range[0]))
            & (filtered["snapshot_date"] <= pd.Timestamp(date_range[1]))
        ]

    if filtered.empty:
        st.info("No data matches the selected filters.")
        return

    col1, col2 = st.columns(2)

    with col1:
        if "railroad" in filtered.columns and "carloads" in filtered.columns:
            by_rr = filtered.groupby("railroad")["carloads"].sum().reset_index()
            fig = px.pie(by_rr, values="carloads", names="railroad", title="Carloads by Railroad")
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        if "commodity" in filtered.columns and "carloads" in filtered.columns:
            by_comm = (
                filtered.groupby("commodity")["carloads"]
                .sum()
                .reset_index()
                .sort_values("carloads", ascending=False)
            )
            fig = px.bar(
                by_comm.head(15), x="commodity", y="carloads", title="Top Commodities by Carloads"
            )
            st.plotly_chart(fig, use_container_width=True)

    if "snapshot_date" in filtered.columns and "carloads" in filtered.columns:
        trend = (
            filtered.groupby("snapshot_date")
            .agg(
                total_carloads=("carloads", "sum"),
                record_count=("carloads", "count"),
            )
            .reset_index()
        )
        fig = px.line(trend, x="snapshot_date", y="total_carloads", title="Carloads Over Time")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader(f"Raw Data ({len(filtered)} rows)")
    st.dataframe(
        filtered.drop(
            columns=[c for c in ["raw_record", "ingested_at"] if c in filtered.columns],
            errors="ignore",
        )
    )


def show_ocean_rates() -> None:
    st.header("🚢 Ocean Freight Rates (FBX)")
    df = load_data("ocean_freight_rates")
    if df.empty:
        st.info("No ocean freight rate data available.")
        return

    with st.expander("Filters", expanded=True):
        cols = st.columns(3)
        with cols[0]:
            if "route_code" in df.columns:
                routes = sorted(df["route_code"].dropna().unique())
                selected_routes = st.multiselect("Route", routes, default=routes)
        with cols[1]:
            if "container_type" in df.columns:
                types = sorted(df["container_type"].dropna().unique())
                selected_types = st.multiselect("Container Type", types, default=types)
        with cols[2]:
            if "snapshot_date" in df.columns:
                min_date = df["snapshot_date"].min()
                max_date = df["snapshot_date"].max()
                date_range = st.date_input("Date Range", [min_date, max_date])

    filtered = df.copy()
    if "route_code" in df.columns and selected_routes:
        filtered = filtered[filtered["route_code"].isin(selected_routes)]
    if "container_type" in df.columns and selected_types:
        filtered = filtered[filtered["container_type"].isin(selected_types)]
    if "snapshot_date" in filtered.columns and len(date_range) == 2:
        filtered = filtered[
            (filtered["snapshot_date"] >= pd.Timestamp(date_range[0]))
            & (filtered["snapshot_date"] <= pd.Timestamp(date_range[1]))
        ]

    if filtered.empty:
        st.info("No data matches the selected filters.")
        return

    col1, col2 = st.columns(2)

    with col1:
        if "route_code" in filtered.columns and "rate_usd" in filtered.columns:
            avg_by_route = filtered.groupby("route_code")["rate_usd"].mean().reset_index()
            fig = px.bar(
                avg_by_route.sort_values("rate_usd", ascending=False),
                x="route_code",
                y="rate_usd",
                title="Average Rate by Route (USD)",
                color="rate_usd",
                color_continuous_scale="Viridis",
            )
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        if "trade_lane" in filtered.columns and "rate_usd" in filtered.columns:
            by_lane = (
                filtered.groupby("trade_lane")["rate_usd"].agg(["mean", "min", "max"]).reset_index()
            )
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Mean", x=by_lane["trade_lane"], y=by_lane["mean"]))
            fig.add_trace(go.Bar(name="Min", x=by_lane["trade_lane"], y=by_lane["min"]))
            fig.add_trace(go.Bar(name="Max", x=by_lane["trade_lane"], y=by_lane["max"]))
            fig.update_layout(title="Rate Statistics by Trade Lane", barmode="group")
            st.plotly_chart(fig, use_container_width=True)

    if (
        "snapshot_date" in filtered.columns
        and "rate_usd" in filtered.columns
        and "route_code" in filtered.columns
    ):
        trend = filtered.groupby(["snapshot_date", "route_code"])["rate_usd"].mean().reset_index()
        fig = px.line(
            trend,
            x="snapshot_date",
            y="rate_usd",
            color="route_code",
            title="Rate Trends by Route",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader(f"Raw Data ({len(filtered)} rows)")
    st.dataframe(
        filtered.drop(
            columns=[c for c in ["raw_record", "ingested_at"] if c in filtered.columns],
            errors="ignore",
        )
    )


def show_raw_explorer(available: list[str]) -> None:
    st.header("🔍 Raw Data Explorer")
    selected_table = st.selectbox("Select Table", available)
    df = load_data(selected_table)
    if df.empty:
        st.info(f"No data in table: {selected_table}")
        return

    st.metric("Rows", len(df))
    st.metric("Columns", len(df.columns))

    st.subheader("Column Info")
    col_info = pd.DataFrame(
        {
            "dtype": df.dtypes,
            "non_null": df.count(),
            "null_pct": (df.isnull().sum() / len(df) * 100).round(1),
            "unique": [
                df[c].nunique() if df[c].dtype in ["object", "category"] else "N/A"
                for c in df.columns
            ],
        }
    )
    st.dataframe(col_info)

    st.subheader("Sample Data")
    st.dataframe(df.head(100))

    st.subheader("Summary Statistics")
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        st.dataframe(df[numeric_cols].describe())
    else:
        st.info("No numeric columns for summary statistics.")


if __name__ == "__main__":
    main()

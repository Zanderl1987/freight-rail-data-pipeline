from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import PipelineConfig
from ..pipeline import FreightPipeline

console = Console()
log = logging.getLogger(__name__)


def _setup_cli_logging(verbose: bool) -> None:
    level = "DEBUG" if verbose else "INFO"
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.version_option(version="0.1.0", prog_name="freight-pipe")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    _setup_cli_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = PipelineConfig.from_env()


@main.command()
@click.option("--sources", "-s", default="", help="Comma-separated source names: usda,fbx")
@click.option("--date", "-d", "snapshot_date", default=None, help="Snapshot date (YYYY-MM-DD)")
@click.option("--output-dir", "-o", default=None, help="Override output directory")
@click.pass_context
def run(ctx: click.Context, sources: str, snapshot_date: Optional[str], output_dir: Optional[str]) -> None:
    pipeline = FreightPipeline(config=ctx.obj["config"])

    source_list: Optional[list[str]] = None
    if sources:
        source_list = [s.strip() for s in sources.split(",") if s.strip()]

    parsed_date: Optional[date] = None
    if snapshot_date:
        parsed_date = date.fromisoformat(snapshot_date)

    console.print(Panel.fit("[bold cyan]Freight Rail Data Pipeline[/]", subtitle="Starting run..."))

    result = pipeline.run(sources=source_list, snapshot_date=parsed_date)

    summary_table = Table(title="Pipeline Run Summary", show_header=True, header_style="bold cyan")
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Value")
    summary_table.add_row("Run ID", result.run_id)
    summary_table.add_row("Duration", f"{result.duration_seconds:.1f}s")
    summary_table.add_row("Total Records", str(result.total_records))
    summary_table.add_row("Sources", ", ".join(result.source_results.keys()) or "none")
    summary_table.add_row("Failed Sources", ", ".join(result.failed_sources) or "none")
    summary_table.add_row("Output Paths", str(len(result.output_paths)))
    summary_table.add_row("Success", "[green]Yes[/]" if result.success else "[red]No[/]")

    console.print(summary_table)

    if result.source_results:
        records_table = Table(title="Records per Source", show_header=True)
        records_table.add_column("Source")
        records_table.add_column("Records Written")
        for src_name, count in result.source_results.items():
            records_table.add_row(src_name, str(count))
        console.print(records_table)

    if result.errors:
        console.print("[bold red]Errors:[/]")
        for err in result.errors:
            console.print(f"  - {err}")

    if result.output_paths:
        console.print("[bold green]Output Files:[/]")
        for path in result.output_paths[:10]:
            console.print(f"  {path}")
        if len(result.output_paths) > 10:
            console.print(f"  ... and {len(result.output_paths) - 10} more")

    sys.exit(0 if result.success else 1)


@main.command()
@click.pass_context
def sources(ctx: click.Context) -> None:
    pipeline = FreightPipeline(config=ctx.obj["config"])
    available = pipeline.list_sources()
    validation = pipeline.validate_sources()

    table = Table(title="Available Sources", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Description")

    for name in sorted(available):
        desc = (available[name] or "").replace("\n", " ")[:80]
        warnings = validation.get(name, [])
        status = "[green]OK[/]" if not warnings else "[yellow]Warnings[/]"
        table.add_row(name, status, desc)

    console.print(table)

    for name, warnings in validation.items():
        if warnings:
            console.print(f"\n[bold yellow]{name} warnings:[/]")
            for w in warnings:
                console.print(f"  - {w}")


@main.command()
@click.argument("table", required=False)
@click.option("--source", "-s", "source_dir", default="data", help="Data directory to inspect")
@click.pass_context
def explore(ctx: click.Context, table: Optional[str], source_dir: str) -> None:
    import pandas as pd

    data_path = Path(source_dir)
    if not data_path.exists():
        console.print(f"[red]Data directory not found: {data_path}[/]")
        sys.exit(1)

    parquet_files = list(data_path.rglob("*.parquet"))
    if not parquet_files:
        console.print("[yellow]No Parquet files found in data directory.[/]")
        return

    if table:
        matching = [f for f in parquet_files if table in str(f)]
        if not matching:
            console.print(f"[yellow]No files matching '{table}'[/]")
            return
        parquet_files = matching

    for pf in parquet_files:
        rel_path = pf.relative_to(data_path)
        try:
            df = pd.read_parquet(pf)
            table_display = Table(title=str(rel_path), show_header=True)
            for col in df.columns:
                table_display.add_column(col[:20])
            for _, row in df.head(5).iterrows():
                table_display.add_row(*[str(v)[:20] for v in row])
            console.print(table_display)
            console.print(f"  [dim]{len(df)} rows × {len(df.columns)} cols[/]\n")
        except Exception as exc:
            console.print(f"[red]Could not read {rel_path}: {exc}[/]")


@main.command()
@click.option("--port", default=8501, help="Streamlit dashboard port")
@click.option("--data-dir", default="data", help="Data directory for the dashboard")
@click.pass_context
def dashboard(ctx: click.Context, port: int, data_dir: str) -> None:
    import subprocess
    import sys as _sys

    dashboard_path = Path(__file__).parent / "dashboard.py"
    if not dashboard_path.exists():
        console.print(f"[red]Dashboard script not found at {dashboard_path}[/]")
        _sys.exit(1)

    env = {
        "FREIGHT_PIPELINE_DATA_DIR": str(Path(data_dir).resolve()),
        "STREAMLIT_SERVER_PORT": str(port),
        "STREAMLIT_SERVER_HEADLESS": "true",
    }

    console.print(f"[green]Launching Streamlit dashboard on port {port}...[/]")
    console.print(f"[dim]Data directory: {Path(data_dir).resolve()}[/]")

    subprocess.run(
        [_sys.executable, "-m", "streamlit", "run", str(dashboard_path)],
        env={**dict(_sys.environ), **env},
    )


if __name__ == "__main__":
    main()

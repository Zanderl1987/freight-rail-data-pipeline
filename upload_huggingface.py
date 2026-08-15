#!/usr/bin/env python3
"""
Upload the freight-rail data pipeline's collected data to HuggingFace as a dataset.

This pipeline has no curated/dedup layer yet (see storage.py) -- raw output lives at
data/freight/<table>/year=YYYY/month=MM/day=DD/<table>.parquet, one file per collection
run. This script concatenates each table's partition files into a single parquet before
uploading, mirroring financial-data-pipeline's upload_huggingface.py pattern.

Usage:
    python upload_huggingface.py [--repo-name freight-rail-data-pipeline] [--private]

Requires HUGGINGFACE_TOKEN or HF_TOKEN env variable (in .env).
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import HfApi, login

from freight_rail_pipeline.config import PipelineConfig

load_dotenv(Path(__file__).parent / ".env")

EXPORT_DIR = Path(__file__).parent / "data" / "hf_export"

README_TEMPLATE = """---
language:
  - en
tags:
  - freight
  - rail
  - shipping
  - logistics
  - supply-chain
  - pipeline
task_categories:
  - other
size_categories:
  - n<1MB
---

# Freight Rail Data Pipeline — Snapshot

Rail carloadings, rail service metrics, and ocean container freight rate data.

## Data Sources

| Table | Rows | Description |
|---|---|---|
{table_rows}

## Usage

```python
from datasets import load_dataset

ds = load_dataset("{repo_id}", trust_remote_code=True)
df = ds["{first_table}"].to_pandas()
```

Or load individual parquet files directly:

```python
import pandas as pd

df = pd.read_parquet("path/to/parquet/file.parquet")
```

## Engineering & data quality

- **140 tests at 76% line coverage**, run on every push/PR via GitHub Actions (CI badge
  on the repo). Source adapters are tested against recorded fixtures — including the AAR
  weekly press-release PDF parser — so a source-format regression shows up in CI instead
  of silently landing as a malformed table.
- **Ingest-time dedup**: reruns against the same partition overwrite the file, but a
  history fetch that runs on multiple ingestion dates would otherwise duplicate every
  record. Rows are deduplicated on record identity (all columns except `ingested_at`),
  keeping the newest ingest.

## Build Info

- **Generated**: {generated_date}
- **Pipeline**: freight-rail-data-pipeline (https://github.com/Zanderl1987/freight-rail-data-pipeline)
- **Tables**: {n_tables}
- **Total Rows**: {n_rows:,}
- **Total Size**: {total_size_mb:.1f} MB

## License

CC BY 4.0 — data sourced from public APIs (USDA AgTransport, Freightos FBX).
"""


def export_tables(output_dir: Path) -> list[tuple[str, int, int]]:
    """Concatenate each table's partition files into one parquet file.

    Returns a list of (table_name, row_count, file_size_bytes).
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in EXPORT_DIR.glob("*.parquet"):
        stale.unlink()

    freight_dir = output_dir / "freight"
    if not freight_dir.exists():
        return []

    stats = []
    for table_dir in sorted(p for p in freight_dir.iterdir() if p.is_dir()):
        table_name = table_dir.name
        files = sorted(table_dir.glob("**/*.parquet"))
        if not files:
            continue

        df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
        if df.empty:
            continue

        # Reruns against the same partition overwrite the file, but a history
        # fetch written under multiple ingestion dates duplicates every record
        # (differing only in ingested_at). Dedup on record identity, keeping the
        # newest ingest timestamp.
        identity_cols = [c for c in df.columns if c != "ingested_at"]
        if identity_cols and "ingested_at" in df.columns:
            df = (
                df.sort_values("ingested_at")
                .drop_duplicates(subset=identity_cols, keep="last")
                .reset_index(drop=True)
            )
        if df.empty:
            continue

        out_path = EXPORT_DIR / f"{table_name}.parquet"
        df.to_parquet(out_path, compression="zstd", index=False)
        stats.append((table_name, len(df), out_path.stat().st_size))

    return stats


def main(
    repo_name: str = "freight-rail-data-pipeline",
    private: bool = False,
    owner: str = "ZanderL1337",
) -> None:
    token = os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HF_TOKEN")
    if not token:
        print("ERROR: Set HUGGINGFACE_TOKEN or HF_TOKEN env variable.")
        return

    config = PipelineConfig.from_env()
    print(f"Exporting tables from {config.output_dir} ...")
    stats = export_tables(config.output_dir)

    if not stats:
        print("No data collected yet -- nothing to upload.")
        return

    total_rows = sum(s[1] for s in stats)
    total_size_mb = sum(s[2] for s in stats) / 1024 / 1024

    print(f"\n{len(stats)} tables, {total_rows:,} rows, {total_size_mb:.2f} MB")
    for name, count, size in stats:
        print(f"  {name}: {count:,} rows ({size / 1024:.1f} KB)")

    login(token=token)
    api = HfApi()

    repo_id = f"{owner}/{repo_name}"
    print(f"\nCreating/updating repo: {repo_id} (private={private})")
    api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)

    # create_repo's `private` only applies when it actually creates the repo --
    # with exist_ok=True it silently no-ops on an existing one, so --private
    # would print "private=True" and still publish to a public repo. Found in
    # the shipping pipeline 2026-08-10, where that sent a real upload out
    # publicly. Enforce the requested visibility BEFORE any data is uploaded.
    current = api.dataset_info(repo_id).private
    if current != private:
        print(f"  repo already existed with private={current}; setting private={private}")
        api.update_repo_settings(repo_id=repo_id, repo_type="dataset", private=private)

    table_rows = "\n".join(f"| {name} | {count:,} | |" for name, count, _ in stats)
    readme = README_TEMPLATE.format(
        repo_id=repo_id,
        n_tables=len(stats),
        n_rows=total_rows,
        total_size_mb=total_size_mb,
        generated_date=datetime.now(UTC).strftime("%Y-%m-%d"),
        first_table=stats[0][0],
        table_rows=table_rows,
    )
    (EXPORT_DIR / "README.md").write_text(readme, encoding="utf-8")

    print(f"\nUploading to {repo_id}...")
    api.upload_folder(
        folder_path=str(EXPORT_DIR),
        repo_id=repo_id,
        repo_type="dataset",
        allow_patterns=["*.parquet", "README.md"],
        commit_message=f"Update snapshot ({len(stats)} tables, {total_rows:,} rows)",
    )

    print(f"\nDone! Dataset: https://huggingface.co/datasets/{repo_id}")
    print(f"  Load with: ds = load_dataset('{repo_id}')")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload freight-rail data to HuggingFace")
    parser.add_argument("--repo-name", default="freight-rail-data-pipeline", help="HF repo name")
    parser.add_argument("--owner", default="ZanderL1337", help="HF user/org that owns the dataset")
    parser.add_argument("--private", action="store_true", help="Make dataset private")
    args = parser.parse_args()
    main(repo_name=args.repo_name, private=args.private, owner=args.owner)

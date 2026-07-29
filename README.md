# Freight Rail Data Pipeline

Multi-source data pipeline that ingests, normalizes, and stores freight rail and
ocean container shipping data. Outputs Parquet and CSV files suitable for
datalake ingestion (Iceberg-compatible schema design).

## Data Sources

| Source | Data | Access | Frequency |
|--------|------|--------|-----------|
| **USDA AgTransport** | Rail carloadings by commodity, rail service metrics (speed/dwell/cars-on-line), rail tariff rates | Public Socrata API (free, no key required) | Weekly |
| **Freightos Baltic Index (FBX)** | Ocean container spot rates on 12 major trade lanes | Public API (free tier) | Daily/weekly |
| **STB Waybill** (planned) | Origin-destination commodity flows by rail | Public Use File (annual CSV) | Annual |
| **BTS Freight Analysis Framework** (planned) | Multimodal freight tonnage/value forecasts | CSV downloads | Periodic |

## Architecture

```
USDA Socrata API ─┐
                   ├──► Normalizer ──► Storage ──► Parquet/CSV
Freightos FBX ────┘       │
                           └──► Reporting
                                ├── CLI (click + rich)
                                └── Streamlit dashboard
```

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install
pip install -e ".[dev]"

# Run the pipeline
freight-pipe run --sources usda,fbx

# Launch the dashboard
freight-pipe dashboard

# See all commands
freight-pipe --help
```

## Project Structure

```
src/freight_rail_pipeline/
├── config.py            # Environment & config management
├── logging_setup.py     # Structured logging configuration
├── pipeline.py          # Main orchestrator
├── storage.py           # Parquet/CSV output writer
├── sources/
│   ├── base.py          # Abstract source interface
│   ├── usda_agtransport.py
│   └── freightos_fbx.py
├── models/
│   ├── schemas.py       # Pydantic data models
│   └── normalizer.py    # Raw-to-canonical transformation
└── reporting/
    ├── cli.py            # Click-based CLI
    └── dashboard.py      # Streamlit app
```

## Design Decisions (pending Infrastructure Plan)

See [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) for a log of architectural decisions
held pending the broader infrastructure plan. These are integration points we
will revisit when wiring into the data lake, Iceberg tables, shipping pipeline,
and financial data pipeline.

## License

MIT

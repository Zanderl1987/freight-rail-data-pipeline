# Freight Rail Data Pipeline

Multi-source data pipeline that ingests, normalizes, and stores freight rail and
ocean container shipping data. Outputs Parquet and CSV files suitable for
datalake ingestion (Iceberg-compatible schema design).

## Data Sources

| Source | Data | Access | Frequency |
|--------|------|--------|-----------|
| **USDA AgTransport** | Rail carloadings by commodity, rail service metrics (speed/dwell/cars-on-line), rail tariff rates | Public Socrata API (free, no key required) | Weekly |
| **Freightos Baltic Index (FBX)** | Ocean container spot rates on 12 major trade lanes | Public API (free tier) | Daily/weekly |
| **BTS Freight Indicators** | Truck spot rates (DAT), rail carloads/intermodal, train speed/dwell, ocean container rates | Public Socrata API (free, no key) | Weekly/monthly |
| **FRA Safety Data** | Rail accidents/incidents (Form 54/57) | Public Socrata API (free, no key) | Monthly |
| **FMCSA Carrier Census** | Motor carrier registrations (universe table) | Public API (free, no key) | ~Annual |
| **Eurostat rail freight** | EU rail goods transported (tonnes + tonne-km, 37 countries) | Public JSON-stat API (free, no key) | Annual (2004+) |
| **FRED (Cass + Truck Tonnage)** | Cass Freight Index (shipments/expenditures), ATA Truck Tonnage Index | Free API (requires `FRED_API_KEY`) | Monthly |
| **STB Waybill PUF** | Origin-destination commodity flows by rail (annual stratified sample, fixed-width) | Public Use File zip (free, no key) | Annual |
| **BTS TransBorder Freight** | US–Canada/Mexico freight value/weight by mode, state, port, commodity | Monthly raw-data zips (free, no key) | Monthly |
| **AAR Weekly Rail Traffic** | US/Canada/Mexico weekly carloads + intermodal by commodity, YoY | Weekly press-release PDF (free, no key) | Weekly (forward-only) |
| **BTS Freight Analysis Framework** (planned) | Multimodal freight tonnage/value forecasts | CSV downloads | Periodic |
| **Census Intl Trade / UN Comtrade / EIA / BLS** (planned) | Trade by port/mode, energy, PPI | Free APIs (key signups TODO) | Monthly |

## Architecture

```
USDA Socrata API ─┐
BTS Freight Inds ─┤
FRA Safety ───────┤
FMCSA Census ─────┼──► Normalizer ──► Storage ──► Parquet/CSV
Eurostat ─────────┤       │
FRED ─────────────┤       └──► Reporting
Freightos FBX ────┤            ├── CLI (click + rich)
STB Waybill ──────┤            └── Streamlit dashboard
BTS TransBorder ──┤
AAR weekly ───────┘
```

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install
pip install -e ".[dev]"

# Run the pipeline
freight-pipe run --sources usda,fbx,bts,fra,fmcsa,eurostat,fred

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
│   ├── freightos_fbx.py
│   ├── bts_freight_indicators.py
│   ├── fra_safety.py
│   ├── fmcsa_carrier_census.py
│   ├── eurostat_rail.py
│   ├── fred.py
│   ├── stb_waybill.py
│   ├── bts_transborder.py
│   └── aar_weekly.py
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

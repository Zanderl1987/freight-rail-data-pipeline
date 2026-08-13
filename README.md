# Freight Rail Data Pipeline

![CI](https://github.com/Zanderl1987/freight-rail-data-pipeline/actions/workflows/test.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Multi-source data pipeline that ingests, normalizes, and stores freight rail and
ocean container shipping data. Outputs Parquet and CSV files suitable for
datalake ingestion (Iceberg-compatible schema design).

Ten public sources, each with its own idea of what a date is, what a region is, and
how often anything updates, land in one normalized store you can actually join across.

## What's in the store

Current local build, 51 million rows across 10 tables:

| Table | Rows | What it is |
|---|---:|---|
| `transborder_freight` | 27,015,354 | US–Canada/Mexico freight value and weight by mode, state, port, commodity |
| `waybill_shipments` | 20,113,513 | Origin-destination rail commodity flows (STB stratified sample) |
| `motor_carrier_census` | 2,085,534 | Motor carrier registrations, the universe table |
| `rail_service_metrics` | 1,553,679 | Speed, dwell, and cars-on-line by railroad |
| `rail_safety_incidents` | 952,160 | FRA accident and incident reports |
| `rail_carloadings` | 199,286 | Carloads by railroad and commodity |
| `freight_indicators` | 25,632 | Truck spot rates, intermodal, ocean container rates |
| `rail_tariff_rates` | 6,802 | Published tariff rates by lane and commodity |
| `rail_eurostat_freight` | 1,329 | EU rail goods transported, 37 countries |
| `aar_weekly_traffic` | 52 | Weekly carloads and intermodal, parsed from press-release PDFs |

The AAR table is forward-only: the source is a weekly PDF press release with no
archive, so history exists only from the point the pipeline started collecting it.
That constraint is the reason the table is small, not a bug.

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

## Testing

```bash
pytest
```

140 tests at 76% line coverage, run on every push and pull request via GitHub Actions.
Source adapters are tested against recorded fixtures, including the AAR press-release
PDF, so a parser regression shows up in CI rather than as a quietly malformed table.

## Design Decisions (pending Infrastructure Plan)

See [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) for a log of architectural decisions
held pending the broader infrastructure plan. These are integration points we
will revisit when wiring into the data lake, Iceberg tables, shipping pipeline,
and financial data pipeline.

## License

MIT — see [LICENSE](LICENSE).

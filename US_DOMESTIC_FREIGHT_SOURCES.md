# US Domestic Freight & Transportation Data Sources — Research Report

Research date: 2026-08-02 (updated 2026-08-09). Scope: free/low-cost sources for
US domestic freight and transportation data (rail, truck, barge, pipeline, air)
to expand the freight rail pipeline beyond the existing USDA AgTransport
(Socrata) and Freightos FBX sources. The 2026-08-09 update adds verified live
endpoint checks for new candidates (Eurostat, FRED, FMC, Census, UN Comtrade,
AIS/maritime).

Verdict key:

- **GO** — public, free, machine-readable, automated access permitted. Build on it.
- **SPIKE** — promising but has an unverified gate (fee, key, auth, member portal, file format). Small probe required before committing.
- **NO-GO** — blocked (member-gated, discontinued, scraping-hostile) unless noted otherwise.

---

## Summary

| Source | Access | Free? | Backfill | Cadence | Verdict |
|---|---|---|---|---|---|
| **STB Rail Service Data** | Bulk download + AgTransport Socrata (`axkm-yjzy`) | Yes | Oct 2014+ | Weekly | **GO** |
| **STB Waybill PUF** | Annual Public Use File (CSV) | Yes (PUF); full sample gated | Years of annual files | Annual | **GO** (PUF only) |
| **BTS Freight Indicators** | data.bts.gov Socrata | Yes | Varies by series (some to ~1990s) | Monthly / weekly | **GO** |
| **BTS TransBorder Freight** | data.bts.gov Socrata | Yes | 1994+ | Monthly | **GO** (bulk/ArcGIS; Socrata table non-tabular) |
| **BTS FAF6** | `faf.ornl.gov/faf6` tabulation tool + bulk | Yes | 2012–2050 (estimates/forecast) | Periodic | **GO** |
| **AAR weekly rail traffic** | Weekly press-release PDFs | Yes (PDF); full history gated | Spot-check needed | Weekly | **SPIKE** |
| **FRA Safety Data** | data.transportation.gov Socrata + OData/ArcGIS APIs | Yes | Decades (accidents to 1975+) | Monthly | **GO** |
| **EIA API v2** | REST + free API key | Yes | 2000s+ by series | Weekly/monthly | **GO** |
| **EIA rail crude movements** | (former series) | — | Discontinued Oct 2025 | — | **NO-GO** |
| **USDA Grain Transportation Report** | Weekly PDF + GTR datasets page | Yes | 2000s+ | Weekly | **GO** |
| **FRED** | REST API, free key | Yes | Decades | Monthly/weekly | **GO** |
| **BLS PPI** | API (key) + FRED tags | Yes | Decades (1947+ for some) | Monthly | **GO** |
| **USACE/WCSC barge data** | ContentDM file downloads | Yes | 2000–2016+ | Annual | **SPIKE** |
| **Census USA Trade Online** | Pivot web app + JSON/CSV export | Mostly (fee tier unverified) | Monthly history | Monthly | **SPIKE** |
| **Census Commodity Flow Survey** | Public use microdata | Yes | Every 5 yrs (2012, 2017, 2022) | Quinquennial | **SPIKE** |
| **FMCSA Carrier Census** | Bulk CSV (`ai.fmcsa.dot.gov`) | Yes | Snapshots (last May 2024) | ~Annual | **SPIKE** |
| **DAT truck spot rates** | Via BTS Freight Indicators | Yes (via BTS) | Varies | Weekly/monthly | **GO** (through BTS) |
| **IANA intermodal report** | Member-gated; press-hosted PDFs only | No | — | Quarterly | **NO-GO** |
| **BTS FLOW** | Confidential participant data | No public data | — | — | **NO-GO** |
| **Eurostat rail freight** | `rail_go_total` JSON-stat API | Yes (no key) | 2004+ annual, 37 geos | Annual (retroactive) | **GO** (built 2026-08-09) |
| **FRED Cass + Truck Tonnage** | REST API (free key) + keyless CSV | Yes | Decades | Monthly | **GO** (built 2026-08-09) |
| **FMC Containerized Freight** | Quarterly XLSX downloads | Yes | ~quarterly history | Quarterly | **GO** (spike) |
| **Census International Trade** | `api.census.gov` REST | Yes (key now required) | Decades | Monthly | **GO** (needs key) |
| **UN Comtrade** | REST API free tier | Yes (key, 500 req/day) | Decades | Monthly | **GO** (needs key) |
| **EIA API v2** | REST + free key | Yes | 2000s+ | Weekly/monthly | **GO** (needs key) |
| **BLS API v2** | REST + free key | Yes (500 req/day) | Decades | Monthly | **GO** (needs key) |
| **ShippingRates.org** | REST, 25 free req/month/IP | Partial | — | — | **NO-GO** (quota) |
| **Maritime AIS (Kystverket/TRAFICOM)** | Open data feeds | Yes | varies | Live | **SPIKE** |
| **Port of LA/LB container stats** | Socrata/catalogs | Yes | varies | Daily/monthly | **SPIKE** |

---

## Per-source detail

### 1. STB — Surface Transportation Board

**Rail Service Data** (weekly Class I service metrics)
- URL: `stb.gov/reports-data/rail-service-data/`
- Data: cars-on-line, speed, dwell, and 8 more categories filed weekly by Class I railroads; collected since Oct 2014 (final rule Mar 2017). Best weekly "health of the rail network" signal available.
- Access: bulk files on stb.gov; also mirrored on USDA AgTransport Socrata at `agtransport.usda.gov/Rail/STB-Railroad-Service-Metrics/axkm-yjzy` — same Socrata domain the pipeline already ingests, so reuse the existing client. STB also runs a beta Open Data Portal (`opendata.stb.gov`, OpenDataSoft/OdS platform, "EP 724 Rail Service Data", API console present) — flagged beta, treat as secondary.
- Backfill: Oct 2014 to present.
- Verdict: **GO**. Add as a Socrata dataset via the existing AgTransport client; cross-check against stb.gov bulk.

**Carload Waybill Sample**
- URL: `stb.gov/reports-data/waybill/`
- Data: annual stratified sample of carloads with origin–destination and commodity — the richest rail OD dataset.
- Access: **Public Use File** (confidentiality-scrubbed, fields collapsed) is public CSV. The full confidential file requires a "confidential user" application and STB approval — do not plan on it.
- Backfill: annual files spanning many years.
- Verdict: **GO** for the PUF only; expect heavy scrubbing (revenue/OD collapsed). Full-sample access is effectively a dead end without an agency data agreement.

### 2. BTS — Bureau of Transportation Statistics

**Freight Indicators**
- URL: `bts.gov/freight-indicators` (data on `data.bts.gov`, Socrata)
- Data: truck spot rates (DAT-sourced), rail carloads/intermodal, train speed/dwell, port truck speeds, PPI trucking, grain barge rates, ocean container rates. One page, many modes — the best multimodal dashboard source.
- Access: public Socrata, no key. Check each indicator's Socrata dataset for backfill depth.
- Verdict: **GO**. This is the free answer to trucking spot rates (DAT data is otherwise a paid product).

**TransBorder Freight**
- URL: `bts.gov/transborder` (full app); Socrata story `kijm-95mr`.
- Data: monthly truck/rail/pipeline/cable freight value and weight across US borders (NAFTA + all partners).
- Access: public Socrata, monthly (R/P1M), accessLevel public. **2026-08-09 probe**: the Socrata "story" `kijm-95mr` is a non-tabular dataset — the Socrata query API returns 403 ("no row or column access to non-tabular tables"). `crem-w557` is a different (unrelated) dataset, not TransBorder. Use the bulk/ArcGIS or the bts.gov app rather than the Socrata query endpoint.
- Backfill: 1994+.
- Verdict: **GO** (via bulk/ArcGIS path), **SPIKE** on exact bulk URL.

**FAF6 — Freight Analysis Framework**
- URL: `bts.gov/faf`; tabulation tool at `faf.ornl.gov/faf6`
- Data: 42 commodity types, all modes, state/regional + metro flows; tons/value.
- Access: bulk/CSV downloads plus the ORNL tabulation tool.
- Caveat: **modeled estimates/forecasts**, not observed data. 2012–2050 horizon (historical back to 2012).
- Verdict: **GO** as a reference/benchmark layer, not a live signal.

**FLOW**
- URL: `bts.gov/flow`
- Access: public-private partnership; participant data is confidential, BTS is data steward, no public raw dataset (per FAQ).
- Verdict: **NO-GO** for raw data. Public dashboards/charts only. Would change only if BTS releases a public tabulation.

### 3. AAR — Association of American Railroads

- URL: `aar.org/news/` weekly rail traffic press releases (verified live for 2026: e.g. `2026-06-17-railtraffic.pdf` on aar.org).
- Data: weekly US rail carloads + intermodal units, commodity breakdown, YoY comparisons.
- Access: weekly releases now carry public downloadable PDF links — an improvement over the older "member-gated chart only" situation. Full historical tabular dataset still sits behind the member portal; not verified whether the PDFs alone give usable historical depth.
- Verdict: **SPIKE**. Probe: pull a year of weekly PDFs and confirm (a) machine-parseable tables, (b) enough history for meaningful backfill. If parse works, it's a weekly GO; if it needs the member portal, it stays a manual/NO-GO.

### 4. FRA — Federal Railroad Administration

- URLs: `dataportal.fra.dot.gov/home/APIs` (GCIS Grade Crossing OData API, ArcGIS REST API) and `safetydata.fra.dot.gov` (Safety Data hub, relaunched Dec 2024).
- Data: rail accidents/incidents (Equipment Accident/Incident Data — Form 54, e.g. `data.transportation.gov` datasets `85tf-25kj`, `nxz3-j3de`), grade crossings, track, rolling stock.
- Access: Socrata on data.transportation.gov (no key) plus FRA's OData/ArcGIS endpoints.
- Backfill: accidents to 1975+, crossings decades.
- Caveat: current auth model of the OData/ArcGIS endpoints not verified this session; Socrata datasets are the safe path.
- Verdict: **GO** via data.transportation.gov Socrata. SPIKE only on the OData/ArcGIS endpoints.

### 5. EIA — Energy Information Administration

- API: `eia.gov/opendata/documentation.php` — API v2, RESTful, free key via email registration (`eia.gov/opendata`), tree hierarchy. Active patch notes through Mar 2026.
- Relevant series: petroleum supply/disposals (diesel, gasoline), which double as a trucking-demand proxy; natural gas pipeline movements.
- ⚠️ **Rail crude movements discontinued**: `eia.gov/petroleum/transportation/` states "We no longer publish U.S. Movements of Crude Oil by Rail" — data runs through Oct 2025 (released Dec 31, 2025), now folded into Petroleum Supply Monthly. This kills the dedicated rail-by-rail energy series.
- Rate limit: exact current daily quota **not verified** this session (historically ~5,000 req/day). Probe at spike.
- Verdict: **GO** for petroleum/diesel/pipeline series. **NO-GO** for rail crude movements specifically; would change only if EIA restarts the rail-by-rail series (unlikely).

### 6. USDA Grain Transportation Report (AMS)

- URLs: `ams.usda.gov/services/transportation-analysis/gtr` (weekly PDF, e.g. `GTR07092026.pdf`); `ams.usda.gov/services/transportation-analysis/gtr-datasets` (data behind the report's tables/figures, sourced from "non-confidential and non-copyrighted" inputs).
- Data: grain barge rates, rail rates/carloads, ocean rates, truck rates for grains.
- Access: PDF weekly + dataset download page; grain datasets/dashboards also on AgTransport Socrata (`agtransport.usda.gov/browse?q=grain`).
- Backfill: 2000s+.
- Verdict: **GO** — same Socrata domain as the existing USDA source; add grain datasets alongside the existing rail carloadings.

### 7. FRED (St. Louis Fed)

- API: `fred.stlouisfed.org/docs/api/api_key.html` — free API key (email signup), REST.
- Relevant series: `TRUCKD11` Truck Tonnage Index (monthly; source BTS/ATA — note the series' copyright caveat in its notes, affects redistribution).
- **2026-08-09 verified live**:
  - Cass Freight Index **Shipments** (`FRGSHPUSM649NCIS`) and **Expenditures** (`FRGEXPUSM649NCIS`) are both available on FRED (note: these are Cass-sourced; index values not $ figures).
  - Keyless CSV download works: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=FRGSHPUSM649NCIS` returns CSV without any key.
  - Pipeline source built and tested (no-key runs collect 0 records + warning; with `FRED_API_KEY` set it pulls the series from `config.fred_series`).
- Rate limit: ~120 req/min per the `fredr` package's documented 429 handling — **not from official FRED docs**; verify at spike.
- Verdict: **GO**. Beware redistribution/copyright for ATA-sourced series.

### 8. BLS — Bureau of Labor Statistics

- API: free, key required; exact current rate limit (historically 500 req/day) **not re-verified**.
- Data: PPI rail/trucking/water freight series (surfaced via FRED tags and BTS Freight Indicators); CPI transportation; employment (OES/QCEW).
- Backfill: decades (some PPI series to 1947+).
- Verdict: **GO**.

### 9. USACE / WCSC — waterway commodity statistics

- URL: `usace.contentdm.oclc.org` — WCUS Manuscript Cargo and Trips Files (Parts 1–4 + Summary; `manu9950` file covers 2000–2016).
- Data: annual barge tons and trips by waterway and commodity.
- Access: file downloads from ContentDM.
- Caveats: backfill appears to stop ~2016; file format (and whether a clean machine-readable tabular export exists) **not verified**.
- Verdict: **SPIKE**. Probe format + current coverage before committing.

### 10. Census

**USA Trade Online**
- URL: `usatradeonline.census.gov` (new version).
- Data: detailed US import/export by HS code, partner, port, mode — a census of trade, incl. surface modes.
- Access: pivot tool with JSON/Excel/CSV export; authorization-code login. Fee tier for full exports **not verified** (historically paid ~$24/yr for the pro tier with a free basic).
- Verdict: **SPIKE** — confirm free-vs-paid for API-style access.

**Commodity Flow Survey**
- URL: `census.gov/programs-surveys/cfs/`
- Data: domestic freight shipments by origin-destination, commodity, mode — the authoritative national freight dataset.
- Access: public-use microdata (PUM) releases; every 5 years (2012, 2017, 2022).
- Verdict: **SPIKE** — quinquennial, so it's a reference layer, not a live feed.

### 11. Eurostat rail freight (international benchmark)

- API: `ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data` — JSON-stat REST, **no key**.
- Dataset: `rail_go_total` (annual rail transport of goods) — **verified live 2026-08-09**: 2004+, 37 geographies, units THS_T (thousand tonnes) and MIO_TKM (million tonne-km), ~1329 observations, row-major order [freq, unit, geo, time].
- Other rail_go_* breakdown datasets (rail_go_typegrp, rail_go_tot, rail_go_pa_type, rail_go_lan, rail_go_mar) return **404** — only the total and passenger datasets are published.
- Built into the pipeline (2026-08-09): `sources/eurostat_rail.py`, model `EurostatRailFreight`, storage table `rail_eurostat_freight`, partitioned per year.
- Verdict: **GO**. Useful as the non-US benchmark layer for rail freight demand.

### 12. FMC Containerized Freight Statistics

- URL: `fmc.gov/what-we-do/containerized-freight-statistics/`; quarterly XLSX (e.g. `https://www.fmc.gov/wp-content/uploads/2026/08/CFS_2025_Data.xlsx`).
- Data: quarterly US import/export container counts by trade lane, all US ports.
- Access: direct XLSX download, no key. Need a library (openpyxl) to parse.
- Verdict: **GO** (spike on xlsx parsing).

### 13. Census International Trade (key-gated)

- API: `api.census.gov` (REST, key now required). 2026-08-09 probe returned "Missing Key" HTML without a key.
- Data: US imports/exports by HS code, port, mode, partner — monthly.
- Verdict: **GO** once a free Census key is registered (TODO signup).

### 14. UN Comtrade (free tier)

- API: `comtradedeveloper.un.org` — free tier needs a key, ~500 req/day.
- Data: international merchandise trade by partner/commodity, monthly/quarterly.
- Verdict: **GO** for a global trade layer (complements Eurostat).

### 15. Maritime AIS (spike)

- Norwegian Kystverket (`kystverket.no`) AIS is open data (NLOD) via TCP socket feed, no registration. Finnish TRAFICOM similarly open. Global Fishing Watch has vessel traffic data behind free registration.
- Utility for this rail pipeline: vessel arrival/port-call signals as a port-congestion proxy.
- Verdict: **SPIKE** — format/volume unknown; low priority vs rail/truck.

### 16. Port of LA / Long Beach container stats (spike)

- data.lacity.org `38a8-tm7u` (Port of LA historical TEU) — **verified**: 36 rows, but stale (data through 2020, attribution Port of LA). data.longbeach.gov Socrata endpoint works but no public container dataset found in a quick probe.
- Verdict: **SPIKE** — port pages/dashboards are the more current path, but tabular backfill is thin.

### 17. Rejected / rate-limited

- **ShippingRates.org**: free tier is 25 requests/month/IP, then HTTP 402 requiring payment. **NO-GO** for any real cadence.
- **Container xChange Insights**: commercial; no free API. **NO-GO**.
- **BTS TransBorder via Socrata query API**: non-tabular 403 (see #2). Bulk path still open.

### 18. Extras worth knowing

- **DAT truck spot rates**: not directly free; the free path is BTS Freight Indicators (see #2). Direct DAT/licensed data is a paid product.
- **IANA intermodal report**: member-gated; only press-hosted PDFs (e.g. Railway Age hosting) are public. **NO-GO** — would change if IANA publishes its own free tabular release.
- **FMCSA carrier registrations**: bulk CSV at `ai.fmcsa.dot.gov/SMS/Tools/Downloads.aspx` (catalog snapshot updated May 2024). A static-ish register of active carriers — useful as a universe table. **SPIKE** on freshness.
- **BTS FLOW**: see #2 — **NO-GO** for raw data.
- **Motley Fool / scraper-only sources**: excluded — no automated access.

---

## Unverified items to pin down at spike/probe time

1. EIA API v2 exact daily quota (2026-08-09: docs no longer quote a daily cap; ~9k req/hr throttle noted).
2. BLS API exact daily quota (500/day registered per docs).
3. FRED 120 req/min figure (third-party source only).
4. FMC XLSX parsing and exact current-quarter file URL pattern.
5. USA Trade Online free vs paid tier for programmatic export.
6. AAR weekly PDFs: parseability + historical depth without member portal.
7. FRA OData/ArcGIS current auth model.
8. USACE/WCSC file format and post-2016 coverage.
9. ATA-truck-tonnage redistribution limits on FRED/FRED terms.
10. BTS TransBorder bulk/ArcGIS exact download URL (Socrata table is non-tabular).
11. UN Comtrade free tier exact daily quota and endpoint shape.

## Suggested build order

1. **BTS Freight Indicators** (Socrata, no key — same client shape as existing USDA source). **DONE**
2. **FRA safety** via data.transportation.gov Socrata. **DONE**
3. **Eurostat rail freight** (`rail_go_total`, no key). **DONE 2026-08-09**
4. **FRED Cass + Truck Tonnage** (key registration, then monthly pull). **DONE 2026-08-09** — needs `FRED_API_KEY`
5. **EIA API** (petroleum/diesel) — key registration, then weekly pull.
6. **BLS PPI** — key registration (500 req/day).
7. **Census International Trade** — key registration.
8. **UN Comtrade** — key registration (free tier).
9. **FMC quarterly XLSX** — parse + schedule quarterly.
10. **STB Rail Service Metrics** via AgTransport Socrata dataset `axkm-yjzy`.
11. **USDA GTR grain datasets** on AgTransport.
12. Spikes: AAR weekly PDFs, USA Trade Online, FMCSA, USACE/WCSC, maritime AIS.

# Design Decisions (Held Pending Infrastructure Plan)

This file logs architectural decisions made during initial build that are
subject to change once the broader infrastructure plan (data lake, Iceberg
tables, shipping pipeline, financial pipeline) is finalized.

---

## DECISION-001: Output Format

**Status:** Provisional — Parquet with Hive-style partitioning

**What we chose:** We output Parquet files with Hive-style partitioning
(`year=YYYY/month=MM/day=DD/`). CSV is also written as a fallback for
quick inspection.

**Why provisional:** The infrastructure plan may specify Iceberg table formats,
partitioning schemes, or catalog integration (e.g., AWS Glue, Nessie,
Hive Metastore) that differ. Our Parquet files can be read directly by
Iceberg via `parquet` or converted with a schema migration step.

---

## DECISION-002: Partitioning Strategy

**Status:** Provisional — Date-based only

**What we chose:** `year/month/day` partitioning on ingestion date.

**Why provisional:** The data lake architecture may require:
- Partitioning by source + date
- Bucketing by commodity or railroad
- Z-order clustering on origin/destination
- Different temporal granularity (hourly, monthly)

---

## DECISION-003: Schema Design

**Status:** Provisional — Flat tables per source type

**What we chose:** Separate normalized tables/schemas for:
- `rail_carloadings`
- `rail_service_metrics`
- `rail_tariff_rates`
- `ocean_freight_rates`

**Why provisional:** The data lake may require:
- A unified star schema or vault-style model
- Surrogate keys for commodity, location, carrier dimensions
- Slowly-changing dimension handling
- Cross-pipeline joins with shipping/financial data

---

## DECISION-004: Storage Location

**Status:** Provisional — Local filesystem

**What we chose:** A local `data/` directory for output.

**Why provisional:** Production will use S3 / ADLS / GCS with proper
partitioning and catalog registration. The current choice is purely
for local development.

---

## DECISION-005: Scheduling

**Status:** Not implemented — manual run only

**What we chose:** No scheduler; invoke via CLI or cron.

**Why provisional:** The infrastructure plan may prescribe Airflow, Dagster,
Prefect, or a managed orchestrator. We will add a sensor/DAG wrapper
once the runner is chosen.

---

## DECISION-006: Credential Management

**Status:** Provisional — Environment variables / `.env` file

**What we chose:** `python-dotenv` loads from `.env`.

**Why provisional:** Production will use a secrets manager (AWS Secrets Manager,
Azure Key Vault, HashiCorp Vault). The `BaseSource` class is designed
with a `get_credential()` hook that can be swapped out.

---

## DECISION-007: Error Handling & Retries

**Status:** Implemented — `tenacity` for retries with exponential backoff

**What we chose:** Retry on transient HTTP failures (5xx, 429) with
jittered exponential backoff. Fail fast on 4xx.

**Why provisional:** The orchestrator layer may add its own retry/dead-letter
queue semantics. Our per-source retry logic is a reasonable default
for standalone runs.

---

## DECISION-008: Monitoring & Alerting

**Status:** Not implemented — logs only

**What we chose:** Structured JSON logging to stdout and rolling files.

**Why provisional:** Production will need metrics emission (CloudWatch,
Datadog, Prometheus), dead-letter queues, and alerting rules. The
logging setup is designed so a metric sink can be added without
changing source code.

---

## DECISION-009: Schema Evolution

**Status:** Not implemented — strict schemas

**What we chose:** Pydantic models validate at write time. Schema changes
require code changes.

**Why provisional:** A production data lake will need schema evolution
policies (backward-compatible additions, versioned schemas, AVRO
schema registry integration).

---

## DECISION-010: Testing Strategy

**Status:** Implemented — unit tests with mocked HTTP, integration tests
tagged with `integration` marker

**What we chose:**
- Unit tests use `responses` library to mock HTTP calls
- Integration tests hit real APIs when `--run-integration` is passed
- Tests are independent of external state

**Why provisional:** The broader pipeline may require contract testing,
schema validation tests, or end-to-end tests in a staging environment.

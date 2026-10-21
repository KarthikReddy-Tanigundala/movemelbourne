# ADR-006: DuckDB + dbt-duckdb as the warehouse, with no dbt packages

- **Status:** Accepted (2026-10-21)

## Context

The workload is analytical SQL over Parquet: tens of millions of realtime rows, a few million
timetable rows. The project must stay free, reproducible from the public dataset by anyone, and
testable in CI without credentials or network.

## Decision

- **DuckDB** single-file warehouse. Bronze is a set of views over the lake's Parquet, rebuilt on
  every run (`movemelbourne.load.bronze`); there is no ingestion copy step.
- **dbt-core + dbt-duckdb** for staging (views), intermediate (tables) and marts (tables;
  `fact_stop_event` incremental with delete+insert on service date and a 2-day lookback).
- **No dbt packages.** The one helper needed (`accepted_range`) is a local generic test, so `dbt
  build` needs no `dbt deps` download and runs offline in CI.
- `config/study.yaml` is the single source of thresholds; `scripts/run_pipeline.py` passes them to
  dbt as `--vars`, so SQL and Python cannot disagree.
- Timezone maths uses DuckDB's ICU extension (bundled) for display bucketing only. Arithmetic stays
  in epoch seconds.

## Consequences

- Full keyless rebuild on the committed sample takes about 13 s (150 dbt nodes: models, seeds,
  tests, unit test). It runs in CI on every PR, and dbt docs deploy from the same build.
- Single-writer DuckDB: the Streamlit app never opens the warehouse; it reads small Parquet exports
  (`scripts/export_gold.py`).
- A move to a cloud warehouse would mean a profile change plus a handful of DuckDB-specific
  functions (`arg_max`, `asof join`, `quantile_cont`), which are listed in ARCHITECTURE.md.

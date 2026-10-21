# Changelog

## [Unreleased]

### Added
- GTFS-Realtime collector: runtime auth negotiation, per-mode rate limiting, retries, key
  redaction, fixed-schema flattening with `extra_json`, 29-minute poll loop, one Hugging Face
  commit per run, coverage log. GitHub Actions workflow plus a Windows scheduled-task "bridge".
- Weekly versioned GTFS Schedule snapshot (`feed_version = date_sha8`), nested-zip handling.
- DST-correct service calendar (`ref_epoch`, GTFS noon-minus-12h rule) and schedule validation.
- Local lake mirroring the dataset layout; DuckDB bronze views.
- dbt-duckdb star schema: versioned timetable join, observed-arrival inference (last prediction
  and vehicle positions), collection sessions and gaps, proxy OTP, reliability, delay
  distribution, segment delay, tram headways, disruption impact, coverage report; 150 dbt nodes.
- Trip-clustered bootstrap CIs for route ranking.
- Synthetic realtime sample over a real timetable slice, so CI and the Quickstart need no API key.
- Streamlit dashboard (8 pages), Power BI semantic model, DAX, page spec and theme.
- CI, coverage-check, static-snapshot and dbt-docs workflows; ADR-001…008, METHODOLOGY,
  ARCHITECTURE, generated DATA_DICTIONARY.

### Changed (vs the original spec)
- Collector loop is 29 minutes instead of 27, removing a recurring ≥ 3-minute blind spot at each
  run boundary (ADR-002).
- No dbt packages, so `dbt build` runs offline (ADR-006).

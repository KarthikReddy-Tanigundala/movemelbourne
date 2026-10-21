# CLAUDE.md — Project: MoveMelbourne
## Melbourne Public Transport Reliability Analytics (GTFS-Realtime · DuckDB · dbt · Geospatial)
### Master Build Instructions for Claude Code (Opus 4.8) — v1.0 (all gap-analysis fixes built in)

> Data facts verified live against the Transport Victoria Open Data Portal on 21 October 2026.
> Anything marked **VERIFY** must still be confirmed by a probe at build time.

---

## 0. PURPOSE & MISSION

You are building **MoveMelbourne** — an end-to-end data-engineering and analytics platform that
measures how reliably Melbourne's trains and trams run. It continuously collects Victoria's
**GTFS-Realtime** feeds (which disappear the moment they are served), joins them to the
**GTFS Schedule** timetable, and produces on-time performance (OTP), delay distributions,
reliability hotspots and tram bunching analysis, presented in a geospatial dashboard and a
Power BI report.

This is **project 5 of 5** in Karthik Reddy Tanigundala's data portfolio. It is the portfolio's
**data-engineering showcase**: a real, running pipeline over self-collected live data, not a
static CSV analysis. Target roles: Data Analyst, Analytics Engineer, BI Analyst, Data Engineer
(junior/mid) at Melbourne employers including the Department of Transport and Planning (DTP),
Metro Trains Melbourne, Yarra Trams (Yarra Journey Makers), V/Line, Suburban Rail Loop
Authority, Arup, WSP and GHD (the last three appear as Transport Victoria open-data showcases).

**Standard, not tenure.** Build to the architecture, testing and documentation standard a
data team expects from strong production work. This is a portfolio project built by a Master
of Data Science candidate. It demonstrates senior-level capability, not claimed years of
experience. In interviews Karthik says "I built this to production standard," never "I have
10 years' experience."

**What separates this from tutorial clones (build ALL of these):**
1. **Self-collected realtime data** — a scheduled collector that ran for a stated multi-week
   window, with a published coverage report showing exactly what was captured and what was missed
2. **A documented method for inferring observed arrivals** from prediction-style feeds (the
   hardest and most interview-worthy part of GTFS-RT analytics)
3. **Validation against official published performance figures** for the same month
4. **A versioned timetable join** — each realtime record is matched to the timetable that was
   actually in force that day, not today's timetable
5. **A Kimball star schema in dbt-on-DuckDB** with tests, incremental models and lineage docs
6. **Distribution-aware metrics** (P50/P90/P95, delay bands), not just averages
7. **Geospatial depth** — stop-level and segment-level delay maps on real route shapes
8. **Honest limitations** — what the feeds cannot tell you, stated plainly

**Outputs:**
1. A public GitHub repo (`movemelbourne`) with a standout README
2. A public Hugging Face dataset holding the collected snapshots (CC BY 4.0, attributed)
3. A live Streamlit dashboard (Streamlit Community Cloud)
4. A dbt docs site on GitHub Pages
5. A Power BI report (built by Karthik by hand from Claude Code's artifacts)
6. A written study report (`docs/STUDY_REPORT.md`) with findings

---

## 0.5 PORTFOLIO CONTEXT & CROSS-LINKING

This project is one of five. The README MUST include a "Part of a wider portfolio" section
linking to the other four and to the GitHub profile README
(github.com/KarthikReddy-Tanigundala):

| Project | Domain | Stack signal |
|---|---|---|
| LittleVitals | Health-system BI | Snowflake · dbt · Power BI · RLS |
| AusPolicyRAG | GenAI / RAG | LangChain · ChromaDB · hybrid retrieval · RAGAS |
| GridCast | Time-series forecasting | nemosis · mlforecast · conformal intervals |
| FootyForecast | Sports ML | Elo · XGBoost · clustering · SHAP |
| **MoveMelbourne** | **Data engineering** | **GTFS-RT · DuckDB · dbt · geospatial** |

Leave the other projects' URLs as clearly marked placeholders (`<LITTLEVITALS_URL>` etc.). Do not
invent URLs.

---

## 1. CRITICAL CONSTRAINTS (READ FIRST — THESE SHAPE EVERY DECISION)

### 1.1 Data collection is the binding constraint — START IT ON DAY ONE
GTFS-Realtime is ephemeral. There is no official historical archive for Melbourne. Every hour the
collector is not running is data lost forever. Therefore:
- **Phase 1 of the build is the collector.** Nothing else comes first except the repo skeleton
  and secrets safety.
- Everything else (static ingestion, DuckDB, dbt, dashboards) is built **while data accumulates**.
- Target collection window: **28 consecutive days** (minimum 14). Record the exact start and end
  timestamps in `config/study.yaml` and the README.
- Calendar note for a late-2026 window: Melbourne Cup Day (Tuesday 3 November 2026) is a public
  holiday in metropolitan Melbourne and runs special services. Treat it as a flagged anomaly day,
  not an error. Confirm Victorian public holidays from the `holidays` package (`subdiv="VIC"`).

### 1.2 Scope (locked — record in ADR-001)
- **Core:** Metro Train + Yarra Trams. They have all three feeds (trip updates, vehicle positions,
  service alerts) and the clearest punctuality definitions.
- **Stretch:** Metro & Regional Bus (very large feed, trip updates + vehicle positions only) and
  V/Line (trip updates + vehicle positions only). Collect bus/V/Line only if the day-1 volume
  measurement (§6.6) shows storage and Actions time can absorb it.
- Optional ML (delay prediction) is a clearly labelled stretch, never the headline.

### 1.3 Free-tier only
All data is free (CC BY 4.0). Collection runs on GitHub Actions (free on public repos). Storage on
a public Hugging Face dataset. Warehouse is DuckDB (local file). Dashboard on Streamlit
Community Cloud. No paid service is required.

### 1.4 Claude Code cannot do these — they are HUMAN-EXECUTED (mark as "Karthik — manual")
- Registering the Transport Victoria Open Data Portal account and copying the API key
- Adding secrets to GitHub and Hugging Face
- Building the Power BI `.pbix` (Claude Code produces the measures, model and page specs)
- Recording `demo.gif`, taking dashboard screenshots
- Connecting the repo to Streamlit Community Cloud

Claude Code must create correctly named placeholder image paths in the README, add a MANUAL
checklist item for each, and **never claim these exist**. Claude Code CAN generate static chart
images from data with matplotlib/plotly and should commit those.

---

## 2. DATA SOURCES — EXACT SPECIFICATIONS (verified 21 Oct 2026)

### 2.1 GTFS Schedule (static timetable, no API key)
- Page: `https://opendata.transport.vic.gov.au/dataset/gtfs-schedule`
- **Direct download:**
  `https://opendata.transport.vic.gov.au/dataset/3f4e292e-7f8a-4ffe-831f-1953be0fe448/resource/fb152201-859f-4882-9206-b768060b50ad/download/gtfs.zip`
- Size: **255.45 MB** zipped (last updated 16 October 2026). Updated weekly or as needed.
- Contents: a **rolling 30 days** of service from the export date.
- Licence: Creative Commons Attribution 4.0. Publisher: Department of Transport and Planning.
- Release notes: `https://data.ptv.vic.gov.au/downloads/GTFSReleaseNotes.pdf`
- **Folder structure (Victorian quirk):** the outer zip contains numbered folders, each a separate
  GTFS feed (each folder may itself hold a `google_transit.zip` — **VERIFY** by listing contents
  before writing the loader):

  | Folder | Mode branch | In scope |
  |---|---|---|
  | `1` | Regional Train (V/Line) | Stretch |
  | `2` | Metropolitan Train | **Core** |
  | `3` | Metropolitan Tram | **Core** |
  | `4` | Myki Bus (Metro + Regional Town Bus) | Stretch |
  | `5` | Regional Coach | No |
  | `6` | Regional Bus | No |
  | `10` | Interstate | No |
  | `11` | SkyBus | No |

- Files include `agency, stops, routes, trips, stop_times, calendar, calendar_dates, shapes,
  transfers, pathways, levels`. `stops.txt` holds Metro Train platform records with parent
  stations, and bus-replacement stops with `platform_code = 'R-Bus'`.
- **Join-critical facts from DTP's notes:** tram `route_id` and `trip_id` include business
  identifiers "to improve matching to GTFS Realtime data feeds"; train `route_id`/`trip_id`
  structure changed during DTP's backend changes. **Never hard-code ID formats.**

### 2.2 GTFS-Realtime (free API key required)
- Page: `https://opendata.transport.vic.gov.au/dataset/gtfs-realtime`
- Register (MANUAL): `https://opendata.transport.vic.gov.au/user/login` → profile shows the key.
- **Endpoint pattern (confirmed from the official OpenAPI spec):**
  `https://api.opendata.transport.vic.gov.au/opendata/public-transport/gtfs/realtime/v1/{mode}/{feed}`

  | Mode | `{mode}` | Trip updates | Vehicle positions | Service alerts | Scope |
  |---|---|---|---|---|---|
  | Metro Train | `metro` | ✅ | ✅ | ✅ | **Core** |
  | Yarra Trams | `tram` | ✅ | ✅ | ✅ | **Core** |
  | Metro & Regional Bus | `bus` | ✅ | ✅ | — | Stretch |
  | V/Line | `vline` | ✅ | ✅ | — | Stretch |

  `{feed}` ∈ `trip-updates`, `vehicle-positions`, `service-alerts`.
  **VERIFY** the `tram`/`bus`/`vline` path segments against each mode's OpenAPI JSON (linked from
  the dataset page) in the day-1 probe. Only `metro` was confirmed verbatim.
- **Authentication — DTP's own documents conflict:**
  - OpenAPI spec: header `Ocp-Apim-Subscription-Key`, or query param `subscription-key`
  - Dataset page: "The API Key is to be used in the request header. Header name is 'KeyID'."
  - **Implement runtime negotiation:** try `Ocp-Apim-Subscription-Key` → on 401/403 try `KeyID`
    → then the `subscription-key` query param. Cache the winning method per mode and log it.
  - Never put the key in a URL that gets logged. Redact it in all logs and error messages.
- **Rate limits:** dataset page states 24 calls per 60 seconds per mode (metro, tram, bus). The
  OpenAPI spec states 20–27 calls/minute depending on data size, with 30-second caching. Design
  for **≤ 6 calls/minute per mode** (huge safety margin).
- **Refresh:** Metro Train near real-time; Tram every 60 seconds; Bus near real-time. Polling
  faster than 30–60 s returns cached data — poll each feed every **60 s**.
- **Format:** Protocol Buffers (binary). Parse with `gtfs-realtime-bindings`.
- **Recent changes (dataset page):** Metro Train trip updates gained schedule relationship,
  `stop_id` and `route_id`; vehicle positions gained `route_id` (conditionally required); service
  alerts gained planned/unplanned disruption detail, `route_id` and `direction_id`.
- **Known limitation (verbatim from the spec):** the Metro Train trip-updates feed "doesn't include
  train replacement buses, service deviations (skipping stops or changing routes) and platform
  information." State this in the README limitations.

### 2.3 Official performance figures (validation benchmark — the differentiator)
Victoria publishes monthly train and tram punctuality and reliability results.
- **VERIFY-FIRST:** locate the current official monthly performance page on vic.gov.au/PTV in
  Phase 0 and record the URL in `docs/sources.md`. If monthly figures for the study month are not
  yet published when the build finishes, state that and compare against the most recent
  published months instead.
- Use it to answer: "How close is my independently computed OTP to the official figure?" The
  official measure uses specific measurement points and rules, so expect a gap. Explaining the gap
  is the senior signal.

### 2.4 Melbourne punctuality definitions (cite in METHODOLOGY.md)
- **Metro train (official):** on time if it arrives no later than **4 minutes 59 seconds** after
  the scheduled time. Metro contract targets: **92% punctuality**, **98.5% reliability (service
  delivery)**. Customer Service Charter threshold ≥ 90%.
- **Tram:** **VERIFY** the official tram punctuality definition (early tolerance and late threshold)
  and target from the same official source before coding. Until verified, implement thresholds as
  config values, not constants.
- MoveMelbourne's metric is a **proxy**: it measures at every observed stop, not only at official
  measurement points. Label every chart "MoveMelbourne proxy OTP" and explain the difference.

### 2.5 Optional enrichment
- **Weather:** Open-Meteo archive API (free, no key, CC BY 4.0), Melbourne lat −37.81, lon 144.96,
  hourly `temperature_2m`, `precipitation`. Only for the stretch delay model.
- **Legacy PTV Timetable API** (`timetableapi.ptv.vic.gov.au`, HMAC-SHA1 signing with devid + key):
  mention in README as a known alternative. **Do not build on it.**

---

## 3. TIME & IDENTIFIER GOTCHAS (write tests for every one of these)

| Gotcha | Rule |
|---|---|
| GTFS-RT timestamps are POSIX epoch seconds (UTC) | Store raw epoch; convert with `Australia/Melbourne` (DST-aware — unlike AEMO data, Melbourne PT time DOES observe daylight saving) |
| GTFS `stop_times` times are service-day local times and can exceed 24:00:00 (e.g. `25:12:00`) | Never parse as clock time. Compute scheduled epoch = service_date's "noon minus 12h" local reference + seconds since that reference (GTFS spec rule). Handles DST and after-midnight trips |
| Service date ≠ calendar date for after-midnight trips | Take service date from `TripDescriptor.start_date`; if absent, derive from schedule |
| DST transitions (first Sunday of October / first Sunday of April) | Unit-test a service date that spans a DST change |
| Static timetable rolls weekly (30-day window) | Snapshot every static release with a `feed_version` (download date + SHA-256). Join realtime to the version in force on that service date |
| `trip_id` / `route_id` formats changed recently | Join on IDs as delivered; measure match rate; never reshape IDs by regex without evidence |
| `stop_id` in realtime may be a platform (child) stop while schedule uses the parent station (or vice versa) | Normalise via `parent_station` in `stops.txt`; test both directions |
| `schedule_relationship` values (SCHEDULED, ADDED, CANCELED, SKIPPED, NO_DATA) | Handle each explicitly; cancelled trips feed reliability, not punctuality |
| Duplicate entities across snapshots | Deduplicate on (feed, entity_id, trip_id, stop key, observation_time) in silver |
| Schema drift (DTP keeps adding fields) | Flatten to a fixed core schema plus a JSON `extra` column; DuckDB `read_parquet(..., union_by_name=true)` |

---

## 4. TECH STACK & VERSIONS

Python **3.12**, managed with **uv**. Commit `.python-version` and set `requires-python = ">=3.12,<3.13"`
in `pyproject.toml`. Set the Streamlit Cloud Python version to match.

```
# Collection & parsing
gtfs-realtime-bindings   # provides google.transit.gtfs_realtime_pb2 (MobilityData)
protobuf                 # compatible with the bindings
requests
tenacity                 # retry with backoff
huggingface_hub          # upload snapshots to the HF dataset

# Static GTFS
gtfs-kit                 # GTFS loading + analytics (no built-in validator since v10)
partridge                # fast reader, read_busiest_date for slimming

# Warehouse & transforms
duckdb                   # 1.x; extensions: spatial, httpfs
dbt-core>=1.8
dbt-duckdb               # matched to the duckdb version
pyarrow
pandas
polars                   # optional, fast flattening

# Geospatial
geopandas>=1.0
shapely>=2
pyproj
pyogrio

# Dashboard
streamlit
streamlit-folium
folium
pydeck
plotly

# Quality & dev
pytest
ruff
pre-commit
detect-secrets
holidays
```
**Pin exact versions** in `uv.lock` after a clean resolve. Versions move; resolve at build time,
then freeze. The deployed Streamlit app gets its own minimal `requirements.txt` (no dbt, no
gtfs-kit, no geopandas if avoidable) to stay inside free-tier memory.

External tool (optional, Java): MobilityData GTFS Validator for the static feed.

---

## 5. ARCHITECTURE

```
            ┌──────────────── COLLECTION (runs 24/7 for the study window) ────────────────┐
 GTFS-RT ──►│ GitHub Actions cron (*/30) → poll loop ~27 min, every feed every 60 s       │
 (metro,    │ → parse protobuf → flatten → per-run Parquet per feed                        │
  tram,     │ → ONE commit per run to Hugging Face dataset (raw/realtime/...)             │
  [bus,     │ → coverage log row (polls attempted / succeeded / auth method / bytes)       │
  vline])   └─────────────────────────────────────────────────────────────────────────────┘
 GTFS       ┌──────────────── WEEKLY STATIC SNAPSHOT ─────────────────────────────────────┐
 Schedule ─►│ GitHub Actions cron (weekly + manual) → download gtfs.zip → SHA-256          │
            │ → if new: extract folders 2,3 (+1,4) → Parquet tagged feed_version → HF     │
            └─────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
            ┌──────────────── WAREHOUSE (local or CI) ────────────────────────────────────┐
            │ DuckDB movemelbourne.duckdb                                                  │
            │ bronze: external views over HF Parquet (hive partitions, union_by_name)      │
            │ dbt-duckdb: staging → intermediate → marts (star schema) + tests + docs     │
            └─────────────────────────────────────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼───────────────────────────┐
              ▼                          ▼                           ▼
   Streamlit dashboard          Power BI report (manual)     dbt docs → GitHub Pages
   (reads small gold Parquet)   (gold Parquet/CSV export)    Study report (markdown)
```

Why these choices (each becomes an ADR, §13):
- **GitHub Actions + Hugging Face dataset** instead of committing to git: snapshots accumulate to
  gigabytes; committing them to the code repo would bloat it and hit GitHub limits.
- **One long poll loop per run** instead of a 5-minute cron: GitHub's minimum schedule is 5 minutes
  and runs can start late. A 27-minute loop polls densely and cuts commits to ~48/day.
- **DuckDB + dbt** instead of a cloud warehouse: free, fast on Parquet, fully reproducible.

---

## 6. PHASE 0–1: SECRETS SAFETY, PROBE, AND THE COLLECTOR (DAY ONE)

### 6.1 Secrets safety (before the first push)
- `.gitignore`: `.env`, `*.duckdb`, `data/`, `target/`, `dbt_packages/`, `logs/`, `__pycache__/`,
  `.venv/`, `.DS_Store`
- `.env.example` with placeholders only: `TVOD_API_KEY=` and `HF_TOKEN=`
- `pre-commit` with `detect-secrets` and `ruff`. Run `gitleaks detect --source . --verbose` before
  making the repo public; it must report zero findings.
- If a key is ever committed, even briefly: revoke/regenerate it in the portal, then scrub history
  with `git filter-repo`.
- GitHub secrets (MANUAL): `TVOD_API_KEY`, `HF_TOKEN` (write access to the dataset repo only).

### 6.2 Day-one probe (`scripts/probe_feeds.py`)
Before writing the collector, a throwaway probe must:
1. For each mode in scope and each feed, call the endpoint with the auth negotiation from §2.2.
2. Print: HTTP status, winning auth method, response bytes, `header.timestamp`, entity count, and
   for trip updates: share of `stop_time_update` rows with `arrival.delay` populated vs
   `arrival.time` populated, presence of `stop_id`, `stop_sequence`, `start_date`.
3. Save one raw `.pb` per feed to `tests/fixtures/` (small, for offline tests and CI).
4. Write findings to `docs/probe_results.md`.
Also list the outer `gtfs.zip` structure and record whether folders contain nested zips.

**Gate:** if any core endpoint fails all three auth methods, stop and report to Karthik. Do not
guess another URL.

### 6.3 Collector (`src/movemelbourne/collect/`)
- `client.py`: session with auth negotiation, timeouts (10 s connect / 30 s read), `tenacity`
  exponential backoff with jitter on 429/5xx, a per-mode token bucket (≤ 6 calls/min/mode),
  key redaction in logs.
- `parse.py`: `gtfs_realtime_pb2.FeedMessage().ParseFromString(content)` → flat rows:
  - **trip_updates:** one row per `stop_time_update`: `feed_ts`, `poll_ts_utc`, `entity_id`,
    `trip_id`, `route_id`, `direction_id`, `start_date`, `start_time`,
    `trip_schedule_relationship`, `vehicle_id`, `stop_sequence`, `stop_id`, `arrival_time`,
    `arrival_delay`, `departure_time`, `departure_delay`, `stu_schedule_relationship`, `extra_json`
  - **vehicle_positions:** `feed_ts`, `poll_ts_utc`, `vehicle_id`, `trip_id`, `route_id`,
    `start_date`, `latitude`, `longitude`, `bearing`, `speed`, `current_stop_sequence`, `stop_id`,
    `current_status`, `vehicle_ts`, `occupancy_status`, `congestion_level`, `extra_json`
  - **service_alerts:** one row per informed entity: `alert_id`, active period start/end, `cause`,
    `effect`, header/description text (English translation), `route_id`, `stop_id`, `trip_id`,
    `direction_id`, `extra_json`
- `run_collection.py`: loop until `max_runtime` (default 27 min) → poll each feed every 60 s →
  buffer rows → on exit write one Parquet per feed per run:
  `raw/realtime/{feed}/mode={mode}/dt={YYYY-MM-DD}/run_{run_id}.parquet` (zstd compression) →
  upload the run folder with a single `huggingface_hub` commit → append a coverage row to
  `raw/coverage/dt=.../run_{run_id}.parquet`: polls attempted, succeeded, failed, auth method,
  bytes, entity counts, earliest/latest `feed_ts`.
- Must be idempotent (run_id = GitHub run id + attempt) and survive partial failure (write what it
  has, record the failure, exit non-zero only after uploading).

### 6.4 Collection workflow (`.github/workflows/collect.yml`)
```yaml
name: collect-realtime
on:
  schedule:
    - cron: "*/30 * * * *"      # UTC; runs may start late — the loop absorbs this
  workflow_dispatch:
concurrency:
  group: collect-realtime
  cancel-in-progress: false      # never overlap two collectors
jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 32
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen --only-group collect
      - run: uv run python -m movemelbourne.collect.run_collection --max-runtime-min 27
        env:
          TVOD_API_KEY: ${{ secrets.TVOD_API_KEY }}
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
```
- Failures must be **loud**: non-zero exit shows a red run; a separate daily
  `coverage-check.yml` reads the coverage parquet and opens a GitHub issue if any 2-hour gap
  exists or success rate falls below 90%.
- **GitHub disables scheduled workflows in public repos after 60 days without repository
  activity.** The collection window is shorter than that, but if collection continues longer,
  the weekly static-snapshot job's commits or a manual commit must keep the repo active. Note this
  in the README.
- Backup option (document, do not build unless Actions proves unreliable): run the same collector
  on an always-on free VM or home machine with cron.

### 6.5 Weekly static snapshot (`.github/workflows/static_snapshot.yml`)
Weekly (Monday 03:17 UTC) + manual: download `gtfs.zip`, compute SHA-256, skip if unchanged,
otherwise extract in-scope folders, convert each `.txt` to Parquet tagged with
`feed_version = <download_date>_<sha8>`, upload to the HF dataset under
`raw/schedule/feed_version=.../mode_branch=.../{table}.parquet`, and record validity dates
(`calendar` min/max). The 255 MB zip must be streamed to disk, never loaded into memory.

### 6.6 Day-one volume measurement (gate for stretch modes)
After the first 24 hours: compute bytes/day per feed from the coverage table, project 28-day
volume, and estimate Actions minutes. Write to `docs/volume_estimate.md`. Add bus and V/Line only
if the projection stays comfortable (rough guide: total under ~20 GB and runs consistently
finishing under 30 minutes).

---

## 7. PHASE 2: STATIC GTFS INGESTION & DIMENSIONS

`src/movemelbourne/ingest/load_schedule.py`:
- Read each in-scope folder's feed with `gtfs_kit` (or `partridge` for speed); handle nested zips.
- Tag every row with `mode_branch` and `feed_version`.
- Validate: required files present; `stop_times` references valid `trip_id`/`stop_id`;
  `shapes.txt` geometries load; optional MobilityData validator report saved to `docs/`.
- Pre-compute for dbt: `scheduled_arrival_epoch` per (feed_version, service_date, trip_id,
  stop_sequence) using the GTFS noon-minus-12h rule and `calendar`/`calendar_dates` to decide
  which trips run on each service date.
- Build geometry: stops as points, shapes as linestrings (EPSG:4326); store WKB for DuckDB spatial
  and GeoParquet for GeoPandas.

---

## 8. PHASE 3: DUCKDB WAREHOUSE & DBT MODELS

### 8.1 Bronze (`src/movemelbourne/load/bronze.py`)
- Persistent `movemelbourne.duckdb`; `INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;`
- Bronze views over local synced Parquet (preferred: `huggingface_hub.snapshot_download` to a
  local cache first; `hf://` reads are a fallback):
  `read_parquet('data/raw/realtime/trip_updates/**/*.parquet', hive_partitioning=true, union_by_name=true)`

### 8.2 dbt project (`dbt/`)
```
dbt/
├── dbt_project.yml          # materializations: staging=view, intermediate=table, marts=table/incremental
├── profiles.yml.example     # duckdb path via env var
├── packages.yml             # dbt-utils, dbt-expectations
├── seeds/
│   ├── otp_thresholds.csv   # mode, early_tolerance_s, late_threshold_s, source, verified_on
│   ├── time_bands.csv       # AM peak 07:00–09:00, inter-peak, PM peak 16:00–19:00, evening, night
│   └── vic_public_holidays.csv
├── models/
│   ├── staging/             # stg_rt_trip_updates, stg_rt_vehicle_positions, stg_rt_service_alerts,
│   │                        # stg_gtfs_trips, stg_gtfs_stop_times, stg_gtfs_stops, stg_gtfs_routes,
│   │                        # stg_gtfs_shapes, stg_coverage
│   ├── intermediate/
│   │   ├── int_rt_stop_predictions_dedup.sql     # one row per (service_date, trip, stop, poll)
│   │   ├── int_observed_stop_events.sql          # inferred observed arrival (see §9.1)
│   │   ├── int_scheduled_stop_events.sql         # timetable in force per service_date
│   │   ├── int_stop_events_matched.sql           # schedule ⨝ observed, with match_status
│   │   ├── int_trip_outcomes.sql                 # ran / cancelled / partially observed
│   │   └── int_headways.sql                      # actual vs scheduled headway at timepoints
│   └── marts/
│       ├── dim_date.sql  dim_time_band.sql  dim_route.sql  dim_stop.sql (with geometry)
│       ├── dim_trip.sql  dim_mode.sql  dim_feed_version.sql
│       ├── fact_stop_event.sql        # grain: service_date × trip × stop  (incremental)
│       ├── fact_trip.sql              # grain: service_date × trip
│       ├── fact_alert.sql             # grain: alert × informed entity × active period
│       ├── agg_otp_daily_route.sql  agg_otp_stop.sql  agg_otp_hour_dow.sql
│       ├── agg_segment_delay.sql      # delay added between consecutive stops
│       ├── agg_headway_adherence.sql
│       └── agg_coverage_daily.sql     # what share of scheduled stop events we observed
├── tests/                   # singular tests (§8.3)
└── macros/                  # gtfs_time_to_epoch, otp_flag, delay_band
```

### 8.3 Tests (zero failures on main)
- Keys: `unique` + `not_null` on every fact grain; `relationships` from facts to every dimension.
- `accepted_values`: mode, direction_id (0/1), schedule relationships, delay_band.
- Range: `delay_seconds` between −1800 and 7200 (rows outside are quarantined to an
  `audit_outliers` model, not silently dropped).
- Reconciliation: observed stop events ≤ scheduled stop events per day; coverage % between 0 and
  100; every service date in the study window present in `agg_coverage_daily`.
- Join quality: `realtime→schedule match rate` per mode per day ≥ 95% (configurable); a test that
  **fails loudly** if it drops, because that means an ID format changed.
- Freshness: dbt source freshness on the latest `poll_ts_utc` (warn > 2 h, error > 6 h) while
  collection is active.
- Python unit tests (`tests/`): auth negotiation (mock 401 → fallback), protobuf parsing against
  fixtures, GTFS >24:00 times, DST service date, parent/child stop normalisation, dedupe logic.

---

## 9. PHASE 4: ANALYTICAL METHODOLOGY (encode in models + METHODOLOGY.md)

### 9.1 Inferring observed arrivals (the core method — document carefully)
Trip-update feeds publish **predictions**, and stops usually drop out of the feed once passed. The
observed arrival is inferred, with a confidence label:
1. **Primary (trip updates):** for each (service_date, trip, stop), take the **last prediction
   captured before the stop disappeared** from the trip's `stop_time_update` list. Accept it only
   if that snapshot was taken within a freshness window of the predicted time (default 120 s;
   configurable). Label `method = 'last_prediction'`.
2. **Secondary (vehicle positions, especially trams):** the first `current_status = STOPPED_AT`
   (or proximity within 30 m of the stop with near-zero speed) for that trip and stop. Label
   `method = 'vehicle_position'`.
3. If both exist, compare them and report agreement statistics (median absolute difference) — this
   is a self-validation of the method.
4. Stop events with neither are `unobserved`, never imputed. They count against coverage, not OTP.
Choose the primary per mode based on the probe and the first week's data, and record the choice in
ADR-004. If `arrival_delay` is populated directly, use it but still check it against
`arrival_time − scheduled_arrival_epoch`.

### 9.2 Metrics
- `delay_seconds = observed_arrival_epoch − scheduled_arrival_epoch`
- **Proxy OTP %** per mode using `otp_thresholds` seed: on time if
  `−early_tolerance_s ≤ delay_seconds ≤ late_threshold_s` (metro late threshold 299 s).
- **Delay bands:** early, on time, minor late (5–15 min), major late (> 15 min).
- **Distribution:** P50, P85, P90, P95 delay. Never report a mean alone.
- **Reliability (service delivery):** share of scheduled trips that ran
  (`1 − cancelled/scheduled`), using CANCELED trip updates and full-trip absence. Separate
  "confirmed cancelled" from "no data".
- **Coverage:** observed stop events ÷ scheduled stop events. Every OTP number shown is paired with
  its coverage.
- **Segment delay:** change in delay between consecutive stops = where time is lost, mapped on
  shapes.
- **Headway adherence (trams):** actual vs scheduled headway at timepoints; bunching when actual
  headway < 0.5 × scheduled; coefficient of variation of headways per route and time band.
- **Alerts:** join active alerts to routes/stops; compare OTP inside vs outside disruption windows.

### 9.3 Statistical honesty
- Minimum sample rule: suppress (grey out) any route/stop/hour cell with fewer than 30 observed
  events; show the count on hover.
- Bootstrap 95% confidence intervals for route-level OTP in the ranking (rank by lower bound, not
  point estimate, to avoid crowning tiny-sample routes).
- Compare weekdays vs weekends and peaks vs off-peak; flag holiday and event days (Melbourne Cup).

### 9.4 Validation against official figures
`analysis/official_comparison.py` produces `docs/validation.md`: MoveMelbourne proxy OTP vs the
official monthly figure for the same mode and month, with a written explanation of differences
(measurement points, definition, coverage, replacement buses excluded from the feed).

### 9.5 Optional stretch: delay model (clearly labelled)
LightGBM predicting `delay_seconds` at stop level from route, stop, hour, day of week, time band,
upstream delay, and optional weather. Time-based train/test split (last 7 days held out). Report
MAE vs a naive baseline (route × hour median). Ship only if it beats the baseline; otherwise
report the negative result.

---

## 10. PHASE 5: DASHBOARD (Streamlit Community Cloud)

### 10.1 Data for the app
- A `scripts/export_gold.py` step writes **small, pre-aggregated** Parquet files to
  `app/data/` (target < 50 MB total) plus a `manifest.json` (study window, feed versions, row
  counts, build timestamp). The app never runs dbt or reads raw snapshots.
- App dependencies limited to `streamlit, pandas, pyarrow, plotly, pydeck` (and `folium` +
  `streamlit-folium` if used). Use `@st.cache_data`. Stay well below the free tier's ~1 GB.

### 10.2 Pages
1. **Network health:** proxy OTP and reliability KPI cards per mode vs the 92% / 98.5% metro
   benchmarks, coverage badge, study-window banner.
2. **Route reliability ranking:** routes ranked by OTP lower-bound CI, P90 delay, cancellations;
   small-sample cells greyed.
3. **Delay map:** stop-level P90 delay (pydeck ScatterplotLayer / HexagonLayer) and segment-level
   delay on route shapes (PathLayer); mode and time-band filters.
4. **When it goes wrong:** hour × day-of-week heatmap; peak vs off-peak; holiday/event flags.
5. **Tram bunching:** headway CV by route; bunching events over time.
6. **Disruptions:** alerts timeline joined to delay spikes.
7. **Data quality & method:** coverage over time, collector uptime, inference-method agreement,
   official-figure validation table, known limitations.
8. **Live now (optional):** current vehicle positions on a map, fetched with the API key from
   Streamlit secrets and cached with `ttl=60` so many viewers never exceed the rate limit. Disable
   gracefully if the key is absent.

### 10.3 Design rules
- Colour-blind-safe palette (Okabe-Ito or viridis); never red/green alone — pair with labels or
  shapes; WCAG AA contrast.
- Every page footer: "Data: Department of Transport and Planning, GTFS Schedule and GTFS Realtime,
  CC BY 4.0. MoveMelbourne figures are independent proxy estimates, not official performance
  results."
- A visible "last updated / study window" stamp on every page.

---

## 11. PHASE 6: POWER BI (artifacts by Claude Code, build by Karthik)

Claude Code produces, Karthik builds the `.pbix` by hand:
- `powerbi/data/`: gold CSV/Parquet exports (fact_stop_event sampled or aggregated, dims, aggs)
- `powerbi/SEMANTIC_MODEL.md`: tables, relationships (single direction, star), date table marked
- `powerbi/DAX_MEASURES.md`: ready-to-paste measures, at minimum:
  `Proxy OTP %`, `Reliability %`, `P90 Delay (min)` (via `PERCENTILEX.INC`), `Coverage %`,
  `Observed Stop Events`, `OTP vs Target (pp)`, `OTP Rolling 7d`, `Bunching Rate %`,
  `Major Delay Share %`, and a `Sample Size Flag` used for conditional formatting
- `powerbi/PAGE_SPEC.md`: four pages (Network overview, Route scorecard with map, Time patterns,
  Disruptions) with visuals, slicers and formatting
- Use Import mode so the report needs no live connection. Publishing is optional and manual.
Claude Code must not claim the `.pbix` exists or is published.

---

## 12. REPOSITORY STRUCTURE

```
movemelbourne/
├── README.md  ARCHITECTURE.md  METHODOLOGY.md  DATA_DICTIONARY.md  CHANGELOG.md  LICENSE (MIT)
├── .python-version  pyproject.toml  uv.lock  .env.example  .gitignore  .pre-commit-config.yaml
├── config/
│   ├── feeds.yaml           # modes, feeds, endpoints, poll interval, per-mode limits
│   └── study.yaml           # study window start/end, scope, thresholds, sample minimums
├── scripts/                 # probe_feeds.py, export_gold.py, volume_estimate.py
├── src/movemelbourne/
│   ├── collect/             # client.py, parse.py, run_collection.py, upload.py
│   ├── ingest/              # load_schedule.py, static_snapshot.py
│   ├── load/                # bronze.py, sync_from_hf.py
│   ├── analysis/            # official_comparison.py, bootstrap.py, delay_model.py (stretch)
│   └── utils/               # timeutil.py (GTFS time + DST), logging.py (key redaction)
├── dbt/                     # §8.2
├── app/                     # streamlit_app.py, pages/, data/ (small gold exports), requirements.txt
├── powerbi/                 # §11
├── tests/                   # unit tests + fixtures/*.pb + sample schedule subset
├── docs/
│   ├── adr/                 # ADR-001 … ADR-008
│   ├── probe_results.md  volume_estimate.md  validation.md  STUDY_REPORT.md  sources.md
│   └── images/              # generated charts + MANUAL screenshots/gif placeholders
└── .github/workflows/       # collect.yml, static_snapshot.yml, coverage_check.yml,
                             # ci.yml, dbt_docs.yml
```

---

## 13. ARCHITECTURE DECISION RECORDS (Context / Decision / Consequences)

| ADR | Decision |
|---|---|
| ADR-001 | Scope: metro train + tram core; bus/V/Line stretch gated by volume |
| ADR-002 | Self-collection on GitHub Actions (30-min schedule, 27-min poll loop) |
| ADR-003 | Snapshots stored in a Hugging Face dataset, not the git repo |
| ADR-004 | Observed-arrival inference method per mode (last prediction vs vehicle position) |
| ADR-005 | Versioned static timetable join (`feed_version`) |
| ADR-006 | DuckDB + dbt-duckdb as the warehouse instead of a cloud warehouse |
| ADR-007 | Proxy OTP definition and why it differs from official figures |
| ADR-008 | Runtime auth-header negotiation because DTP's documents conflict |

---

## 14. CI/CD

- `ci.yml` (PR + push): ruff, pytest (fixtures only, no API key needed), `dbt build` against a
  small committed sample (`tests/sample/`), gitleaks scan.
- `dbt_docs.yml` (push to main): `dbt docs generate` on the sample → publish to GitHub Pages.
- `collect.yml`, `static_snapshot.yml`, `coverage_check.yml` as in §6.
- All workflows fail loudly; none swallow errors.

---

## 15. README.md SPECIFICATION

Order (first screen must sell the project):
1. Title + one-line problem statement: "How reliable are Melbourne's trains and trams? An
   independent measurement from N weeks of self-collected live data."
2. Live links table: dashboard, HF dataset, dbt docs, study report.
3. `demo.gif` (MANUAL placeholder) and one generated delay-map image.
4. Headline findings (3–5 bullets with numbers, each paired with coverage), filled from real
   results only. Never invent numbers.
5. Mermaid architecture diagram (from §5).
6. **Quickstart (5 minutes):** clone → `uv sync` → `uv run python scripts/run_sample.py` builds
   DuckDB + dbt on the committed sample and opens the dashboard. No API key needed.
7. Full reproduction: collect your own data (API key), sync from HF, `dbt build`.
8. Data model (ERD), methodology summary, validation vs official figures.
9. **Demo status & persistence:** study window dates; whether collection is still running; the
   dashboard shows a fixed study unless "Live now" is enabled; how a viewer can tell.
10. Limitations: proxy metric; feed excludes replacement buses, deviations and platforms;
    inference uncertainty; coverage gaps; GitHub Actions timing jitter.
11. Data sources & licence (CC BY 4.0 attribution to DTP), part-of-portfolio links, About.

---

## 16. BUILD ORDER (execute in sequence; validate each gate)

```
PHASE 0 — SKELETON & SAFETY (hours, not days)
  0.1 Repo structure, pyproject + uv, .python-version, .gitignore, .env.example, pre-commit
  0.2 MANUAL: Karthik registers portal account, adds TVOD_API_KEY + HF_TOKEN secrets,
      creates the public HF dataset repo
  0.3 scripts/probe_feeds.py → docs/probe_results.md, fixtures saved
      GATE: core endpoints return 200 with a negotiated auth method

PHASE 1 — COLLECTOR LIVE (same day as Phase 0)
  1.1 collect/client.py, parse.py, run_collection.py, upload.py + unit tests on fixtures
  1.2 collect.yml + coverage_check.yml; trigger manually once, confirm HF upload
  1.3 Record study start timestamp in config/study.yaml
      GATE: 24 h of continuous runs with ≥ 90% poll success
  1.4 volume_estimate.md → decide bus/V/Line (ADR-001)

PHASE 2 — STATIC TIMETABLE
  2.1 static_snapshot.py + workflow; first snapshot uploaded with feed_version
  2.2 load_schedule.py; utils/timeutil.py with >24:00 and DST tests
      GATE: scheduled stop events generated for each study date

PHASE 3 — WAREHOUSE & DBT
  3.1 bronze views; dbt staging models + source freshness
  3.2 intermediate: dedup, scheduled events, observed-event inference, matching
      GATE: realtime→schedule match rate ≥ 95% for metro and tram on day-one data
      (if not: investigate ID formats and stop parent/child mapping before going further)
  3.3 marts + aggregates + all tests; dbt docs locally

PHASE 4 — ANALYSIS (needs ≥ 14 days collected; refine at 28)
  4.1 metrics, bootstrap CIs, sample suppression
  4.2 inference-method agreement report
  4.3 official comparison → docs/validation.md (VERIFY official page first)
  4.4 optional delay model (only if time allows)

PHASE 5 — DASHBOARD
  5.1 export_gold.py → app/data (< 50 MB) + manifest
  5.2 Streamlit pages; local run; MANUAL: connect to Streamlit Community Cloud

PHASE 6 — POWER BI ARTIFACTS
  6.1 powerbi/data exports, SEMANTIC_MODEL.md, DAX_MEASURES.md, PAGE_SPEC.md
  6.2 MANUAL: Karthik builds the .pbix

PHASE 7 — DOCS & POLISH
  7.1 ADR-001…008, METHODOLOGY.md, DATA_DICTIONARY.md, STUDY_REPORT.md
  7.2 README per §15 with real numbers only; generated charts committed
  7.3 MANUAL: demo.gif + screenshots
  7.4 Final: all tests pass, gitleaks clean, every link works, study window stated
  7.5 Decide: stop collection (fixed study) or keep running; update README "Demo status"
```

---

## 17. QUALITY STANDARDS — NON-NEGOTIABLE

- Type hints, docstrings, structured logging (no print); API key redacted everywhere
- All thresholds, windows, intervals in `config/*.yaml` or dbt seeds — none hard-coded
- No `SELECT *` in intermediate or mart models; every mart column documented in YAML
- Every number in README/dashboard comes from a committed model output; never invented
- Every OTP figure shown with its coverage and sample size
- Unobserved events are never imputed into OTP
- Licence attribution visible in the app, README and HF dataset card
- Australian English in all prose

---

## 18. INTERVIEW DEFENSIBILITY MAP

| Topic | Likely question | Answer |
|---|---|---|
| Why collect data | "Why not just download history?" | "There isn't any. Victoria's GTFS-Realtime feeds are live only, so I built a collector that polled metro and tram feeds every minute for four weeks, stored snapshots as Parquet in a Hugging Face dataset, and published a coverage report showing exactly what I captured and missed." |
| Observed arrivals | "The feed gives predictions — how do you know when a train actually arrived?" | "I take the last prediction captured just before the stop drops out of the feed, but only if that snapshot was fresh, and I cross-check against vehicle positions. I report how often the two methods agree. Stops I couldn't observe count against coverage; I never impute them." |
| Timetable join | "How did you match realtime to the timetable?" | "The static feed is a rolling 30-day file updated weekly, so I versioned every release and joined each service date to the timetable in force that day. I also handled GTFS times past midnight and daylight saving, and I test the match rate every day so an ID-format change fails loudly." |
| Official figures | "Do your numbers match Metro's published punctuality?" | "Not exactly, and I explain why: the official measure uses specific measurement points, while mine is a proxy across all observed stops, and the feed excludes replacement buses. I show both side by side with the gap explained." |
| Statistics | "How do you avoid misleading rankings?" | "Every OTP number has its coverage and sample size. I suppress cells under 30 events and rank routes by the lower bound of a bootstrap confidence interval, so a route with five lucky observations doesn't top the table." |
| Architecture | "Why DuckDB and dbt, not a cloud warehouse?" | "It's free, fast on Parquet, and fully reproducible — anyone can rebuild the whole warehouse from the public dataset. The modelling is standard Kimball: stop-event and trip facts, conformed date, route and stop dimensions, with dbt tests on keys, relationships and join quality." |
| Collection reliability | "GitHub Actions isn't a real scheduler." | "Right, runs can start late and the minimum is five minutes, so each run polls in a loop for 27 minutes, runs never overlap, and a daily job opens an issue if there's a gap over two hours. The coverage report makes any gaps visible." |
| Auth | "Any surprises with the API?" | "DTP's own documents disagree on the auth header, so the client negotiates at runtime and logs which method worked. I also kept polling well under the published rate limit." |

---

## 19. AFTER THE BUILD — RESUME KNOWLEDGE BASE UPDATE (MANUAL)

Karthik's KB currently lists dbt under Do Not Claim. After this project ships, follow the KB
Update Protocol: add dbt, DuckDB, GTFS/GTFS-Realtime, geospatial analysis and pipeline
orchestration (GitHub Actions) at **Project** exposure (not Production), add the project to
Section 8 with real metrics, and bump the KB minor version.

---

## 20. FINAL DELIVERABLES CHECKLIST

- [ ] Probe results documented; auth method recorded per mode
- [ ] Collector ran ≥ 14 days (target 28) with coverage report; study window stated
- [ ] HF dataset public, with dataset card and CC BY 4.0 attribution
- [ ] Weekly static snapshots versioned; versioned join working
- [ ] Match rate ≥ 95% (metro, tram) or documented reason
- [ ] dbt build passes with zero test failures; dbt docs live on GitHub Pages
- [ ] Observed-arrival method documented with agreement statistics (ADR-004)
- [ ] OTP, reliability, P90, coverage, segment delay, bunching computed
- [ ] Official-figure validation written (or documented as unavailable)
- [ ] Streamlit app live; small gold exports only; attribution footer; colour-blind-safe
- [ ] Power BI artifacts committed (MANUAL: .pbix built)
- [ ] 8 ADRs; METHODOLOGY, DATA_DICTIONARY, STUDY_REPORT written
- [ ] README per §15 with real numbers only; Quickstart works without an API key
- [ ] gitleaks clean; no key anywhere in history
- [ ] MANUAL: demo.gif, screenshots, Streamlit deploy, KB update
- [ ] Karthik can speak for 60+ seconds on every row of §18

---

*CLAUDE.md v1.0 — MoveMelbourne · Generated for Karthik Reddy Tanigundala — RMIT Master of Data
Science 2026 · Project 5 of 5 (data-engineering showcase) · Data facts verified 21 Oct 2026*

---

## 21. ERRATA & BUILD DECISIONS (supersede earlier sections where they conflict)

Recorded during the build (2026-10-21). Each is backed by an ADR or a test.

| # | Spec said | Build does | Why / evidence |
|---|---|---|---|
| 1 | `tram`/`bus`/`vline` paths: VERIFY | Verified from each mode's OpenAPI JSON | `docs/sources.md` |
| 2 | Auth: `Ocp-Apim…` / `KeyID` / query | Same negotiation; V/Line spec also says `KeyId` | ADR-008 |
| 3 | Tram definition: VERIFY | −59 s / +4:59, target 82% (charter Oct 2025, vic.gov.au) | `otp_thresholds.csv` |
| 4 | Official monthly figures | Daily operational reports also exist → day-level validation | ADR-007, `docs/validation.md` |
| 5 | 27-minute poll loop | **29 minutes**; a 27-min loop leaves a ≥ 3-min blind spot every 30 min (~10% of time) | ADR-002 |
| 6 | Bronze over `hf://` or synced files | One local **lake** mirroring the HF layout; local runs, static snapshots and HF sync share paths (file-level dedupe) | ADR-003 |
| 7 | Pre-compute `scheduled_arrival_epoch` per stop in Python | Python computes only `ref_epoch` per service date (DST-correct); dbt adds GTFS seconds (keeps 8M-row joins in DuckDB) | ADR-005, `test_timeutil.py` |
| 8 | DST reference "midnight" assumption | Noon-minus-12h = 23:00 previous evening on DST-start day, 01:00 on DST-end day | `test_timeutil.py` |
| 9 | packages.yml with dbt-utils, dbt-expectations | **No packages**; local `accepted_range` test; offline CI | ADR-006 |
| 10 | Last prediction before the stop disappears | Latest snapshot with \|prediction − snapshot\| ≤ 120 s + evidence of passing; works for drop-out and keep-stop feeds | ADR-004 |
| 11 | Coverage = observed ÷ scheduled | Classified per event: collected / collection_gap / outside_collection, using **collection sessions** (runs < 1 h apart); gaps inside a session count against coverage | METHODOLOGY §5 |
| 12 | Metro replacement buses | Excluded from scheduled events (`route_id` suffix `-R:` / "Replacement Bus"); not in the RT feed | `stg_gtfs_routes` |
| 13 | Bootstrap CI | Trip-**clustered** bootstrap (stops on a trip are correlated); Wilson bound kept as SQL guard | `analysis/bootstrap.py`, tests |
| 14 | Sample for CI | Real timetable slice + **synthetic** realtime (clearly labelled), exercising every edge case | `tests/sample/README.md` |
| 15 | Static GTFS 255.45 MB | 267,860,262 bytes (16 Oct 2026 release); nested `N/google_transit.zip` confirmed | `docs/schedule_validation.md` |
| 16 | `scripts/run_sample.py` builds + opens dashboard | Implemented; `run_pipeline.py` is the general runner (passes `study.yaml` as dbt vars) | README Quickstart |

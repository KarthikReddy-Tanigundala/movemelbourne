# MoveMelbourne: a beginner's guide

Read this first if you want to understand the whole project, from "what is it for?" to "which file
do I open to change X?". No prior knowledge of GTFS, dbt or data engineering is assumed. Reading
time: about 25 minutes.

---

## 1. The idea in one minute

**Question:** how reliable are Melbourne's trains and trams?

**Problem:** Victoria publishes a *live* feed saying where every train and tram is and when it
will reach each stop. But the feed only shows *now*. Nothing is archived. If you don't write it
down, it's gone.

**Solution (this project):**

1. **Record** the live feeds every minute, for four weeks.
2. **Compare** what happened against the **timetable** (what *should* have happened).
3. **Measure**: what share of arrivals were on time, how late the worst ones were, which trips
   were cancelled, which routes and stops are the worst, and when trams bunch up.
4. **Show** the results on a dashboard, and be honest about what the data can't tell us.

The project is also a **portfolio piece**: it demonstrates a real, running data pipeline (not a
one-off analysis of a downloaded CSV).

---

## 2. Vocabulary you need (plain English)

| Term | Meaning |
|---|---|
| **GTFS** | A standard file format for **timetables**: routes, trips, stops, and the scheduled time at each stop. Published as a zip of text files. |
| **GTFS Schedule** | The timetable zip. Victoria replaces it weekly and it only covers the next ~30 days. |
| **GTFS-Realtime (GTFS-RT)** | A standard for **live** data. Three feeds: *trip updates* (predicted arrival times), *vehicle positions* (GPS), *service alerts* (disruptions). |
| **Protobuf** | The compact binary format GTFS-RT arrives in. We decode it into normal tables. |
| **API key** | A password-like code that lets us call Victoria's API. Lives only in your private `.env` file. |
| **Trip** | One vehicle's run along a route at a specific time (e.g. the 08:14 Frankston train). |
| **Service date** | The *operating day* a trip belongs to. A 00:30 tram belongs to the *previous* day's timetable. |
| **Delay** | Actual arrival minus scheduled arrival, in seconds. Negative = early. |
| **OTP (on-time performance)** | The share of arrivals that were "on time". Metro: no more than 4 min 59 s late. Tram: no more than 59 s early and 4 min 59 s late. |
| **Proxy OTP** | *Our* version of OTP, measured at every stop. The official figure is measured differently, so ours is labelled "proxy" everywhere and is not official. |
| **Coverage** | The share of arrivals we were actually able to observe. Always shown next to OTP, so a number built on thin data looks thin. |
| **Reliability** | Share of scheduled trips that actually ran (1 minus the share cancelled). |
| **P50 / P90 / P95** | Percentiles: "90% of arrivals were no later than the P90 delay". Better than an average, because a few huge delays distort averages. |
| **Headway / bunching** | Headway is the gap between consecutive trams. Bunching is when a tram arrives in under half the scheduled gap, so two arrive together and then there's a long wait. |
| **Parquet** | A compact, fast table file format (what we store collected data in). |
| **DuckDB** | A database that lives in one file and is very fast at analysis. No server needed. |
| **dbt** | A tool for turning raw tables into clean, tested tables with plain SQL files. Think "a recipe book for data, with automatic quality checks". |
| **Star schema** | A tidy layout: **fact** tables (events, such as one row per stop arrival) surrounded by **dimension** tables (descriptions: route, stop, date). |

---

## 3. The big picture

```
 Victoria's live feeds ──► COLLECTOR ──► Hugging Face dataset (public storage)
 (every 60 seconds)       (GitHub Actions                │
                           + your laptop)                ▼
 Victoria's timetable ──► weekly snapshot ──►     LOCAL "LAKE" folder (data/lake)
                                                         │
                                                         ▼
                                        DuckDB "bronze" views (raw tables)
                                                         │   dbt
                                                         ▼
                              staging → intermediate → marts (star schema, tested)
                                                         │
                                         ┌───────────────┴───────────────┐
                                         ▼                               ▼
                                 Streamlit dashboard            Power BI report
```

Think of it as five stages: **collect → store → clean → measure → show**.

---

## 4. Stage by stage

### Stage 1: Collect (`src/movemelbourne/collect/`)

The collector is a Python program that, every 60 seconds, asks Victoria's API for six feeds
(metro and tram × trip updates, vehicle positions, service alerts), decodes them, and saves them
as Parquet files.

Details worth knowing:

- **Login negotiation.** Victoria's own documents disagree about how to send the API key. The
  client tries each method and remembers the one that works (`KeyID` header, found by testing).
- **Polite polling.** At most 6 calls a minute per mode, far under the published limit.
- **Runs.** One run lasts about 29 minutes, and a new one starts every 30 minutes.
- **Crash safety.** Every 5 minutes the data so far is written to disk (atomically, so a power cut
  can't leave a corrupt file). On the next start, any unfinished run is recovered and uploaded.
- **Coverage log.** Each run also writes a record: how many polls were attempted, succeeded,
  failed. That's how we measure what we missed.
- **Two collectors.** GitHub's servers (primary: never sleep) and the local Windows task (backup).
  If both capture the same snapshot, the warehouse removes the duplicate.

Files: `client.py` (talking to the API), `parse.py` (decoding), `run_collection.py` (the loop,
checkpoints, recovery), `upload.py` (sending to Hugging Face).

### Stage 2: Store

- **Hugging Face dataset** (`Karry001/movemelbourne-gtfsr`): the public home of the raw data, so
  anyone can rebuild the project. The git repo stays small because it holds no data.
- **The lake** (`data/lake/raw/...`): a local copy with the *same folder layout* as the dataset.
  Everything (collector runs, timetable snapshots, downloads from Hugging Face) lands there.
- **Timetable snapshots** (`ingest/static_snapshot.py`): every Monday, GitHub downloads Victoria's
  timetable zip and saves it as an immutable **`feed_version`** (date + a fingerprint of the file).
  Why? Because the timetable changes weekly, and a delay measured last Tuesday must be compared
  against *last Tuesday's* timetable, not today's.

### Stage 3: Clean (dbt, `dbt/models/`)

dbt runs SQL files in order, and each file is one table. Three layers:

| Layer | What it does | Examples |
|---|---|---|
| **staging** (`stg_*`) | Rename and type-cast raw columns. No logic. | `stg_rt_trip_updates`, `stg_gtfs_stops` |
| **intermediate** (`int_*`) | The real thinking: join, deduplicate, infer. | `int_scheduled_stop_events`, `int_observed_stop_events`, `int_stop_events_matched` |
| **marts** (`dim_*`, `fact_*`, `agg_*`) | The final, documented, tested tables the dashboards read. | `fact_stop_event`, `dim_route`, `agg_otp_daily_mode` |

**The clever part: inferring when a vehicle actually arrived.** The live feed gives
*predictions*, not arrivals ("it will reach stop 12 at 08:14:30"). We estimate the arrival from the
**last prediction made just before the vehicle reached the stop** (within 2 minutes), and
cross-check against GPS positions. Where we can't tell, the event is marked **unobserved** and is
*never guessed*. It lowers coverage but never touches OTP. Full reasoning: `METHODOLOGY.md`,
`docs/adr/ADR-004`.

**Other things this layer handles:**
- Timetable times can exceed 24:00 (`25:12:00` = 1:12 am next day).
- Daylight saving days (the "start of day" isn't midnight on those days).
- Cancelled trips, skipped stops, and "added" trips not in the timetable.
- Collection gaps: events during a gap in our recording are classified as `collection_gap`,
  separate from "outside collection".

**Tests (150 of them).** Examples: every key is unique; every fact row links to a real route/stop;
at least 95% of live trips match the timetable (if Victoria changes its ID format, the build
**fails loudly**); scheduled times never go backwards within a trip; unobserved events never carry
a delay.

### Stage 4: Measure (the marts)

| Table | Answers |
|---|---|
| `agg_otp_daily_mode` | How did each mode do each day (OTP, P50/P90/P95, reliability, coverage)? |
| `agg_otp_route` / `agg_otp_daily_route` | Which routes are best and worst? |
| `agg_otp_stop` | Which stops have the worst delays (for the map)? |
| `agg_segment_delay` | Between which two stops is time being lost? |
| `agg_otp_hour_dow` | Which hours and days go wrong (peak vs off-peak, weekends, holidays)? |
| `agg_headway_adherence` | How much do trams bunch? |
| `agg_disruption_otp` | Is punctuality worse while an alert is active? |
| `agg_coverage_daily` | What did we capture and miss, and did the join to the timetable work? |
| `agg_inference_agreement` | How closely do the two arrival-timing methods agree? |

**Fair ranking.** A route with 5 observations could look perfect by luck. So routes are ranked by
the **lower end of a 95% confidence interval** (`analysis/bootstrap.py`), which resamples whole
*trips* (stops on one trip are not independent). Cells with fewer than 30 observations are greyed
out and never ranked.

### Stage 5: Show

- **Streamlit dashboard** (`app/`): 8 pages (Network health, Route reliability, Delay map, When it
  goes wrong, Tram bunching, Disruptions, Data quality & method, Live now). It never touches the
  database: it reads small pre-built files in `app/data/` made by `scripts/export_gold.py`.
- **Power BI** (`powerbi/`): written instructions (data model, 20+ DAX measures, page layouts, a
  theme). The `.pbix` file itself must be built by hand in Power BI Desktop.
- **dbt docs site**: auto-generated documentation and a lineage diagram, published on GitHub Pages.

---

## 5. Honesty features (why this is not "just charts")

1. Every OTP number shows **coverage** and **sample size**.
2. Small samples are **greyed out**, not ranked.
3. Unobserved events are **never imputed**.
4. Everything is labelled **proxy**, with a written explanation of why it differs from official
   figures (`docs/adr/ADR-007`).
5. Synthetic data is **loudly labelled**: the committed sample (`tests/sample`) has *simulated*
   realtime data over a real timetable, used only so tests and demos work without an API key.
   The dashboard shows a banner whenever it's showing it.
6. Known limits are written down: metro times are whole minutes; the metro feed excludes
   replacement buses; arrivals are inferred from 60-second snapshots.

---

## 6. Folder map: "where do I look for...?"

```
movemelbourne/
├── README.md              start here for the pitch, links, quickstart
├── METHODOLOGY.md         how every number is computed, and the limitations
├── ARCHITECTURE.md        diagrams, components, tests, workflows
├── DATA_DICTIONARY.md     every column of every final table (generated)
├── CLAUDE.md              the original spec + an errata table of what changed and why
├── config/
│   ├── feeds.yaml         API endpoints, polling speed, login method order
│   └── study.yaml         study dates, thresholds (on-time window, min sample...)
├── src/movemelbourne/
│   ├── collect/           the live collector
│   ├── ingest/            timetable snapshot + service calendar
│   ├── load/              sync from Hugging Face; DuckDB "bronze" views
│   ├── analysis/          confidence intervals
│   └── utils/             time/DST maths, secret-hiding logs, the data "lake" layout
├── dbt/                   models/ (SQL), seeds/ (small CSVs), tests/, macros/
├── app/                   Streamlit dashboard (views/ = pages, data/ = pre-built files)
├── powerbi/               model, DAX, page spec, theme
├── scripts/               run_pipeline, export_gold, probe_feeds, collector_status, ...
├── tests/                 Python tests, real captured feed samples, the synthetic sample
├── docs/
│   ├── adr/               8 "why we decided X" records
│   ├── feed_behaviour.md  what the live feeds really do
│   ├── volume_estimate.md how much data we expect
│   └── STUDY_REPORT.md    template, filled in after the study
└── .github/workflows/     the automation (below)
```

**The automation (GitHub Actions):**

| Workflow | When | Does |
|---|---|---|
| `collect.yml` | every 30 min | Runs the collector on GitHub's servers |
| `static_snapshot.yml` | Mondays | Saves the new timetable version |
| `coverage_check.yml` | daily | Opens an issue if collection stalled or had gaps |
| `ci.yml` | every push | Lint, tests, a full dbt build on the sample, secret scan |
| `dbt_docs.yml` | dbt changes | Publishes the docs website |

---

## 7. Trying it yourself (Windows, PowerShell)

Run from `C:\Users\karth\Downloads\movemelbourne`. The `.venv` Python is used directly, so you
don't need `uv` on your PATH.

**See the project working, with no API key (uses the synthetic sample):**
```bash
.\.venv\Scripts\python.exe scripts\run_sample.py
```
It builds the database, runs all 150 checks, exports the dashboard files and opens the dashboard.

**Check that data collection is healthy:**
```bash
.\.venv\Scripts\python.exe scripts\collector_status.py
```

**Build the warehouse on your real collected data, then look at it:**
```bash
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```
```bash
.\.venv\Scripts\python.exe scripts\export_gold.py --app-dir data/app_preview --no-powerbi
```
Then launch `app/streamlit_app.py` with the environment variable `MOVEMELBOURNE_APP_DATA`
pointing at `data\app_preview`.

**Run the tests:**
```bash
.\.venv\Scripts\python.exe -m pytest
```

**Rule:** your API key and token live only in `.env`, which is gitignored. Never paste them into
chat, code or commits.

---

## 8. Following one number from start to finish

Take "tram route 96 was 4 min late at Stop X at 08:15 on a Thursday":

1. **Collector** polls the tram trip-updates feed at 08:14 and 08:15. In it, trip
   `03-96--8-T5-…` is predicted to reach Stop X at 08:19:20.
2. **Timetable** (the `feed_version` in force that Thursday) says it was due at 08:15:20. The
   scheduled time is computed from the service date plus the timetable's elapsed seconds
   (DST-safe) in `int_scheduled_stop_events`.
3. **Inference** (`int_observed_stop_events`): the last prediction within 2 minutes of the
   snapshot says 08:19:20, so observed minus scheduled = **+240 s** (4:00 late).
4. **Matching** (`int_stop_events_matched`) joins the schedule to the observation and labels the
   event `observed`.
5. **Fact table** (`fact_stop_event`): `delay_seconds = 240`; tram window says ≤ 299 s is on time,
   so `is_on_time = true`.
6. **Aggregate** (`agg_otp_daily_route`): this event is one of many; route 96's OTP that day is
   on-time events ÷ observed events, shown with its coverage.
7. **Export + dashboard**: the Route reliability page shows that route with a confidence interval.

---

## 9. Common questions

**Why isn't this just a Jupyter notebook?** Because the point is a *pipeline*: it keeps collecting,
rebuilds from scratch, is tested, and fails loudly when something upstream changes.

**Why DuckDB and not a cloud warehouse?** Free, fast on Parquet, one file, and anyone can reproduce
the whole thing (ADR-006).

**Why compare to the timetable "in force that day"?** The timetable file changes weekly. Using
today's file for old data would mismatch trips (ADR-005).

**Why is some data missing from 22-25 Oct?** The laptop collector slept on battery and rebooted.
Those gaps are measured in the coverage report. GitHub's collector fixes this going forward.

**Is this official punctuality?** No. It's an independent proxy. The comparison with official
figures goes in `docs/validation.md` after the study.

**What's still to do?** Wait for 14-28 days of data; then write the study report and validation,
switch the dashboard to real data, deploy it on Streamlit Cloud, and build the Power BI report.

---

## 10. A 60-second explanation (for interviews)

> "Victoria's live train and tram feeds aren't archived, so I built a collector that polls them
> every minute on GitHub Actions and stores the snapshots as Parquet in a public Hugging Face
> dataset. Each day is joined to the timetable that was in force that day, versioned by hash. The
> feeds give predictions, not arrivals, so I infer the actual arrival from the last prediction
> before the stop drops out, cross-check it against vehicle positions, and never impute what I
> can't observe. It's modelled as a star schema in dbt on DuckDB with 150 tests, including a
> match-rate test that fails if Victoria changes its trip ID format. I report on-time
> performance as a proxy, always with coverage and a trip-clustered bootstrap interval, and I
> compare it with the official figures to explain the gap."

---

## 11. Where to read next

1. `README.md`: the pitch and quickstart
2. `METHODOLOGY.md`: how every number is computed
3. `docs/feed_behaviour.md`: what the live data is really like
4. `docs/adr/`: why each big decision was made
5. `ARCHITECTURE.md` and the dbt docs site: how it fits together
6. The code, in this order: `collect/parse.py` → `collect/run_collection.py` →
   `dbt/models/intermediate/int_observed_stop_events.sql` → `dbt/models/marts/fact_stop_event.sql`

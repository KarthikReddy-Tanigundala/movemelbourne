---
license: cc-by-4.0
pretty_name: MoveMelbourne - Melbourne train & tram GTFS-Realtime snapshots
language:
  - en
tags:
  - gtfs
  - gtfs-realtime
  - public-transport
  - melbourne
  - victoria
  - australia
  - transport
  - time-series
  - geospatial
size_categories:
  - 10M<n<100M
configs:
  - config_name: trip_updates
    data_files: "raw/realtime/trip_updates/**/*.parquet"
  - config_name: vehicle_positions
    data_files: "raw/realtime/vehicle_positions/**/*.parquet"
  - config_name: service_alerts
    data_files: "raw/realtime/service_alerts/**/*.parquet"
  - config_name: coverage
    data_files: "raw/coverage/**/*.parquet"
---

# MoveMelbourne: Melbourne train & tram GTFS-Realtime snapshots

Self-collected, minute-by-minute snapshots of Victoria's **GTFS-Realtime** feeds for **Metro
Trains** and **Yarra Trams**, plus every weekly **GTFS Schedule** release in force during the
collection. GTFS-Realtime is live-only (there is no public Melbourne archive), so this dataset
preserves what the feeds said, to measure punctuality and reliability after the fact.

Built for the **MoveMelbourne** project: https://github.com/KarthikReddy-Tanigundala/movemelbourne
(method, data model and limitations).

## Source and licence

Contains data from the **Department of Transport and Planning (Victoria)**: GTFS Schedule and
GTFS-Realtime, published under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/)
via the [Transport Victoria Open Data Portal](https://opendata.transport.vic.gov.au/). This
dataset is a reformatted copy (protobuf flattened to Parquet) and keeps the same licence. It is
not an official DTP product; figures derived from it are independent estimates, not official
performance results.

## Collection

- **Feeds:** `metro` and `tram` × `trip-updates`, `vehicle-positions`, `service-alerts`
  (`https://api.opendata.transport.vic.gov.au/opendata/public-transport/gtfs/realtime/v1/{mode}/{feed}`).
- **Cadence:** each feed is polled every 60 s in 29-minute runs every 30 minutes. A snapshot whose
  `header.timestamp` matches the previous one (DTP caches ~30 s) is counted but not stored.
- **Collectors:** a local bridge collector (from 22 Oct 2026 00:35 AEDT) and GitHub Actions (from
  25 Oct 2026). Overlapping snapshots from both are expected; deduplicate on
  `(mode, feed_ts, trip_id, stop_sequence)`.
- **Study window:** planned 22 Oct – 19 Nov 2026 (includes Melbourne Cup Day, 3 Nov).
- **Gaps:** the local collector missed many hours on 22–25 Oct (laptop sleep and power loss).
  Every run writes a row to `raw/coverage`, so gaps are measurable rather than hidden.

## Layout

```
raw/realtime/trip_updates/mode={metro|tram}/dt=YYYY-MM-DD/run_<run_id>[_cNNN].parquet
raw/realtime/vehicle_positions/...      raw/realtime/service_alerts/...
raw/coverage/dt=YYYY-MM-DD/run_<run_id>.parquet          one row per run x mode x feed
raw/pb_samples/...                                       first raw protobuf per feed per run (gzip)
raw/schedule/feed_version=<date>_<sha8>/mode_branch={2|3}/<table>.parquet   GTFS Schedule, all strings
raw/schedule_versions/feed_version=<v>.parquet           release metadata (sha256, calendar span)
```

`dt` is the Melbourne-local date of the run start; `_cNNN` are 5-minute checkpoint chunks.

### Main columns

| Table | Grain | Key columns |
|---|---|---|
| trip_updates | stop_time_update × snapshot (one stop-less row for trips with none, e.g. CANCELED) | `feed_ts`, `poll_ts_utc`, `trip_id`, `route_id`, `start_date`, `trip_schedule_relationship`, `stop_sequence`, `stop_id`, `arrival_time`, `arrival_delay`, `departure_time`, `departure_delay`, `stu_schedule_relationship`, `extra_json` |
| vehicle_positions | vehicle × snapshot | `feed_ts`, `vehicle_id`, `trip_id`, `start_date`, `latitude`, `longitude`, `bearing`, `vehicle_ts` |
| service_alerts | alert × informed entity × active period × snapshot | `alert_id`, `active_start`, `active_end`, `cause`, `effect`, `header_text`, `description_text`, `route_id`, `stop_id`, `direction_id` |
| coverage | run × mode × feed | `run_id`, `collector`, `run_start_utc`, `run_end_utc`, `polls_attempted`, `polls_succeeded`, `polls_duplicate`, `auth_method`, `rows_written` |

Times are POSIX epoch seconds (UTC). Fields DTP adds later land in `extra_json`.

## Feed behaviour worth knowing

Measured on the live feeds (details in the repo's `docs/feed_behaviour.md`):

- Metro trip updates list all remaining stops and keep a passed stop for 1–4 minutes. **Metro
  times are whole minutes.** Tram trip updates list only the current and next one or two stops,
  to the second.
- Vehicle positions carry no `current_status`, `stop_id` or `speed`; about a quarter of metro
  positions are more than 3 minutes old.
- The metro trip-updates feed excludes replacement buses, service deviations and platforms.

## Loading

```python
import duckdb
from huggingface_hub import snapshot_download

path = snapshot_download("Karry001/movemelbourne-gtfsr", repo_type="dataset",
                         allow_patterns=["raw/realtime/trip_updates/**", "raw/coverage/**"])
duckdb.sql(f"""
    select mode, count(distinct feed_ts) as snapshots, count(*) as rows
    from read_parquet('{path}/raw/realtime/trip_updates/**/*.parquet', union_by_name = true)
    group by mode
""").show()
```

## Citation

> Tanigundala, K. R. (2026). *MoveMelbourne: Melbourne train & tram GTFS-Realtime snapshots*
> [Data set]. Hugging Face. https://huggingface.co/datasets/Karry001/movemelbourne-gtfsr.
> Contains data from the Department of Transport and Planning (Victoria), CC BY 4.0.

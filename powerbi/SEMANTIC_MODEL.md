# Power BI semantic model (MANUAL build)

> **Status:** these are build instructions. The `.pbix` does not exist until Karthik builds it
> by hand in Power BI Desktop. Nothing in this repo claims it has been built or published.

## 1. Get the data

```bash
uv run python scripts/run_pipeline.py          # build the warehouse (real data)
uv run python scripts/export_gold.py           # writes powerbi/data/*.parquet
```

(`--sample` on both commands produces the synthetic sample instead: fine for building the
report layout, but every page must then show the "Synthetic sample" banner.)

**Storage mode: Import** for every table. The report never needs a live connection; refreshing
means re-running the export and clicking Refresh.

Load each Parquet file with *Get data → Parquet*, or paste this Power Query (M) per table, changing
the file name. A `DataFolder` parameter keeps the path in one place:

```m
// Home > Manage parameters > New: DataFolder (Text) = C:\Users\karth\Downloads\movemelbourne\powerbi\data\
let
    Source = Parquet.Document(File.Contents(DataFolder & "fact_stop_event.parquet"))
in
    Source
```

Set data types after loading: keys as **Text**, `date_key` / `time_band_key` / `direction_id` /
`stop_sequence` as **Whole number**, `*_pct` as **Decimal**, `scheduled_arrival_local` /
`observed_arrival_local` as **Date/Time**, booleans as **True/False**.

## 2. Tables

| Table | Grain | Rows (sample) | Role |
|---|---|---|---|
| `fact_stop_event` | service date × trip × stop | ~5k sample / millions real | Punctuality, delay, coverage |
| `fact_trip` | service date × scheduled trip | ~240 sample | Reliability (cancellations) |
| `fact_alert` | alert × informed entity × active period | small | Disruptions |
| `agg_coverage_daily` | service date × mode | small | Coverage & collector health |
| `agg_headway_adherence` | date × tram route × direction × time band | small | Bunching |
| `agg_segment_delay` | route × stop pair | small | Where time is lost (map) |
| `agg_route_summary` | route | small | Ranking with bootstrap CI |
| `agg_disruption_otp` | route × in/out of alert window | small | Disruption impact |
| `dim_date` | service date | study days | **Mark as date table** on `date_day` |
| `dim_time_band` | hour of day | 24 | Peak / off-peak |
| `dim_mode` | mode | 2 | Targets and on-time definitions |
| `dim_route` | route | | Names, colours |
| `dim_stop` | stop / platform | | Names, coordinates |
| `dim_trip` | trip_id | | Headsign, direction |

## 3. Relationships (star; all many-to-one, single direction, dimension filters fact)

| From (many) | To (one) | Key |
|---|---|---|
| `fact_stop_event[date_key]` | `dim_date[date_key]` | Whole number |
| `fact_stop_event[time_band_key]` | `dim_time_band[time_band_key]` | Whole number |
| `fact_stop_event[mode]` | `dim_mode[mode]` | Text |
| `fact_stop_event[route_key]` | `dim_route[route_key]` | Text |
| `fact_stop_event[stop_key]` | `dim_stop[stop_key]` | Text |
| `fact_stop_event[trip_key]` | `dim_trip[trip_key]` | Text |
| `fact_trip[date_key]` | `dim_date[date_key]` | |
| `fact_trip[time_band_key]` | `dim_time_band[time_band_key]` | |
| `fact_trip[mode]` | `dim_mode[mode]` | |
| `fact_trip[route_key]` | `dim_route[route_key]` | |
| `fact_trip[trip_key]` | `dim_trip[trip_key]` | |
| `fact_alert[route_key]` | `dim_route[route_key]` | |
| `fact_alert[mode]` | `dim_mode[mode]` | |
| `agg_coverage_daily[date_key]` | `dim_date[date_key]` | |
| `agg_coverage_daily[mode]` | `dim_mode[mode]` | |
| `agg_headway_adherence[date_key]` | `dim_date[date_key]` | |
| `agg_headway_adherence[route_key]` | `dim_route[route_key]` | |
| `agg_segment_delay[route_key]` | `dim_route[route_key]` | |
| `agg_route_summary[route_key]` | `dim_route[route_key]` | |
| `agg_disruption_otp[route_key]` | `dim_route[route_key]` | |

Rules: **no bidirectional filters, no many-to-many.** Do not relate `dim_trip` to `dim_route`
(that would snowflake the model and create two filter paths from route to fact). Hide every key
column and every raw numeric column that a measure replaces (`delay_seconds`, flags) from report view.

## 4. Formatting

- Apply `powerbi/theme.json` (View → Themes → Browse). It carries the same colour tokens as the
  Streamlit app: Metro = `#2a78d6`, Yarra Trams = `#eb6834`, sequential blue ramp, status colours.
- `dim_route[route_display_name]` sorted by `dim_route[route_short_name]`;
  `dim_time_band[time_band]` sorted by `dim_time_band[time_band_sort]`;
  `dim_date[day_type]` in the order Weekday, Saturday, Sunday / public holiday.
- Percent measures: format as Percentage, 1 decimal. Delay measures: decimal minutes, 1 decimal.

## 5. Validation before publishing (MANUAL)

Compare these Power BI card values with the Streamlit "Network health" page for the same data:
Proxy OTP %, Coverage %, Reliability % per mode. They must match to 0.1 pt (both read the same
gold tables). Any difference means a relationship or filter is wrong.

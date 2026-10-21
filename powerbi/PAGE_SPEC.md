# Report page specification (MANUAL build)

Canvas 16:9 (1280 × 720). Every page has the same header band:

- **Title**: a dynamic card using `Page Title - Network` (or the page's own title text).
- **Data stamp**: card with `Data Stamp`.
- **Synthetic badge**: a text box "SYNTHETIC SAMPLE: not real Melbourne services", shown only
  when the report was built from `--sample` data. Delete it for the real study build.
- **Footer**: "Data: Department of Transport and Planning, GTFS Schedule and GTFS Realtime,
  CC BY 4.0. MoveMelbourne figures are independent proxy estimates, not official performance
  results."

Slicers sit in one row under the header: **Mode** (`dim_mode[mode_label]`, tiles),
**Date** (`dim_date[date_day]`, between), **Day type** (`dim_date[day_type]`),
**Time band** (`dim_time_band[time_band]`).

## Page 1 - Network overview

| Visual | Fields | Notes |
|---|---|---|
| 4 KPI cards per mode (small multiples by `dim_mode[mode_label]`) | `Proxy OTP %`, `Reliability %`, `Coverage %`, `P90 Delay (min)` | Under OTP: `OTP Status` (icon + words). |
| Line chart | X `dim_date[date_day]`; Y `Proxy OTP %`; legend `dim_mode[mode_label]` | Constant line at each mode's target (`OTP Target %`), dashed grey; tooltip adds `Observed Stop Events`, `Coverage %`. |
| Column chart | X `fact_stop_event[delay_band]`; Y `Observed Stop Events` as % of column total | Order: Early, On time, Minor late, Major late. |
| Card | `Cancelled Trips`, `No-data Trips` | Shown side by side so "no data" is never mistaken for "cancelled". |

## Page 2 - Route scorecard with map

| Visual | Fields | Notes |
|---|---|---|
| Table | `dim_route[route_display_name]`, `agg_route_summary[otp_pct]`, `otp_ci_low_pct`, `otp_ci_high_pct`, `rank_by_ci_low`, `P90 Delay (min)`, `Reliability %`, `Coverage %`, `Observed Stop Events` | Sort by `rank_by_ci_low`. Conditional font colour on OTP via `Sample Size Flag` (grey when insufficient). Data bars on CI low. |
| Azure / ArcGIS map | Lat `dim_stop[stop_lat]`, Lon `dim_stop[stop_lon]`, size `Observed Stop Events`, colour saturation `P90 Delay (min)` | Single-hue sequential (theme blue), never red/green. Tooltip: stop name, P90, OTP, n. |
| Bar chart | `agg_segment_delay` top 10 by `median_added_delay_s` (filter `is_sample_sufficient`) | "Where time is lost": label `from_stop_name → to_stop_name`. |

## Page 3 - Time patterns

| Visual | Fields | Notes |
|---|---|---|
| Matrix heatmap | Rows `dim_date[day_type]`; columns `dim_time_band[hour_of_day]`; values `1 - Proxy OTP %` | Background colour scale: theme sequential blue (light = fewer late). Blank cells where `Sample Size Flag` = insufficient (use a visual-level filter on a helper measure). |
| Clustered column | X `dim_time_band[time_band]`; Y `Proxy OTP %`; legend mode | Peak vs off-peak. |
| Line | `OTP Rolling 7d` by date | Only meaningful once ≥ 14 days are collected. |
| Card | Holiday days | `dim_date[holiday_name]` for dates in range (e.g. Melbourne Cup Day). |

## Page 4 - Disruptions

| Visual | Fields | Notes |
|---|---|---|
| Table | `fact_alert` header text, route, active start/end, cause, effect | Sorted by start. |
| Clustered column | X `dim_route[route_display_name]`; Y `agg_disruption_otp[otp_pct]`; legend `agg_disruption_otp[during_disruption]` | Caption: "association, not causation". Grey where `is_sample_sufficient` is false. |
| Bar | `Bunching Rate %` and `Excess Wait (min)` by tram route | Grey bars where pairs < 30. |

## Accessibility checklist

- Never colour alone: status uses `OTP Status` text; maps use one sequential hue.
- Alt text on every visual (Format → General → Alt text) describing the takeaway.
- Tab order set (View → Selection → Tab order) header → slicers → KPIs → charts.
- Contrast: theme text colours meet WCAG AA on the light canvas.

## MANUAL deliverables

- [ ] `.pbix` built (Import mode) and saved as `powerbi/MoveMelbourne.pbix` (gitignored if > 50 MB)
- [ ] Screenshots of the four pages → `docs/images/powerbi_page{1..4}.png`
- [ ] Optional: publish to the Power BI service; record the URL in the README

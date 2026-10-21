# Methodology

How MoveMelbourne turns live prediction feeds into punctuality and reliability measures, what
each number means, and where its limits are. Design decisions are recorded in [docs/adr](docs/adr).

## 1. Data

| Source | What | How |
|---|---|---|
| GTFS-Realtime: trip updates, vehicle positions, service alerts (metro, tram) | Live predictions, positions, disruptions | Polled every 60 s, 24/7, for the study window (ADR-002) |
| GTFS Schedule | The timetable (rolling 30 days, replaced weekly) | Versioned snapshot every Monday (ADR-005) |

Both are published by the Department of Transport and Planning (DTP) under CC BY 4.0.

**Study window:** 28 consecutive days (minimum 14), with exact start and end in
`config/study.yaml` and the README. Melbourne Cup Day (Tue 3 Nov 2026) is a public holiday with a
special timetable. It is flagged in `dim_date` and analysed as a Sunday/public-holiday day type,
not treated as an error.

## 2. Inferring when a vehicle actually arrived

The feeds never say "arrived"; they say "will arrive at". MoveMelbourne infers arrivals and labels
how (`fact_stop_event.inference_method`):

1. **Last prediction** (primary, ADR-004). Of all the snapshots that listed this stop for this
   trip, keep the latest one whose predicted time was within **120 s** of the moment the snapshot
   was taken. Accept it only when the stop was not skipped, the following snapshot came within
   **180 s**, and there is evidence the stop was passed (it dropped out of the feed while the trip
   continued, the trip was still tracked after the predicted time, or the trip vanished while we
   were still polling).
2. **Vehicle position** (fallback). The first fresh position (≤ 180 s old) within 30 m of one of
   the trip's scheduled stops. DTP's vehicle-position feeds have no stop or status fields, so
   proximity is the signal ([docs/feed_behaviour.md](docs/feed_behaviour.md)).

Where both exist, their agreement is reported (`agg_inference_agreement`) as a self-check.

**Nothing is imputed.** A scheduled stop event with no accepted observation is `unobserved` and
lowers coverage. It never contributes to OTP.

Matching realtime to timetable: by `stop_sequence` when the feed sends it, otherwise by `stop_id`
or the parent station (feeds may report a platform where the timetable lists the station). The
service date comes from `TripDescriptor.start_date`. When that is missing, it is the service date
on which that `trip_id` runs closest in time to the snapshot, because trip IDs repeat every day a
service runs.

## 3. Metrics

| Metric | Definition | Where |
|---|---|---|
| **Delay** | observed arrival − scheduled arrival (seconds; negative = early) | `fact_stop_event.delay_seconds` |
| **Proxy OTP** | on-time ÷ observed events. Metro on time: delay ≤ 299 s. Tram: −59 s ≤ delay ≤ 299 s (ADR-007) | `agg_otp_*` |
| **Delay bands** | Early (beyond tolerance) / On time / Minor late (5–15 min) / Major late (> 15 min) | `delay_band` |
| **Distribution** | P50, P85, P90, P95 delay. A mean is never shown on its own | `agg_otp_*` |
| **Coverage** | observed ÷ collectable scheduled events (§5) | `agg_coverage_daily`, every OTP table |
| **Reliability** | 1 − confirmed cancelled ÷ scheduled trips wholly inside collected time; "no data" trips reported separately | `fact_trip`, `agg_otp_*` |
| **Segment delay** | change in delay between two adjacent observed stops of the same trip: where time is lost | `agg_segment_delay` |
| **Bunching** (trams) | at three proxy measurement points per route (regularly served stops nearest 25/50/75% along the trip), the share of consecutive observed tram pairs whose actual headway is < 0.5 × scheduled | `agg_headway_adherence` |
| **Headway CV** | standard deviation ÷ mean of actual headways | `agg_headway_adherence` |
| **Excess wait** | E[h²]/2E[h] of actual minus scheduled headways: the extra wait for a passenger arriving at random | `agg_headway_adherence` |
| **Disruption OTP** | proxy OTP for events whose scheduled time falls inside an active alert naming the route vs outside | `agg_disruption_otp` |

Delays outside −30 / +120 min are quarantined in `audit_outliers` and excluded from OTP
(`quality.delay_min_s` / `delay_max_s`).

## 4. Statistical honesty

- **Minimum sample:** any route, stop, hour or segment cell with fewer than **30** observed events
  is greyed out, shows its n on hover, and is never ranked.
- **Clustered uncertainty:** stops on the same trip share their delay, so route-level 95% CIs come
  from a **trip-clustered bootstrap** (2,000 resamples of whole trips, seed 42;
  `src/movemelbourne/analysis/bootstrap.py`). Routes are ranked by the **lower bound**. A per-stop
  binomial (Wilson) interval is kept only as a SQL-side guard, because it is too narrow. On the
  synthetic sample, Glen Waverley's bootstrap CI is 89.6–100% while the Wilson bound alone
  suggested 93.2%.
- **Comparisons are stratified:** weekday vs Saturday vs Sunday/public holiday, peak vs off-peak.
- **Association, not causation:** alerts are often issued *because* services are late.

## 5. Coverage and collection gaps

The collector heartbeat is the series of trip-update snapshots. Each scheduled stop event is
classified at its scheduled time:

| State | Meaning | Counts in coverage denominator |
|---|---|---|
| `collected` | snapshots before and after it, less than 180 s apart | yes |
| `collection_gap` | inside a collector session but in a poll gap > 180 s | **yes** (a miss) |
| `outside_collection` | no collector session at that time | no; reported as lost uptime |

A **session** is a run of collector runs less than 1 hour apart (`int_collection_sessions`), so a
normal restart between runs never hides a gap. Coverage per mode per day is published in
`agg_coverage_daily` and on the app's "Data quality" page.

## 6. Time handling

- Raw epochs (UTC) are the system of record. They are converted to Australia/Melbourne
  (DST-aware) only for bucketing.
- GTFS `stop_times` values are elapsed time since "noon minus 12 h" of the service day, may exceed
  24:00:00, and on DST days the reference is not midnight: 23:00 the evening before on
  DST-start day, 01:00 on DST-end day. `ref_epoch` is computed per service date in Python and
  unit-tested for both DST changes. A dbt test asserts that scheduled times never go backwards
  within a trip.

## 7. Validation against official figures

`docs/validation.md` will compare proxy OTP with the Victorian Government's official figures for
the same period. Monthly results are usually published around the 10th of the following month;
daily operational reports also exist, which allows a day-level comparison. Expected sources of
difference: measurement points (all stops vs operator monitoring points), early-running treatment,
replacement buses (absent from the feed), and coverage. The comparison is written only from
published figures; if they are not yet available, the document says so.

## 8. Limitations

- **Proxy, not official.** Use the official results for any contractual or public statement.
- **Feed exclusions.** The metro trip-updates feed omits replacement buses, service deviations
  (skipped stops, diversions) and platform information (DTP OpenAPI spec).
- **Inference uncertainty.** 60-second sampling bounds precision. Method agreement is published.
- **Metro minute resolution.** Metro realtime times are whole minutes, so metro delays are
  quantised to 60 s around the 4:59 threshold.
- **Coverage gaps.** API outages, GitHub Actions scheduling jitter and collector restarts. They are
  measured, not hidden.
- **Cancellation visibility.** Only trips flagged `CANCELED` count as cancelled; partial
  cancellations and short-shunts may appear as unobserved stops instead.
- **Synthetic sample.** The committed sample in `tests/sample` has simulated realtime data and is
  used only for testing and demonstration. No finding is drawn from it.

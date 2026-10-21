# ADR-005: Join each service date to the timetable that was in force that day

- **Status:** Accepted (2026-10-21)

## Context

DTP's GTFS Schedule is a rolling 30-day file replaced weekly (roughly 256 MB zipped). Its service IDs
are week-specific (`T2`, `T2_1`, `T2_2`, ...) and include holiday exceptions such as Melbourne
Cup Day (service `UU` on 3 Nov 2026). Joining three-week-old realtime data to today's file would
match the wrong trips, or none.

## Decision

- Every release is stored immutably as `feed_version = <download date>_<sha256[:8]>`
  (weekly workflow, skipped when the SHA-256 is unchanged).
- `int_feed_version_in_force` picks, per mode and service date, **the latest release downloaded on
  or before that date** whose calendar covers it. For dates before the first snapshot it falls back
  to the earliest release covering the date.
- The rule is pinned by a dbt **unit test** (`test_feed_version_in_force_picks_release_in_force`),
  including the Cup Day case.
- Scheduled instants are computed as `ref_epoch + GTFS seconds`, where `ref_epoch` is the GTFS
  "noon minus 12 h" reference computed in Python with `zoneinfo`. That handles times past 24:00 and
  both daylight-saving changes. On DST-start day the reference is 23:00 the previous evening, not
  midnight; this is covered by `tests/test_timeutil.py`.

## Consequences

- Trip and route IDs are joined exactly as delivered, never reshaped by regex. A daily
  **match-rate test** (`assert_trip_match_rate`, ≥ 95%) fails loudly if DTP changes an ID format.
- `dim_feed_version` is the audit trail: which release, its hash, its calendar span.
- Storage grows by about 13 MB of Parquet per weekly version (metro + tram).

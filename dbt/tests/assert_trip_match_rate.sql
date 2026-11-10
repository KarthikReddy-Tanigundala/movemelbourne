-- Join quality gate (CLAUDE.md §8.3): on any day with a meaningful number of realtime trips,
-- at least `min_match_rate` of them must match a scheduled trip. A drop means DTP changed the
-- trip_id format or the versioned timetable join broke - fail loudly, do not publish OTP.
-- Known unrecoverable days (reviewed 2026-11-10): the timetable release in force on these tram days
-- was never captured (weekly snapshots began 21/25 Oct; DTP rotated tram trip ids in between and
-- again on 5 Nov), so their trips cannot be matched. They stay in coverage as unmatched; any NEW
-- failing day still fails this test.
select
    service_date,
    mode,
    n_rt_trips,
    n_rt_trips_matched,
    trip_match_rate
from {{ ref('agg_coverage_daily') }}
where n_rt_trips >= 20
  and trip_match_rate < {{ var('min_match_rate') }}
  and (service_date, mode) not in (
    (date '2026-10-22', 'tram'),
    (date '2026-10-23', 'tram'),
    (date '2026-11-05', 'tram')
  )

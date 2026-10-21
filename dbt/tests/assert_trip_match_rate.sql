-- Join quality gate (CLAUDE.md §8.3): on any day with a meaningful number of realtime trips,
-- at least `min_match_rate` of them must match a scheduled trip. A drop means DTP changed the
-- trip_id format or the versioned timetable join broke - fail loudly, do not publish OTP.
select
    service_date,
    mode,
    n_rt_trips,
    n_rt_trips_matched,
    trip_match_rate
from {{ ref('agg_coverage_daily') }}
where n_rt_trips >= 20
  and trip_match_rate < {{ var('min_match_rate') }}

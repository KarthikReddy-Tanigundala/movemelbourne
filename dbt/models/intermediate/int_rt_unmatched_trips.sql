-- Realtime trips that do not match any scheduled trip on the resolved service date.
-- The join-quality test fails loudly if these rise above (1 - min_match_rate): that is the
-- signature of DTP changing trip_id formats (CLAUDE.md §3).
select
    p.mode,
    p.service_date,
    p.trip_id,
    p.route_id,
    p.service_date_source,
    p.is_added,
    p.is_canceled,
    p.n_polls,
    p.first_seen_feed_ts,
    p.last_seen_feed_ts
from {{ ref('int_rt_trip_presence') }} as p
left join {{ ref('int_scheduled_trips') }} as s
    on s.mode = p.mode
    and s.service_date = p.service_date
    and s.trip_id = p.trip_id
where s.trip_id is null

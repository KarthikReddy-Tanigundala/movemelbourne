-- One row per scheduled trip: did it run, was it cancelled, or do we simply not know?
-- Reliability = 1 - confirmed_cancelled / scheduled, using only trips whose whole timetabled
-- run fell inside collected time ("reliability-eligible"). "No data" (never in the feed while
-- we were polling) is reported separately, never silently counted as cancelled or as ran.
with stop_rollup as (
    select
        mode,
        service_date,
        trip_id,
        count(*) as n_stops,
        count(*) filter (where collection_state = 'collected') as n_collected_stops,
        count(*) filter (where match_status = 'observed') as n_observed_stops,
        min(delay_seconds) filter (where is_first_stop) as origin_delay_s,
        max(delay_seconds) filter (where is_last_stop) as destination_delay_s,
        max(delay_seconds) as max_delay_s
    from {{ ref('int_stop_events_matched') }}
    group by mode, service_date, trip_id
)

select
    t.mode,
    t.service_date,
    t.trip_id,
    t.feed_version,
    t.route_id,
    t.direction_id,
    t.shape_id,
    t.trip_headsign,
    t.first_departure_epoch,
    t.last_arrival_epoch,
    r.n_stops,
    r.n_collected_stops,
    r.n_observed_stops,
    r.origin_delay_s,
    r.destination_delay_s,
    r.max_delay_s,
    p.trip_id is not null as in_feed,
    coalesce(p.is_canceled, false) as is_canceled,
    p.n_polls,
    r.n_collected_stops = r.n_stops as is_reliability_eligible,
    case
        when coalesce(p.is_canceled, false) then 'cancelled'
        when p.trip_id is not null or r.n_observed_stops > 0 then 'ran'
        when r.n_collected_stops = r.n_stops then 'no_data'
        when r.n_collected_stops > 0 then 'partially_collected'
        else 'outside_collection'
    end as trip_outcome
from {{ ref('int_scheduled_trips') }} as t
inner join stop_rollup as r
    on r.mode = t.mode
    and r.service_date = t.service_date
    and r.trip_id = t.trip_id
left join {{ ref('int_rt_trip_presence') }} as p
    on p.mode = t.mode
    and p.service_date = t.service_date
    and p.trip_id = t.trip_id

-- Every scheduled stop event on every service date we collected, from the timetable version in
-- force that day (ADR-005). Scheduled instant = ref_epoch ("noon minus 12h", DST-correct,
-- computed in Python) + GTFS elapsed seconds, so 25:12:00 and DST days are handled exactly.
-- Replacement-bus routes are excluded: the realtime feed does not carry them (CLAUDE.md §2.2).
with study_dates as (
    -- A poll on local date D can see after-midnight trips of service date D-1.
    select distinct mode, poll_local_date as service_date from {{ ref('int_rt_polls') }}
    union
    select distinct mode, poll_local_date - 1 as service_date from {{ ref('int_rt_polls') }}
),

version_in_force as (
    select
        v.mode,
        v.service_date,
        v.feed_version
    from {{ ref('int_feed_version_in_force') }} as v
    inner join study_dates as d
        on d.mode = v.mode
        and d.service_date = v.service_date
),

running_services as (
    select
        c.mode,
        c.service_date,
        c.feed_version,
        c.service_id,
        c.ref_epoch
    from {{ ref('stg_service_calendar') }} as c
    inner join version_in_force as v
        on v.mode = c.mode
        and v.service_date = c.service_date
        and v.feed_version = c.feed_version
),

running_trips as (
    select
        s.mode,
        s.service_date,
        s.feed_version,
        s.ref_epoch,
        t.trip_id,
        t.route_id,
        t.direction_id,
        t.shape_id,
        t.trip_headsign
    from running_services as s
    inner join {{ ref('stg_gtfs_trips') }} as t
        on t.feed_version = s.feed_version
        and t.mode = s.mode
        and t.service_id = s.service_id
    inner join {{ ref('stg_gtfs_routes') }} as r
        on r.feed_version = t.feed_version
        and r.mode = t.mode
        and r.route_id = t.route_id
    where not r.is_replacement_bus
),

events as (
    select
        rt.mode,
        rt.service_date,
        rt.feed_version,
        rt.trip_id,
        rt.route_id,
        rt.direction_id,
        rt.shape_id,
        rt.trip_headsign,
        st.stop_sequence,
        st.stop_id,
        coalesce(sp.station_key, st.stop_id) as station_key,
        st.shape_dist_traveled_m,
        rt.ref_epoch + coalesce(st.arrival_secs, st.departure_secs) as scheduled_arrival_epoch,
        rt.ref_epoch + coalesce(st.departure_secs, st.arrival_secs) as scheduled_departure_epoch
    from running_trips as rt
    inner join {{ ref('stg_gtfs_stop_times') }} as st
        on st.feed_version = rt.feed_version
        and st.mode = rt.mode
        and st.trip_id = rt.trip_id
    left join {{ ref('stg_gtfs_stops') }} as sp
        on sp.feed_version = st.feed_version
        and sp.mode = st.mode
        and sp.stop_id = st.stop_id
)

select
    mode || '|' || service_date || '|' || trip_id || '|' || stop_sequence as event_id,
    mode,
    service_date,
    feed_version,
    trip_id,
    route_id,
    direction_id,
    shape_id,
    trip_headsign,
    stop_sequence,
    stop_id,
    station_key,
    shape_dist_traveled_m,
    scheduled_arrival_epoch,
    scheduled_departure_epoch,
    row_number() over trip_order = 1 as is_first_stop,
    row_number() over trip_order = count(*) over (partition by mode, service_date, trip_id)
        as is_last_stop,
    count(*) over (partition by mode, service_date, trip_id) as n_trip_stops,
    row_number() over trip_order as stop_position
from events
window trip_order as (partition by mode, service_date, trip_id order by stop_sequence)

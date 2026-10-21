-- Observed arrival from VEHICLE POSITIONS (secondary method, METHODOLOGY §2, ADR-004).
--
-- DTP's vehicle-position feeds (probe, 2026-10-21) carry trip, latitude/longitude and timestamp
-- only: no current_status, stop_id or speed. So the main signal is PROXIMITY: the first fresh
-- position within `vp_proximity_m` of one of the trip's own scheduled stops. If a future feed
-- version adds STOPPED_AT + stop_id, that signal is used too. Positions older than
-- `vp_max_age_s` at poll time are dropped (24% of metro positions were stale on day one), and a
-- report repeated across polls counts once.
-- With 60 s polling this is biased late by up to one poll interval and misses short dwells,
-- which is why it is the secondary method and why agreement is reported.
with positions as (
    select
        mode,
        trip_id,
        start_date,
        latitude,
        longitude,
        speed,
        current_status,
        stop_id,
        observed_ts
    from {{ ref('stg_rt_vehicle_positions') }}
    where trip_id is not null
      and latitude is not null
      and feed_ts - observed_ts <= {{ var('vp_max_age_s') }}
    qualify row_number() over (partition by mode, trip_id, observed_ts order by feed_ts) = 1
),

dated as (
    select
        p.*,
        coalesce(p.start_date, st.service_date) as service_date
    from positions as p
    left join {{ ref('int_scheduled_trips') }} as st
        on p.start_date is null
        and st.mode = p.mode
        and st.trip_id = p.trip_id
        and p.observed_ts between st.first_departure_epoch - 7200 and st.last_arrival_epoch + 7200
    qualify row_number() over (
        partition by p.mode, p.trip_id, p.observed_ts
        order by greatest(st.first_departure_epoch - p.observed_ts,
                          p.observed_ts - st.last_arrival_epoch, 0)
    ) = 1
),

trip_stops as (
    select
        e.mode,
        e.service_date,
        e.trip_id,
        e.stop_sequence,
        e.stop_id,
        e.station_key,
        e.scheduled_arrival_epoch,
        s.stop_lat,
        s.stop_lon
    from {{ ref('int_scheduled_stop_events') }} as e
    inner join {{ ref('stg_gtfs_stops') }} as s
        on s.feed_version = e.feed_version
        and s.mode = e.mode
        and s.stop_id = e.stop_id
),

candidates as (
    -- Explicit signal, when the feed provides one.
    select
        d.mode,
        d.service_date,
        d.trip_id,
        t.stop_sequence,
        d.observed_ts,
        'stopped_at' as vp_signal
    from dated as d
    inner join trip_stops as t
        on t.mode = d.mode
        and t.service_date = d.service_date
        and t.trip_id = d.trip_id
        and (t.stop_id = d.stop_id or t.station_key = d.stop_id)
    where d.current_status = 'STOPPED_AT'

    union all

    -- Proximity to the trip's own scheduled stops (the signal DTP's feeds actually support).
    -- The time window keeps the distance join small: a stop is a candidate only within
    -- 30 min early to 60 min late of its schedule.
    select
        d.mode,
        d.service_date,
        d.trip_id,
        t.stop_sequence,
        d.observed_ts,
        'proximity' as vp_signal
    from dated as d
    inner join trip_stops as t
        on t.mode = d.mode
        and t.service_date = d.service_date
        and t.trip_id = d.trip_id
        and d.observed_ts between t.scheduled_arrival_epoch - 1800 and t.scheduled_arrival_epoch + 3600
    where (d.speed is null or d.speed <= {{ var('vp_max_speed_mps') }})
      and {{ haversine_m('d.latitude', 'd.longitude', 't.stop_lat', 't.stop_lon') }}
          <= {{ var('vp_proximity_m') }}
)

select
    mode,
    service_date,
    trip_id,
    stop_sequence,
    min(observed_ts) as vp_arrival_epoch,
    arg_min(vp_signal, observed_ts) as vp_signal,
    count(*) as n_vp_snapshots
from candidates
where service_date is not null
group by mode, service_date, trip_id, stop_sequence

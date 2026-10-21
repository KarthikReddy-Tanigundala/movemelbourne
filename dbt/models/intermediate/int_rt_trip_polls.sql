-- One row per (mode, service_date, trip_id, snapshot). Resolves the service date:
-- TripDescriptor.start_date when present; otherwise derived from the schedule by finding the
-- service date whose run of this trip_id is closest in time to the snapshot (trip_ids repeat
-- every day a service runs, so the local calendar date alone is ambiguous after midnight).
with trip_polls as (
    select
        mode,
        trip_id,
        start_date,
        feed_ts,
        any_value(route_id) as route_id,
        any_value(direction_id) as direction_id,
        any_value(vehicle_id) as vehicle_id,
        bool_or(trip_schedule_relationship = 'CANCELED') as is_canceled,
        bool_or(trip_schedule_relationship = 'ADDED') as is_added,
        max(n_stop_time_updates) as n_stop_time_updates
    from {{ ref('stg_rt_trip_updates') }}
    group by mode, trip_id, start_date, feed_ts
),

undated as (
    select distinct mode, trip_id, feed_ts
    from trip_polls
    where start_date is null
),

derived as (
    select
        u.mode,
        u.trip_id,
        u.feed_ts,
        s.service_date
    from undated as u
    inner join {{ ref('int_scheduled_trips') }} as s
        on s.mode = u.mode
        and s.trip_id = u.trip_id
        and u.feed_ts between s.first_departure_epoch - 7200 and s.last_arrival_epoch + 7200
    qualify row_number() over (
        partition by u.mode, u.trip_id, u.feed_ts
        order by greatest(s.first_departure_epoch - u.feed_ts, u.feed_ts - s.last_arrival_epoch, 0)
    ) = 1
)

select
    p.mode,
    coalesce(p.start_date, d.service_date, {{ local_ts('p.feed_ts') }}::date) as service_date,
    case
        when p.start_date is not null then 'start_date'
        when d.service_date is not null then 'derived_from_schedule'
        else 'unresolved_local_date'
    end as service_date_source,
    p.trip_id,
    p.start_date as rt_start_date,
    p.feed_ts,
    p.route_id,
    p.direction_id,
    p.vehicle_id,
    p.is_canceled,
    p.is_added,
    p.n_stop_time_updates
from trip_polls as p
left join derived as d
    on p.start_date is null
    and d.mode = p.mode
    and d.trip_id = p.trip_id
    and d.feed_ts = p.feed_ts

-- Tram headway adherence at measurement points (METHODOLOGY §3.5).
-- Official tram punctuality uses monitoring points along each route; the feed does not say
-- which stops those are, so we pick three proxy points per route-direction: the regularly
-- served stops nearest 25%, 50% and 75% of the way along the trip.
-- Pairs are consecutive SCHEDULED trips at a point; a pair counts only if both were observed.
with tram_events as (
    select
        service_date,
        route_id,
        direction_id,
        trip_id,
        stop_id,
        stop_position,
        n_trip_stops,
        scheduled_arrival_epoch,
        observed_arrival_epoch,
        match_status
    from {{ ref('int_stop_events_matched') }}
    where mode = 'tram'
),

stop_profile as (
    select
        route_id,
        direction_id,
        stop_id,
        count(distinct trip_id) as n_trips_serving,
        median((stop_position - 1)::double / greatest(n_trip_stops - 1, 1)) as rel_position
    from tram_events
    group by route_id, direction_id, stop_id
),

route_trips as (
    select route_id, direction_id, count(distinct trip_id) as n_trips
    from tram_events
    group by route_id, direction_id
),

points as (
    select
        sp.route_id,
        sp.direction_id,
        sp.stop_id,
        q.quantile as point_quantile
    from stop_profile as sp
    inner join route_trips as rt
        on rt.route_id = sp.route_id
        and rt.direction_id is not distinct from sp.direction_id
    cross join (values (0.25), (0.5), (0.75)) as q (quantile)
    where sp.n_trips_serving >= 0.8 * rt.n_trips
    qualify row_number() over (
        partition by sp.route_id, sp.direction_id, q.quantile
        order by abs(sp.rel_position - q.quantile), sp.stop_id
    ) = 1
),

ordered as (
    select
        e.service_date,
        e.route_id,
        e.direction_id,
        e.stop_id,
        p.point_quantile,
        e.trip_id,
        e.scheduled_arrival_epoch,
        e.observed_arrival_epoch,
        e.match_status,
        lag(e.trip_id) over w as prev_trip_id,
        lag(e.scheduled_arrival_epoch) over w as prev_scheduled_arrival_epoch,
        lag(e.observed_arrival_epoch) over w as prev_observed_arrival_epoch,
        lag(e.match_status) over w as prev_match_status
    from tram_events as e
    inner join points as p
        on p.route_id = e.route_id
        and p.direction_id is not distinct from e.direction_id
        and p.stop_id = e.stop_id
    window w as (
        partition by e.service_date, e.route_id, e.direction_id, e.stop_id
        order by e.scheduled_arrival_epoch
    )
)

select
    service_date,
    route_id,
    direction_id,
    stop_id,
    point_quantile,
    trip_id,
    prev_trip_id,
    scheduled_arrival_epoch,
    observed_arrival_epoch,
    scheduled_arrival_epoch - prev_scheduled_arrival_epoch as scheduled_headway_s,
    observed_arrival_epoch - prev_observed_arrival_epoch as actual_headway_s,
    (observed_arrival_epoch - prev_observed_arrival_epoch)
        < {{ var('bunching_ratio') }} * (scheduled_arrival_epoch - prev_scheduled_arrival_epoch)
        as is_bunched
from ordered
where match_status = 'observed'
  and prev_match_status = 'observed'
  and scheduled_arrival_epoch > prev_scheduled_arrival_epoch

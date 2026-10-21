-- One row per scheduled trip per service date (trip-level roll-up of scheduled stop events).
select
    mode,
    service_date,
    trip_id,
    any_value(feed_version) as feed_version,
    any_value(route_id) as route_id,
    any_value(direction_id) as direction_id,
    any_value(shape_id) as shape_id,
    any_value(trip_headsign) as trip_headsign,
    min(scheduled_departure_epoch) as first_departure_epoch,
    max(scheduled_arrival_epoch) as last_arrival_epoch,
    count(*) as n_stops
from {{ ref('int_scheduled_stop_events') }}
group by mode, service_date, trip_id

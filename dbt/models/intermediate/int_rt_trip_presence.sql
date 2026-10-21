-- One row per realtime trip per service date: when it was first/last seen and how it was flagged.
select
    mode,
    service_date,
    trip_id,
    any_value(service_date_source) as service_date_source,
    any_value(route_id) as route_id,
    any_value(direction_id) as direction_id,
    any_value(vehicle_id) as vehicle_id,
    min(feed_ts) as first_seen_feed_ts,
    max(feed_ts) as last_seen_feed_ts,
    count(*) as n_polls,
    bool_or(is_canceled) as is_canceled,
    bool_or(is_added) as is_added
from {{ ref('int_rt_trip_polls') }}
group by mode, service_date, trip_id

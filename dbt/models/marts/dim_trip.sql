-- One row per timetable trip_id (SCD type 1 across timetable versions).
select
    md5(mode || '|' || trip_id) as trip_key,
    mode,
    trip_id,
    arg_max(route_id, feed_version) as route_id,
    md5(mode || '|' || arg_max(route_id, feed_version)) as route_key,
    arg_max(direction_id, feed_version) as direction_id,
    arg_max(trip_headsign, feed_version) as trip_headsign,
    arg_max(shape_id, feed_version) as shape_id,
    arg_max(service_id, feed_version) as service_id,
    max(feed_version) as latest_feed_version
from {{ ref('stg_gtfs_trips') }}
group by mode, trip_id

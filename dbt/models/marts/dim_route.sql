-- One row per route (SCD type 1: attributes from the latest timetable version that has it).
select
    md5(mode || '|' || route_id) as route_key,
    mode,
    route_id,
    arg_max(route_short_name, feed_version) as route_short_name,
    arg_max(route_long_name, feed_version) as route_long_name,
    arg_max(route_type, feed_version) as route_type,
    arg_max(route_color, feed_version) as route_color,
    arg_max(route_text_color, feed_version) as route_text_color,
    arg_max(is_replacement_bus, feed_version) as is_replacement_bus,
    case
        when mode = 'tram' then 'Route ' || arg_max(route_short_name, feed_version)
        else coalesce(arg_max(route_long_name, feed_version), arg_max(route_short_name, feed_version))
    end as route_display_name,
    max(feed_version) as latest_feed_version
from {{ ref('stg_gtfs_routes') }}
group by mode, route_id

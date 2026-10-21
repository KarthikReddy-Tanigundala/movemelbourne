-- One row per stop / platform (SCD type 1), with its station roll-up and point geometry (WKT,
-- EPSG:4326) so Power BI, pydeck and DuckDB spatial can all map it.
with latest as (
    select
        mode,
        stop_id,
        arg_max(stop_name, feed_version) as stop_name,
        arg_max(stop_lat, feed_version) as stop_lat,
        arg_max(stop_lon, feed_version) as stop_lon,
        arg_max(location_type, feed_version) as location_type,
        arg_max(parent_station, feed_version) as parent_station,
        arg_max(platform_code, feed_version) as platform_code,
        arg_max(station_key, feed_version) as station_key,
        max(feed_version) as latest_feed_version
    from {{ ref('stg_gtfs_stops') }}
    group by mode, stop_id
)

select
    md5(l.mode || '|' || l.stop_id) as stop_key,
    l.mode,
    l.stop_id,
    l.stop_name,
    l.stop_lat,
    l.stop_lon,
    'POINT(' || l.stop_lon || ' ' || l.stop_lat || ')' as geom_wkt,
    l.location_type,
    l.parent_station,
    l.platform_code,
    l.station_key,
    coalesce(p.stop_name, l.stop_name) as station_name,
    l.latest_feed_version
from latest as l
left join latest as p
    on p.mode = l.mode
    and p.stop_id = l.parent_station

select
    s.feed_version,
    m.mode,
    s.stop_id,
    s.stop_name,
    try_cast(s.stop_lat as double) as stop_lat,
    try_cast(s.stop_lon as double) as stop_lon,
    coalesce(try_cast(nullif(s.location_type, '') as integer), 0) as location_type,
    nullif(s.parent_station, '') as parent_station,
    nullif(s.platform_code, '') as platform_code,
    -- Station-level key: platforms roll up to their parent station; trams have no parents.
    coalesce(nullif(s.parent_station, ''), s.stop_id) as station_key
from {{ source('bronze', 'gtfs_stops') }} as s
join {{ ref('modes') }} as m on m.mode_branch = s.mode_branch

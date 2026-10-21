select
    t.feed_version,
    m.mode,
    t.trip_id,
    t.route_id,
    t.service_id,
    nullif(t.shape_id, '') as shape_id,
    nullif(t.trip_headsign, '') as trip_headsign,
    try_cast(t.direction_id as integer) as direction_id,
    nullif(t.block_id, '') as block_id
from {{ source('bronze', 'gtfs_trips') }} as t
join {{ ref('modes') }} as m on m.mode_branch = t.mode_branch

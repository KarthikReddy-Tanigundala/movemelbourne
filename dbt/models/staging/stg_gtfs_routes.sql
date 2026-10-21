select
    r.feed_version,
    m.mode,
    r.route_id,
    nullif(r.route_short_name, '') as route_short_name,
    nullif(r.route_long_name, '') as route_long_name,
    try_cast(r.route_type as integer) as route_type,
    nullif(r.route_color, '') as route_color,
    nullif(r.route_text_color, '') as route_text_color,
    -- Metro publishes a parallel "Replacement Bus" route per line (route_id suffix "-R:").
    -- The trip-updates feed excludes replacement buses, so they are out of OTP scope.
    (r.route_short_name = 'Replacement Bus' or r.route_id like '%-R:') as is_replacement_bus
from {{ source('bronze', 'gtfs_routes') }} as r
join {{ ref('modes') }} as m on m.mode_branch = r.mode_branch

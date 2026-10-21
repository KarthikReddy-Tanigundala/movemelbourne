select
    sh.feed_version,
    m.mode,
    sh.shape_id,
    cast(sh.shape_pt_sequence as integer) as shape_pt_sequence,
    try_cast(sh.shape_pt_lat as double) as shape_pt_lat,
    try_cast(sh.shape_pt_lon as double) as shape_pt_lon,
    try_cast(nullif(sh.shape_dist_traveled, '') as double) as shape_dist_traveled_m
from {{ source('bronze', 'gtfs_shapes') }} as sh
join {{ ref('modes') }} as m on m.mode_branch = sh.mode_branch

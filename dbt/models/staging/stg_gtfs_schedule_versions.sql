select
    v.feed_version,
    v.mode_branch,
    m.mode,
    cast(v.valid_from as date) as valid_from,
    try_strptime(v.calendar_start, '%Y%m%d')::date as calendar_start,
    try_strptime(v.calendar_end, '%Y%m%d')::date as calendar_end,
    v.sha256,
    cast(v.downloaded_at_utc as timestamptz) as downloaded_at_utc,
    v.n_trips,
    v.n_stop_times,
    v.n_stops
from {{ source('bronze', 'gtfs_schedule_versions') }} as v
join {{ ref('modes') }} as m on m.mode_branch = v.mode_branch

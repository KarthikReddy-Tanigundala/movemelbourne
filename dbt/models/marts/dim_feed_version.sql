-- One row per timetable release x mode: the versioned-join audit trail (ADR-005).
select
    feed_version,
    mode,
    mode_branch,
    valid_from,
    calendar_start,
    calendar_end,
    sha256,
    downloaded_at_utc,
    n_trips,
    n_stop_times,
    n_stops
from {{ ref('stg_gtfs_schedule_versions') }}

select
    mode,
    feed_ts,
    poll_ts_utc,
    alert_id,
    active_start,
    active_end,
    cause,
    effect,
    header_text,
    description_text,
    url,
    agency_id,
    route_id,
    route_type,
    stop_id,
    trip_id,
    direction_id,
    extra_json,
    source_file
from {{ source('bronze', 'rt_service_alerts') }}
where feed_ts is not null

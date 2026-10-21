-- One row per stop_time_update per poll, typed and renamed. No joins, no filtering of content.
select
    mode,
    feed_ts,
    poll_ts_utc,
    entity_id,
    trip_id,
    route_id,
    direction_id,
    try_strptime(start_date, '%Y%m%d')::date as start_date,
    start_time,
    coalesce(trip_schedule_relationship, 'SCHEDULED') as trip_schedule_relationship,
    vehicle_id,
    trip_update_ts,
    n_stop_time_updates,
    stu_index,
    stop_sequence,
    stop_id,
    arrival_time,
    arrival_delay,
    departure_time,
    departure_delay,
    coalesce(stu_schedule_relationship, 'SCHEDULED') as stu_schedule_relationship,
    stop_id is not null or stop_sequence is not null as has_stop,
    extra_json,
    source_file
from {{ source('bronze', 'rt_trip_updates') }}
where feed_ts is not null
  and trip_id is not null

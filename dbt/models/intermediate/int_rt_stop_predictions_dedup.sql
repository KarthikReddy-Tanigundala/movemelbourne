-- One row per (service_date, trip, stop, snapshot). Two collectors (the local bridge and GitHub
-- Actions) can capture the same snapshot, and a stop can repeat within a payload; keep one.
select
    p.mode,
    p.service_date,
    tu.trip_id,
    tu.feed_ts,
    tu.stop_sequence,
    tu.stop_id,
    tu.arrival_time,
    tu.arrival_delay,
    tu.departure_time,
    tu.departure_delay,
    tu.stu_schedule_relationship,
    tu.poll_ts_utc
from {{ ref('stg_rt_trip_updates') }} as tu
inner join {{ ref('int_rt_trip_polls') }} as p
    on p.mode = tu.mode
    and p.trip_id = tu.trip_id
    and p.feed_ts = tu.feed_ts
    and p.rt_start_date is not distinct from tu.start_date
where tu.has_stop
qualify row_number() over (
    partition by p.mode, p.service_date, tu.trip_id, tu.feed_ts,
                 coalesce(tu.stop_sequence, -1), coalesce(tu.stop_id, '')
    order by tu.poll_ts_utc, tu.source_file
) = 1

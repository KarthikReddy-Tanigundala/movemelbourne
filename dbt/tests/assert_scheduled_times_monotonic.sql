-- Within a trip, scheduled arrivals must never go backwards as stop_sequence increases. Catches
-- GTFS >24:00 parsing errors and DST reference mistakes (both would produce a jump backwards).
select
    mode,
    service_date,
    trip_id,
    stop_sequence,
    scheduled_arrival_epoch,
    prev_epoch
from (
    select
        mode,
        service_date,
        trip_id,
        stop_sequence,
        scheduled_arrival_epoch,
        lag(scheduled_arrival_epoch) over (
            partition by mode, service_date, trip_id order by stop_sequence
        ) as prev_epoch
    from {{ ref('int_scheduled_stop_events') }}
) as t
where scheduled_arrival_epoch < prev_epoch

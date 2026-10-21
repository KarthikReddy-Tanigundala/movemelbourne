-- Observed arrival from VEHICLE POSITIONS (secondary method, METHODOLOGY §2): the first snapshot
-- where the vehicle is STOPPED_AT the stop, or (fallback) within `vp_proximity_m` of it at or
-- below `vp_max_speed_mps`. With 60 s polling this is biased late by up to one poll interval
-- and misses short dwells, which is why it is the secondary method and why agreement with the
-- trip-update method is reported (agg_inference_agreement).
with stop_coords as (
    select
        mode,
        stop_id,
        any_value(stop_lat) as stop_lat,
        any_value(stop_lon) as stop_lon
    from {{ ref('stg_gtfs_stops') }}
    group by mode, stop_id
),

signals as (
    select
        vp.mode,
        vp.trip_id,
        vp.start_date,
        vp.stop_id,
        vp.observed_ts,
        case
            when vp.current_status = 'STOPPED_AT' then 'stopped_at'
            when vp.speed <= {{ var('vp_max_speed_mps') }}
                and {{ haversine_m('vp.latitude', 'vp.longitude', 'sc.stop_lat', 'sc.stop_lon') }}
                    <= {{ var('vp_proximity_m') }}
                then 'proximity'
        end as vp_signal
    from {{ ref('stg_rt_vehicle_positions') }} as vp
    left join stop_coords as sc
        on sc.mode = vp.mode
        and sc.stop_id = vp.stop_id
    where vp.trip_id is not null
      and vp.stop_id is not null
),

dated as (
    select
        s.mode,
        s.trip_id,
        s.stop_id,
        s.observed_ts,
        s.vp_signal,
        coalesce(s.start_date, st.service_date) as service_date
    from signals as s
    left join {{ ref('int_scheduled_trips') }} as st
        on s.start_date is null
        and st.mode = s.mode
        and st.trip_id = s.trip_id
        and s.observed_ts between st.first_departure_epoch - 7200 and st.last_arrival_epoch + 7200
    where s.vp_signal is not null
    qualify row_number() over (
        partition by s.mode, s.trip_id, s.stop_id, s.observed_ts
        order by greatest(st.first_departure_epoch - s.observed_ts,
                          s.observed_ts - st.last_arrival_epoch, 0)
    ) = 1
),

per_stop as (
    select
        mode,
        service_date,
        trip_id,
        stop_id,
        min(observed_ts) as vp_arrival_epoch,
        arg_min(vp_signal, observed_ts) as vp_signal,
        count(*) as n_vp_snapshots
    from dated
    where service_date is not null
    group by mode, service_date, trip_id, stop_id
)

-- Map to the scheduled stop (platform or parent station), nearest scheduled time if repeated.
select
    p.mode,
    p.service_date,
    p.trip_id,
    s.stop_sequence,
    p.vp_arrival_epoch,
    p.vp_signal,
    p.n_vp_snapshots
from per_stop as p
inner join {{ ref('int_scheduled_stop_events') }} as s
    on s.mode = p.mode
    and s.service_date = p.service_date
    and s.trip_id = p.trip_id
    and (s.stop_id = p.stop_id or s.station_key = p.stop_id)
qualify row_number() over (
    partition by p.mode, p.service_date, p.trip_id, s.stop_sequence
    order by abs(p.vp_arrival_epoch - s.scheduled_arrival_epoch)
) = 1

-- Schedule LEFT JOIN observation: one row per scheduled stop event with its inferred arrival,
-- inference method and match_status. Collection state is decided at the SCHEDULED time:
-- outside any collector session (int_collection_sessions), inside a session but in a poll gap
-- longer than `max_poll_gap_s` (int_rt_polls), or collected. Coverage = observed / (collected +
-- collection_gap) events, so gaps inside a session always count against us.
{%- set primary = var('inference_primary') %}
with sched as (
    select
        event_id,
        mode,
        service_date,
        feed_version,
        trip_id,
        route_id,
        direction_id,
        shape_id,
        stop_sequence,
        stop_id,
        station_key,
        shape_dist_traveled_m,
        scheduled_arrival_epoch,
        is_first_stop,
        is_last_stop,
        stop_position,
        n_trip_stops
    from {{ ref('int_scheduled_stop_events') }}
),

polls as (
    select mode, feed_ts, next_feed_ts
    from {{ ref('int_rt_polls') }}
),

sessions as (
    select mode, session_start_epoch, session_end_epoch
    from {{ ref('int_collection_sessions') }}
),

with_session as (
    select
        s.*,
        se.session_end_epoch is not null
            and s.scheduled_arrival_epoch <= se.session_end_epoch as in_session
    from sched as s
    asof left join sessions as se
        on se.mode = s.mode
        and s.scheduled_arrival_epoch >= se.session_start_epoch
),

with_collection as (
    select
        s.*,
        case
            when not s.in_session then 'outside_collection'
            when p.feed_ts is null or p.next_feed_ts is null
                or p.next_feed_ts - p.feed_ts > {{ var('max_poll_gap_s') }} then 'collection_gap'
            else 'collected'
        end as collection_state
    from with_session as s
    asof left join polls as p
        on p.mode = s.mode
        and s.scheduled_arrival_epoch >= p.feed_ts
),

joined as (
    select
        c.*,
        o.tu_observed_arrival_epoch,
        o.any_skipped,
        o.prediction_type,
        o.stop_match_method,
        o.disappearance,
        v.vp_arrival_epoch,
        v.vp_signal,
        coalesce(tp.is_canceled, false) as trip_is_canceled,
        tp.trip_id is not null as trip_in_feed,
        case c.mode
            {%- for m, method in primary.items() %}
            when '{{ m }}' then '{{ method }}'
            {%- endfor %}
            else 'last_prediction'
        end as primary_method
    from with_collection as c
    left join {{ ref('int_observed_stop_events') }} as o
        on o.mode = c.mode
        and o.service_date = c.service_date
        and o.trip_id = c.trip_id
        and o.stop_sequence = c.stop_sequence
    left join {{ ref('int_vp_stop_arrivals') }} as v
        on v.mode = c.mode
        and v.service_date = c.service_date
        and v.trip_id = c.trip_id
        and v.stop_sequence = c.stop_sequence
    left join {{ ref('int_rt_trip_presence') }} as tp
        on tp.mode = c.mode
        and tp.service_date = c.service_date
        and tp.trip_id = c.trip_id
),

resolved as (
    select
        *,
        case
            when primary_method = 'vehicle_position'
                then coalesce(vp_arrival_epoch, tu_observed_arrival_epoch)
            else coalesce(tu_observed_arrival_epoch, vp_arrival_epoch)
        end as observed_arrival_epoch,
        case
            when primary_method = 'vehicle_position' and vp_arrival_epoch is not null
                then 'vehicle_position'
            when tu_observed_arrival_epoch is not null then 'last_prediction'
            when vp_arrival_epoch is not null then 'vehicle_position'
        end as inference_method
    from joined
)

select
    event_id,
    mode,
    service_date,
    feed_version,
    trip_id,
    route_id,
    direction_id,
    shape_id,
    stop_sequence,
    stop_id,
    station_key,
    shape_dist_traveled_m,
    is_first_stop,
    is_last_stop,
    stop_position,
    n_trip_stops,
    scheduled_arrival_epoch,
    collection_state,
    trip_in_feed,
    trip_is_canceled,
    prediction_type,
    stop_match_method,
    disappearance,
    tu_observed_arrival_epoch,
    vp_arrival_epoch,
    vp_signal,
    case when trip_is_canceled then null else observed_arrival_epoch end as observed_arrival_epoch,
    case when trip_is_canceled then null else inference_method end as inference_method,
    case when trip_is_canceled then null
         else observed_arrival_epoch - scheduled_arrival_epoch end as delay_seconds,
    case
        when trip_is_canceled then 'cancelled'
        when coalesce(any_skipped, false) then 'skipped'
        when observed_arrival_epoch is not null then 'observed'
        when collection_state <> 'collected' then collection_state
        else 'unobserved'
    end as match_status
from resolved

-- Observed arrival inferred from trip-update PREDICTIONS (METHODOLOGY §2, ADR-004).
--
-- For each (service_date, trip, scheduled stop) we look at every snapshot that listed the stop
-- and keep the latest one whose predicted arrival was within `freshness_window_s` of the moment
-- the snapshot was taken (i.e. the vehicle was about to arrive, or had just arrived). That works
-- for both feed styles: feeds that drop a stop once passed (we get the last prediction) and feeds
-- that keep a passed stop with its actual time (we get the time reported just after passing).
--
-- The value is accepted only if (a) the stop was not SKIPPED, (b) the next snapshot came within
-- `max_poll_gap_s` (we did not miss a correction), and (c) there is evidence the stop was passed:
-- it dropped out while the trip stayed in the feed, the trip was still tracked after the
-- predicted time, or the trip vanished while the collector was still polling.
-- Anything else stays unobserved; nothing is imputed.
with preds as (
    select
        mode,
        service_date,
        trip_id,
        feed_ts,
        stop_sequence,
        stop_id,
        arrival_time,
        arrival_delay,
        departure_time,
        departure_delay,
        stu_schedule_relationship
    from {{ ref('int_rt_stop_predictions_dedup') }}
),

stop_lookup as (
    select
        mode,
        stop_id,
        any_value(station_key) as station_key
    from {{ ref('stg_gtfs_stops') }}
    group by mode, stop_id
),

-- Match each prediction to a scheduled stop: by stop_sequence when the feed sends it, else by
-- stop_id / parent station (feeds may report a platform where the timetable has the station).
matched as (
    select
        p.mode,
        p.service_date,
        p.trip_id,
        p.feed_ts,
        p.stu_schedule_relationship,
        s.stop_sequence,
        s.scheduled_arrival_epoch,
        case when p.stop_sequence is not null then 'stop_sequence' else 'stop_id_or_station' end
            as stop_match_method,
        coalesce(
            p.arrival_time,
            p.departure_time,
            s.scheduled_arrival_epoch + coalesce(p.arrival_delay, p.departure_delay)
        ) as predicted_arrival_epoch,
        case when p.arrival_time is null and p.departure_time is null then 'delay_only'
             else 'absolute_time' end as prediction_type
    from preds as p
    left join stop_lookup as sl
        on sl.mode = p.mode
        and sl.stop_id = p.stop_id
    inner join {{ ref('int_scheduled_stop_events') }} as s
        on s.mode = p.mode
        and s.service_date = p.service_date
        and s.trip_id = p.trip_id
        and (
            (p.stop_sequence is not null and s.stop_sequence = p.stop_sequence)
            or (p.stop_sequence is null
                and (s.stop_id = p.stop_id or s.station_key = coalesce(sl.station_key, p.stop_id)))
        )
    qualify row_number() over (
        partition by p.mode, p.service_date, p.trip_id, p.feed_ts,
                     coalesce(p.stop_sequence, -1), coalesce(p.stop_id, '')
        order by s.stop_sequence
    ) = 1
),

per_stop as (
    select
        mode,
        service_date,
        trip_id,
        stop_sequence,
        any_value(stop_match_method) as stop_match_method,
        min(feed_ts) as first_seen_feed_ts,
        max(feed_ts) as last_seen_feed_ts,
        count(*) as n_snapshots,
        bool_or(stu_schedule_relationship = 'SKIPPED') as any_skipped,
        max(feed_ts) filter (
            where abs(predicted_arrival_epoch - feed_ts) <= {{ var('freshness_window_s') }}
        ) as chosen_feed_ts,
        arg_max(predicted_arrival_epoch, feed_ts) filter (
            where abs(predicted_arrival_epoch - feed_ts) <= {{ var('freshness_window_s') }}
        ) as chosen_predicted_arrival_epoch,
        arg_max(prediction_type, feed_ts) as prediction_type,
        arg_max(predicted_arrival_epoch, feed_ts) as last_predicted_arrival_epoch
    from matched
    group by mode, service_date, trip_id, stop_sequence
),

with_context as (
    select
        ps.*,
        tp.last_seen_feed_ts as trip_last_seen_feed_ts,
        chosen_poll.next_feed_ts - ps.chosen_feed_ts as gap_after_chosen_s,
        trip_end_poll.next_feed_ts as poll_after_trip_last_seen
    from per_stop as ps
    inner join {{ ref('int_rt_trip_presence') }} as tp
        on tp.mode = ps.mode
        and tp.service_date = ps.service_date
        and tp.trip_id = ps.trip_id
    left join {{ ref('int_rt_polls') }} as chosen_poll
        on chosen_poll.mode = ps.mode
        and chosen_poll.feed_ts = ps.chosen_feed_ts
    left join {{ ref('int_rt_polls') }} as trip_end_poll
        on trip_end_poll.mode = tp.mode
        and trip_end_poll.feed_ts = tp.last_seen_feed_ts
)

select
    mode,
    service_date,
    trip_id,
    stop_sequence,
    stop_match_method,
    prediction_type,
    first_seen_feed_ts,
    last_seen_feed_ts,
    n_snapshots,
    any_skipped,
    chosen_feed_ts,
    chosen_predicted_arrival_epoch,
    last_predicted_arrival_epoch,
    chosen_predicted_arrival_epoch - chosen_feed_ts as prediction_lead_s,
    gap_after_chosen_s,
    case
        when last_seen_feed_ts < trip_last_seen_feed_ts then 'stop_dropped'
        when poll_after_trip_last_seen is null then 'collection_ended'
        else 'trip_ended'
    end as disappearance,
    case
        when not any_skipped
            and chosen_predicted_arrival_epoch is not null
            and coalesce(gap_after_chosen_s, 1e9) <= {{ var('max_poll_gap_s') }}
            and (
                last_seen_feed_ts < trip_last_seen_feed_ts
                or trip_last_seen_feed_ts > chosen_predicted_arrival_epoch
                or poll_after_trip_last_seen is not null
            )
            then chosen_predicted_arrival_epoch
    end as tu_observed_arrival_epoch
from with_context

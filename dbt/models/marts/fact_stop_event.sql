{{
    config(
        materialized='incremental',
        unique_key='stop_event_key',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}
-- Grain: service_date x mode x trip x stop_sequence (every SCHEDULED stop event in collected
-- dates, observed or not). Incremental: each run rebuilds the last `incremental_lookback_days`
-- service dates, because a late snapshot sync can still complete a recent day.
with events as (
    select
        event_id,
        mode,
        service_date,
        feed_version,
        trip_id,
        route_id,
        direction_id,
        stop_id,
        stop_sequence,
        stop_position,
        n_trip_stops,
        is_first_stop,
        is_last_stop,
        shape_dist_traveled_m,
        scheduled_arrival_epoch,
        observed_arrival_epoch,
        tu_observed_arrival_epoch,
        vp_arrival_epoch,
        delay_seconds,
        inference_method,
        prediction_type,
        stop_match_method,
        collection_state,
        match_status
    from {{ ref('int_stop_events_matched') }}
    {% if is_incremental() %}
    where service_date >= (
        select coalesce(max(service_date), date '1900-01-01')
            - interval {{ var('incremental_lookback_days') }} day
        from {{ this }}
    )
    {% endif %}
),

thresholds as (
    select mode, early_tolerance_s, late_threshold_s
    from {{ ref('otp_thresholds') }}
),

flagged as (
    select
        e.*,
        t.early_tolerance_s,
        t.late_threshold_s,
        e.delay_seconds is not null
            and e.delay_seconds not between {{ var('delay_min_s') }} and {{ var('delay_max_s') }}
            as is_delay_outlier
    from events as e
    left join thresholds as t
        on t.mode = e.mode
)

select
    md5(event_id) as stop_event_key,
    event_id,
    cast(strftime(service_date, '%Y%m%d') as integer) as date_key,
    service_date,
    mode,
    md5(mode || '|' || route_id) as route_key,
    md5(mode || '|' || stop_id) as stop_key,
    md5(mode || '|' || trip_id) as trip_key,
    feed_version,
    hour({{ local_ts('scheduled_arrival_epoch') }}) as time_band_key,
    trip_id,
    direction_id,
    stop_sequence,
    stop_position,
    n_trip_stops,
    is_first_stop,
    is_last_stop,
    shape_dist_traveled_m,
    scheduled_arrival_epoch,
    {{ local_ts('scheduled_arrival_epoch') }} as scheduled_arrival_local,
    observed_arrival_epoch,
    {{ local_ts('observed_arrival_epoch') }} as observed_arrival_local,
    delay_seconds,
    round(delay_seconds / 60.0, 2) as delay_minutes,
    inference_method,
    prediction_type,
    stop_match_method,
    vp_arrival_epoch - tu_observed_arrival_epoch as vp_minus_tu_s,
    collection_state,
    match_status,
    -- Coverage scope: scheduled inside a collector session, and not cancelled/skipped.
    collection_state <> 'outside_collection'
        and match_status not in ('cancelled', 'skipped') as is_in_coverage_scope,
    match_status = 'observed' as is_observed,
    is_delay_outlier,
    match_status = 'observed' and not is_delay_outlier as is_otp_eligible,
    case when match_status = 'observed' and not is_delay_outlier
         then {{ otp_flag('delay_seconds', 'early_tolerance_s', 'late_threshold_s') }} end
        as is_on_time,
    case when match_status = 'observed' and not is_delay_outlier
         then {{ delay_band('delay_seconds', 'early_tolerance_s', 'late_threshold_s') }} end
        as delay_band
from flagged

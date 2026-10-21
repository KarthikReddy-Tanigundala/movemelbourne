-- Observed stop events whose delay falls outside [delay_min_s, delay_max_s]. Quarantined here
-- for review instead of being silently dropped; excluded from every OTP figure.
select
    stop_event_key,
    service_date,
    mode,
    route_key,
    stop_key,
    trip_id,
    stop_sequence,
    scheduled_arrival_local,
    observed_arrival_local,
    delay_seconds,
    inference_method,
    case when delay_seconds < {{ var('delay_min_s') }} then 'too_early' else 'too_late' end
        as outlier_reason
from {{ ref('fact_stop_event') }}
where is_delay_outlier

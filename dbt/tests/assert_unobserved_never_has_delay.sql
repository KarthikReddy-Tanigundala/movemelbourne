-- Methodology guard (§9.1): events we did not observe must never carry a delay or an on-time
-- verdict - unobserved events count against coverage, never towards OTP.
select
    stop_event_key,
    match_status,
    delay_seconds,
    is_on_time
from {{ ref('fact_stop_event') }}
where match_status <> 'observed'
  and (delay_seconds is not null or is_on_time is not null)

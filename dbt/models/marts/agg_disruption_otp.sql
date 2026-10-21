-- Proxy OTP inside vs outside active service-alert windows, per route (CLAUDE.md §9.2).
-- An event is "during disruption" when an alert naming its route (any direction, or its own
-- direction) was active at the scheduled time.
with route_alerts as (
    select distinct
        mode,
        route_key,
        direction_id,
        effect,
        active_start_epoch,
        coalesce(active_end_epoch, last_seen_feed_ts) as active_end_epoch
    from {{ ref('fact_alert') }}
    where route_key is not null
      and active_start_epoch is not null
),

events as (
    select
        f.mode,
        f.route_key,
        f.stop_event_key,
        f.is_on_time,
        f.delay_seconds,
        exists (
            select 1
            from route_alerts as a
            where a.route_key = f.route_key
              and (a.direction_id is null or a.direction_id = f.direction_id)
              and f.scheduled_arrival_epoch between a.active_start_epoch and a.active_end_epoch
        ) as during_disruption
    from {{ ref('fact_stop_event') }} as f
    where f.is_otp_eligible
      and f.route_key in (select route_key from route_alerts)
)

select
    mode,
    route_key,
    during_disruption,
    count(*) as n_observed,
    round(100.0 * avg(is_on_time::int), 2) as otp_pct,
    quantile_cont(delay_seconds, 0.90) as p90_delay_s,
    count(*) >= {{ var('min_sample_events') }} as is_sample_sufficient
from events
group by mode, route_key, during_disruption

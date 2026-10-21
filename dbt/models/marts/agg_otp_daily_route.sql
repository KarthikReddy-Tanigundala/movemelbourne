-- Route x service date: proxy OTP with coverage, delay percentiles and reliability.
with events as (
    select
        service_date,
        mode,
        route_key,
        count(*) filter (where is_in_coverage_scope) as n_in_scope,
        count(*) filter (where is_otp_eligible) as n_observed,
        count(*) filter (where is_on_time) as n_on_time,
        count(*) filter (where delay_band = 'Major late (>15 min)') as n_major_late,
        quantile_cont(delay_seconds, 0.50) filter (where is_otp_eligible) as p50_delay_s,
        quantile_cont(delay_seconds, 0.90) filter (where is_otp_eligible) as p90_delay_s,
        quantile_cont(delay_seconds, 0.95) filter (where is_otp_eligible) as p95_delay_s
    from {{ ref('fact_stop_event') }}
    group by service_date, mode, route_key
),

trips as (
    select
        service_date,
        route_key,
        count(*) filter (where is_reliability_eligible) as n_trips_eligible,
        count(*) filter (where is_reliability_eligible and is_confirmed_cancelled) as n_trips_cancelled
    from {{ ref('fact_trip') }}
    group by service_date, route_key
)

select
    md5(e.service_date || '|' || e.route_key) as route_day_key,
    e.service_date,
    cast(strftime(e.service_date, '%Y%m%d') as integer) as date_key,
    e.mode,
    e.route_key,
    e.n_in_scope,
    e.n_observed,
    e.n_on_time,
    round(100.0 * e.n_on_time / nullif(e.n_observed, 0), 2) as otp_pct,
    round(100.0 * e.n_observed / nullif(e.n_in_scope, 0), 2) as coverage_pct,
    round(100.0 * e.n_major_late / nullif(e.n_observed, 0), 2) as major_late_pct,
    e.p50_delay_s,
    e.p90_delay_s,
    e.p95_delay_s,
    t.n_trips_eligible,
    t.n_trips_cancelled,
    round(100.0 * (1 - t.n_trips_cancelled / nullif(t.n_trips_eligible, 0)), 2) as reliability_pct,
    e.n_observed >= {{ var('min_sample_events') }} as is_sample_sufficient
from events as e
left join trips as t
    on t.service_date = e.service_date
    and t.route_key = e.route_key
where e.n_in_scope > 0

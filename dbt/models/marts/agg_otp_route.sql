-- Whole-study route ranking. Ranked by the Wilson lower bound of OTP, not the point estimate,
-- so a route with a handful of lucky observations cannot top the table (METHODOLOGY §4).
-- The trip-clustered bootstrap CI (analysis/bootstrap.py) refines this for the study report.
with events as (
    select
        mode,
        route_key,
        count(*) filter (where is_in_coverage_scope) as n_in_scope,
        count(*) filter (where is_otp_eligible) as n_observed,
        count(*) filter (where is_on_time) as n_on_time,
        count(distinct trip_id) filter (where is_otp_eligible) as n_trips_observed,
        quantile_cont(delay_seconds, 0.50) filter (where is_otp_eligible) as p50_delay_s,
        quantile_cont(delay_seconds, 0.90) filter (where is_otp_eligible) as p90_delay_s,
        quantile_cont(delay_seconds, 0.95) filter (where is_otp_eligible) as p95_delay_s,
        count(*) filter (where delay_band = 'Major late (>15 min)') as n_major_late
    from {{ ref('fact_stop_event') }}
    group by mode, route_key
),

trips as (
    select
        route_key,
        count(*) filter (where is_reliability_eligible) as n_trips_eligible,
        count(*) filter (where is_reliability_eligible and is_confirmed_cancelled) as n_trips_cancelled
    from {{ ref('fact_trip') }}
    group by route_key
),

scored as (
    select
        e.*,
        t.n_trips_eligible,
        t.n_trips_cancelled,
        round(100.0 * e.n_on_time / nullif(e.n_observed, 0), 2) as otp_pct,
        round(100.0 * {{ wilson_lower('e.n_on_time', 'e.n_observed') }}, 2) as otp_wilson_low_pct,
        e.n_observed >= {{ var('min_sample_events') }} as is_sample_sufficient
    from events as e
    left join trips as t
        on t.route_key = e.route_key
    where e.n_in_scope > 0
)

select
    mode,
    route_key,
    n_in_scope,
    n_observed,
    n_on_time,
    n_trips_observed,
    otp_pct,
    otp_wilson_low_pct,
    round(100.0 * n_observed / nullif(n_in_scope, 0), 2) as coverage_pct,
    p50_delay_s,
    p90_delay_s,
    p95_delay_s,
    round(100.0 * n_major_late / nullif(n_observed, 0), 2) as major_late_pct,
    n_trips_eligible,
    n_trips_cancelled,
    round(100.0 * (1 - n_trips_cancelled / nullif(n_trips_eligible, 0)), 2) as reliability_pct,
    is_sample_sufficient,
    case when is_sample_sufficient
         then rank() over (partition by mode, is_sample_sufficient order by otp_wilson_low_pct desc)
    end as otp_rank_in_mode
from scored

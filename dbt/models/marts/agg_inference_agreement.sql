-- Self-validation of the observed-arrival method (ADR-004): where BOTH the trip-update
-- last-prediction and the vehicle-position method produced an arrival, how close are they?
-- vp_minus_tu_s > 0 means vehicle positions saw the arrival later (expected with 60 s polling).
select
    f.mode,
    count(*) as n_both_methods,
    median(abs(f.vp_minus_tu_s)) as median_abs_diff_s,
    quantile_cont(abs(f.vp_minus_tu_s), 0.90) as p90_abs_diff_s,
    median(f.vp_minus_tu_s) as median_signed_diff_s,
    round(100.0 * avg((abs(f.vp_minus_tu_s) <= 60)::int), 2) as pct_within_60s,
    round(100.0 * avg((abs(f.vp_minus_tu_s) <= 120)::int), 2) as pct_within_120s,
    -- Share of events whose on-time verdict would change under the other method.
    round(100.0 * avg((
        {{ otp_flag('f.delay_seconds', 't.early_tolerance_s', 't.late_threshold_s') }}
        <> {{ otp_flag('f.delay_seconds + f.vp_minus_tu_s', 't.early_tolerance_s', 't.late_threshold_s') }}
    )::int), 2) as pct_otp_verdict_flips
from {{ ref('fact_stop_event') }} as f
inner join {{ ref('otp_thresholds') }} as t
    on t.mode = f.mode
where f.vp_minus_tu_s is not null
  and f.inference_method = 'last_prediction'
group by f.mode

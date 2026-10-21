-- Stop-level delay for the delay map. Cells below the minimum sample are flagged, not dropped,
-- so the app can grey them out and still show n on hover.
select
    f.mode,
    f.stop_key,
    s.stop_id,
    s.stop_name,
    s.station_name,
    s.stop_lat,
    s.stop_lon,
    count(*) filter (where f.is_otp_eligible) as n_observed,
    count(*) filter (where f.is_in_coverage_scope) as n_in_scope,
    round(100.0 * count(*) filter (where f.is_on_time)
          / nullif(count(*) filter (where f.is_otp_eligible), 0), 2) as otp_pct,
    quantile_cont(f.delay_seconds, 0.50) filter (where f.is_otp_eligible) as p50_delay_s,
    quantile_cont(f.delay_seconds, 0.90) filter (where f.is_otp_eligible) as p90_delay_s,
    count(*) filter (where f.is_otp_eligible) >= {{ var('min_sample_events') }} as is_sample_sufficient
from {{ ref('fact_stop_event') }} as f
inner join {{ ref('dim_stop') }} as s
    on s.stop_key = f.stop_key
group by f.mode, f.stop_key, s.stop_id, s.stop_name, s.station_name, s.stop_lat, s.stop_lon
having count(*) filter (where f.is_in_coverage_scope) > 0

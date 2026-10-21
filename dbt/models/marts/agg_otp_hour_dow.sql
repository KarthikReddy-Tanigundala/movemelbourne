-- "When it goes wrong": proxy OTP by day type x hour of scheduled time.
select
    f.mode,
    d.day_type,
    d.day_of_week,
    d.day_name,
    f.time_band_key as hour_of_day,
    tb.time_band,
    count(*) filter (where f.is_otp_eligible) as n_observed,
    round(100.0 * count(*) filter (where f.is_on_time)
          / nullif(count(*) filter (where f.is_otp_eligible), 0), 2) as otp_pct,
    quantile_cont(f.delay_seconds, 0.90) filter (where f.is_otp_eligible) as p90_delay_s,
    count(*) filter (where f.is_otp_eligible) >= {{ var('min_sample_events') }} as is_sample_sufficient
from {{ ref('fact_stop_event') }} as f
inner join {{ ref('dim_date') }} as d
    on d.date_key = f.date_key
inner join {{ ref('dim_time_band') }} as tb
    on tb.time_band_key = f.time_band_key
group by f.mode, d.day_type, d.day_of_week, d.day_name, f.time_band_key, tb.time_band
having count(*) filter (where f.is_otp_eligible) > 0

-- Tram headway adherence per route x direction x service date x time band.
-- bunching_rate: share of consecutive observed pairs with actual headway < bunching_ratio x
--   scheduled headway.
-- headway_cv: coefficient of variation of actual headways (0 = perfectly even).
-- excess_wait_s: average extra wait for a passenger arriving at random, versus the timetable
--   (E[h^2] / 2E[h], actual minus scheduled), the standard high-frequency service measure.
select
    h.service_date,
    cast(strftime(h.service_date, '%Y%m%d') as integer) as date_key,
    md5('tram|' || h.route_id) as route_key,
    h.direction_id,
    tb.time_band,
    count(*) as n_pairs,
    round(100.0 * avg(h.is_bunched::int), 2) as bunching_rate_pct,
    stddev_samp(h.actual_headway_s) / nullif(avg(h.actual_headway_s), 0) as headway_cv,
    avg(h.scheduled_headway_s) as mean_scheduled_headway_s,
    avg(h.actual_headway_s) as mean_actual_headway_s,
    sum(h.actual_headway_s * h.actual_headway_s) / nullif(2.0 * sum(h.actual_headway_s), 0)
      - sum(h.scheduled_headway_s * h.scheduled_headway_s) / nullif(2.0 * sum(h.scheduled_headway_s), 0)
        as excess_wait_s,
    count(*) >= {{ var('min_sample_events') }} as is_sample_sufficient
from {{ ref('int_headways') }} as h
inner join {{ ref('dim_time_band') }} as tb
    on tb.time_band_key = hour({{ local_ts('h.scheduled_arrival_epoch') }})
group by h.service_date, h.route_id, h.direction_id, tb.time_band

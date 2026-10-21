-- Where time is lost: delay added between consecutive OBSERVED stops of the same trip, rolled
-- up per route segment (from stop -> to stop) with coordinates for the segment map.
with observed as (
    select
        mode,
        route_key,
        trip_id,
        service_date,
        stop_key,
        stop_sequence,
        delay_seconds
    from {{ ref('fact_stop_event') }}
    where is_otp_eligible
),

pairs as (
    select
        mode,
        route_key,
        lag(stop_key) over w as from_stop_key,
        stop_key as to_stop_key,
        delay_seconds - lag(delay_seconds) over w as added_delay_s,
        stop_sequence - lag(stop_sequence) over w as sequence_step
    from observed
    window w as (partition by mode, service_date, trip_id order by stop_sequence)
)

select
    md5(p.route_key || '|' || p.from_stop_key || '|' || p.to_stop_key) as segment_key,
    p.mode,
    p.route_key,
    p.from_stop_key,
    p.to_stop_key,
    fs.stop_name as from_stop_name,
    ts.stop_name as to_stop_name,
    fs.stop_lat as from_lat,
    fs.stop_lon as from_lon,
    ts.stop_lat as to_lat,
    ts.stop_lon as to_lon,
    count(*) as n_pairs,
    median(p.added_delay_s) as median_added_delay_s,
    quantile_cont(p.added_delay_s, 0.90) as p90_added_delay_s,
    avg(p.added_delay_s) as mean_added_delay_s,
    count(*) >= {{ var('min_sample_events') }} as is_sample_sufficient
from pairs as p
inner join {{ ref('dim_stop') }} as fs
    on fs.stop_key = p.from_stop_key
inner join {{ ref('dim_stop') }} as ts
    on ts.stop_key = p.to_stop_key
where p.from_stop_key is not null
  and p.sequence_step = 1  -- adjacent stops only; a gap in observation is not a segment
group by p.mode, p.route_key, p.from_stop_key, p.to_stop_key,
         fs.stop_name, ts.stop_name, fs.stop_lat, fs.stop_lon, ts.stop_lat, ts.stop_lon

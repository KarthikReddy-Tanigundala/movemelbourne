-- What we captured and what we missed, per mode per service date (the published coverage
-- report). Join quality (trip match rate) lives here too, so an ID-format change at DTP shows
-- up as a failed test on this model rather than as a silent drop in OTP.
with events as (
    select
        service_date,
        mode,
        count(*) as n_scheduled_events,
        count(*) filter (where collection_state <> 'outside_collection') as n_in_session_events,
        count(*) filter (where is_in_coverage_scope) as n_in_scope_events,
        count(*) filter (where is_observed and is_in_coverage_scope) as n_observed_in_scope,
        count(*) filter (where is_observed) as n_observed_events,
        count(*) filter (where match_status = 'collection_gap') as n_collection_gap_events,
        count(*) filter (where match_status = 'unobserved') as n_unobserved_events,
        count(*) filter (where match_status = 'cancelled') as n_cancelled_events,
        count(*) filter (where match_status = 'skipped') as n_skipped_events,
        count(*) filter (where inference_method = 'last_prediction') as n_method_last_prediction,
        count(*) filter (where inference_method = 'vehicle_position') as n_method_vehicle_position,
        count(*) filter (where is_delay_outlier) as n_delay_outliers
    from {{ ref('fact_stop_event') }}
    group by service_date, mode
),

rt_trips as (
    select
        p.service_date,
        p.mode,
        count(*) filter (where not p.is_added) as n_rt_trips,
        count(*) filter (where not p.is_added and u.trip_id is null) as n_rt_trips_matched,
        count(*) filter (where p.is_added) as n_rt_trips_added
    from {{ ref('int_rt_trip_presence') }} as p
    left join {{ ref('int_rt_unmatched_trips') }} as u
        on u.mode = p.mode
        and u.service_date = p.service_date
        and u.trip_id = p.trip_id
    group by p.service_date, p.mode
),

polls as (
    select
        run_local_date as service_date,
        mode,
        sum(polls_attempted) as polls_attempted,
        sum(polls_succeeded) as polls_succeeded,
        sum(polls_duplicate) as polls_duplicate,
        count(distinct run_id) as n_runs,
        sum(run_end_utc - run_start_utc) / 3600.0 as collector_hours
    from {{ ref('stg_rt_coverage') }}
    where feed = 'trip-updates'
    group by run_local_date, mode
)

select
    e.service_date,
    cast(strftime(e.service_date, '%Y%m%d') as integer) as date_key,
    e.mode,
    e.n_scheduled_events,
    e.n_in_session_events,
    e.n_in_scope_events,
    e.n_observed_in_scope,
    e.n_observed_events,
    e.n_collection_gap_events,
    e.n_unobserved_events,
    e.n_cancelled_events,
    e.n_skipped_events,
    e.n_method_last_prediction,
    e.n_method_vehicle_position,
    e.n_delay_outliers,
    round(100.0 * e.n_observed_in_scope / nullif(e.n_in_scope_events, 0), 2) as coverage_pct,
    r.n_rt_trips,
    r.n_rt_trips_matched,
    r.n_rt_trips_added,
    r.n_rt_trips_matched::double / nullif(r.n_rt_trips, 0) as trip_match_rate,
    p.n_runs,
    p.collector_hours,
    p.polls_attempted,
    p.polls_succeeded,
    p.polls_duplicate,
    round(100.0 * p.polls_succeeded / nullif(p.polls_attempted, 0), 2) as poll_success_pct
from events as e
left join rt_trips as r
    on r.service_date = e.service_date
    and r.mode = e.mode
left join polls as p
    on p.service_date = e.service_date
    and p.mode = e.mode
where e.n_in_session_events > 0

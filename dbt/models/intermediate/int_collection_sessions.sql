-- Periods when the collector was meant to be running, per mode, from the coverage log.
-- Consecutive trip-update runs less than an hour apart (normal cron cadence plus GitHub start
-- jitter) merge into one session. Inside a session, any poll gap counts AGAINST coverage; time
-- between sessions is "outside collection" and is reported as lost uptime instead
-- (agg_coverage_daily.session_hours), so an outage is never hidden, only classified.
with runs as (
    select
        mode,
        run_start_utc,
        run_end_utc
    from {{ ref('stg_rt_coverage') }}
    where feed = 'trip-updates'
      and polls_attempted > 0
),

flagged as (
    select
        mode,
        run_start_utc,
        run_end_utc,
        case
            when run_start_utc - max(run_end_utc) over (
                partition by mode order by run_start_utc
                rows between unbounded preceding and 1 preceding
            ) <= 3600 then 0
            else 1
        end as is_new_session
    from runs
),

numbered as (
    select
        mode,
        run_start_utc,
        run_end_utc,
        cast(sum(is_new_session) over (partition by mode order by run_start_utc) as integer)
            as session_number
    from flagged
)

select
    mode,
    session_number,
    min(run_start_utc) as session_start_epoch,
    max(run_end_utc) as session_end_epoch,
    count(*) as n_runs,
    (max(run_end_utc) - min(run_start_utc)) / 3600.0 as session_hours
from numbered
group by mode, session_number

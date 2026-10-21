-- ADR-005: which timetable release was in force on each service date, per mode.
-- Rule: the latest release downloaded on or before the service date whose calendar covers that
-- date; for dates before our first snapshot, fall back to the earliest release covering it.
with candidates as (
    select distinct
        c.mode,
        c.service_date,
        c.feed_version,
        v.valid_from
    from {{ ref('stg_service_calendar') }} as c
    inner join (
        select distinct feed_version, mode, valid_from
        from {{ ref('stg_gtfs_schedule_versions') }}
    ) as v
        on v.feed_version = c.feed_version
        and v.mode = c.mode
)

select
    mode,
    service_date,
    coalesce(
        max_by(feed_version, valid_from) filter (where valid_from <= service_date),
        min_by(feed_version, valid_from)
    ) as feed_version,
    case
        when count(*) filter (where valid_from <= service_date) > 0
            then 'latest_release_on_or_before_date'
        else 'earliest_release_covering_date'
    end as selection_rule,
    count(*) as n_candidate_versions
from candidates
group by mode, service_date

-- Every service date on which a collector session covered at least one scheduled event must
-- appear in the coverage report: a missing day would silently vanish from every average.
with session_days as (
    select distinct
        mode,
        service_date
    from {{ ref('fact_stop_event') }}
    where collection_state <> 'outside_collection'
)

select
    s.mode,
    s.service_date
from session_days as s
left join {{ ref('agg_coverage_daily') }} as c
    on c.mode = s.mode
    and c.service_date = s.service_date
where c.service_date is null

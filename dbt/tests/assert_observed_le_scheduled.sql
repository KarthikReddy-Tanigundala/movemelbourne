-- Reconciliation: we can never observe more in-scope stop events than were scheduled in scope,
-- and the scope can never exceed what was scheduled.
select
    service_date,
    mode,
    n_scheduled_events,
    n_in_scope_events,
    n_observed_in_scope
from {{ ref('agg_coverage_daily') }}
where n_observed_in_scope > n_in_scope_events
   or n_in_scope_events > n_scheduled_events

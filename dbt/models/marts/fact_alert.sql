-- Grain: alert x informed entity x active period, deduplicated across the many snapshots that
-- carried it. first/last_seen show how long the alert was live in the feed.
with alerts as (
    select
        mode,
        alert_id,
        route_id,
        stop_id,
        trip_id,
        direction_id,
        active_start,
        active_end,
        cause,
        effect,
        header_text,
        description_text,
        feed_ts
    from {{ ref('stg_rt_service_alerts') }}
)

select
    md5(concat_ws('|', mode, alert_id, coalesce(route_id, ''), coalesce(stop_id, ''),
                  coalesce(trip_id, ''), coalesce(direction_id::varchar, ''),
                  coalesce(active_start::varchar, ''), coalesce(active_end::varchar, '')))
        as alert_key,
    mode,
    alert_id,
    case when route_id is not null then md5(mode || '|' || route_id) end as route_key,
    case when stop_id is not null then md5(mode || '|' || stop_id) end as stop_key,
    route_id,
    stop_id,
    trip_id,
    direction_id,
    active_start as active_start_epoch,
    active_end as active_end_epoch,
    {{ local_ts('active_start') }} as active_start_local,
    {{ local_ts('active_end') }} as active_end_local,
    arg_max(cause, feed_ts) as cause,
    arg_max(effect, feed_ts) as effect,
    arg_max(header_text, feed_ts) as header_text,
    arg_max(description_text, feed_ts) as description_text,
    min(feed_ts) as first_seen_feed_ts,
    max(feed_ts) as last_seen_feed_ts,
    count(*) as n_snapshots
from alerts
group by mode, alert_id, route_id, stop_id, trip_id, direction_id, active_start, active_end

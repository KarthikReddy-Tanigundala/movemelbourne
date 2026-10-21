-- One row per distinct trip-updates snapshot per mode, with the previous and next snapshot.
-- This is the collector's heartbeat: gaps between consecutive snapshots define collection gaps.
with polls as (
    select distinct
        mode,
        feed_ts
    from {{ ref('stg_rt_trip_updates') }}
)

select
    mode,
    feed_ts,
    {{ local_ts('feed_ts') }}::date as poll_local_date,
    lag(feed_ts) over w as prev_feed_ts,
    lead(feed_ts) over w as next_feed_ts,
    lead(feed_ts) over w - feed_ts as gap_to_next_s
from polls
window w as (partition by mode order by feed_ts)

select
    st.feed_version,
    m.mode,
    st.trip_id,
    st.stop_id,
    cast(st.stop_sequence as integer) as stop_sequence,
    {{ gtfs_time_to_seconds('st.arrival_time') }} as arrival_secs,
    {{ gtfs_time_to_seconds('st.departure_time') }} as departure_secs,
    try_cast(nullif(st.shape_dist_traveled, '') as double) as shape_dist_traveled_m,
    try_cast(nullif(st.pickup_type, '') as integer) as pickup_type,
    try_cast(nullif(st.drop_off_type, '') as integer) as drop_off_type
from {{ source('bronze', 'gtfs_stop_times') }} as st
join {{ ref('modes') }} as m on m.mode_branch = st.mode_branch

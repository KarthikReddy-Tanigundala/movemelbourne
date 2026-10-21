-- Hour-of-day grain (local scheduled time) with its time band.
select
    hour_of_day as time_band_key,
    hour_of_day,
    time_band,
    is_peak,
    sort_order as time_band_sort
from {{ ref('time_bands') }}

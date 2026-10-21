select
    c.feed_version,
    m.mode,
    c.service_date,
    c.service_id,
    c.ref_epoch
from {{ source('bronze', 'service_calendar') }} as c
join {{ ref('modes') }} as m on m.mode_branch = c.mode_branch

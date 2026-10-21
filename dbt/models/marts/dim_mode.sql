select
    m.mode,
    m.mode_branch,
    m.mode_label,
    m.in_core_scope,
    t.early_tolerance_s,
    t.late_threshold_s,
    t.target_punctuality_pct,
    t.target_reliability_pct,
    t.source as definition_source,
    t.verified_on as definition_verified_on
from {{ ref('modes') }} as m
left join {{ ref('otp_thresholds') }} as t
    on t.mode = m.mode

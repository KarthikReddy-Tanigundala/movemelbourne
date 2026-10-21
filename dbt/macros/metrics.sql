{#-
  otp_flag(delay, early_tolerance, late_threshold)
  True when -early_tolerance <= delay <= late_threshold. A null bound is not applied (metro's
  official measure does not penalise early running). Returns null when delay is null, so
  unobserved events can never be counted as on time or late.
-#}
{% macro otp_flag(delay, early_tolerance, late_threshold) -%}
    case when {{ delay }} is null then null
         else ({{ late_threshold }} is null or {{ delay }} <= {{ late_threshold }})
          and ({{ early_tolerance }} is null or {{ delay }} >= -{{ early_tolerance }})
    end
{%- endmacro %}


{#-
  delay_band(delay, early_tolerance, late_threshold)
  Early / On time / Minor late (to 15 min) / Major late (> 15 min). Bands are aligned with the
  per-mode on-time window so that "On time" here always equals otp_flag = true.
-#}
{% macro delay_band(delay, early_tolerance, late_threshold) -%}
    case when {{ delay }} is null then null
         when {{ early_tolerance }} is not null and {{ delay }} < -{{ early_tolerance }} then 'Early'
         when {{ delay }} <= {{ late_threshold }} then 'On time'
         when {{ delay }} <= 900 then 'Minor late (5-15 min)'
         else 'Major late (>15 min)'
    end
{%- endmacro %}


{#-
  wilson_lower(successes, n, z=1.96)
  Lower bound of the Wilson score interval for a proportion (0-1). Used as a cheap, always-
  available ranking guard; the cluster bootstrap in analysis/bootstrap.py is the headline CI.
-#}
{% macro wilson_lower(successes, n, z=1.96) -%}
    case when {{ n }} > 0 then
        (({{ successes }}::double / {{ n }}) + {{ z }}*{{ z }} / (2.0 * {{ n }})
         - {{ z }} * sqrt((({{ successes }}::double / {{ n }}) * (1 - {{ successes }}::double / {{ n }})
                         + {{ z }}*{{ z }} / (4.0 * {{ n }})) / {{ n }}))
        / (1 + {{ z }}*{{ z }} / {{ n }})
    end
{%- endmacro %}

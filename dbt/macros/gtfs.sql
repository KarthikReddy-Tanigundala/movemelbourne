{#-
  gtfs_time_to_seconds(col)
  GTFS stop_times value "HH:MM:SS" -> seconds since the service-day reference. Hours may exceed
  23 (after-midnight trips), so this is never parsed as a clock time. Null/blank -> null.
-#}
{% macro gtfs_time_to_seconds(col) -%}
    case when nullif(trim({{ col }}), '') is null then null
         else cast(split_part(trim({{ col }}), ':', 1) as integer) * 3600
            + cast(split_part(trim({{ col }}), ':', 2) as integer) * 60
            + cast(split_part(trim({{ col }}), ':', 3) as integer)
    end
{%- endmacro %}


{#-
  local_ts(epoch_col)
  POSIX epoch seconds -> naive Australia/Melbourne timestamp (DST-aware via ICU). Raw epochs
  stay the system of record; this is only for bucketing (hour, day of week, time band).
-#}
{% macro local_ts(epoch_col) -%}
    (to_timestamp({{ epoch_col }}) at time zone 'Australia/Melbourne')
{%- endmacro %}


{#-
  haversine_m(lat1, lon1, lat2, lon2)
  Great-circle distance in metres. Used for the vehicle-position proximity fallback.
-#}
{% macro haversine_m(lat1, lon1, lat2, lon2) -%}
    (2 * 6371008.8 * asin(sqrt(
        power(sin(radians({{ lat2 }} - {{ lat1 }}) / 2), 2)
      + cos(radians({{ lat1 }})) * cos(radians({{ lat2 }}))
      * power(sin(radians({{ lon2 }} - {{ lon1 }}) / 2), 2))))
{%- endmacro %}

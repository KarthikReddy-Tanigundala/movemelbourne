{#-
  accepted_range: fail rows where column_name is outside [min_value, max_value].
  Local replacement for dbt_utils.accepted_range so the project builds with no package download.
  Optional `where` restricts the rows tested (e.g. only OTP-eligible events).
-#}
{% test accepted_range(model, column_name, min_value=none, max_value=none, where=none) %}
select *
from {{ model }}
where {{ column_name }} is not null
  {% if where %}and ({{ where }}){% endif %}
  and (
        {% if min_value is not none %}{{ column_name }} < {{ min_value }}{% else %}false{% endif %}
     or {% if max_value is not none %}{{ column_name }} > {{ max_value }}{% else %}false{% endif %}
  )
{% endtest %}

-- Conformed date dimension (service dates). Day type follows timetable practice: public
-- holidays run Sunday-like services, so they are grouped with Sundays.
with spine as (
    select cast(d as date) as date_day
    from generate_series(
        date '{{ var("date_spine_start") }}', date '{{ var("date_spine_end") }}', interval 1 day
    ) as t (d)
)

select
    cast(strftime(s.date_day, '%Y%m%d') as integer) as date_key,
    s.date_day,
    isodow(s.date_day) as day_of_week,
    dayname(s.date_day) as day_name,
    isodow(s.date_day) >= 6 as is_weekend,
    h.holiday_date is not null as is_public_holiday,
    h.holiday_name,
    case
        when h.holiday_date is not null or isodow(s.date_day) = 7 then 'Sunday / public holiday'
        when isodow(s.date_day) = 6 then 'Saturday'
        else 'Weekday'
    end as day_type,
    date_trunc('week', s.date_day)::date as week_start,
    date_trunc('month', s.date_day)::date as month_start,
    strftime(s.date_day, '%Y-%m') as year_month
from spine as s
left join {{ ref('vic_public_holidays') }} as h
    on h.holiday_date = s.date_day

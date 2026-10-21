# DAX measures (ready to paste)

Create a measures-only table first: *Home → Enter data →* one empty column, name it `_Measures`,
then add each measure below to it. All measures respect the star schema in
[SEMANTIC_MODEL.md](SEMANTIC_MODEL.md). Definitions mirror the dbt marts exactly, so card values
match the Streamlit app (see METHODOLOGY.md for the reasoning).

## Volume and coverage

```dax
Observed Stop Events =
CALCULATE ( COUNTROWS ( fact_stop_event ), fact_stop_event[is_otp_eligible] = TRUE () )

In-scope Stop Events =
CALCULATE ( COUNTROWS ( fact_stop_event ), fact_stop_event[is_in_coverage_scope] = TRUE () )

Coverage % =
DIVIDE (
    CALCULATE (
        COUNTROWS ( fact_stop_event ),
        fact_stop_event[is_in_coverage_scope] = TRUE (),
        fact_stop_event[is_observed] = TRUE ()
    ),
    [In-scope Stop Events]
)

Sample Size Flag =
IF ( [Observed Stop Events] < 30, "Insufficient (n < 30)", "OK" )
```

`Sample Size Flag` drives conditional formatting: grey font / grey bar for "Insufficient".

## Punctuality

```dax
On-time Stop Events =
CALCULATE ( COUNTROWS ( fact_stop_event ), fact_stop_event[is_on_time] = TRUE () )

Proxy OTP % =
DIVIDE ( [On-time Stop Events], [Observed Stop Events] )

OTP Target % =
DIVIDE ( SELECTEDVALUE ( dim_mode[target_punctuality_pct] ), 100 )

OTP vs Target (pp) =
IF (
    NOT ISBLANK ( [OTP Target %] ),
    ( [Proxy OTP %] - [OTP Target %] ) * 100
)

OTP Rolling 7d =
CALCULATE (
    [Proxy OTP %],
    DATESINPERIOD ( dim_date[date_day], MAX ( dim_date[date_day] ), -7, DAY )
)

Major Delay Share % =
DIVIDE (
    CALCULATE (
        COUNTROWS ( fact_stop_event ),
        fact_stop_event[delay_band] = "Major late (>15 min)"
    ),
    [Observed Stop Events]
)

OTP Status =
VAR gap = [OTP vs Target (pp)]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( gap ), "– No target",
        gap >= 0, "✔ Meets target",
        gap >= -5, "▲ Within 5 pts",
        "✖ Below target"
    )
```

`OTP Status` always pairs the icon with words, so status never relies on colour alone.

## Delay distribution

```dax
P50 Delay (min) =
DIVIDE (
    PERCENTILEX.INC (
        FILTER ( fact_stop_event, fact_stop_event[is_otp_eligible] = TRUE () ),
        fact_stop_event[delay_seconds],
        0.5
    ),
    60
)

P90 Delay (min) =
DIVIDE (
    PERCENTILEX.INC (
        FILTER ( fact_stop_event, fact_stop_event[is_otp_eligible] = TRUE () ),
        fact_stop_event[delay_seconds],
        0.9
    ),
    60
)

P95 Delay (min) =
DIVIDE (
    PERCENTILEX.INC (
        FILTER ( fact_stop_event, fact_stop_event[is_otp_eligible] = TRUE () ),
        fact_stop_event[delay_seconds],
        0.95
    ),
    60
)
```

Never show a mean delay on its own: delay is long-tailed, so the mean hides the bad tail.

## Reliability (service delivery)

```dax
Eligible Trips =
CALCULATE ( COUNTROWS ( fact_trip ), fact_trip[is_reliability_eligible] = TRUE () )

Cancelled Trips =
CALCULATE (
    COUNTROWS ( fact_trip ),
    fact_trip[is_reliability_eligible] = TRUE (),
    fact_trip[is_confirmed_cancelled] = TRUE ()
)

No-data Trips =
CALCULATE (
    COUNTROWS ( fact_trip ),
    fact_trip[is_reliability_eligible] = TRUE (),
    fact_trip[is_no_data] = TRUE ()
)

Reliability % =
IF ( [Eligible Trips] > 0, 1 - DIVIDE ( [Cancelled Trips], [Eligible Trips] ) )

Reliability Target % =
DIVIDE ( SELECTEDVALUE ( dim_mode[target_reliability_pct] ), 100 )
```

"No data" trips are shown next to reliability, never folded into it.

## Tram headways

```dax
Bunching Rate % =
DIVIDE (
    SUMX ( agg_headway_adherence,
           agg_headway_adherence[bunching_rate_pct] * agg_headway_adherence[n_pairs] ),
    SUM ( agg_headway_adherence[n_pairs] )
) / 100

Excess Wait (min) =
DIVIDE (
    SUMX ( agg_headway_adherence,
           agg_headway_adherence[excess_wait_s] * agg_headway_adherence[n_pairs] ),
    SUM ( agg_headway_adherence[n_pairs] )
) / 60
```

## Storytelling

```dax
Page Title - Network =
VAR m = SELECTEDVALUE ( dim_mode[mode_label], "All modes" )
RETURN
    m & ": proxy OTP " & FORMAT ( [Proxy OTP %], "0.0%" )
        & " vs " & FORMAT ( [OTP Target %], "0%" ) & " target, "
        & FORMAT ( [Coverage %], "0%" ) & " of collectable stop events observed"

Data Stamp =
"Collected " & FORMAT ( MIN ( dim_date[date_day] ), "d mmm yyyy" )
    & " – " & FORMAT ( MAX ( dim_date[date_day] ), "d mmm yyyy" )
    & " · MoveMelbourne proxy estimates, not official results"
```

# MoveMelbourne study report

> **Status: not yet written.** The collection study has not run. This file is a template; it is
> filled in only from committed model outputs once at least 14 days (target 28) of real data have
> been collected. No number below may be added by hand without a model output behind it.

## 1. Study window and coverage

- Window: `config/study.yaml` (start, end, days)
- Collector uptime (session hours ÷ window hours) and coverage per mode: `agg_coverage_daily`
- Gaps and their causes: coverage-check issues, `scripts/collector_status.py`

## 2. Headline results (each with coverage and n)

- Proxy OTP per mode vs target: `agg_otp_daily_mode`
- Reliability per mode: `fact_trip`
- Delay distribution (P50 / P90 / P95): `agg_otp_daily_mode`

## 3. Where and when

- Best and worst routes by bootstrap CI lower bound: `app/data/route_summary.parquet`
- Segments that add the most delay: `agg_segment_delay`
- Peak vs off-peak, weekday vs weekend, Melbourne Cup Day: `agg_otp_hour_dow`
- Tram bunching and excess wait: `agg_headway_adherence`
- Disruptions: `agg_disruption_otp`

## 4. Method checks

- Inference method agreement: `agg_inference_agreement`
- Join quality (trip match rate): `agg_coverage_daily.trip_match_rate`
- Outliers quarantined: `audit_outliers`

## 5. Validation against official figures

See [validation.md](validation.md).

## 6. Limitations

See [METHODOLOGY.md §8](../METHODOLOGY.md#8-limitations).

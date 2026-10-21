# ADR-007: The proxy OTP definition, and why it differs from official figures

- **Status:** Accepted (2026-10-21)

## Context

Official punctuality is measured by the operators under contract rules:

- **Metro:** a train is on time if it arrives no later than 4 min 59 s after schedule. Target 92%.
- **Yarra Trams:** a tram is on time if it is no more than 59 s early and no more than 4 min 59 s
  late, averaged over 3 of 5 monitoring points per route. Target 82% (charter, October 2025).

The realtime feed reports neither the operators' monitoring points nor replacement buses, and
arrivals have to be inferred (ADR-004).

## Decision

- **MoveMelbourne proxy OTP** = on-time observed stop events ÷ observed stop events, measured at
  **every observed stop**, using the same windows: metro `delay ≤ 299 s` (early not penalised);
  tram `−59 s ≤ delay ≤ 299 s`. Thresholds live in the `otp_thresholds` seed, with source and
  verification date.
- Every figure is labelled **"proxy OTP"** and shown with its **coverage** and **sample size**.
  Cells under 30 observed events are greyed out and never ranked.
- Routes are ranked by the **lower bound** of a trip-clustered bootstrap 95% CI (resampling
  trips, because stops on one trip share their delay); a Wilson bound is kept in the marts as a
  cheap SQL-side guard.
- **Reliability** = 1 − confirmed cancelled ÷ scheduled trips whose entire run fell inside
  collected time. "No data" trips (never seen while we were polling) are reported separately,
  never counted as cancelled or as run.
- Delays outside −30 / +120 min are quarantined in `audit_outliers`, not dropped silently.

## Consequences

- Expect a gap to the official figure. All-stop measurement weights long routes and the CBD
  heavily, early running is visible at intermediate stops, and the feed cannot see replacement
  buses. `docs/validation.md` explains the gap for the study month.
- Victoria also publishes **daily** operational performance reports, which allows a day-by-day
  comparison, not just one monthly number.

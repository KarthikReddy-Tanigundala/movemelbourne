# ADR-004: Inferring observed arrivals from prediction feeds

- **Status:** Accepted for build (2026-10-21); **primary method per mode to be confirmed after the
  day-one probe and the first week of real data** (`config/study.yaml: inference.primary_method`).

## Context

Trip-update feeds publish *predictions*: "this tram will reach stop 12 at 08:14:30". Nothing says
"it arrived at 08:14:42". Feeds also differ in what happens once a stop is passed: most drop the
stop from the trip's list, some keep it briefly with an updated time. Vehicle positions report
where a vehicle is and whether it is `STOPPED_AT` a stop, but only at the moment of each
60-second poll.

## Decision

Two methods, each labelled on every event (`inference_method`):

1. **Last prediction (primary).** For each service date × trip × scheduled stop, take the
   *latest* snapshot whose predicted arrival was within `freshness_window_s` (120 s) of the
   moment that snapshot was taken. That is the vehicle about to arrive (drop-out feeds), or just
   after it arrived (keep-stop feeds), so the rule works for both feed styles. Accept it only if:
   - the stop was not flagged `SKIPPED`;
   - the next snapshot came within `max_poll_gap_s` (180 s), so no correction was missed;
   - there is evidence the stop was passed: it dropped out while the trip stayed in the feed,
     the trip was still tracked after the predicted time, or the trip vanished while the
     collector was still polling.
2. **Vehicle position (secondary).** The first snapshot where the vehicle is `STOPPED_AT` the stop,
   or within 30 m of it at ≤ 1 m/s. Biased late by up to one poll interval, and misses short
   dwells.

Where both exist, `agg_inference_agreement` reports the median and P90 absolute difference and the
share of events whose on-time verdict would flip under the other method: the method's
self-validation.

**Unobserved events are never imputed.** They count against coverage, never towards OTP (enforced
by the dbt test `assert_unobserved_never_has_delay`).

## Consequences

- Precision is bounded by the 60 s polling: a last prediction can be up to one poll old, and the
  prediction itself has error. On the synthetic sample the methods agree to a median of 12 s
  (metro) and 18 s (tram); real figures replace these after collection.
- If DTP's feed turns out to send `arrival.delay` only, the model reconstructs the time as
  scheduled + delay (`prediction_type = 'delay_only'`).
- Switching a mode to vehicle-position-primary is one config value; the comparison data to justify
  it is produced automatically.

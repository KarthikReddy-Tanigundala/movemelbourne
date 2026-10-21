# Validation against official performance figures

> **Status: pending.** Written after the study, from published figures only. If the official
> results for the study period are not yet published when the report is finalised, this file says
> so and compares against the most recent published period instead.

## Sources to compare against

- Monthly: https://www.vic.gov.au/public-transport-monthly-performance (published around the 10th
  of the following month).
- Daily: https://www.vic.gov.au/public-transport-daily-operational-performance-reports
  (day-level, so each study day can be compared directly).

## Comparison table (to fill)

| Mode | Period | Official punctuality | MoveMelbourne proxy OTP | Coverage | Gap (pp) |
|---|---|---|---|---|---|
| Metro | | | | | |
| Tram | | | | | |

## Expected reasons for a gap

1. **Measurement points.** Official tram punctuality averages 3 of 5 monitoring points per route,
   and metro uses defined points. The proxy uses every observed stop, which weights long routes and
   the CBD more heavily.
2. **Early running.** The tram window penalises > 59 s early. At intermediate stops early running
   is more visible than at monitoring points.
3. **Replacement buses.** They are in the official service-delivery picture but absent from the
   realtime feed.
4. **Coverage.** Unobserved events (collector gaps, stale predictions) are excluded from the proxy.
   If they are not random (for example, more gaps during disruptions), the proxy is biased.
5. **Inference error.** Arrivals are inferred from 60-second snapshots (see the method-agreement
   statistics).

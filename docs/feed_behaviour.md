# Observed feed behaviour (first live test)

Measured on 21 Oct 2026, 22:56–23:02 AEDT: a 6-minute collection run (6 polls per feed, all
successful), then the full warehouse build on that data. It is a late-evening sliver, so these
are **behaviour checks, not performance findings**. Day-one probe details:
[probe_results.md](probe_results.md).

## Authentication

- `Ocp-Apim-Subscription-Key` header (what the OpenAPI specs say): **HTTP 401** for metro and tram.
- `KeyID` header (what the dataset page says): **HTTP 200**. Now first in
  `config/feeds.yaml: auth_methods`; negotiation stays in place in case DTP changes it (ADR-008).

## Trip updates

| | Metro | Tram |
|---|---|---|
| Trips in feed (23:00) | ~130 | ~250 |
| Stops listed per trip | all remaining stops (mean 4.1 at night, up to 14) | ~2.5: the stop being served and the next one or two |
| When a stop first appears | well ahead: median 24 min before its time | median **0 s** from its time: trams report stops as they reach them |
| After the stop is passed | stays listed with a past time for 1–4 min; ~17% of stops had their value revised, sometimes *after* passing (e.g. delay −60 → −120 s) | stays ~1 poll with a past time |
| Time precision | **whole minutes** (every `arrival_time` minute-aligned; delays in multiples of 60 s) | seconds |
| `start_date`, `stop_id`, `stop_sequence` | 100% populated | 100% populated |
| `direction_id`, `vehicle.id` | absent | absent |
| Trip ID format | matches the static timetable (`02-HBE--71-T5-1957`) | matches (`03-86--8-T5-146654548`) |
| `ADDED` trips | 2, with a different ID scheme (`vic:02SUY:_:R:vpt._Sunbury_Z352_20261021`) | none |

**Consequences**
- The inference rule (latest snapshot within ±120 s of the reported time) fits both patterns. For
  trams it effectively reads the time reported as the tram reaches the stop. For metro it reads
  the value shortly after passing, which includes post-passing revisions.
- **Metro minute resolution** limits precision. A train reported at "+5 min" may have been 4:31
  or 5:29 late, depending on how DTP rounds. Proxy OTP for metro is therefore quantised around
  the 4:59 threshold; this is stated in ADR-007 and METHODOLOGY §8, and the validation against
  official figures will show whether it biases the result.
- **Trip match rate 100%** (metro 132/132, tram 251/251 non-ADDED trips) against the versioned
  timetable, so no ID reshaping is needed.

## Vehicle positions

- Fields present: trip (with `start_date`), latitude/longitude, timestamp, vehicle id (metro: the
  consist, e.g. `1172T-1181T-611M-643M-644M-662M`; tram: fleet number plus label).
- **Absent:** `current_status`, `stop_id`, `current_stop_sequence`, `speed` (metro has bearing).
- Freshness at poll time: tram median 68 s (P90 90 s). Metro median 19 s, but **24% are older
  than 3 minutes** (likely stabled or terminating trains).

**Consequences.** The `STOPPED_AT` fallback cannot work on this feed. `int_vp_stop_arrivals` now
uses **proximity to the trip's own scheduled stops** (first fresh position within 30 m),
drops positions older than 180 s, and counts a repeated report once. First agreement check
between the two methods (same stop events, n small):

| Mode | Events with both methods | Median gap | Within 60 s | On-time verdict flips |
|---|---|---|---|---|
| Tram | 94 | 30.5 s | 83% | 12.8% |
| Metro | 23 | 27 s | 91% | 0% |

## Service alerts

- Metro: 29 alerts; tram: 1 alert at the time of the test.

## Volume (first indication; the full 24-hour estimate goes in `volume_estimate.md`)

The 6-minute run produced 13 files. Payload sizes at 23:00: metro trip updates ~48 KB, tram
~40 KB per poll. Daytime payloads will be larger; measure over 24 h before deciding on bus or
V/Line (ADR-001).

# ADR-001: Scope is Metro Train + Yarra Trams; bus and V/Line are gated stretch

- **Status:** Accepted (2026-10-21)
- **Deciders:** Karthik Reddy Tanigundala

## Context

Transport Victoria publishes GTFS-Realtime for four modes. They differ in what they offer:

| Mode | Trip updates | Vehicle positions | Service alerts | Notes |
|---|---|---|---|---|
| Metro Train | ✅ | ✅ | ✅ | Official punctuality: ≤ 4 min 59 s late; 92% target |
| Yarra Trams | ✅ | ✅ | ✅ | Official: −59 s / +4 min 59 s at monitoring points; 82% target |
| Metro & Regional Bus | ✅ | ✅ | — | Very large feed; no cancellations in trip updates (DTP spec) |
| V/Line | ✅ | ✅ | — | Different auth header name in its spec (`KeyId`) |

Collection runs on free infrastructure (GitHub Actions minutes, a free Hugging Face dataset) for
28 days, and every extra mode multiplies storage and run time. The two core modes also have the
clearest published punctuality definitions to validate against.

## Decision

Collect **metro and tram only** from day one. Bus and V/Line stay in the code (`config/feeds.yaml`,
`enabled: false`) and are switched on only if `docs/volume_estimate.md`, written after the first
24 hours, shows the 28-day projection stays comfortable (rough guide: under ~20 GB, runs finishing
inside the 29-minute loop).

## Consequences

- The study answers "how reliable are Melbourne's trains and trams", not the whole network.
- Enabling a stretch mode is a config change plus a timetable branch (`--include-stretch`), with
  no code change, because nothing is hard-coded per mode except seeds (`modes.csv`,
  `otp_thresholds.csv`) that need a row for the new mode.
- Bus OTP would need its own definition and could not report reliability from trip updates alone
  (no cancellations in that feed), which is another reason it is not core.

# Sources (verified 2026-10-21)

| What | URL | Notes |
|---|---|---|
| GTFS-Realtime dataset page | https://opendata.transport.vic.gov.au/dataset/gtfs-realtime | Says header `KeyID`; 24 calls / 60 s per mode; tram refresh 60 s |
| Realtime endpoint pattern | `https://api.opendata.transport.vic.gov.au/opendata/public-transport/gtfs/realtime/v1/{metro,tram,bus,vline}/{trip-updates,vehicle-positions,service-alerts}` | Paths confirmed in each mode's OpenAPI JSON (linked from the dataset page). Bus and V/Line have no service-alerts feed |
| OpenAPI auth (metro, tram, bus) | dataset page → per-feed `*.openapi.json` | `Ocp-Apim-Subscription-Key` header or `subscription-key` query; "rate limit of 20-27 calls per minute … caching time of 30 seconds" |
| OpenAPI auth (V/Line) | dataset page → `gtfsr_vline_trip_updates.openapi.json` | header `KeyId` |
| Metro feed limitation | metro trip-updates OpenAPI description | excludes replacement buses, service deviations and platform information |
| GTFS Schedule | https://opendata.transport.vic.gov.au/dataset/gtfs-schedule | Release of 16 Oct 2026: 267,860,262 bytes; outer folders 1-6, 10, 11, each a nested `google_transit.zip` |
| GTFS release notes | https://data.ptv.vic.gov.au/downloads/GTFSReleaseNotes.pdf | |
| Official monthly performance | https://www.vic.gov.au/public-transport-monthly-performance | Metro target 92% punctuality / 98.5% reliability; tram 82% / 98.5% (MR5 contract from 1 Dec 2024) |
| Official daily reports | https://www.vic.gov.au/public-transport-daily-operational-performance-reports | Day-level validation |
| Network performance method | https://www.vic.gov.au/public-transport-network-performance | Tram punctuality averaged over 3 of 5 monitoring points; ≤ 4:59 late and ≤ 0:59 early |
| Yarra Trams Customer Charter (Oct 2025) | https://yarratrams.com.au/media/n3kptrjv/yarra-trams-customer-charter-2025_october.pdf | Tram on-time window and 82% compensation threshold |
| Victorian public holidays | `holidays` Python package, `Australia(subdiv="VIC")` | Seed `vic_public_holidays.csv`; includes Melbourne Cup Day 3 Nov 2026 |

Licence: GTFS Schedule and GTFS-Realtime © Department of Transport and Planning, Creative Commons
Attribution 4.0.

**Still to verify** (once the API key exists): the day-one probe (`scripts/probe_feeds.py` →
`docs/probe_results.md`) records the auth method that actually works per mode, field population
(`arrival.time` vs `arrival.delay`, `start_date`, `stop_sequence`), and whether passed stops drop
out of the trip-updates feed.

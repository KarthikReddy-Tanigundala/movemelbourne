# Day-one probe results

Probed 2026-10-21 22:55 AEDT by `scripts/probe_feeds.py`.
Fixtures saved to `tests/fixtures/` (trimmed to the first 40 entities).

| Mode | Feed | HTTP | Auth method | Bytes | Header ts (local) | Lag s | Entities |
|---|---|---|---|---|---|---|---|
| metro | trip-updates | 200 | `keyid_header` | 48,158 | 2026-10-21 22:55:17 | 4 | 131 |
| metro | vehicle-positions | 200 | `keyid_header` | 12,296 | 2026-10-21 22:55:21 | 1 | 88 |
| metro | service-alerts | 200 | `keyid_header` | 33,719 | 2026-10-21 22:55:13 | 9 | 29 |
| tram | trip-updates | 200 | `keyid_header` | 40,263 | 2026-10-21 22:55:17 | 5 | 243 |
| tram | vehicle-positions | 200 | `keyid_header` | 8,863 | 2026-10-21 22:54:56 | 27 | 73 |
| tram | service-alerts | 200 | `keyid_header` | 1,624 | 2026-10-21 22:55:12 | 11 | 1 |

## Trip-update field population

### metro trip updates

| Field | Populated |
|---|---|
| trips | 131 |
| stop_time_updates | 1000 |
| stu.arrival.delay | 93.5% |
| stu.arrival.time | 93.5% |
| stu.departure.delay | 98.6% |
| stu.departure.time | 98.6% |
| stu.stop_id | 100.0% |
| stu.stop_sequence | 100.0% |
| trip.canceled | 0.0% |
| trip.direction_id | 0.0% |
| trip.route_id | 100.0% |
| trip.start_date | 100.0% |
| vehicle.id | 0.0% |
| example trip_id | `02-HBE--71-T5-1957` |
| example route_id | `aus:vic:vic-02-HBE:` |
| example stop_id | `15337` |

### tram trip updates

| Field | Populated |
|---|---|
| trips | 243 |
| stop_time_updates | 503 |
| stu.arrival.delay | 68.0% |
| stu.arrival.time | 75.3% |
| stu.departure.delay | 78.1% |
| stu.departure.time | 85.5% |
| stu.stop_id | 100.0% |
| stu.stop_sequence | 100.0% |
| trip.canceled | 0.0% |
| trip.direction_id | 0.0% |
| trip.route_id | 100.0% |
| trip.start_date | 100.0% |
| vehicle.id | 0.0% |
| example trip_id | `03-86--8-T5-146654548` |
| example route_id | `aus:vic:vic-03-86:` |
| example stop_id | `46874` |

## Reading this table

- **Auth method** is the first method in `config/feeds.yaml: auth_methods` that the gateway accepted (ADR-008).
- **arrival.time vs arrival.delay** population decides the observed-arrival inference method per mode (ADR-004).
- **Lag** = poll time minus `header.timestamp`; DTP caches responses ~30 s.

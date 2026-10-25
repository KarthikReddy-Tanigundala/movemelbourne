# Volume estimate

Generated 2026-10-25 16:10 by `scripts/volume_estimate.py` from 16.1 collector-hours of real data (local bridge collector, 22–25 Oct 2026). Projection: 28 days at 100% uptime (672 h).

## Core modes (measured)

| Mode | Feed | Collector-h | MB downloaded / h | MB stored / h | Rows / h | Projected stored (28 d) | Projected rows |
|---|---|---|---|---|---|---|---|
| metro | service-alerts | 16.1 | 1.35 | 0.09 | 11,585 | 0.06 GB | 7.8 M |
| metro | trip-updates | 16.1 | 2.40 | 0.32 | 50,378 | 0.22 GB | 33.9 M |
| metro | vehicle-positions | 16.1 | 0.57 | 0.13 | 4,055 | 0.09 GB | 2.7 M |
| tram | service-alerts | 16.1 | 0.05 | 0.04 | 986 | 0.02 GB | 0.7 M |
| tram | trip-updates | 16.1 | 2.36 | 0.40 | 32,864 | 0.27 GB | 22.1 M |
| tram | vehicle-positions | 16.1 | 0.46 | 0.11 | 3,800 | 0.07 GB | 2.6 M |

**Core total (28 days):** about **0.7 GB** of zstd Parquet and **70 M rows**; downloads about 4.8 GB. Parquet keeps 15% of downloaded bytes (columnar + zstd + duplicate snapshots skipped).

Note: the measured hours are skewed to evenings and nights (laptop availability), when fewer services run, so daytime-heavy full days will be larger. Treat these as lower bounds and re-run after a week of the GitHub Actions collector.

## Stretch modes (one live payload each)

Sampled Sun 25 Oct 16:10. Projection = payload bytes x 60 polls/h x 672 h x 0.15 (core bytes-to-Parquet ratio).

| Mode | Feed | Payload KB | Auth | Projected stored |
|---|---|---|---|---|
| bus | trip-updates | 988 | `keyid_header` | 6.0 GB |
| bus | vehicle-positions | 93 | `keyid_header` | 0.6 GB |
| vline | trip-updates | 9 | `keyid_header` | 0.1 GB |
| vline | vehicle-positions | 4 | `keyid_header` | 0.0 GB |

**Stretch total:** about **6.7 GB** on top of the core modes.

## Limits this has to fit

- **GitHub Actions:** public repo, so minutes are free. The collector uses about 30 runner-minutes per 30-minute slot (~1,440 min/day), well inside a 6-hour job limit.
- **Hugging Face:** one commit per run (~48/day); public datasets have generous storage, and the core projection is small.
- **Local warehouse:** DuckDB scans Parquet out of core; tens of millions of rows build in minutes on a laptop.

## Decision (ADR-001)

Scope stays **metro + tram** (decided 21 Oct 2026). These numbers say what extending would cost: V/Line is a negligible addition; bus is roughly ten times the core volume but still inside the ~20 GB guide. Enabling either is `enabled: true` in `config/feeds.yaml` plus a timetable snapshot with `--include-stretch`.

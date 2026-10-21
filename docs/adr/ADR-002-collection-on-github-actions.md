# ADR-002: Self-collection with a 29-minute poll loop on a 30-minute schedule

- **Status:** Accepted (2026-10-21; loop length revised from the spec's 27 minutes)

## Context

GTFS-Realtime is ephemeral: there is no official Melbourne archive, so every hour without a
collector is data lost for good. The collector must run unattended for 28 days on free
infrastructure. GitHub Actions is free for public repos, but its minimum schedule is 5 minutes and
scheduled runs often start several minutes late. DTP caches responses for 30 s, so polling faster
than every 60 s returns copies.

## Decision

- Each scheduled run polls every enabled feed every **60 s in one long loop**, then writes one
  Parquet file per feed and publishes the run in **one** Hugging Face commit.
- The loop runs **29 minutes** on a **30-minute** cron, with a concurrency group that queues
  (never cancels or overlaps) runs.
- Until the repo and secrets exist, the **same code** runs as a local "bridge" collector from a
  Windows scheduled task (`scripts/register_local_collector.ps1`), uploading to the same dataset.
  Duplicate snapshots from overlapping collectors are removed in dbt.
- A daily `coverage_check.yml` opens a GitHub issue on any gap over 2 hours or poll success
  under 90%.

### Why 29 and not 27 minutes

An arrival can only be inferred if a snapshot was taken shortly before it (ADR-004). With a
27-minute loop every 30 minutes, each run boundary leaves a gap of at least 3 minutes plus
start-up time. That is roughly 10% of all clock time when arrivals are unobservable, and the gaps
fall at the same minute past every half hour, which would bias by time of day. With 29 minutes:

- On Actions, a late scheduled start simply queues behind the running loop and starts the moment
  it ends (only setup time is lost).
- Locally, the gap is about a minute, below `max_poll_gap_s` (180 s), so events in it still count
  as collected.

## Consequences

- Up to ~48 Hugging Face commits per day, well inside its limits; the git repo stays small.
- Runs are idempotent (run id = GitHub run id + attempt), so a re-run overwrites rather than
  duplicates.
- A partial run is never discarded: the collector writes and uploads what it has before exiting
  non-zero. If the upload itself fails, the workflow keeps the run as an artifact for 7 days.
- GitHub disables schedules after 60 days without repo activity; the weekly static snapshot commits
  a line to `docs/feed_versions.md`, which keeps the repo active.
- Backup (documented, not built): the same collector on an always-on free VM with cron.

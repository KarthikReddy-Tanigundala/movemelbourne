"""Summarise collection health from the coverage log in the local lake.

    uv run python scripts/collector_status.py                     # last 24 hours
    uv run python scripts/collector_status.py --hours 168
    uv run python scripts/collector_status.py --report status.md  # markdown (coverage_check.yml)

Prints per-feed poll success, rows captured and the auth method in use, plus every gap of more
than 3 minutes between consecutive runs. Exits 1 (unhealthy) when, within the window:
- any gap between runs exceeds `quality.coverage_gap_alert_hours`,
- the latest run is older than that threshold (collector stopped), or
- poll success for any feed is below `quality.min_poll_success_rate`.
The daily GitHub workflow turns a non-zero exit into an issue, so failures are loud.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from movemelbourne import config
from movemelbourne.utils.lake import lake_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--report", type=Path, help="also write a markdown report here")
    args = parser.parse_args()
    quality = config.study_config()["quality"]
    gap_alert_s = quality["coverage_gap_alert_hours"] * 3600
    min_success_pct = 100 * quality["min_poll_success_rate"]

    cov = lake_dir() / "raw" / "coverage"
    if not any(cov.rglob("*.parquet")):
        message = f"No coverage files under {cov}: the collector has not published anything."
        print(message)
        if args.report:
            args.report.write_text(f"## Collector health\n\n{message}\n", encoding="utf-8")
        return 1

    now = int(time.time())
    since = int(now - args.hours * 3600)
    con = duckdb.connect()
    con.execute(
        f"create view cov as select * from read_parquet('{cov.as_posix()}/**/*.parquet', "
        f"union_by_name = true) where run_start_utc >= {since}"
    )
    feeds = con.sql("""
        select mode, feed, count(distinct run_id) as runs, sum(polls_attempted) as attempted,
               round(100.0 * sum(polls_succeeded) / nullif(sum(polls_attempted), 0), 1)
                   as success_pct,
               sum(polls_duplicate) as duplicate, sum(rows_written) as rows_written,
               string_agg(distinct auth_method, ', ') as auth,
               strftime(max(to_timestamp(latest_feed_ts) at time zone 'Australia/Melbourne'),
                        '%Y-%m-%d %H:%M') as latest_local
        from cov group by all order by mode, feed""").df()
    gaps = con.sql("""
        with r as (select distinct run_start_utc, run_end_utc from cov where feed = 'trip-updates')
        select strftime(to_timestamp(prev_end) at time zone 'Australia/Melbourne',
                        '%Y-%m-%d %H:%M') as gap_from,
               strftime(to_timestamp(run_start_utc) at time zone 'Australia/Melbourne',
                        '%Y-%m-%d %H:%M') as gap_to,
               round((run_start_utc - prev_end) / 60.0, 1) as minutes
        from (select *, lag(run_end_utc) over (order by run_start_utc) as prev_end from r)
        where run_start_utc - prev_end > 180 order by gap_from""").df()
    latest_end = con.sql("select max(run_end_utc) from cov").fetchone()[0]

    problems: list[str] = []
    if latest_end is None or now - latest_end > gap_alert_s:
        problems.append(f"no collector run has finished in the last {gap_alert_s / 3600:g} h")
    long_gaps = gaps[gaps["minutes"] * 60 > gap_alert_s]
    if len(long_gaps):
        problems.append(f"{len(long_gaps)} gap(s) longer than {gap_alert_s / 3600:g} h")
    low = feeds[feeds["success_pct"].fillna(0) < min_success_pct]
    for _, row in low.iterrows():
        problems.append(
            f"{row['mode']}/{row['feed']} poll success {row['success_pct']}% < {min_success_pct:g}%"
        )

    gaps_text = gaps.to_string(index=False) if len(gaps) else "  none"
    print(f"Collection health, last {args.hours:g} h ({lake_dir()})\n")
    print(feeds.to_string(index=False))
    print(f"\nGaps between runs over 3 minutes:\n{gaps_text}")
    print("\nStatus: " + ("UNHEALTHY - " + "; ".join(problems) if problems else "healthy"))

    if args.report:
        lines = [
            f"## Collector health - last {args.hours:g} h",
            "",
            "**Status:** " + ("UNHEALTHY" if problems else "healthy"),
            "",
        ]
        lines += [f"- {p}" for p in problems] + ([""] if problems else [])
        lines += [
            "### Per feed",
            "",
            feeds.to_markdown(index=False),
            "",
            "### Gaps between runs over 3 minutes",
            "",
            gaps.to_markdown(index=False) if len(gaps) else "None.",
            "",
        ]
        args.report.write_text("\n".join(lines), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

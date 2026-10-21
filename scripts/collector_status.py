"""Summarise collection health from the coverage log in the local lake.

    uv run python scripts/collector_status.py            # last 24 hours
    uv run python scripts/collector_status.py --hours 168

Prints per-feed poll success, rows captured, the auth method in use, and every gap longer than
3 minutes between consecutive runs, so a sleeping PC or a stalled
GitHub schedule is obvious within minutes rather than at analysis time.
"""

from __future__ import annotations

import argparse
import sys
import time

import duckdb

from movemelbourne import config
from movemelbourne.utils.lake import lake_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--hours", type=float, default=24)
    args = parser.parse_args()
    cov = lake_dir() / "raw" / "coverage"
    if not any(cov.rglob("*.parquet")):
        print(f"No coverage files under {cov} yet.")
        return 1
    since = int(time.time() - args.hours * 3600)
    gap_alert_s = config.study_config()["quality"]["coverage_gap_alert_hours"] * 3600
    con = duckdb.connect()
    con.execute(
        f"create view cov as select * from read_parquet('{cov.as_posix()}/**/*.parquet', "
        f"union_by_name = true) where run_start_utc >= {since}"
    )
    print(f"Collection health, last {args.hours:g} h ({lake_dir()})\n")
    print(
        con.sql("""
        select mode, feed, count(distinct run_id) runs, sum(polls_attempted) attempted,
               round(100.0 * sum(polls_succeeded) / nullif(sum(polls_attempted), 0), 1) success_pct,
               sum(polls_duplicate) duplicate, sum(rows_written) rows_written, any_value(auth_method) auth,
               max(to_timestamp(latest_feed_ts) at time zone 'Australia/Melbourne') latest_local
        from cov group by all order by mode, feed""")
        .df()
        .to_string(index=False)
    )
    gaps = con.sql("""
        with r as (select distinct run_start_utc, run_end_utc from cov where feed = 'trip-updates')
        select to_timestamp(prev_end) at time zone 'Australia/Melbourne' as gap_from,
               to_timestamp(run_start_utc) at time zone 'Australia/Melbourne' as gap_to,
               round((run_start_utc - prev_end) / 60.0, 1) as minutes
        from (select *, lag(run_end_utc) over (order by run_start_utc) prev_end from r)
        where run_start_utc - prev_end > 180 order by gap_from""").df()
    print("\nGaps between runs over 3 minutes:")
    print(gaps.to_string(index=False) if len(gaps) else "  none")
    long_gaps = gaps[gaps["minutes"] * 60 > gap_alert_s] if len(gaps) else gaps
    return 1 if len(long_gaps) else 0


if __name__ == "__main__":
    sys.exit(main())

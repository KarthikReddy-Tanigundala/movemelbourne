"""Create the bronze layer: DuckDB views over the Parquet files in the local lake (§8.1).

Bronze is deliberately thin: one view per source, columns exactly as written by the collector or
the static snapshot, plus ``source_file`` for lineage. dbt staging models read these views via
``source('bronze', ...)``.

    uv run python -m movemelbourne.load.bronze

Views are rebuilt on every run, so new files in the lake are picked up without touching dbt.
When a source has no files yet (e.g. service alerts on day one) the view is an empty table with
the collector's fixed schema, so downstream models still compile and run.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import pyarrow as pa

from movemelbourne import config
from movemelbourne.collect.parse import SCHEMAS
from movemelbourne.collect.run_collection import COVERAGE_SCHEMA
from movemelbourne.utils.lake import lake_dir
from movemelbourne.utils.logging import setup_logging

logger = logging.getLogger("movemelbourne.bronze")

REALTIME = {
    "rt_trip_updates": ("realtime/trip_updates", SCHEMAS["trip-updates"]),
    "rt_vehicle_positions": ("realtime/vehicle_positions", SCHEMAS["vehicle-positions"]),
    "rt_service_alerts": ("realtime/service_alerts", SCHEMAS["service-alerts"]),
    "rt_coverage": ("coverage", COVERAGE_SCHEMA),
}
SCHEDULE_TABLES = (
    "agency",
    "routes",
    "trips",
    "stops",
    "stop_times",
    "calendar",
    "calendar_dates",
    "shapes",
)


def _sql_type(dtype: pa.DataType) -> str:
    return {
        pa.string(): "VARCHAR",
        pa.int64(): "BIGINT",
        pa.int32(): "INTEGER",
        pa.float64(): "DOUBLE",
        pa.float32(): "FLOAT",
    }[dtype]


def _empty_view(con: duckdb.DuckDBPyConnection, name: str, schema: pa.Schema) -> None:
    cols = ", ".join(f"cast(null as {_sql_type(f.type)}) as {f.name}" for f in schema)
    con.execute(
        f"create or replace view bronze.{name} as "
        f"select {cols}, cast(null as varchar) as source_file where false"
    )


def _glob(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def build(con: duckdb.DuckDBPyConnection, lake: Path, derived: Path) -> dict[str, int]:
    """(Re)create every bronze view. Returns file counts per view for logging/tests."""
    con.execute("create schema if not exists bronze")
    counts: dict[str, int] = {}
    raw = lake / "raw"

    for view, (sub, schema) in REALTIME.items():
        files = sorted((raw / sub).rglob("*.parquet"))
        counts[view] = len(files)
        if not files:
            _empty_view(con, view, schema)
            continue
        # The collector writes `mode` both as a column and a hive folder; read the column only.
        con.execute(f"""
            create or replace view bronze.{view} as
            select * exclude (filename), filename as source_file
            from read_parquet('{_glob(raw / sub)}/**/*.parquet', union_by_name = true,
                              hive_partitioning = false, filename = true)""")

    for table in SCHEDULE_TABLES:
        files = sorted((raw / "schedule").glob(f"feed_version=*/mode_branch=*/{table}.parquet"))
        counts[f"gtfs_{table}"] = len(files)
        if not files:
            if table == "calendar_dates":
                con.execute("""create or replace view bronze.gtfs_calendar_dates as
                    select null::varchar service_id, null::varchar date, null::varchar exception_type,
                           null::varchar feed_version, null::varchar mode_branch,
                           null::varchar source_file where false""")
                continue
            raise FileNotFoundError(
                f"no {table}.parquet in {raw / 'schedule'}; run static_snapshot"
            )
        con.execute(f"""
            create or replace view bronze.gtfs_{table} as
            select * exclude (filename), filename as source_file
            from read_parquet('{_glob(raw / "schedule")}/feed_version=*/mode_branch=*/{table}.parquet',
                              union_by_name = true, hive_partitioning = true,
                              hive_types_autocast = false, filename = true)""")

    versions = sorted((raw / "schedule_versions").glob("*.parquet"))
    counts["gtfs_schedule_versions"] = len(versions)
    con.execute(f"""
        create or replace view bronze.gtfs_schedule_versions as
        select * from read_parquet('{_glob(raw / "schedule_versions")}/*.parquet',
                                   union_by_name = true, hive_partitioning = false)""")

    calendar = derived / "service_calendar.parquet"
    if not calendar.exists():
        raise FileNotFoundError(f"{calendar} missing; run movemelbourne.ingest.load_schedule")
    con.execute(
        f"create or replace view bronze.service_calendar as "
        f"select * from read_parquet('{_glob(calendar)}')"
    )
    counts["service_calendar"] = 1
    return counts


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=config.WAREHOUSE_PATH)
    args = parser.parse_args(argv)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(args.db)) as con:
        counts = build(con, lake_dir(), config.DATA_DIR / "derived")
        for view, n in counts.items():
            rows = con.sql(f"select count(*) from bronze.{view}").fetchone()[0]
            logger.info("bronze.%-24s %4d files %12s rows", view, n, f"{rows:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

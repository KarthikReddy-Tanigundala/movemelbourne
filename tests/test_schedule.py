"""Service calendar expansion, lake publishing and bronze views over the committed sample."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

from movemelbourne.ingest.load_schedule import build_service_calendar, expand_calendar
from movemelbourne.load import bronze
from movemelbourne.utils.lake import publish_to_lake
from movemelbourne.utils.timeutil import service_day_reference_epoch

SAMPLE_LAKE = Path(__file__).parent / "sample" / "lake"
WEEKDAYS = {
    "monday": "1",
    "tuesday": "1",
    "wednesday": "1",
    "thursday": "1",
    "friday": "1",
    "saturday": "0",
    "sunday": "0",
}


def test_expand_calendar_applies_weekdays_and_exceptions():
    calendar = [{"service_id": "T5", **WEEKDAYS, "start_date": "20261102", "end_date": "20261106"}]
    calendar_dates = [
        {"service_id": "T5", "date": "20261103", "exception_type": "2"},  # Cup Day removed
        {"service_id": "UU", "date": "20261103", "exception_type": "1"},  # holiday service added
    ]
    active = expand_calendar(calendar, calendar_dates)
    running = sorted((d, s) for (d, s), runs in active.items() if runs)
    assert (date(2026, 11, 3), "T5") not in running
    assert (date(2026, 11, 3), "UU") in running
    assert [d.day for d, s in running if s == "T5"] == [2, 4, 5, 6]


def test_publish_to_lake_mirrors_relative_paths(tmp_path):
    run = tmp_path / "runs" / "r1"
    f = run / "raw" / "realtime" / "trip_updates" / "mode=tram" / "dt=2026-10-22" / "run_r1.parquet"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    lake = tmp_path / "lake"
    assert publish_to_lake(run, lake) == 1
    assert (lake / f.relative_to(run)).read_bytes() == b"x"
    assert publish_to_lake(run, lake) == 1  # idempotent overwrite, still one file


@pytest.mark.skipif(not SAMPLE_LAKE.exists(), reason="sample not generated")
def test_service_calendar_on_sample_has_dst_correct_reference():
    table = build_service_calendar(SAMPLE_LAKE).to_pylist()
    assert table, "sample timetable should produce service days"
    for row in table[:50]:
        assert row["ref_epoch"] == service_day_reference_epoch(row["service_date"])


@pytest.mark.skipif(not SAMPLE_LAKE.exists(), reason="sample not generated")
def test_bronze_views_over_sample(tmp_path):
    derived = tmp_path / "derived"
    derived.mkdir()
    pq.write_table(build_service_calendar(SAMPLE_LAKE), derived / "service_calendar.parquet")
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    counts = bronze.build(con, SAMPLE_LAKE, derived)
    assert counts["rt_trip_updates"] > 0 and counts["gtfs_stop_times"] == 2
    # Hive partition values stay strings so IDs and branch codes are never reshaped.
    assert (
        con.sql("select typeof(mode_branch) from bronze.gtfs_routes limit 1").fetchone()[0]
        == "VARCHAR"
    )
    assert con.sql("select count(*) from bronze.rt_trip_updates").fetchone()[0] > 0


def test_bronze_empty_realtime_source_gives_typed_empty_view(tmp_path):
    con = duckdb.connect()
    con.execute("create schema bronze")
    bronze._empty_view(con, "rt_service_alerts", bronze.REALTIME["rt_service_alerts"][1])
    cols = {r[0]: r[1] for r in con.sql("describe bronze.rt_service_alerts").fetchall()}
    assert cols["active_start"] == "BIGINT" and cols["source_file"] == "VARCHAR"
    assert con.sql("select count(*) from bronze.rt_service_alerts").fetchone()[0] == 0

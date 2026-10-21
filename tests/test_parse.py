"""Protobuf flattening: core schema, cancellations, multi-entity alerts, schema drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FEED_TS

from movemelbourne.collect.parse import SCHEMAS, parse_feed, to_table

FIXTURES = Path(__file__).parent / "fixtures"


def test_trip_updates_one_row_per_stop_plus_cancelled_trip(trip_updates_pb):
    rows, feed_ts, n = parse_feed("trip-updates", trip_updates_pb, "metro", FEED_TS + 2)
    assert feed_ts == FEED_TS and n == 2
    assert len(rows) == 3
    first, skipped, cancelled = rows
    assert first["arrival_delay"] == 75 and first["arrival_time"] == FEED_TS + 60
    assert first["departure_delay"] is None  # unset optional stays null, not 0
    assert first["direction_id"] == 1 and first["n_stop_time_updates"] == 2
    assert skipped["stu_schedule_relationship"] == "SKIPPED" and skipped["arrival_time"] is None
    assert cancelled["trip_schedule_relationship"] == "CANCELED"
    assert cancelled["stop_id"] is None and cancelled["n_stop_time_updates"] == 0


def test_trip_update_extras_capture_fields_outside_core_schema(trip_updates_pb):
    rows, *_ = parse_feed("trip-updates", trip_updates_pb, "metro", FEED_TS)
    extra = json.loads(rows[0]["extra_json"])
    assert extra["trip_update"]["vehicle"] == {"label": "1M"}
    assert extra["stu"]["arrival"] == {"uncertainty": 30}
    assert rows[0]["vehicle_id"] == "X'Trap 1"


def test_vehicle_positions(vehicle_positions_pb):
    rows, *_ = parse_feed("vehicle-positions", vehicle_positions_pb, "tram", FEED_TS)
    (row,) = rows
    assert row["current_status"] == "STOPPED_AT"
    assert row["occupancy_status"] == "FEW_SEATS_AVAILABLE"
    assert row["vehicle_label"] == "E 6001"
    assert row["latitude"] == pytest.approx(-37.81)
    assert row["speed"] == pytest.approx(0.4)


def test_alerts_explode_entities_by_periods(service_alerts_pb):
    rows, *_ = parse_feed("service-alerts", service_alerts_pb, "tram", FEED_TS)
    assert len(rows) == 4  # 2 informed entities x 2 active periods
    assert {r["effect"] for r in rows} == {"SIGNIFICANT_DELAYS"}
    assert sum(r["active_end"] is None for r in rows) == 2  # open-ended period
    assert rows[0]["header_text"] == "Delays on route 109"
    assert json.loads(rows[0]["extra_json"]) == {"severity_level": "WARNING"}


@pytest.mark.parametrize("feed", list(SCHEMAS))
def test_to_table_matches_fixed_schema(feed, request):
    fixture = {"trip-updates": "trip_updates_pb", "vehicle-positions": "vehicle_positions_pb",
               "service-alerts": "service_alerts_pb"}[feed]
    rows, *_ = parse_feed(feed, request.getfixturevalue(fixture), "tram", FEED_TS)
    table = to_table(feed, rows)
    assert table.schema.equals(SCHEMAS[feed])
    assert table.num_rows == len(rows)


def test_empty_feed_gives_empty_table():
    from google.transit import gtfs_realtime_pb2 as rt

    msg = rt.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    rows, ts, n = parse_feed("trip-updates", msg.SerializeToString(), "metro", 0)
    assert rows == [] and ts is None and n == 0
    assert to_table("trip-updates", rows).num_rows == 0


@pytest.mark.parametrize("pb", sorted(FIXTURES.glob("*.pb")), ids=lambda p: p.name)
def test_real_captured_fixtures_parse(pb: Path):
    """Payloads captured by scripts/probe_feeds.py must always parse (parser regression guard)."""
    mode, feed = pb.stem.split("__")
    rows, feed_ts, n = parse_feed(feed, pb.read_bytes(), mode, 0)
    assert feed_ts is not None
    to_table(feed, rows)

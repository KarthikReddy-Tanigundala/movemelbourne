"""Shared fixtures: small GTFS-Realtime messages built in code.

Real captured payloads (from scripts/probe_feeds.py) live in tests/fixtures/*.pb and are tested
separately when present; these hand-built ones pin down edge cases the live feed may not show
on any given day (cancelled trips, multi-period alerts, unknown extra fields).
"""

from __future__ import annotations

import pytest
from google.transit import gtfs_realtime_pb2 as rt

FEED_TS = 1_792_490_400  # 2026-10-20T10:00:00Z (21:00 Melbourne)


def _header(msg: rt.FeedMessage, ts: int = FEED_TS) -> None:
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.incrementality = rt.FeedHeader.FULL_DATASET
    msg.header.timestamp = ts


@pytest.fixture
def trip_updates_pb() -> bytes:
    msg = rt.FeedMessage()
    _header(msg)
    e = msg.entity.add(id="tu-1")
    tu = e.trip_update
    tu.trip.trip_id = "02-ALM--1-T2-2302"
    tu.trip.route_id = "aus:vic:vic-02-ALM:"
    tu.trip.direction_id = 1
    tu.trip.start_date = "20261020"
    tu.trip.start_time = "04:57:00"
    tu.trip.schedule_relationship = rt.TripDescriptor.SCHEDULED
    tu.vehicle.id = "X'Trap 1"
    tu.vehicle.label = "1M"
    tu.timestamp = FEED_TS - 5
    s1 = tu.stop_time_update.add(stop_sequence=2, stop_id="11198")
    s1.arrival.time = FEED_TS + 60
    s1.arrival.delay = 75
    s1.arrival.uncertainty = 30
    s1.departure.time = FEED_TS + 90
    s2 = tu.stop_time_update.add(stop_sequence=3, stop_id="11199")
    s2.schedule_relationship = rt.TripUpdate.StopTimeUpdate.SKIPPED
    # A cancelled trip carries no stop_time_update at all.
    c = msg.entity.add(id="tu-2").trip_update
    c.trip.trip_id = "03-109--8-T2-146645308"
    c.trip.start_date = "20261020"
    c.trip.schedule_relationship = rt.TripDescriptor.CANCELED
    return msg.SerializeToString()


@pytest.fixture
def vehicle_positions_pb() -> bytes:
    msg = rt.FeedMessage()
    _header(msg)
    vp = msg.entity.add(id="vp-1").vehicle
    vp.trip.trip_id = "03-109--8-T2-146645308"
    vp.trip.route_id = "aus:vic:vic-03-109:"
    vp.vehicle.id = "3001"
    vp.vehicle.label = "E 6001"
    vp.position.latitude = -37.81
    vp.position.longitude = 144.96
    vp.position.bearing = 90.0
    vp.position.speed = 0.4
    vp.current_stop_sequence = 12
    vp.stop_id = "19781"
    vp.current_status = rt.VehiclePosition.STOPPED_AT
    vp.timestamp = FEED_TS - 3
    vp.occupancy_status = rt.VehiclePosition.FEW_SEATS_AVAILABLE
    return msg.SerializeToString()


@pytest.fixture
def service_alerts_pb() -> bytes:
    msg = rt.FeedMessage()
    _header(msg)
    a = msg.entity.add(id="alert-1").alert
    a.active_period.add(start=FEED_TS - 3600, end=FEED_TS + 3600)
    a.active_period.add(start=FEED_TS + 86400)
    a.informed_entity.add(route_id="aus:vic:vic-03-109:", direction_id=0)
    a.informed_entity.add(stop_id="19781")
    a.cause = rt.Alert.TECHNICAL_PROBLEM
    a.effect = rt.Alert.SIGNIFICANT_DELAYS
    a.header_text.translation.add(text="Delays on route 109", language="en")
    a.description_text.translation.add(text="Due to a faulty tram.", language="en")
    a.severity_level = rt.Alert.WARNING
    return msg.SerializeToString()

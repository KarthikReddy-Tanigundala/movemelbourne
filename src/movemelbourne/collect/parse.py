"""Flatten GTFS-Realtime protobuf messages into fixed-schema rows.

Each feed type has a fixed **core schema** (below). Anything DTP adds later that is not in the
core lands in ``extra_json`` instead of breaking the pipeline (schema drift rule, CLAUDE.md §3).
Trip updates that carry no ``stop_time_update`` (typically CANCELED trips) still produce one row
with null stop fields, because cancellations drive the reliability metric.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pyarrow as pa
from google.protobuf.json_format import MessageToDict
from google.transit import gtfs_realtime_pb2 as rt

TRIP_UPDATES_SCHEMA = pa.schema(
    [
        ("mode", pa.string()),
        ("feed_ts", pa.int64()),
        ("poll_ts_utc", pa.int64()),
        ("entity_id", pa.string()),
        ("trip_id", pa.string()),
        ("route_id", pa.string()),
        ("direction_id", pa.int32()),
        ("start_date", pa.string()),
        ("start_time", pa.string()),
        ("trip_schedule_relationship", pa.string()),
        ("vehicle_id", pa.string()),
        ("trip_update_ts", pa.int64()),
        ("n_stop_time_updates", pa.int32()),
        ("stu_index", pa.int32()),
        ("stop_sequence", pa.int32()),
        ("stop_id", pa.string()),
        ("arrival_time", pa.int64()),
        ("arrival_delay", pa.int32()),
        ("departure_time", pa.int64()),
        ("departure_delay", pa.int32()),
        ("stu_schedule_relationship", pa.string()),
        ("extra_json", pa.string()),
    ]
)

VEHICLE_POSITIONS_SCHEMA = pa.schema(
    [
        ("mode", pa.string()),
        ("feed_ts", pa.int64()),
        ("poll_ts_utc", pa.int64()),
        ("entity_id", pa.string()),
        ("vehicle_id", pa.string()),
        ("vehicle_label", pa.string()),
        ("trip_id", pa.string()),
        ("route_id", pa.string()),
        ("direction_id", pa.int32()),
        ("start_date", pa.string()),
        ("start_time", pa.string()),
        ("trip_schedule_relationship", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("bearing", pa.float32()),
        ("speed", pa.float32()),
        ("current_stop_sequence", pa.int32()),
        ("stop_id", pa.string()),
        ("current_status", pa.string()),
        ("vehicle_ts", pa.int64()),
        ("occupancy_status", pa.string()),
        ("congestion_level", pa.string()),
        ("extra_json", pa.string()),
    ]
)

SERVICE_ALERTS_SCHEMA = pa.schema(
    [
        ("mode", pa.string()),
        ("feed_ts", pa.int64()),
        ("poll_ts_utc", pa.int64()),
        ("alert_id", pa.string()),
        ("active_start", pa.int64()),
        ("active_end", pa.int64()),
        ("cause", pa.string()),
        ("effect", pa.string()),
        ("header_text", pa.string()),
        ("description_text", pa.string()),
        ("url", pa.string()),
        ("agency_id", pa.string()),
        ("route_id", pa.string()),
        ("route_type", pa.int32()),
        ("stop_id", pa.string()),
        ("trip_id", pa.string()),
        ("direction_id", pa.int32()),
        ("extra_json", pa.string()),
    ]
)

SCHEMAS: dict[str, pa.Schema] = {
    "trip-updates": TRIP_UPDATES_SCHEMA,
    "vehicle-positions": VEHICLE_POSITIONS_SCHEMA,
    "service-alerts": SERVICE_ALERTS_SCHEMA,
}


def _opt(msg: Any, name: str) -> Any:
    """Value of an optional proto2 field, or None when unset."""
    try:
        return getattr(msg, name) if msg.HasField(name) else None
    except ValueError:  # field not present in this bindings version
        return None


def _enum(msg: Any, name: str, enum_type: Any) -> str | None:
    value = _opt(msg, name)
    if value is None:
        return None
    try:
        return enum_type.Name(value)
    except ValueError:
        return str(value)


def _extra(message: Any, known: Iterable[str]) -> dict[str, Any]:
    """Fields of ``message`` (camelCase JSON names) not covered by the core schema."""
    data = MessageToDict(message, preserving_proto_field_name=True)
    for key in known:
        data.pop(key, None)
    return data


def _dump(extra: dict[str, Any]) -> str | None:
    extra = {k: v for k, v in extra.items() if v not in (None, {}, [])}
    return json.dumps(extra, sort_keys=True, separators=(",", ":")) if extra else None


def _translation(ts: Any) -> str | None:
    """English translation of a TranslatedString, falling back to the first available."""
    if ts is None or not ts.translation:
        return None
    for t in ts.translation:
        if t.language in ("", "en", "EN", "en-AU", "en-au"):
            return t.text
    return ts.translation[0].text


def decode(content: bytes) -> rt.FeedMessage:
    """Parse protobuf bytes into a ``FeedMessage``."""
    message = rt.FeedMessage()
    message.ParseFromString(content)
    return message


def _trip_fields(trip: Any) -> dict[str, Any]:
    return {
        "trip_id": _opt(trip, "trip_id"),
        "route_id": _opt(trip, "route_id"),
        "direction_id": _opt(trip, "direction_id"),
        "start_date": _opt(trip, "start_date"),
        "start_time": _opt(trip, "start_time"),
        "trip_schedule_relationship": _enum(
            trip, "schedule_relationship", rt.TripDescriptor.ScheduleRelationship
        ),
    }


_TRIP_KNOWN = ("trip_id", "route_id", "direction_id", "start_date", "start_time", "schedule_relationship")


def parse_trip_updates(feed: rt.FeedMessage, mode: str, poll_ts: int) -> list[dict[str, Any]]:
    """One row per ``stop_time_update`` (or one stop-less row for a trip with none)."""
    feed_ts = _opt(feed.header, "timestamp")
    rows: list[dict[str, Any]] = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip_extra = _extra(tu.trip, _TRIP_KNOWN)
        tu_extra = _extra(tu, ("trip", "stop_time_update", "timestamp"))
        if tu.HasField("vehicle"):
            vehicle_extra = tu_extra.pop("vehicle", {})
            vehicle_extra.pop("id", None)
            if vehicle_extra:
                tu_extra["vehicle"] = vehicle_extra
        base = {
            "mode": mode,
            "feed_ts": feed_ts,
            "poll_ts_utc": poll_ts,
            "entity_id": entity.id,
            **_trip_fields(tu.trip),
            "vehicle_id": _opt(tu.vehicle, "id") if tu.HasField("vehicle") else None,
            "trip_update_ts": _opt(tu, "timestamp"),
            "n_stop_time_updates": len(tu.stop_time_update),
        }
        if not tu.stop_time_update:
            rows.append({**base, "stu_index": None, "stop_sequence": None, "stop_id": None,
                         "arrival_time": None, "arrival_delay": None, "departure_time": None,
                         "departure_delay": None, "stu_schedule_relationship": None,
                         "extra_json": _dump({"trip": trip_extra, "trip_update": tu_extra})})
            continue
        for idx, stu in enumerate(tu.stop_time_update):
            arr = stu.arrival if stu.HasField("arrival") else None
            dep = stu.departure if stu.HasField("departure") else None
            stu_extra = _extra(stu, ("stop_sequence", "stop_id", "schedule_relationship"))
            for key, event in (("arrival", arr), ("departure", dep)):
                ev = stu_extra.pop(key, {})
                ev.pop("time", None)
                ev.pop("delay", None)
                if event is not None and ev:
                    stu_extra[key] = ev
            extra = {"trip": trip_extra, "trip_update": tu_extra} if idx == 0 else {}
            if stu_extra:
                extra["stu"] = stu_extra
            rows.append(
                {
                    **base,
                    "stu_index": idx,
                    "stop_sequence": _opt(stu, "stop_sequence"),
                    "stop_id": _opt(stu, "stop_id"),
                    "arrival_time": _opt(arr, "time") if arr is not None else None,
                    "arrival_delay": _opt(arr, "delay") if arr is not None else None,
                    "departure_time": _opt(dep, "time") if dep is not None else None,
                    "departure_delay": _opt(dep, "delay") if dep is not None else None,
                    "stu_schedule_relationship": _enum(
                        stu, "schedule_relationship",
                        rt.TripUpdate.StopTimeUpdate.ScheduleRelationship,
                    ),
                    "extra_json": _dump(extra),
                }
            )
    return rows


def parse_vehicle_positions(feed: rt.FeedMessage, mode: str, poll_ts: int) -> list[dict[str, Any]]:
    """One row per vehicle entity."""
    feed_ts = _opt(feed.header, "timestamp")
    rows: list[dict[str, Any]] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vp = entity.vehicle
        pos = vp.position if vp.HasField("position") else None
        trip = _trip_fields(vp.trip) if vp.HasField("trip") else dict.fromkeys(
            ("trip_id", "route_id", "direction_id", "start_date", "start_time",
             "trip_schedule_relationship"))
        extra = _extra(vp, ("trip", "position", "current_stop_sequence", "stop_id",
                            "current_status", "timestamp", "occupancy_status",
                            "congestion_level"))
        vehicle_desc = extra.pop("vehicle", {})
        vehicle_desc.pop("id", None)
        vehicle_desc.pop("label", None)
        if vehicle_desc:
            extra["vehicle"] = vehicle_desc
        if vp.HasField("trip"):
            trip_extra = _extra(vp.trip, _TRIP_KNOWN)
            if trip_extra:
                extra["trip"] = trip_extra
        rows.append(
            {
                "mode": mode,
                "feed_ts": feed_ts,
                "poll_ts_utc": poll_ts,
                "entity_id": entity.id,
                "vehicle_id": _opt(vp.vehicle, "id") if vp.HasField("vehicle") else None,
                "vehicle_label": _opt(vp.vehicle, "label") if vp.HasField("vehicle") else None,
                **trip,
                "latitude": pos.latitude if pos is not None else None,
                "longitude": pos.longitude if pos is not None else None,
                "bearing": _opt(pos, "bearing") if pos is not None else None,
                "speed": _opt(pos, "speed") if pos is not None else None,
                "current_stop_sequence": _opt(vp, "current_stop_sequence"),
                "stop_id": _opt(vp, "stop_id"),
                "current_status": _enum(vp, "current_status", rt.VehiclePosition.VehicleStopStatus),
                "vehicle_ts": _opt(vp, "timestamp"),
                "occupancy_status": _enum(vp, "occupancy_status", rt.VehiclePosition.OccupancyStatus),
                "congestion_level": _enum(vp, "congestion_level", rt.VehiclePosition.CongestionLevel),
                "extra_json": _dump(extra),
            }
        )
    return rows


def parse_service_alerts(feed: rt.FeedMessage, mode: str, poll_ts: int) -> list[dict[str, Any]]:
    """One row per alert x informed entity x active period (nulls when a list is empty)."""
    feed_ts = _opt(feed.header, "timestamp")
    rows: list[dict[str, Any]] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        extra = _extra(alert, ("active_period", "informed_entity", "cause", "effect",
                               "header_text", "description_text", "url"))
        periods = [(_opt(p, "start"), _opt(p, "end")) for p in alert.active_period] or [(None, None)]
        informed = list(alert.informed_entity) or [None]
        common = {
            "mode": mode,
            "feed_ts": feed_ts,
            "poll_ts_utc": poll_ts,
            "alert_id": entity.id,
            "cause": _enum(alert, "cause", rt.Alert.Cause),
            "effect": _enum(alert, "effect", rt.Alert.Effect),
            "header_text": _translation(alert.header_text) if alert.HasField("header_text") else None,
            "description_text": (_translation(alert.description_text)
                                 if alert.HasField("description_text") else None),
            "url": _translation(alert.url) if alert.HasField("url") else None,
            "extra_json": _dump(extra),
        }
        for ie in informed:
            ie_fields = {
                "agency_id": _opt(ie, "agency_id") if ie is not None else None,
                "route_id": _opt(ie, "route_id") if ie is not None else None,
                "route_type": _opt(ie, "route_type") if ie is not None else None,
                "stop_id": _opt(ie, "stop_id") if ie is not None else None,
                "trip_id": (_opt(ie.trip, "trip_id")
                            if ie is not None and ie.HasField("trip") else None),
                "direction_id": _opt(ie, "direction_id") if ie is not None else None,
            }
            for start, end in periods:
                rows.append({**common, **ie_fields, "active_start": start, "active_end": end})
    return rows


PARSERS = {
    "trip-updates": parse_trip_updates,
    "vehicle-positions": parse_vehicle_positions,
    "service-alerts": parse_service_alerts,
}


def parse_feed(feed_name: str, content: bytes, mode: str, poll_ts: int) -> tuple[list[dict], int | None, int]:
    """Decode and flatten a payload. Returns (rows, header timestamp, entity count)."""
    message = decode(content)
    rows = PARSERS[feed_name](message, mode, poll_ts)
    return rows, _opt(message.header, "timestamp"), len(message.entity)


def to_table(feed_name: str, rows: list[dict[str, Any]]) -> pa.Table:
    """Rows -> Arrow table with the fixed core schema for ``feed_name``."""
    return pa.Table.from_pylist(rows, schema=SCHEMAS[feed_name])

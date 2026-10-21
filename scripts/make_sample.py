"""Build the committed offline sample in ``tests/sample/``.

**The realtime part of this sample is SYNTHETIC.** It exists so that CI, the Quickstart and the
dbt tests run on a fresh clone with no API key. It is never used for findings.

- Timetable: a REAL slice of the DTP GTFS Schedule release (Alamein + Glen Waverley trains,
  routes 109 + 96 trams), copied unchanged from the lake.
- Realtime: simulated 60-second polls of trip updates, vehicle positions and service alerts for
  two windows (Thu 22 Oct 2026 07:00-09:00 AM peak, Sat 24 Oct 11:00-12:00), plus coverage rows.

The simulation deliberately exercises every edge case the pipeline must handle: cancelled trips,
trips with no data, tram trip updates without ``start_date``, metro stop IDs reported as the
parent station without ``stop_sequence``, a 12-minute collection gap, an incident with a matching
service alert, delay-only vs time-only predictions, and stops dropping out of the feed once passed.

    uv run python scripts/make_sample.py          # needs a static snapshot in data/lake
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from movemelbourne import config
from movemelbourne.collect.parse import to_table
from movemelbourne.collect.run_collection import COVERAGE_SCHEMA, FEED_DIRS
from movemelbourne.ingest.load_schedule import expand_calendar, version_branches
from movemelbourne.utils.lake import lake_dir
from movemelbourne.utils.logging import setup_logging
from movemelbourne.utils.timeutil import MELBOURNE, service_day_reference_epoch

logger = logging.getLogger("make_sample")

SAMPLE_DIR = config.REPO_ROOT / "tests" / "sample"
ROUTES = {
    "2": ["aus:vic:vic-02-ALM:", "aus:vic:vic-02-GWY:"],
    "3": ["aus:vic:vic-03-109:", "aus:vic:vic-03-96:"],
}
MODES = {"2": "metro", "3": "tram"}
WINDOWS = [(date(2026, 10, 22), "07:00", "09:00"), (date(2026, 10, 24), "11:00", "12:00")]
GAP = (date(2026, 10, 24), "11:20", "11:32")  # simulated collector outage
INCIDENT = {
    "route_id": "aus:vic:vic-03-96:",
    "day": date(2026, 10, 22),
    "start": "07:30",
    "end": "08:15",
    "extra_s": 300,
}
POLL_S = 60
RUN_S = 1800


def local_epoch(d: date, hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=MELBOURNE).timestamp())


def stable_unit(*parts: str) -> float:
    """Deterministic pseudo-random number in [0, 1) from strings (independent of RNG order)."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16) / 0x1_0000_0000


def copy_timetable_slice(con: duckdb.DuckDBPyConnection, feed_version: str) -> None:
    """Write the real timetable rows for the sample routes, unchanged, into the sample lake."""
    src_root = lake_dir() / "raw" / "schedule" / f"feed_version={feed_version}"
    dst_root = SAMPLE_DIR / "lake" / "raw" / "schedule" / f"feed_version={feed_version}"
    for branch, routes in ROUTES.items():
        src, dst = src_root / f"mode_branch={branch}", dst_root / f"mode_branch={branch}"
        dst.mkdir(parents=True, exist_ok=True)
        p = {t.stem: t.as_posix() for t in src.glob("*.parquet")}
        route_list = ", ".join(f"'{r}'" for r in routes)
        queries = {
            "agency": f"select * from '{p['agency']}'",
            "calendar": f"select * from '{p['calendar']}'",
            "calendar_dates": f"select * from '{p['calendar_dates']}'",
            "routes": f"select * from '{p['routes']}' where route_id in ({route_list})",
            "trips": f"select * from '{p['trips']}' where route_id in ({route_list})",
            "stop_times": f"""select st.* from '{p["stop_times"]}' st
                semi join (select trip_id from '{p["trips"]}' where route_id in ({route_list})) t
                using (trip_id)""",
            "shapes": f"""select * from '{p["shapes"]}' where shape_id in
                (select shape_id from '{p["trips"]}' where route_id in ({route_list}))""",
        }
        for table, sql in queries.items():
            con.execute(
                f"copy ({sql}) to '{(dst / f'{table}.parquet').as_posix()}' "
                "(format parquet, compression zstd)"
            )
        used = f"select distinct stop_id from '{(dst / 'stop_times.parquet').as_posix()}'"
        con.execute(f"""copy (select * from '{p["stops"]}' where stop_id in ({used})
                       or stop_id in (select parent_station from '{p["stops"]}'
                                      where stop_id in ({used})))
                       to '{(dst / "stops.parquet").as_posix()}' (format parquet, compression zstd)""")
    vsrc = lake_dir() / "raw" / "schedule_versions" / f"feed_version={feed_version}.parquet"
    vdst = SAMPLE_DIR / "lake" / "raw" / "schedule_versions" / vsrc.name
    vdst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vsrc, vdst)


def scheduled_events(con: duckdb.DuckDBPyConnection, feed_version: str) -> pd.DataFrame:
    """Scheduled stop events on the sample dates, computed from the sample timetable."""
    frames = []
    root = SAMPLE_DIR / "lake" / "raw" / "schedule" / f"feed_version={feed_version}"
    for branch in ROUTES:
        folder = root / f"mode_branch={branch}"
        active = expand_calendar(
            pq.read_table(folder / "calendar.parquet").to_pylist(),
            pq.read_table(folder / "calendar_dates.parquet").to_pylist(),
        )
        for day, *_ in WINDOWS:
            services = [s for (d, s), runs in active.items() if d == day and runs]
            if not services:
                continue
            svc = ", ".join(f"'{s}'" for s in services)
            df = con.sql(f"""
                select t.trip_id, t.route_id, try_cast(t.direction_id as int) direction_id,
                       st.stop_id, cast(st.stop_sequence as int) stop_sequence,
                       cast(split_part(st.arrival_time, ':', 1) as int) * 3600
                     + cast(split_part(st.arrival_time, ':', 2) as int) * 60
                     + cast(split_part(st.arrival_time, ':', 3) as int) arr_secs,
                       s.stop_lat::double lat, s.stop_lon::double lon,
                       nullif(s.parent_station, '') parent_station
                from '{(folder / "trips.parquet").as_posix()}' t
                join '{(folder / "stop_times.parquet").as_posix()}' st using (trip_id)
                join '{(folder / "stops.parquet").as_posix()}' s using (stop_id)
                where t.service_id in ({svc})
            """).df()
            df["mode"], df["service_date"] = MODES[branch], day
            df["sched"] = service_day_reference_epoch(day) + df["arr_secs"]
            frames.append(df)
    return pd.concat(frames).sort_values(["mode", "service_date", "trip_id", "stop_sequence"])


@dataclass
class SimTrip:
    mode: str
    service_date: date
    trip_id: str
    route_id: str
    direction_id: int
    stops: pd.DataFrame  # sorted by stop_sequence, with sched/actual/delay/dwell columns
    status: str  # normal | cancelled | no_data
    omit_start_date: bool
    station_ids: bool
    vehicle_id: str


def simulate_trip(rng: np.random.Generator, g: pd.DataFrame) -> SimTrip:
    """Draw a realistic delay path for one scheduled trip."""
    first = g.iloc[0]
    mode, day, trip_id = first["mode"], first["service_date"], first["trip_id"]
    u = rng.random()
    status = "cancelled" if u < 0.015 else "no_data" if u < 0.025 else "normal"
    n = len(g)
    peak = 1.3 if day.weekday() < 5 else 1.0
    if mode == "metro":
        origin = rng.gamma(1.2, 30) - 20
        inc = rng.normal(0.5, 8, n) * peak
    else:
        origin = rng.gamma(1.5, 30) - 30
        inc = rng.normal(1.0, 12, n) * peak
        hotspot = np.array([stable_unit(s) < 0.06 for s in g["stop_id"]])
        inc += hotspot * rng.exponential(40, n)
    inc[0] = 0
    if rng.random() < 0.03:  # random incident somewhere along the trip
        inc[rng.integers(1, max(n, 2))] += rng.exponential(400)
    if g.iloc[0]["route_id"] == INCIDENT["route_id"] and day == INCIDENT["day"]:
        start = local_epoch(day, INCIDENT["start"])
        end = local_epoch(day, INCIDENT["end"])
        hit = (g["sched"].to_numpy() >= start) & (g["sched"].to_numpy() <= end)
        if hit.any():
            inc[int(np.argmax(hit))] += INCIDENT["extra_s"]
    delay = np.maximum(origin + np.cumsum(inc), -90)
    actual = g["sched"].to_numpy() + delay
    for i in range(1, n):
        actual[i] = max(actual[i], actual[i - 1] + 20)
    stops = g.reset_index(drop=True).assign(
        actual=np.round(actual).astype("int64"),
        delay=np.round(actual - g["sched"].to_numpy()).astype("int64"),
        dwell=rng.integers(15, 45, n),
    )
    return SimTrip(
        mode,
        day,
        trip_id,
        first["route_id"],
        int(first["direction_id"] or 0),
        stops,
        status,
        mode == "tram" and stable_unit(trip_id, "sd") < 0.05,
        mode == "metro" and stable_unit(trip_id, "st") < 0.10,
        f"{mode[0].upper()}{int(stable_unit(trip_id, 'v') * 400):03d}",
    )


def polls_for(day: date, start: str, end: str) -> list[int]:
    ticks = range(local_epoch(day, start), local_epoch(day, end), POLL_S)
    if day == GAP[0]:
        g0, g1 = local_epoch(day, GAP[1]), local_epoch(day, GAP[2])
        return [t for t in ticks if not g0 <= t < g1]
    return list(ticks)


def trip_update_rows(trip: SimTrip, t: int) -> list[dict]:
    s = trip.stops
    sched0, last_actual = int(s["sched"].iloc[0]), int(s["actual"].iloc[-1])
    base = {
        "mode": trip.mode,
        "feed_ts": t,
        "poll_ts_utc": t + 2,
        "entity_id": trip.trip_id,
        "trip_id": trip.trip_id,
        "route_id": trip.route_id,
        "direction_id": trip.direction_id,
        "start_date": None if trip.omit_start_date else trip.service_date.strftime("%Y%m%d"),
        "start_time": None,
        "vehicle_id": trip.vehicle_id,
        "trip_update_ts": t - 5,
        "extra_json": None,
    }
    if trip.status == "cancelled":
        if sched0 - 1800 <= t <= int(s["sched"].iloc[-1]):
            return [
                {
                    **base,
                    "trip_schedule_relationship": "CANCELED",
                    "vehicle_id": None,
                    "n_stop_time_updates": 0,
                    "stu_index": None,
                    "stop_sequence": None,
                    "stop_id": None,
                    "arrival_time": None,
                    "arrival_delay": None,
                    "departure_time": None,
                    "departure_delay": None,
                    "stu_schedule_relationship": None,
                }
            ]
        return []
    if trip.status == "no_data" or not (sched0 - 1200 <= t < last_actual):
        return []
    passed = s["actual"].to_numpy() <= t
    cur_delay = int(s["delay"].to_numpy()[passed][-1]) if passed.any() else int(s["delay"].iloc[0])
    upcoming = s[~passed]
    rows = []
    for idx, (_, stop) in enumerate(upcoming.iterrows()):
        pred = max(int(stop["sched"]) + cur_delay, t + 30)
        station = trip.station_ids and stop["parent_station"] is not None
        rows.append(
            {
                **base,
                "trip_schedule_relationship": "SCHEDULED",
                "n_stop_time_updates": len(upcoming),
                "stu_index": idx,
                "stop_sequence": None if station else int(stop["stop_sequence"]),
                "stop_id": stop["parent_station"] if station else stop["stop_id"],
                "arrival_time": pred,
                "arrival_delay": cur_delay if trip.mode == "metro" else None,
                "departure_time": pred + 30 if trip.mode == "metro" else None,
                "departure_delay": cur_delay if trip.mode == "metro" else None,
                "stu_schedule_relationship": "SCHEDULED",
            }
        )
    return rows


def vehicle_position_row(trip: SimTrip, t: int) -> dict | None:
    s = trip.stops
    if trip.status != "normal" or not (
        int(s["actual"].iloc[0]) - 60 <= t < int(s["actual"].iloc[-1])
    ):
        return None
    actual, dwell = s["actual"].to_numpy(), s["dwell"].to_numpy()
    at = np.nonzero((actual <= t) & (t < actual + dwell))[0]
    if at.size:
        i, status, frac = int(at[0]), "STOPPED_AT", 0.0
        lat, lon, speed = s["lat"].iloc[i], s["lon"].iloc[i], 0.0
    else:
        i = int(np.searchsorted(actual, t, side="right"))
        i = min(max(i, 1), len(s) - 1)
        span = max(actual[i] - (actual[i - 1] + dwell[i - 1]), 1)
        frac = float(np.clip((t - actual[i - 1] - dwell[i - 1]) / span, 0, 1))
        lat = s["lat"].iloc[i - 1] + frac * (s["lat"].iloc[i] - s["lat"].iloc[i - 1])
        lon = s["lon"].iloc[i - 1] + frac * (s["lon"].iloc[i] - s["lon"].iloc[i - 1])
        status, speed = "IN_TRANSIT_TO", 15.0 if trip.mode == "metro" else 7.5
    return {
        "mode": trip.mode,
        "feed_ts": t,
        "poll_ts_utc": t + 2,
        "entity_id": trip.vehicle_id,
        "vehicle_id": trip.vehicle_id,
        "vehicle_label": trip.vehicle_id,
        "trip_id": trip.trip_id,
        "route_id": trip.route_id,
        "direction_id": trip.direction_id,
        "start_date": trip.service_date.strftime("%Y%m%d"),
        "start_time": None,
        "trip_schedule_relationship": "SCHEDULED",
        "latitude": float(lat),
        "longitude": float(lon),
        "bearing": None,
        "speed": speed,
        "current_stop_sequence": int(s["stop_sequence"].iloc[i]),
        "stop_id": s["stop_id"].iloc[i],
        "current_status": status,
        "vehicle_ts": t - 3,
        "occupancy_status": None,
        "congestion_level": None,
        "extra_json": None,
    }


def alert_rows(mode: str, t: int) -> list[dict]:
    common = {
        "mode": mode,
        "feed_ts": t,
        "poll_ts_utc": t + 2,
        "url": None,
        "agency_id": None,
        "route_type": None,
        "stop_id": None,
        "trip_id": None,
        "extra_json": None,
    }
    if mode == "tram":
        start = local_epoch(INCIDENT["day"], INCIDENT["start"])
        end = local_epoch(INCIDENT["day"], INCIDENT["end"])
        if start - 300 <= t <= end + 600:
            return [
                {
                    **common,
                    "alert_id": "sample-tram-96-disabled",
                    "active_start": start,
                    "active_end": end,
                    "cause": "TECHNICAL_PROBLEM",
                    "effect": "SIGNIFICANT_DELAYS",
                    "header_text": "Route 96: delays up to 10 minutes (SAMPLE)",
                    "description_text": "Synthetic sample alert: a disabled tram near Bourke St.",
                    "route_id": INCIDENT["route_id"],
                    "direction_id": d,
                }
                for d in (0, 1)
            ]
        return []
    works = local_epoch(date(2026, 11, 7), "00:00")
    return [
        {
            **common,
            "alert_id": "sample-metro-alm-works",
            "active_start": works,
            "active_end": works + 86400 * 2 - 1,
            "cause": "MAINTENANCE",
            "effect": "MODIFIED_SERVICE",
            "header_text": "Alamein line: buses replace trains (SAMPLE)",
            "description_text": "Synthetic sample alert for planned works.",
            "route_id": "aus:vic:vic-02-ALM:",
            "direction_id": None,
        }
    ]


def main() -> int:
    setup_logging()
    versions = sorted({v for v, _, _ in version_branches(lake_dir())})
    if not versions:
        logger.error("no static snapshot in %s", lake_dir())
        return 1
    feed_version = versions[-1]
    if SAMPLE_DIR.exists():
        shutil.rmtree(SAMPLE_DIR)
    con = duckdb.connect()
    copy_timetable_slice(con, feed_version)
    events = scheduled_events(con, feed_version)
    rng = np.random.default_rng(42)
    trips = [
        simulate_trip(rng, g)
        for _, g in events.groupby(["mode", "service_date", "trip_id"], sort=True)
    ]
    out = SAMPLE_DIR / "lake" / "raw"
    coverage: list[dict] = []
    for day, start, end in WINDOWS:
        polls = polls_for(day, start, end)
        day_trips = [tr for tr in trips if tr.service_date == day]
        run_starts = range(local_epoch(day, start), local_epoch(day, end), RUN_S)
        for k, run_start in enumerate(run_starts):
            run_id = f"sample-{day:%Y%m%d}-{k:02d}"
            ticks = [t for t in polls if run_start <= t < run_start + RUN_S]
            expected = RUN_S // POLL_S
            for mode in ("metro", "tram"):
                mtrips = [tr for tr in day_trips if tr.mode == mode]
                feeds = {
                    "trip-updates": [
                        r for t in ticks for tr in mtrips for r in trip_update_rows(tr, t)
                    ],
                    "vehicle-positions": [
                        r
                        for t in ticks
                        for tr in mtrips
                        if (r := vehicle_position_row(tr, t)) is not None
                    ],
                    "service-alerts": [r for t in ticks for r in alert_rows(mode, t)],
                }
                for feed, rows in feeds.items():
                    if rows:
                        path = (
                            out
                            / "realtime"
                            / FEED_DIRS[feed]
                            / f"mode={mode}"
                            / f"dt={day:%Y-%m-%d}"
                            / f"run_{run_id}.parquet"
                        )
                        path.parent.mkdir(parents=True, exist_ok=True)
                        pq.write_table(to_table(feed, rows), path, compression="zstd")
                    coverage.append(
                        {
                            "run_id": run_id,
                            "collector": "synthetic-sample",
                            "mode": mode,
                            "feed": feed,
                            "run_start_utc": run_start,
                            "run_end_utc": run_start + RUN_S,
                            "polls_attempted": expected,
                            "polls_succeeded": len(ticks),
                            "polls_failed": expected - len(ticks),
                            "polls_duplicate": 0,
                            "auth_method": "synthetic",
                            "bytes_downloaded": 0,
                            "entities_total": len(
                                {
                                    (r["feed_ts"], r.get("entity_id") or r.get("alert_id"))
                                    for r in rows
                                }
                            ),
                            "rows_written": len(rows),
                            "earliest_feed_ts": min(ticks) if ticks else None,
                            "latest_feed_ts": max(ticks) if ticks else None,
                            "last_error": None if len(ticks) == expected else "simulated outage",
                        }
                    )
        cov_path = out / "coverage" / f"dt={day:%Y-%m-%d}" / f"run_sample-{day:%Y%m%d}.parquet"
        cov_path.parent.mkdir(parents=True, exist_ok=True)
        day_cov = [c for c in coverage if c["run_id"].startswith(f"sample-{day:%Y%m%d}")]
        pq.write_table(pa.Table.from_pylist(day_cov, schema=COVERAGE_SCHEMA), cov_path)
    manifest = {
        "synthetic_realtime": True,
        "timetable_feed_version": feed_version,
        "routes": ROUTES,
        "windows": [{"date": str(d), "start": s, "end": e} for d, s, e in WINDOWS],
        "simulated_gap": {"date": str(GAP[0]), "start": GAP[1], "end": GAP[2]},
        "trips": {s: sum(t.status == s for t in trips) for s in ("normal", "cancelled", "no_data")},
        "generator": "scripts/make_sample.py (numpy seed 42)",
    }
    (SAMPLE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    size = sum(p.stat().st_size for p in SAMPLE_DIR.rglob("*") if p.is_file())
    logger.info("sample written to %s (%.1f MB): %s", SAMPLE_DIR, size / 1e6, manifest["trips"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Collector loop: duplicate suppression, failure accounting and run output layout."""

from __future__ import annotations

import gzip
import time

import pyarrow.parquet as pq

from movemelbourne.collect.client import AuthError, FetchResult
from movemelbourne.collect.run_collection import Collector, FeedStats, write_run


class FakeClient:
    def __init__(
        self,
        payloads: dict[str, bytes],
        fail: set[str] | None = None,
        auth_fail: set[str] | None = None,
    ) -> None:
        self.payloads = payloads
        self.fail = fail or set()
        self.auth_fail = auth_fail or set()

    def fetch(self, mode: str, feed: str) -> FetchResult:
        if mode in self.auth_fail:
            raise AuthError(f"rejected {mode}")
        if feed in self.fail:
            raise RuntimeError("boom")
        return FetchResult(mode, feed, 200, self.payloads[feed], "ocp_header", 0.1, time.time())


def test_duplicate_feed_timestamp_is_counted_not_stored(trip_updates_pb):
    collector = Collector(
        FakeClient({"trip-updates": trip_updates_pb}),
        {"metro": ["trip-updates"]},
        poll_interval_s=60,
        max_runtime_s=1,
    )
    stats = collector.stats[("metro", "trip-updates")]
    collector.poll_once(stats)
    collector.poll_once(stats)
    assert (stats.polls_succeeded, stats.polls_duplicate) == (2, 1)
    assert len(stats.rows) == 3


def test_failures_are_recorded_and_run_continues(trip_updates_pb):
    collector = Collector(
        FakeClient({"trip-updates": trip_updates_pb}, fail={"trip-updates"}),
        {"metro": ["trip-updates"]},
        poll_interval_s=60,
        max_runtime_s=1,
    )
    stats = collector.stats[("metro", "trip-updates")]
    collector.poll_once(stats)
    assert stats.polls_failed == 1 and "boom" in stats.last_error


def test_auth_failure_marks_mode(trip_updates_pb):
    collector = Collector(
        FakeClient({}, auth_fail={"tram"}),
        {"tram": ["trip-updates"]},
        poll_interval_s=60,
        max_runtime_s=5,
    )
    collector.run()  # stops early: every mode failed auth
    assert collector.auth_failed_modes == {"tram"}


def test_write_run_layout(tmp_path, trip_updates_pb, vehicle_positions_pb):
    collector = Collector(
        FakeClient({"trip-updates": trip_updates_pb, "vehicle-positions": vehicle_positions_pb}),
        {"metro": ["trip-updates", "vehicle-positions"]},
        poll_interval_s=60,
        max_runtime_s=1,
    )
    for stats in collector.stats.values():
        collector.poll_once(stats)
    run_dir = write_run(collector, tmp_path, "local-test", 1_792_490_400, 1_792_492_000)
    tu = list(
        run_dir.glob("raw/realtime/trip_updates/mode=metro/dt=2026-10-20/run_local-test.parquet")
    )
    assert len(tu) == 1 and pq.read_table(tu[0]).num_rows == 3
    sample = next(run_dir.glob("raw/pb_samples/mode=metro/dt=*/trip_updates_local-test.pb.gz"))
    assert gzip.decompress(sample.read_bytes()) == trip_updates_pb
    cov = pq.read_table(next(run_dir.glob("raw/coverage/dt=*/run_local-test.parquet"))).to_pylist()
    assert {c["feed"] for c in cov} == {"trip-updates", "vehicle-positions"}
    assert all(c["polls_succeeded"] == 1 and c["collector"] == "local" for c in cov)


def test_feedstats_defaults():
    s = FeedStats("metro", "trip-updates")
    assert s.polls_attempted == 0 and s.rows == []

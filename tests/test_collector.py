"""Collector loop: duplicate suppression, failure accounting and run output layout."""

from __future__ import annotations

import gzip
import os
import time

import pyarrow.parquet as pq

from movemelbourne.collect import run_collection as rc
from movemelbourne.collect.client import AuthError, FetchResult
from movemelbourne.collect.run_collection import (
    Collector,
    FeedStats,
    RunWriter,
    read_state,
    recover_unfinished_runs,
    write_run,
    write_state,
)
from movemelbourne.utils.lake import publish_to_lake


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
        run_dir.glob(
            "raw/realtime/trip_updates/mode=metro/dt=2026-10-20/run_local-test_c000.parquet"
        )
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


def _collector(trip_updates_pb) -> Collector:
    return Collector(
        FakeClient({"trip-updates": trip_updates_pb}),
        {"metro": ["trip-updates"]},
        poll_interval_s=60,
        max_runtime_s=1,
    )


def test_checkpoints_flush_rows_into_numbered_chunks(tmp_path, trip_updates_pb):
    collector = _collector(trip_updates_pb)
    stats = collector.stats[("metro", "trip-updates")]
    writer = RunWriter(tmp_path, "run-a", 1_792_490_400)
    assert read_state(writer.run_dir)["status"] == "running"

    collector.poll_once(stats)
    writer.checkpoint(collector)
    assert stats.rows == [] and stats.rows_written == 3  # buffer released after a checkpoint
    stats.latest_feed_ts = None  # let the next identical payload count as a new snapshot
    collector.poll_once(stats)
    writer.checkpoint(collector, final=True)

    chunks = sorted(writer.run_dir.glob("raw/realtime/trip_updates/**/*.parquet"))
    assert [c.name for c in chunks] == ["run_run-a_c000.parquet", "run_run-a_c001.parquet"]
    cov = pq.read_table(next(writer.run_dir.glob("raw/coverage/**/*.parquet"))).to_pylist()
    assert cov[0]["rows_written"] == 6 and cov[0]["polls_succeeded"] == 2  # rewritten, cumulative
    assert read_state(writer.run_dir)["status"] == "complete"
    assert not list(writer.run_dir.rglob("*.tmp"))  # atomic writes leave no temp files


def test_run_loop_calls_checkpoint_on_schedule(trip_updates_pb):
    calls: list[float] = []
    collector = Collector(
        FakeClient({"trip-updates": trip_updates_pb}),
        {"metro": ["trip-updates"]},
        poll_interval_s=0.05,
        max_runtime_s=0.6,
    )
    collector.run(on_checkpoint=lambda: calls.append(time.monotonic()), checkpoint_every_s=0.2)
    assert 2 <= len(calls) <= 3


def _crashed_run(out_root, run_id: str, trip_updates_pb, age_s: float = 3600):
    """A run that checkpointed once and then died (state stays 'running')."""
    collector = _collector(trip_updates_pb)
    collector.poll_once(collector.stats[("metro", "trip-updates")])
    writer = RunWriter(out_root, run_id, 1_792_490_400)
    writer.checkpoint(collector)
    (writer.run_dir / "raw" / "half_written.parquet.tmp").write_bytes(b"partial")
    old = time.time() - age_s
    for f in writer.run_dir.rglob("*"):
        if f.is_file():
            os.utime(f, (old, old))
    return writer.run_dir


def test_recovery_publishes_crashed_run_and_cleans_temp_files(
    tmp_path, trip_updates_pb, monkeypatch
):
    lake = tmp_path / "lake"
    monkeypatch.setattr(rc, "publish_to_lake", lambda run_dir: publish_to_lake(run_dir, lake))
    monkeypatch.setattr(rc.config, "hf_dataset_repo", lambda: None)
    run_dir = _crashed_run(tmp_path / "runs", "crashed", trip_updates_pb)

    recovered = recover_unfinished_runs(tmp_path / "runs", "current", lake=True, upload=True)

    assert recovered == ["crashed"]
    assert not list(run_dir.rglob("*.tmp"))
    assert list(lake.glob("raw/realtime/trip_updates/**/run_crashed_c000.parquet"))
    assert read_state(run_dir)["status"] == "published"
    # Second pass: nothing left to do.
    assert recover_unfinished_runs(tmp_path / "runs", "current", lake=True, upload=True) == []


def test_recovery_skips_active_current_legacy_and_uploaded_runs(
    tmp_path, trip_updates_pb, monkeypatch
):
    monkeypatch.setattr(rc, "publish_to_lake", lambda run_dir: 0)
    monkeypatch.setattr(rc.config, "hf_dataset_repo", lambda: None)
    runs = tmp_path / "runs"
    _crashed_run(runs, "still-writing", trip_updates_pb, age_s=30)  # possibly a live collector
    _crashed_run(runs, "current", trip_updates_pb)  # this process's own run
    legacy = runs / "legacy" / "raw"  # pre-checkpointing run: no state file
    legacy.mkdir(parents=True)
    (legacy / "x.parquet").write_bytes(b"x")
    done = _crashed_run(runs, "done", trip_updates_pb)
    write_state(done, status="published")

    assert recover_unfinished_runs(runs, "current", lake=True, upload=False) == []


def test_aligned_runtime_ends_before_next_slot():
    slot = 30
    on_time = 1_792_598_400 + 5  # 5 s after a :00/:30 boundary
    assert rc.aligned_runtime_min(on_time, 29, slot) == 29  # normal run: capped at 29 min
    late = 1_792_598_400 + 22 * 60  # started 22 min late (after a reboot)
    assert abs(rc.aligned_runtime_min(late, 29, slot) - (8 * 60 - 45) / 60) < 1e-9
    nearly = 1_792_598_400 + 29 * 60  # 1 min before the boundary: run to the one after
    assert rc.aligned_runtime_min(nearly, 29, slot) == 29

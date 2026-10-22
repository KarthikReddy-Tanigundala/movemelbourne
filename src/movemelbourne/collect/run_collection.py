"""Collector entrypoint: poll every enabled feed for ~29 minutes, checkpointing as it goes.

Usage::

    uv run python -m movemelbourne.collect.run_collection --max-runtime-min 29
    uv run python -m movemelbourne.collect.run_collection --max-runtime-min 3 --no-upload

Design (ADR-002):
- One long poll loop per scheduled run (GitHub's minimum cron is 5 min and runs start late).
- Each feed is polled every ``poll_interval_s``; a poll whose ``header.timestamp`` equals the
  previous one is a cached copy and is counted, not stored.
- Crash safety: every ``checkpoint_every_min`` the buffered rows of each feed are written to a
  numbered chunk file (``run_<id>_cNNN.parquet``) and the run's coverage rows are rewritten, all
  atomically (temp file + rename), so a power cut loses at most one checkpoint interval and never
  leaves a corrupt file. The run folder mirrors the dataset layout.
- On exit (normal, timeout or Ctrl-C) the last chunk is written, the folder is copied to the local
  lake and uploaded to Hugging Face in a single commit. The process exits non-zero only AFTER
  writing and uploading whatever it has.
- Recovery: on start, any earlier run folder whose state is not ``uploaded`` (a crash, a failed
  upload) and that has not been written to recently is published and uploaded first.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from movemelbourne import config
from movemelbourne.collect.client import AuthError, FeedClient
from movemelbourne.collect.parse import parse_feed, to_table
from movemelbourne.collect.upload import upload_run_folder
from movemelbourne.utils.lake import publish_to_lake
from movemelbourne.utils.logging import redact, setup_logging
from movemelbourne.utils.power import keep_awake
from movemelbourne.utils.timeutil import epoch_to_local

logger = logging.getLogger("movemelbourne.collect")

STATE_FILE = "_state.json"  # inside the run folder, never uploaded (uploads take raw/** only)

FEED_DIRS = {
    "trip-updates": "trip_updates",
    "vehicle-positions": "vehicle_positions",
    "service-alerts": "service_alerts",
}

COVERAGE_SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("collector", pa.string()),
        ("mode", pa.string()),
        ("feed", pa.string()),
        ("run_start_utc", pa.int64()),
        ("run_end_utc", pa.int64()),
        ("polls_attempted", pa.int32()),
        ("polls_succeeded", pa.int32()),
        ("polls_failed", pa.int32()),
        ("polls_duplicate", pa.int32()),
        ("auth_method", pa.string()),
        ("bytes_downloaded", pa.int64()),
        ("entities_total", pa.int64()),
        ("rows_written", pa.int64()),
        ("earliest_feed_ts", pa.int64()),
        ("latest_feed_ts", pa.int64()),
        ("last_error", pa.string()),
    ]
)


@dataclass
class FeedStats:
    """Per-feed counters that become one coverage row."""

    mode: str
    feed: str
    polls_attempted: int = 0
    polls_succeeded: int = 0
    polls_failed: int = 0
    polls_duplicate: int = 0
    auth_method: str | None = None
    bytes_downloaded: int = 0
    entities_total: int = 0
    rows_written: int = 0
    earliest_feed_ts: int | None = None
    latest_feed_ts: int | None = None
    last_error: str | None = None
    rows: list[dict] = field(default_factory=list, repr=False)
    raw_sample: bytes | None = field(default=None, repr=False)
    sample_written: bool = field(default=False, repr=False)


def default_run_id() -> str:
    """GitHub run id + attempt in Actions; a timestamped local id otherwise."""
    if os.getenv("GITHUB_RUN_ID"):
        return f"gha-{os.environ['GITHUB_RUN_ID']}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}"
    # No hostname: run ids are published in the public dataset.
    return f"local-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"


def collector_name() -> str:
    return "github-actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local"


class Collector:
    """Polls feeds on a fixed cadence until the deadline or a stop signal."""

    def __init__(
        self,
        client: FeedClient,
        modes: dict[str, list[str]],
        *,
        poll_interval_s: float,
        max_runtime_s: float,
        keep_raw_sample: bool = True,
    ) -> None:
        self.client = client
        self.poll_interval_s = poll_interval_s
        self.max_runtime_s = max_runtime_s
        self.keep_raw_sample = keep_raw_sample
        self.stats = {(m, f): FeedStats(m, f) for m, feeds in modes.items() for f in feeds}
        self._stop = False
        self.auth_failed_modes: set[str] = set()

    def request_stop(self, *_: object) -> None:
        logger.warning("stop requested; finishing current poll and writing output")
        self._stop = True

    def poll_once(self, stats: FeedStats) -> None:
        """Fetch, parse and buffer one feed poll, updating its counters."""
        stats.polls_attempted += 1
        try:
            result = self.client.fetch(stats.mode, stats.feed)
            rows, feed_ts, n_entities = parse_feed(
                stats.feed, result.content, stats.mode, int(result.fetched_at)
            )
        except AuthError as exc:
            stats.polls_failed += 1
            stats.last_error = redact(str(exc))[:500]
            self.auth_failed_modes.add(stats.mode)
            logger.error("%s", stats.last_error)
            return
        except Exception as exc:  # noqa: BLE001 - one bad poll must never kill the run
            stats.polls_failed += 1
            stats.last_error = redact(f"{type(exc).__name__}: {exc}")[:500]
            logger.warning("poll failed %s/%s: %s", stats.mode, stats.feed, stats.last_error)
            return
        stats.polls_succeeded += 1
        stats.auth_method = result.auth_method
        stats.bytes_downloaded += result.n_bytes
        if feed_ts is not None and feed_ts == stats.latest_feed_ts:
            stats.polls_duplicate += 1
            return
        if self.keep_raw_sample and stats.raw_sample is None:
            stats.raw_sample = result.content
        stats.entities_total += n_entities
        stats.rows.extend(rows)
        if feed_ts is not None:
            stats.earliest_feed_ts = min(filter(None, (stats.earliest_feed_ts, feed_ts)))
            stats.latest_feed_ts = feed_ts
        logger.debug(
            "%s/%s ok: %d entities, %d rows, %d bytes",
            stats.mode,
            stats.feed,
            n_entities,
            len(rows),
            result.n_bytes,
        )

    def run(
        self,
        on_checkpoint: Callable[[], None] | None = None,
        checkpoint_every_s: float = 300,
    ) -> None:
        """Poll every feed every ``poll_interval_s`` until the deadline, checkpointing as it goes."""
        deadline = time.monotonic() + self.max_runtime_s
        next_due = {key: time.monotonic() for key in self.stats}
        next_checkpoint = time.monotonic() + checkpoint_every_s
        while not self._stop and time.monotonic() < deadline:
            if on_checkpoint is not None and time.monotonic() >= next_checkpoint:
                on_checkpoint()
                next_checkpoint = time.monotonic() + checkpoint_every_s
            now = time.monotonic()
            for key, due in sorted(next_due.items(), key=lambda kv: kv[1]):
                if self._stop or time.monotonic() >= deadline:
                    break
                if key[0] in self.auth_failed_modes or due > now:
                    continue
                self.poll_once(self.stats[key])
                next_due[key] = due + self.poll_interval_s
                # If we fell far behind (e.g. a slow retry), resync instead of bursting.
                if next_due[key] < time.monotonic():
                    next_due[key] = time.monotonic() + self.poll_interval_s
            if self.auth_failed_modes >= {m for m, _ in self.stats}:
                logger.error("auth failed for every mode; stopping early")
                break
            pending = [d for k, d in next_due.items() if k[0] not in self.auth_failed_modes]
            sleep_for = min(pending, default=deadline) - time.monotonic()
            if sleep_for > 0:
                time.sleep(min(sleep_for, max(deadline - time.monotonic(), 0), 5))


def _atomic_write_table(table: pa.Table, path: Path) -> None:
    """Write Parquet via a temp file + rename, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def _atomic_write_bytes(data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def read_state(run_dir: Path) -> dict:
    """The run's local state file ({} if absent)."""
    path = run_dir / STATE_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_state(run_dir: Path, **values: object) -> None:
    """Merge ``values`` into the run's state file (atomically)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    state = read_state(run_dir) | values | {"updated_utc": int(time.time())}
    _atomic_write_bytes(json.dumps(state).encode(), run_dir / STATE_FILE)


class RunWriter:
    """Writes a run's output incrementally: one chunk file per feed per checkpoint."""

    def __init__(self, out_root: Path, run_id: str, run_start: int) -> None:
        self.run_id = run_id
        self.run_start = run_start
        self.run_dir = out_root / run_id
        self.dt = epoch_to_local(run_start).strftime("%Y-%m-%d")
        self.n_checkpoints = 0
        write_state(self.run_dir, status="running", run_id=run_id, run_start_utc=run_start)

    def checkpoint(self, collector: Collector, *, final: bool = False) -> None:
        """Flush buffered rows to new chunk files and rewrite the coverage rows."""
        chunk = self.n_checkpoints
        for stats in collector.stats.values():
            if stats.rows:
                table = to_table(stats.feed, stats.rows)
                path = (
                    self.run_dir
                    / "raw"
                    / "realtime"
                    / FEED_DIRS[stats.feed]
                    / f"mode={stats.mode}"
                    / f"dt={self.dt}"
                    / f"run_{self.run_id}_c{chunk:03d}.parquet"
                )
                _atomic_write_table(table, path)
                stats.rows_written += table.num_rows
                stats.rows = []
            if stats.raw_sample is not None and not stats.sample_written:
                sample = (
                    self.run_dir
                    / "raw"
                    / "pb_samples"
                    / f"mode={stats.mode}"
                    / f"dt={self.dt}"
                    / f"{FEED_DIRS[stats.feed]}_{self.run_id}.pb.gz"
                )
                _atomic_write_bytes(gzip.compress(stats.raw_sample), sample)
                stats.sample_written = True
        self._write_coverage(collector, run_end=int(time.time()))
        self.n_checkpoints += 1
        write_state(
            self.run_dir, status="complete" if final else "running", checkpoints=self.n_checkpoints
        )
        logger.info("checkpoint %d written%s", chunk, " (final)" if final else "")

    def _write_coverage(self, collector: Collector, run_end: int) -> None:
        rows = []
        for stats in collector.stats.values():
            row = {
                k: v
                for k, v in asdict(stats).items()
                if k not in ("rows", "raw_sample", "sample_written")
            }
            rows.append(
                {
                    "run_id": self.run_id,
                    "collector": collector_name(),
                    "run_start_utc": self.run_start,
                    "run_end_utc": run_end,
                    **row,
                }
            )
        path = self.run_dir / "raw" / "coverage" / f"dt={self.dt}" / f"run_{self.run_id}.parquet"
        _atomic_write_table(pa.Table.from_pylist(rows, schema=COVERAGE_SCHEMA), path)


def write_run(
    collector: Collector, out_root: Path, run_id: str, run_start: int, run_end: int
) -> Path:
    """Write everything still buffered as one final checkpoint (one-shot convenience)."""
    writer = RunWriter(out_root, run_id, run_start)
    writer.checkpoint(collector, final=True)
    return writer.run_dir


def publish_and_upload(run_dir: Path, run_id: str, *, lake: bool, upload: bool) -> bool:
    """Copy a run to the lake and upload it; record the outcome in the run's state file."""
    if lake:
        logger.info("published %d files to the local lake", publish_to_lake(run_dir))
        write_state(run_dir, status="published")
    repo, token = config.hf_dataset_repo(), config.hf_token()
    if not upload or not repo:
        logger.info("upload skipped; run kept at %s", run_dir)
        if not lake:
            write_state(run_dir, status="kept_local")
        return True
    if not token:
        logger.error("HF_TOKEN not set; run kept locally at %s", run_dir)
        return False
    try:
        upload_run_folder(run_dir, repo, token, run_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("upload failed, run kept at %s: %s", run_dir, redact(str(exc)))
        write_state(run_dir, status="upload_failed")
        return False
    write_state(run_dir, status="uploaded")
    return True


def recover_unfinished_runs(
    out_root: Path, current_run_id: str, *, lake: bool, upload: bool, idle_s: float = 600
) -> list[str]:
    """Publish/upload earlier runs that crashed or failed to upload. Returns recovered run ids.

    A folder written to within ``idle_s`` may belong to a collector that is still running (for
    example a bridge run overlapping a scheduled one), so it is left alone for now.
    """
    if not out_root.exists():
        return []
    finished = (
        {"uploaded"}
        if upload and config.hf_dataset_repo()
        else {"uploaded", "published", "kept_local"}
    )
    recovered = []
    for run_dir in sorted(p for p in out_root.iterdir() if p.is_dir()):
        if run_dir.name == current_run_id or not (run_dir / "raw").exists():
            continue
        state = read_state(run_dir)
        # No state file = a run from before checkpointing existed (it wrote and uploaded in one
        # go); every run since writes its state file on start.
        if not state or state.get("status") in finished:
            continue
        newest = max((f.stat().st_mtime for f in run_dir.rglob("*") if f.is_file()), default=0)
        if time.time() - newest < idle_s:
            continue
        logger.warning(
            "recovering unfinished run %s (state=%s)", run_dir.name, state.get("status", "none")
        )
        for tmp in run_dir.rglob("*.tmp"):  # half-written leftovers of a crash
            tmp.unlink()
        if publish_and_upload(run_dir, run_dir.name, lake=lake, upload=upload):
            recovered.append(run_dir.name)
    return recovered


def aligned_runtime_min(
    now_epoch: float, max_runtime_min: float, slot_min: float, margin_s: float = 45
) -> float:
    """Runtime that ends ``margin_s`` before the next slot boundary, capped at ``max_runtime_min``.

    The local task fires at :00 and :30 with IgnoreNew; a run that starts late (after a reboot or
    sleep, Task Scheduler runs the missed slot immediately) would still be running at the next
    slot and that slot would be skipped. Ending at the boundary keeps runs back to back. If the
    next boundary is under 2 minutes away, the run stretches to the boundary after that.
    """
    slot_s = slot_min * 60
    until_next = slot_s - (now_epoch % slot_s) - margin_s
    if until_next < 120:
        until_next += slot_s
    return min(max_runtime_min, until_next / 60)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    feeds_cfg = config.feeds_config()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--max-runtime-min", type=float, default=feeds_cfg["max_runtime_min"])
    parser.add_argument("--poll-interval-s", type=float, default=feeds_cfg["poll_interval_s"])
    parser.add_argument("--modes", nargs="*", help="override enabled modes, e.g. --modes tram")
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--out-dir", type=Path, default=config.DATA_DIR / "runs")
    parser.add_argument("--no-upload", action="store_true", help="keep output local only")
    parser.add_argument(
        "--checkpoint-every-min",
        type=float,
        default=feeds_cfg.get("checkpoint_every_min", 5),
        help="write buffered rows to disk this often (crash safety)",
    )
    parser.add_argument(
        "--no-lake",
        action="store_true",
        help="don't copy the run into data/lake (used in GitHub Actions)",
    )
    parser.add_argument(
        "--align-to-slot-min",
        type=float,
        help="end the run just before the next multiple of this many minutes past the hour "
        "(local scheduled task: a late start would otherwise overlap and skip the next slot)",
    )
    args = parser.parse_args(argv)
    if args.align_to_slot_min:
        args.max_runtime_min = aligned_runtime_min(
            time.time(), args.max_runtime_min, args.align_to_slot_min
        )

    key = config.api_key()
    if not key:
        logger.error("TVOD_API_KEY is not set; copy .env.example to .env and add your key")
        return 2
    modes = config.enabled_modes()
    if args.modes:
        all_modes = feeds_cfg["modes"]
        modes = {m: all_modes[m]["feeds"] for m in args.modes}
    client = FeedClient(
        key,
        feeds_cfg["base_url"],
        auth_methods=feeds_cfg["auth_methods"],
        max_calls_per_min=feeds_cfg["max_calls_per_min_per_mode"],
        connect_timeout_s=feeds_cfg["connect_timeout_s"],
        read_timeout_s=feeds_cfg["read_timeout_s"],
    )
    collector = Collector(
        client,
        modes,
        poll_interval_s=args.poll_interval_s,
        max_runtime_s=args.max_runtime_min * 60,
        keep_raw_sample=feeds_cfg.get("keep_raw_pb_sample", True),
    )
    signal.signal(signal.SIGINT, collector.request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, collector.request_stop)

    recovered = recover_unfinished_runs(
        args.out_dir, args.run_id, lake=not args.no_lake, upload=not args.no_upload
    )
    if recovered:
        logger.info("recovered %d earlier run(s): %s", len(recovered), ", ".join(recovered))

    logger.info(
        "run %s starting: modes=%s runtime=%.0f min", args.run_id, modes, args.max_runtime_min
    )
    run_start = int(time.time())
    writer = RunWriter(args.out_dir, args.run_id, run_start)
    with keep_awake():  # a sleeping PC would silently stop the local bridge collector
        collector.run(
            on_checkpoint=lambda: writer.checkpoint(collector),
            checkpoint_every_s=args.checkpoint_every_min * 60,
        )
    writer.checkpoint(collector, final=True)
    run_dir = writer.run_dir

    for s in collector.stats.values():
        logger.info(
            "%-6s %-17s polls %d ok %d fail %d dup %d rows %d auth=%s",
            s.mode,
            s.feed,
            s.polls_attempted,
            s.polls_succeeded,
            s.polls_failed,
            s.polls_duplicate,
            s.rows_written,
            s.auth_method,
        )

    ok = publish_and_upload(run_dir, args.run_id, lake=not args.no_lake, upload=not args.no_upload)
    exit_code = 0 if ok else 1

    if collector.auth_failed_modes:
        exit_code = 1
    if any(s.polls_succeeded == 0 for s in collector.stats.values()):
        logger.error("at least one feed had zero successful polls")
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

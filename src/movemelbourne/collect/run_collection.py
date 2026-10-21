"""Collector entrypoint: poll every enabled feed for ~29 minutes, then write and publish.

Usage::

    uv run python -m movemelbourne.collect.run_collection --max-runtime-min 29
    uv run python -m movemelbourne.collect.run_collection --max-runtime-min 3 --no-upload

Design (ADR-002):
- One long poll loop per scheduled run (GitHub's minimum cron is 5 min and runs start late).
- Each feed is polled every ``poll_interval_s``; a poll whose ``header.timestamp`` equals the
  previous one is a cached copy and is counted, not stored.
- On exit (normal, timeout or Ctrl-C) one Parquet per feed per mode is written under a run
  folder that mirrors the dataset layout, plus one coverage row per feed, and the folder is
  uploaded to Hugging Face in a single commit. The process exits non-zero only AFTER writing and
  uploading whatever it has, so a partial run is never thrown away.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import signal
import socket
import sys
import time
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
from movemelbourne.utils.timeutil import epoch_to_local

logger = logging.getLogger("movemelbourne.collect")

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


def default_run_id() -> str:
    """GitHub run id + attempt in Actions; a timestamped local id otherwise."""
    if os.getenv("GITHUB_RUN_ID"):
        return f"gha-{os.environ['GITHUB_RUN_ID']}-{os.getenv('GITHUB_RUN_ATTEMPT', '1')}"
    return f"local-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{socket.gethostname()[:12]}"


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

    def run(self) -> None:
        """Poll every feed every ``poll_interval_s`` until the deadline."""
        deadline = time.monotonic() + self.max_runtime_s
        next_due = {key: time.monotonic() for key in self.stats}
        while not self._stop and time.monotonic() < deadline:
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


def write_run(
    collector: Collector, out_root: Path, run_id: str, run_start: int, run_end: int
) -> Path:
    """Write per-feed Parquet, raw samples and the coverage row into ``out_root/<run_id>``."""
    run_dir = out_root / run_id
    dt = epoch_to_local(run_start).strftime("%Y-%m-%d")
    coverage_rows = []
    for stats in collector.stats.values():
        if stats.rows:
            table = to_table(stats.feed, stats.rows)
            path = (
                run_dir
                / "raw"
                / "realtime"
                / FEED_DIRS[stats.feed]
                / f"mode={stats.mode}"
                / f"dt={dt}"
                / f"run_{run_id}.parquet"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(table, path, compression="zstd")
            stats.rows_written = table.num_rows
        if stats.raw_sample is not None:
            sample = (
                run_dir
                / "raw"
                / "pb_samples"
                / f"mode={stats.mode}"
                / f"dt={dt}"
                / f"{FEED_DIRS[stats.feed]}_{run_id}.pb.gz"
            )
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_bytes(gzip.compress(stats.raw_sample))
        row = {k: v for k, v in asdict(stats).items() if k not in ("rows", "raw_sample")}
        coverage_rows.append(
            {
                "run_id": run_id,
                "collector": collector_name(),
                "run_start_utc": run_start,
                "run_end_utc": run_end,
                **row,
            }
        )
    cov_path = run_dir / "raw" / "coverage" / f"dt={dt}" / f"run_{run_id}.parquet"
    cov_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(coverage_rows, schema=COVERAGE_SCHEMA), cov_path, compression="zstd"
    )
    return run_dir


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
        "--no-lake",
        action="store_true",
        help="don't copy the run into data/lake (used in GitHub Actions)",
    )
    args = parser.parse_args(argv)

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

    logger.info(
        "run %s starting: modes=%s runtime=%.0f min", args.run_id, modes, args.max_runtime_min
    )
    run_start = int(time.time())
    collector.run()
    run_end = int(time.time())
    run_dir = write_run(collector, args.out_dir, args.run_id, run_start, run_end)
    if not args.no_lake:
        logger.info("published %d files to the local lake", publish_to_lake(run_dir))

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

    exit_code = 0
    repo, token = config.hf_dataset_repo(), config.hf_token()
    if args.no_upload or not repo:
        logger.info("upload skipped; run kept at %s", run_dir)
    elif not token:
        logger.error("HF_TOKEN not set; run kept locally at %s", run_dir)
        exit_code = 1
    else:
        try:
            upload_run_folder(run_dir, repo, token, args.run_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("upload failed, run kept at %s: %s", run_dir, redact(str(exc)))
            exit_code = 1

    if collector.auth_failed_modes:
        exit_code = 1
    if any(s.polls_succeeded == 0 for s in collector.stats.values()):
        logger.error("at least one feed had zero successful polls")
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

"""Weekly versioned snapshot of the GTFS Schedule release (CLAUDE.md §6.5, ADR-005).

The static timetable is a rolling 30-day file that DTP replaces weekly, so a realtime record from
three weeks ago must be joined to the timetable that was in force then, not today's. Every
release is therefore kept as an immutable ``feed_version = <download date>_<sha256[:8]>``.

    uv run python -m movemelbourne.ingest.static_snapshot              # download, convert, upload
    uv run python -m movemelbourne.ingest.static_snapshot --zip data/downloads/gtfs.zip --no-upload

Layout written (mirrors the HF dataset)::

    data/static/<feed_version>/raw/schedule/feed_version=<v>/mode_branch=<n>/<table>.parquet
    data/static/<feed_version>/raw/schedule_versions/feed_version=<v>.parquet

Victorian quirk (verified 2026-10-16 release): the outer zip holds numbered folders, each with
its own nested ``google_transit.zip``. All columns are kept as strings so IDs are never reshaped.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import logging
import shutil
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import requests

from movemelbourne import config
from movemelbourne.collect.upload import upload_run_folder
from movemelbourne.utils.lake import publish_to_lake
from movemelbourne.utils.logging import setup_logging

logger = logging.getLogger("movemelbourne.static")

REQUIRED_TABLES = ("agency", "routes", "trips", "stops", "stop_times", "calendar")
OPTIONAL_TABLES = ("calendar_dates", "shapes", "transfers", "pathways", "levels", "feed_info")
CHUNK = 1 << 20


def download(url: str, dest: Path) -> tuple[str, int]:
    """Stream ``url`` to ``dest`` (never held in memory). Returns (sha256 hex, bytes)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=(10, 300)) as response:
        response.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in response.iter_content(CHUNK):
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    tmp.replace(dest)
    return digest.hexdigest(), size


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def open_branch(outer: zipfile.ZipFile, branch: str) -> zipfile.ZipFile:
    """Open one numbered folder's feed, handling nested ``google_transit.zip`` or loose files."""
    nested = f"{branch}/google_transit.zip"
    if nested in outer.namelist():
        return zipfile.ZipFile(io.BytesIO(outer.read(nested)))
    # Fallback: loose .txt files directly under the folder.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as inner:
        for name in outer.namelist():
            if name.startswith(f"{branch}/") and name.endswith(".txt"):
                inner.writestr(name.split("/", 1)[1], outer.read(name))
    if not buf.getbuffer().nbytes:
        raise FileNotFoundError(f"folder {branch!r} not found in outer zip")
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def read_txt_as_strings(raw: bytes) -> pa.Table:
    """Read a GTFS .txt with every column typed as string (IDs preserved exactly)."""
    raw = raw.removeprefix(b"\xef\xbb\xbf")
    header = raw.split(b"\n", 1)[0].decode("utf-8").strip().split(",")
    names = [h.strip().strip('"') for h in header]
    return pacsv.read_csv(
        io.BytesIO(raw),
        convert_options=pacsv.ConvertOptions(
            column_types={n: pa.string() for n in names},
            strings_can_be_null=False,
        ),
    )


def calendar_bounds(inner: zipfile.ZipFile) -> tuple[str | None, str | None]:
    """Earliest and latest service date covered by calendar (+ calendar_dates additions)."""
    dates: list[str] = []
    if "calendar.txt" in inner.namelist():
        cal = read_txt_as_strings(inner.read("calendar.txt"))
        dates += cal.column("start_date").to_pylist() + cal.column("end_date").to_pylist()
    if "calendar_dates.txt" in inner.namelist():
        cd = read_txt_as_strings(inner.read("calendar_dates.txt"))
        dates += [
            d
            for d, e in zip(
                cd.column("date").to_pylist(), cd.column("exception_type").to_pylist(), strict=True
            )
            if e == "1"
        ]
    dates = [d for d in dates if d]
    return (min(dates), max(dates)) if dates else (None, None)


def convert(
    zip_path: Path, out_root: Path, feed_version: str, branches: dict[str, str], meta: dict
) -> Path:
    """Extract each in-scope branch to Parquet tagged with feed_version and mode_branch."""
    version_dir = out_root / feed_version
    if version_dir.exists():
        shutil.rmtree(version_dir)
    base = version_dir / "raw" / "schedule" / f"feed_version={feed_version}"
    version_rows = []
    with zipfile.ZipFile(zip_path) as outer:
        for branch, mode in branches.items():
            inner = open_branch(outer, branch)
            names = {n.removesuffix(".txt") for n in inner.namelist() if n.endswith(".txt")}
            missing = [t for t in REQUIRED_TABLES if t not in names]
            if missing:
                raise ValueError(f"branch {branch} ({mode}) missing required files: {missing}")
            counts = {}
            for table in [t for t in REQUIRED_TABLES + OPTIONAL_TABLES if t in names]:
                tbl = read_txt_as_strings(inner.read(f"{table}.txt"))
                dest = base / f"mode_branch={branch}" / f"{table}.parquet"
                dest.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(tbl, dest, compression="zstd")
                counts[table] = tbl.num_rows
            start, end = calendar_bounds(inner)
            version_rows.append(
                {
                    **meta,
                    "feed_version": feed_version,
                    "mode_branch": branch,
                    "mode": mode,
                    "calendar_start": start,
                    "calendar_end": end,
                    "n_trips": counts.get("trips", 0),
                    "n_stop_times": counts.get("stop_times", 0),
                    "n_stops": counts.get("stops", 0),
                }
            )
            logger.info(
                "branch %s (%s): %s",
                branch,
                mode,
                ", ".join(f"{k}={v:,}" for k, v in counts.items()),
            )
    vpath = version_dir / "raw" / "schedule_versions" / f"feed_version={feed_version}.parquet"
    vpath.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(version_rows), vpath)
    return version_dir


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    study = config.study_config()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--zip", type=Path, help="use an already-downloaded gtfs.zip")
    parser.add_argument("--include-stretch", action="store_true", help="also extract bus/V/Line")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--force", action="store_true", help="convert even if already published")
    args = parser.parse_args(argv)

    url = study["static_schedule"]["url"]
    downloaded_at = datetime.now(UTC)
    if args.zip:
        zip_path = args.zip
        sha, size = sha256_file(zip_path), zip_path.stat().st_size
        downloaded_at = datetime.fromtimestamp(zip_path.stat().st_mtime, UTC)
    else:
        zip_path = config.DATA_DIR / "downloads" / "gtfs.zip"
        logger.info("downloading %s", url)
        sha, size = download(url, zip_path)
    feed_version = f"{downloaded_at:%Y%m%d}_{sha[:8]}"
    logger.info("feed_version %s (%s bytes, sha256 %s)", feed_version, f"{size:,}", sha)

    repo, token = config.hf_dataset_repo(), config.hf_token()
    upload = not args.no_upload and repo and token
    # Same bytes as a version already published -> nothing to do (weekly job is idempotent).
    if upload and not args.force:
        from huggingface_hub import HfApi

        existing = HfApi(token=token).list_repo_files(repo, repo_type="dataset")
        if any(
            f.startswith("raw/schedule_versions/") and f"_{sha[:8]}.parquet" in f for f in existing
        ):
            logger.info("release sha %s already published; skipping", sha[:8])
            return 0

    branches = dict(study["static_schedule"]["mode_branches"])
    if args.include_stretch:
        branches.update(study["static_schedule"]["stretch_mode_branches"])
    meta = {
        "sha256": sha,
        "zip_bytes": size,
        "source_url": url,
        "downloaded_at_utc": downloaded_at.isoformat(timespec="seconds"),
        "valid_from": f"{downloaded_at:%Y-%m-%d}",
    }
    version_dir = convert(zip_path, config.DATA_DIR / "static", feed_version, branches, meta)
    logger.info(
        "converted to %s; %d files published to the local lake",
        version_dir,
        publish_to_lake(version_dir),
    )
    if upload:
        upload_run_folder(version_dir, repo, token, f"static {feed_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Volume estimate from collected data, the gate for adding bus / V/Line (CLAUDE.md §6.6, ADR-001).

    uv run python scripts/volume_estimate.py                  # from the local lake
    uv run python scripts/volume_estimate.py --probe-stretch  # + one live payload per stretch feed

Measures, per mode x feed, what one collector-hour costs: bytes downloaded (from the coverage
log), rows written and Parquet bytes stored (from the lake), then projects a full 28-day study at
100% uptime. With --probe-stretch it fetches one payload of each bus / V/Line feed and scales it
by the core modes' measured bytes-to-Parquet ratio. Writes docs/volume_estimate.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from movemelbourne import config  # noqa: E402
from movemelbourne.collect.client import FeedClient  # noqa: E402
from movemelbourne.utils.lake import lake_dir  # noqa: E402

FEED_DIRS = {
    "trip-updates": "trip_updates",
    "vehicle-positions": "vehicle_positions",
    "service-alerts": "service_alerts",
}


def stored_bytes(raw: Path, feed: str, mode: str) -> int:
    folder = raw / "realtime" / FEED_DIRS[feed] / f"mode={mode}"
    return sum(p.stat().st_size for p in folder.rglob("*.parquet")) if folder.exists() else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--probe-stretch", action="store_true")
    parser.add_argument("--days", type=int, default=config.study_config()["study"]["target_days"])
    args = parser.parse_args()
    raw = lake_dir() / "raw"
    con = duckdb.connect()
    cov = con.sql(f"""
        select mode, feed,
               sum(run_end_utc - run_start_utc) / 3600.0 as collector_hours,
               sum(polls_succeeded) as polls_ok,
               sum(bytes_downloaded) as bytes_downloaded,
               sum(rows_written) as rows_written,
               sum(entities_total) as entities
        from read_parquet('{(raw / "coverage").as_posix()}/**/*.parquet', union_by_name = true)
        where collector <> 'synthetic-sample'
        group by all order by mode, feed""").df()
    cov["stored_bytes"] = [stored_bytes(raw, r.feed, r.mode) for r in cov.itertuples()]
    hours = cov["collector_hours"]
    cov["mb_down_per_h"] = cov["bytes_downloaded"] / hours / 1e6
    cov["mb_stored_per_h"] = cov["stored_bytes"] / hours / 1e6
    cov["rows_per_h"] = cov["rows_written"] / hours
    full_h = args.days * 24
    cov["proj_stored_gb"] = cov["mb_stored_per_h"] * full_h / 1e3
    cov["proj_rows_m"] = cov["rows_per_h"] * full_h / 1e6
    stored_per_down = cov["stored_bytes"].sum() / max(cov["bytes_downloaded"].sum(), 1)

    lines = [
        "# Volume estimate",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/volume_estimate.py` from "
        f"{hours.max():.1f} collector-hours of real data (local bridge collector, 22–25 Oct 2026). "
        f"Projection: {args.days} days at 100% uptime ({full_h} h).",
        "",
        "## Core modes (measured)",
        "",
        "| Mode | Feed | Collector-h | MB downloaded / h | MB stored / h | Rows / h | "
        f"Projected stored ({args.days} d) | Projected rows |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in cov.itertuples():
        lines.append(
            f"| {r.mode} | {r.feed} | {r.collector_hours:.1f} | {r.mb_down_per_h:.2f} | "
            f"{r.mb_stored_per_h:.2f} | {r.rows_per_h:,.0f} | {r.proj_stored_gb:.2f} GB | "
            f"{r.proj_rows_m:.1f} M |"
        )
    total_gb = cov["proj_stored_gb"].sum()
    total_rows = cov["proj_rows_m"].sum()
    lines += [
        "",
        f"**Core total ({args.days} days):** about **{total_gb:.1f} GB** of zstd Parquet and "
        f"**{total_rows:,.0f} M rows**; downloads about "
        f"{cov['mb_down_per_h'].sum() * full_h / 1e3:.1f} GB. Parquet keeps "
        f"{100 * stored_per_down:.0f}% of downloaded bytes (columnar + zstd + duplicate snapshots "
        "skipped).",
        "",
        "Note: the measured hours are skewed to evenings and nights (laptop availability), when "
        "fewer services run, so daytime-heavy full days will be larger. Treat these as lower "
        "bounds and re-run after a week of the GitHub Actions collector.",
        "",
    ]

    if args.probe_stretch:
        feeds_cfg = config.feeds_config()
        client = FeedClient(
            config.api_key(), feeds_cfg["base_url"], auth_methods=feeds_cfg["auth_methods"]
        )
        lines += [
            "## Stretch modes (one live payload each)",
            "",
            f"Sampled {datetime.now():%a %d %b %H:%M}. Projection = payload bytes x 60 polls/h x "
            f"{full_h} h x {stored_per_down:.2f} (core bytes-to-Parquet ratio).",
            "",
            "| Mode | Feed | Payload KB | Auth | Projected stored |",
            "|---|---|---|---|---|",
        ]
        stretch_total = 0.0
        for mode in ("bus", "vline"):
            for feed in feeds_cfg["modes"][mode]["feeds"]:
                try:
                    res = client.fetch(mode, feed)
                except Exception as exc:  # noqa: BLE001
                    lines.append(f"| {mode} | {feed} | error: {type(exc).__name__} | | |")
                    continue
                proj = res.n_bytes * 60 * full_h * stored_per_down / 1e9
                stretch_total += proj
                lines.append(
                    f"| {mode} | {feed} | {res.n_bytes / 1e3:,.0f} | "
                    f"`{res.auth_method}` | {proj:.1f} GB |"
                )
                time.sleep(1)
        lines += [
            "",
            f"**Stretch total:** about **{stretch_total:.1f} GB** on top of the core modes.",
            "",
        ]

    lines += [
        "## Limits this has to fit",
        "",
        "- **GitHub Actions:** public repo, so minutes are free. The collector uses about 30 "
        "runner-minutes per 30-minute slot (~1,440 min/day), well inside a 6-hour job limit.",
        "- **Hugging Face:** one commit per run (~48/day); public datasets have generous storage, "
        "and the core projection is small.",
        "- **Local warehouse:** DuckDB scans Parquet out of core; tens of millions of rows build "
        "in minutes on a laptop.",
        "",
        "## Decision (ADR-001)",
        "",
        "Scope stays **metro + tram** (decided 21 Oct 2026). These numbers say what extending "
        "would cost: V/Line is a negligible addition; bus is roughly ten times the core volume "
        "but still inside the ~20 GB guide. Enabling either is `enabled: true` in "
        "`config/feeds.yaml` plus a timetable snapshot with `--include-stretch`.",
        "",
    ]
    out = REPO_ROOT / "docs" / "volume_estimate.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

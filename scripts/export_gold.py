"""Export small, pre-aggregated gold files for the Streamlit app and Power BI (CLAUDE.md §10.1, §11).

    uv run python scripts/export_gold.py --sample     # from tests/sample (SYNTHETIC banner)
    uv run python scripts/export_gold.py              # from the real warehouse in data/

Writes:
- ``app/data/*.parquet`` + ``manifest.json``: aggregates only (target < 50 MB); the app never
  runs dbt or reads raw snapshots.
- ``powerbi/data/*.parquet``: star schema (facts restricted to collected events) for Import mode.

Adds the trip-clustered bootstrap CI to the route ranking (analysis/bootstrap.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
from shapely.geometry import LineString

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from movemelbourne.analysis.bootstrap import cluster_bootstrap_ci  # noqa: E402
from movemelbourne.config import study_config  # noqa: E402

logger = logging.getLogger("export_gold")
APP_DATA = REPO_ROOT / "app" / "data"
PBI_DATA = REPO_ROOT / "powerbi" / "data"

APP_QUERIES: dict[str, str] = {
    "network_daily": """
        select a.*, d.day_type, d.day_name, d.is_public_holiday, d.holiday_name,
               m.mode_label, m.target_punctuality_pct, m.target_reliability_pct
        from marts.agg_otp_daily_mode a
        join marts.dim_date d using (date_key)
        join marts.dim_mode m using (mode)
        order by service_date, mode""",
    "route_daily": """
        select a.*, r.route_display_name, r.route_short_name, r.route_color
        from marts.agg_otp_daily_route a join marts.dim_route r using (route_key)""",
    "stops": "select * from marts.agg_otp_stop",
    "segments": """
        select s.*, r.route_display_name
        from marts.agg_segment_delay s join marts.dim_route r using (route_key)""",
    "hour_dow": "select * from marts.agg_otp_hour_dow",
    "headways": """
        select h.*, r.route_display_name
        from marts.agg_headway_adherence h join marts.dim_route r using (route_key)""",
    "alerts": """
        select a.mode, a.alert_id, r.route_display_name, a.direction_id, a.stop_id,
               a.active_start_local, a.active_end_local, a.cause, a.effect, a.header_text,
               a.description_text, a.first_seen_feed_ts, a.last_seen_feed_ts, a.n_snapshots
        from marts.fact_alert a left join marts.dim_route r using (route_key)""",
    "disruption_otp": """
        select d.*, r.route_display_name
        from marts.agg_disruption_otp d join marts.dim_route r using (route_key)""",
    "coverage_daily": "select * from marts.agg_coverage_daily order by service_date, mode",
    "inference_agreement": "select * from marts.agg_inference_agreement",
    "delay_histogram": """
        select mode, greatest(least(floor(delay_seconds / 30) * 30, 1800), -300) as delay_bin_s,
               count(*) as n
        from marts.fact_stop_event where is_otp_eligible group by all order by mode, delay_bin_s""",
    "time_band_otp": """
        select f.mode, tb.time_band, tb.time_band_sort, d.day_type,
               count(*) filter (where f.is_otp_eligible) as n_observed,
               round(100.0 * count(*) filter (where f.is_on_time)
                     / nullif(count(*) filter (where f.is_otp_eligible), 0), 2) as otp_pct
        from marts.fact_stop_event f
        join marts.dim_time_band tb using (time_band_key)
        join marts.dim_date d using (date_key)
        group by all having count(*) filter (where f.is_otp_eligible) > 0""",
}

PBI_QUERIES: dict[str, str] = {
    "dim_date": """select * from marts.dim_date where date_day between
                   (select min(service_date) from marts.fact_stop_event)
               and (select max(service_date) from marts.fact_stop_event)""",
    "dim_time_band": "select * from marts.dim_time_band",
    "dim_mode": "select * from marts.dim_mode where in_core_scope",
    "dim_route": """select * from marts.dim_route
                    where route_key in (select route_key from marts.fact_trip)""",
    "dim_stop": """select * from marts.dim_stop
                   where stop_key in (select stop_key from marts.fact_stop_event)""",
    "dim_trip": """select * from marts.dim_trip
                   where trip_key in (select trip_key from marts.fact_trip)""",
    "fact_stop_event": """
        select stop_event_key, date_key, mode, route_key, stop_key, trip_key, time_band_key,
               feed_version, direction_id, stop_sequence, scheduled_arrival_local,
               observed_arrival_local, delay_seconds, delay_minutes, inference_method,
               collection_state, match_status, is_in_coverage_scope, is_observed,
               is_otp_eligible, is_on_time, delay_band
        from marts.fact_stop_event
        where collection_state <> 'outside_collection' or is_observed""",
    "fact_trip": """select * exclude (first_departure_epoch, last_arrival_epoch)
                    from marts.fact_trip where trip_outcome <> 'outside_collection'""",
    "fact_alert": "select * from marts.fact_alert",
    "agg_coverage_daily": "select * from marts.agg_coverage_daily",
    "agg_headway_adherence": "select * from marts.agg_headway_adherence",
    "agg_segment_delay": "select * from marts.agg_segment_delay",
    "agg_disruption_otp": "select * from marts.agg_disruption_otp",
}


def route_summary(con: duckdb.DuckDBPyConnection, study: dict) -> pd.DataFrame:
    """Study-level route table with the trip-clustered bootstrap CI and CI-based rank."""
    base = con.sql("""
        select a.*, r.route_display_name, r.route_short_name, r.route_long_name, r.route_color
        from marts.agg_otp_route a join marts.dim_route r using (route_key)""").df()
    per_trip = con.sql("""
        select route_key, service_date, trip_id,
               count(*) filter (where is_otp_eligible) as n_observed,
               count(*) filter (where is_on_time) as n_on_time
        from marts.fact_stop_event group by all
        having count(*) filter (where is_otp_eligible) > 0""").df()
    if per_trip.empty:
        return base
    ci = cluster_bootstrap_ci(
        per_trip,
        group_col="route_key",
        resamples=study["analysis"]["bootstrap_resamples"],
        seed=study["analysis"]["bootstrap_seed"],
    )
    out = base.merge(
        ci[["route_key", "otp_ci_low_pct", "otp_ci_high_pct", "n_trips"]],
        on="route_key",
        how="left",
    )
    ok = out["is_sample_sufficient"]
    out["rank_by_ci_low"] = (
        out[ok].groupby("mode")["otp_ci_low_pct"].rank(ascending=False, method="min")
    )
    return out


def route_shapes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Most-used shape per route x direction, simplified, as [[lon, lat], ...] JSON for PathLayer."""
    shapes = con.sql("""
        with top as (
            select t.mode, t.route_key, t.direction_id, t.feed_version, d.shape_id,
                   count(*) as n
            from marts.fact_trip as t
            join marts.dim_trip as d on d.trip_key = t.trip_key
            where t.trip_outcome = 'ran' and d.shape_id is not null
            group by t.mode, t.route_key, t.direction_id, t.feed_version, d.shape_id
            qualify row_number() over (
                partition by t.route_key, t.direction_id order by count(*) desc) = 1
        )
        select t.mode, t.route_key, t.direction_id, s.shape_id, s.shape_pt_sequence,
               s.shape_pt_lon as lon, s.shape_pt_lat as lat
        from top t join staging.stg_gtfs_shapes s
          on s.feed_version = t.feed_version and s.mode = t.mode and s.shape_id = t.shape_id
        order by t.route_key, t.direction_id, s.shape_pt_sequence""").df()
    rows = []
    for (mode, route_key, direction), g in shapes.groupby(["mode", "route_key", "direction_id"]):
        line = LineString(list(zip(g["lon"], g["lat"], strict=True))).simplify(0.00005)
        rows.append(
            {
                "mode": mode,
                "route_key": route_key,
                "direction_id": direction,
                "path_json": json.dumps([[round(x, 5), round(y, 5)] for x, y in line.coords]),
            }
        )
    return pd.DataFrame(rows)


def manifest(con: duckdb.DuckDBPyConnection, study: dict, counts: dict[str, int]) -> dict:
    window = con.sql("""
        select min(run_start_utc), max(run_end_utc),
               bool_or(collector = 'synthetic-sample') from staging.stg_rt_coverage""").fetchone()

    def fmt(epoch: int | None) -> str | None:
        if not epoch:
            return None
        return pd.Timestamp(epoch, unit="s", tz="UTC").tz_convert("Australia/Melbourne").isoformat()

    versions = con.sql(
        "select distinct feed_version from marts.dim_feed_version order by 1"
    ).fetchall()
    return {
        "built_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "is_synthetic_sample": bool(window[2]),
        "collected_from_local": fmt(window[0]),
        "collected_to_local": fmt(window[1]),
        "study_window": study["study"],
        "feed_versions": [v[0] for v in versions],
        "thresholds": {k: study["quality"][k] for k in ("min_sample_events", "min_match_rate")}
        | {"freshness_window_s": study["inference"]["freshness_window_s"]},
        "row_counts": counts,
        "attribution": (
            "Data: Department of Transport and Planning, GTFS Schedule and GTFS "
            "Realtime, CC BY 4.0. MoveMelbourne figures are independent proxy "
            "estimates, not official performance results."
        ),
    }


def write(df: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, compression="zstd")
    return len(df)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--no-powerbi", action="store_true")
    args = parser.parse_args()
    db = args.db or (
        REPO_ROOT / ("tests/sample" if args.sample else "data") / "movemelbourne.duckdb"
    )
    study = study_config()
    con = duckdb.connect(str(db), read_only=True)

    if APP_DATA.exists():
        shutil.rmtree(APP_DATA)
    counts: dict[str, int] = {}
    for name, sql in APP_QUERIES.items():
        counts[name] = write(con.sql(sql).df(), APP_DATA / f"{name}.parquet")
    counts["route_summary"] = write(route_summary(con, study), APP_DATA / "route_summary.parquet")
    counts["route_shapes"] = write(route_shapes(con), APP_DATA / "route_shapes.parquet")
    info = manifest(con, study, counts)
    (APP_DATA / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in APP_DATA.iterdir()) / 1e6
    logger.info(
        "app data: %d files, %.2f MB, synthetic=%s", len(counts), size, info["is_synthetic_sample"]
    )

    if not args.no_powerbi:
        if PBI_DATA.exists():
            shutil.rmtree(PBI_DATA)
        for name, sql in PBI_QUERIES.items():
            n = write(con.sql(sql).df(), PBI_DATA / f"{name}.parquet")
            logger.info("powerbi/data/%s.parquet: %s rows", name, f"{n:,}")
        write(route_summary(con, study), PBI_DATA / "agg_route_summary.parquet")
        (PBI_DATA / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

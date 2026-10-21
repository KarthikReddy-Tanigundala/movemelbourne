"""Build the warehouse end to end: service calendar -> bronze views -> dbt.

    uv run python scripts/run_pipeline.py --sample          # committed sample, no API key needed
    uv run python scripts/run_pipeline.py                   # real data in data/lake
    uv run python scripts/run_pipeline.py --dbt-args "build --select marts"
    uv run python scripts/run_pipeline.py --sample --docs   # also dbt docs generate

config/study.yaml is the single source of truth for thresholds; they are passed to dbt as
--vars so the SQL and Python layers cannot drift apart.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "tests" / "sample"
DBT_DIR = REPO_ROOT / "dbt"

logger = logging.getLogger("run_pipeline")


def dbt_vars(study: dict) -> dict:
    """Map config/study.yaml onto the dbt vars declared in dbt_project.yml."""
    inf, q, an = study["inference"], study["quality"], study["analysis"]
    return {
        "freshness_window_s": inf["freshness_window_s"],
        "max_poll_gap_s": inf["max_poll_gap_s"],
        "vp_proximity_m": inf["vp_proximity_m"],
        "vp_max_speed_mps": inf["vp_max_speed_mps"],
        "inference_primary": inf["primary_method"],
        "min_match_rate": q["min_match_rate"],
        "delay_min_s": q["delay_min_s"],
        "delay_max_s": q["delay_max_s"],
        "min_sample_events": q["min_sample_events"],
        "bunching_ratio": an["bunching_ratio"],
    }


def run(cmd: list[str], env: dict[str, str]) -> None:
    logger.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env, cwd=REPO_ROOT)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sample", action="store_true", help="use tests/sample instead of data/")
    parser.add_argument(
        "--dbt-args", default="build", help='dbt command, e.g. "build --select marts"'
    )
    parser.add_argument("--skip-load", action="store_true", help="skip calendar + bronze rebuild")
    parser.add_argument("--docs", action="store_true", help="run dbt docs generate afterwards")
    args = parser.parse_args()

    env = dict(os.environ)
    data_dir = (
        SAMPLE_DIR if args.sample else Path(env.get("MOVEMELBOURNE_DATA_DIR", REPO_ROOT / "data"))
    )
    env["MOVEMELBOURNE_DATA_DIR"] = str(data_dir)
    env["MOVEMELBOURNE_DUCKDB"] = str(data_dir / "movemelbourne.duckdb")
    env.setdefault("DBT_PROFILES_DIR", str(DBT_DIR))
    env.setdefault("DBT_USE_COLORS", "false")
    py = sys.executable

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from movemelbourne.config import study_config

    if not args.skip_load:
        schedule_cmd = [py, "-m", "movemelbourne.ingest.load_schedule"]
        if args.sample:
            schedule_cmd.append("--no-report")
        run(schedule_cmd, env)
        run([py, "-m", "movemelbourne.load.bronze"], env)

    dbt = str(Path(py).with_name("dbt.exe" if os.name == "nt" else "dbt"))
    common = [
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        env["DBT_PROFILES_DIR"],
        "--vars",
        json.dumps(dbt_vars(study_config())),
    ]
    run([dbt, *shlex.split(args.dbt_args), *common], env)
    if args.docs:
        run([dbt, "docs", "generate", *common], env)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        logger.error("step failed with exit code %s", exc.returncode)
        sys.exit(exc.returncode)

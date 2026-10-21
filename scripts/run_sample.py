"""Quickstart: build the warehouse on the committed sample and open the dashboard. No API key.

uv run python scripts/run_sample.py            # build + export + launch Streamlit
uv run python scripts/run_sample.py --no-app   # build + export only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-app", action="store_true")
    args = parser.parse_args()
    py = sys.executable
    subprocess.run([py, "scripts/run_pipeline.py", "--sample"], check=True, cwd=REPO_ROOT)
    subprocess.run([py, "scripts/export_gold.py", "--sample"], check=True, cwd=REPO_ROOT)
    if not args.no_app:
        subprocess.run([py, "-m", "streamlit", "run", "app/streamlit_app.py"], cwd=REPO_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

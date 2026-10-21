"""The local lake: one folder that mirrors the Hugging Face dataset layout.

Every producer writes into ``data/lake/raw/...`` using the same relative paths as the dataset:
local collector runs, static snapshots, and ``sync_from_hf`` downloads. Because file names carry
the run id or feed version, the same file arriving twice (uploaded by the local bridge collector
and later downloaded from HF) lands on the same path, so the warehouse never double counts files.
Row-level duplicates between overlapping collectors are removed later in dbt.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from movemelbourne import config


def lake_dir() -> Path:
    """Root of the local lake (``$MOVEMELBOURNE_DATA_DIR/lake``)."""
    return config.DATA_DIR / "lake"


def publish_to_lake(run_dir: Path, lake: Path | None = None) -> int:
    """Copy ``run_dir/raw/**`` into the lake, overwriting same-named files. Returns files copied."""
    lake = lake or lake_dir()
    copied = 0
    for src in (run_dir / "raw").rglob("*"):
        if src.is_file():
            dest = lake / src.relative_to(run_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied

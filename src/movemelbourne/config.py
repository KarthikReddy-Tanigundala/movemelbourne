"""Repository paths, YAML config loading and environment secrets."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = Path(os.getenv("MOVEMELBOURNE_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
WAREHOUSE_PATH = Path(os.getenv("MOVEMELBOURNE_DUCKDB", DATA_DIR / "movemelbourne.duckdb"))

load_dotenv(REPO_ROOT / ".env", override=False)


@cache
def load_yaml(name: str) -> dict[str, Any]:
    """Load ``config/<name>.yaml`` once per process."""
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def feeds_config() -> dict[str, Any]:
    """Feed endpoints, polling cadence and auth negotiation order."""
    return load_yaml("feeds")


def study_config() -> dict[str, Any]:
    """Study window, thresholds and analysis parameters."""
    return load_yaml("study")


def enabled_modes() -> dict[str, list[str]]:
    """Map of enabled mode -> feeds to collect."""
    return {
        mode: spec["feeds"]
        for mode, spec in feeds_config()["modes"].items()
        if spec.get("enabled", False)
    }


def api_key() -> str | None:
    """Transport Victoria Open Data API key from the environment (never from a file in git)."""
    return os.getenv("TVOD_API_KEY") or None


def hf_token() -> str | None:
    """Hugging Face write token."""
    return os.getenv("HF_TOKEN") or None


def hf_dataset_repo() -> str | None:
    """Target Hugging Face dataset repo, or None to keep snapshots local."""
    return os.getenv("HF_DATASET_REPO") or None

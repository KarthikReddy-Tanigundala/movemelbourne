"""Publish a collector run folder to the Hugging Face dataset in a single commit."""

from __future__ import annotations

import logging
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@retry(wait=wait_exponential(multiplier=5, max=60), stop=stop_after_attempt(4), reraise=True)
def upload_run_folder(folder: Path, repo_id: str, token: str, run_id: str) -> str:
    """Upload everything under ``folder`` (mirroring dataset paths) as ONE commit.

    Paths inside the run folder already match the dataset layout (``raw/realtime/...``,
    ``raw/coverage/...``), and file names include the run id, so re-uploading the same run
    overwrites rather than duplicates (idempotent).
    """
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    commit = api.upload_folder(
        folder_path=str(folder),
        path_in_repo="",
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"collector run {run_id}",
        allow_patterns=["raw/**"],  # never the local state file
        ignore_patterns=["**/*.tmp"],
    )
    logger.info("uploaded run %s to %s (%s)", run_id, repo_id, getattr(commit, "oid", commit))
    return str(getattr(commit, "oid", commit))

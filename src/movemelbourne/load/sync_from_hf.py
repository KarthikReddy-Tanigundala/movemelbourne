"""Download the Hugging Face dataset into the local lake (CLAUDE.md §8.1).

    uv run python -m movemelbourne.load.sync_from_hf
    uv run python -m movemelbourne.load.sync_from_hf --since 2026-11-01   # only newer partitions

Files already present with the same content are skipped by huggingface_hub, so re-running is
cheap and incremental.
"""

from __future__ import annotations

import argparse
import logging
import sys

from movemelbourne import config
from movemelbourne.utils.lake import lake_dir
from movemelbourne.utils.logging import setup_logging

logger = logging.getLogger("movemelbourne.sync")


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default=config.hf_dataset_repo())
    parser.add_argument("--since", help="only realtime/coverage partitions with dt >= YYYY-MM-DD")
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="only the coverage log (for the daily coverage check)",
    )
    args = parser.parse_args(argv)
    if not args.repo:
        logger.error("no dataset repo: set HF_DATASET_REPO or pass --repo")
        return 2

    from huggingface_hub import HfApi, snapshot_download

    allow = [] if args.coverage_only else ["raw/schedule/**", "raw/schedule_versions/**"]
    prefixes = ("raw/coverage/",) if args.coverage_only else ("raw/realtime/", "raw/coverage/")
    if args.since:
        files = HfApi(token=config.hf_token()).list_repo_files(args.repo, repo_type="dataset")
        allow += [
            f
            for f in files
            if f.startswith(prefixes) and "dt=" in f and f.split("dt=")[1][:10] >= args.since
        ]
    else:
        allow += [f"{p}**" for p in prefixes]
    path = snapshot_download(
        args.repo,
        repo_type="dataset",
        local_dir=lake_dir(),
        allow_patterns=allow,
        token=config.hf_token(),
    )
    logger.info("synced %s -> %s", args.repo, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

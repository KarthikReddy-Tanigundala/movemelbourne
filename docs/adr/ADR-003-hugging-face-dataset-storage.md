# ADR-003: Snapshots live in a public Hugging Face dataset, not the git repo

- **Status:** Accepted (2026-10-21)

## Context

28 days of 60-second snapshots of six feeds accumulate to gigabytes of Parquet. Committing them to
the code repository would bloat clones, hit GitHub size limits and make every CI checkout slow.
The data should still be public and attributable, so anyone can rebuild the warehouse.

## Decision

- Store raw snapshots in the public dataset **`Karry001/movemelbourne-gtfsr`** (CC BY 4.0,
  attributed to the Department of Transport and Planning), with the layout
  `raw/realtime/<feed>/mode=<m>/dt=<YYYY-MM-DD>/run_<run_id>.parquet`, `raw/coverage/...`,
  `raw/pb_samples/...`, `raw/schedule/feed_version=<v>/mode_branch=<n>/<table>.parquet`.
- Locally, everything lands in one **lake** folder (`data/lake/raw/...`) that mirrors that layout.
  Collector runs, static snapshots and `sync_from_hf` all write into it, so a file that arrives
  twice lands on the same path and is stored once.
- The code repo carries only a small committed sample (`tests/sample/`, ~2 MB) for CI and the
  Quickstart.

## Consequences

- `huggingface_hub.snapshot_download` gives an incremental, resumable sync; `--since` limits it to
  recent partitions.
- File-level deduplication comes from the layout; row-level deduplication (two collectors
  capturing the same snapshot) is done in dbt (`int_rt_stop_predictions_dedup`).
- The HF token in Actions is scoped to write this dataset only.
- The first raw protobuf of each feed per run is kept (gzip) under `raw/pb_samples/`, so a parser
  bug can be fixed and the flattening re-checked against original bytes.

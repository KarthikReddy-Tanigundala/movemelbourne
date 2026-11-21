# Timetable versions captured

Each weekly GTFS Schedule release is stored as an immutable `feed_version` (download date +
SHA-256 prefix) in the Hugging Face dataset (ADR-005). New rows are appended by
`static_snapshot.yml`.

| feed_version | captured (UTC) |
|---|---|
| 20261021_b1608bd3 | 2026-10-21 08:35 (local snapshot; uploaded 2026-10-25) |
| 20261025_e5879f00 | 2026-10-25 05:08 |
| 20261106_b8d4978a | 2026-11-10 06:30 (manual; DTP republished 2026-11-06, trip ids rotated) |
| 20261114_424be6c9 | 2026-11-15 10:58 |
| 20261120_e47c585e | 2026-11-21 11:07 |

"""Day-one probe of every configured GTFS-Realtime feed (CLAUDE.md §6.2).

For each mode x feed: negotiate auth, then report HTTP status, winning auth method, bytes,
header timestamp, entity count and (trip updates) field population rates. Saves one raw payload
per feed to tests/fixtures/<mode>__<feed>.pb and writes docs/probe_results.md.

    uv run python scripts/probe_feeds.py                 # enabled modes
    uv run python scripts/probe_feeds.py --modes metro tram bus vline

Exit code 1 if any core endpoint fails every auth method (the §6.2 gate: stop and report,
do not guess another URL).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from movemelbourne import config
from movemelbourne.collect.client import AuthError, FeedClient
from movemelbourne.collect.parse import decode
from movemelbourne.utils.logging import redact, setup_logging
from movemelbourne.utils.timeutil import epoch_to_local

logger = logging.getLogger("probe")
FIXTURES = config.REPO_ROOT / "tests" / "fixtures"
REPORT = config.REPO_ROOT / "docs" / "probe_results.md"
# Keep committed fixtures small: trim to this many entities.
MAX_FIXTURE_ENTITIES = 40


def trip_update_profile(message) -> dict[str, str]:
    """Share of stop_time_updates with each field populated, plus trip descriptor coverage."""
    c: Counter[str] = Counter()
    trips = 0
    for e in message.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        trips += 1
        c["trip.start_date"] += tu.trip.HasField("start_date")
        c["trip.route_id"] += tu.trip.HasField("route_id")
        c["trip.direction_id"] += tu.trip.HasField("direction_id")
        c["trip.canceled"] += tu.trip.schedule_relationship == 3
        c["vehicle.id"] += tu.HasField("vehicle") and tu.vehicle.HasField("id")
        for s in tu.stop_time_update:
            c["stu"] += 1
            c["stu.stop_id"] += s.HasField("stop_id")
            c["stu.stop_sequence"] += s.HasField("stop_sequence")
            c["stu.arrival.time"] += s.HasField("arrival") and s.arrival.HasField("time")
            c["stu.arrival.delay"] += s.HasField("arrival") and s.arrival.HasField("delay")
            c["stu.departure.time"] += s.HasField("departure") and s.departure.HasField("time")
            c["stu.departure.delay"] += s.HasField("departure") and s.departure.HasField("delay")
    n_stu = c.pop("stu", 0)
    out = {"trips": str(trips), "stop_time_updates": str(n_stu)}
    for k, v in sorted(c.items()):
        denom = trips if k.startswith(("trip.", "vehicle.")) else n_stu
        out[k] = f"{v / denom:.1%}" if denom else "n/a"
    if trips:
        sample = next(e.trip_update for e in message.entity if e.HasField("trip_update"))
        out["example trip_id"] = f"`{sample.trip.trip_id}`"
        out["example route_id"] = f"`{sample.trip.route_id}`"
        if sample.stop_time_update:
            out["example stop_id"] = f"`{sample.stop_time_update[0].stop_id}`"
    return out


def trimmed(message) -> bytes:
    """Serialise the message keeping only the first N entities (small committed fixture)."""
    del message.entity[MAX_FIXTURE_ENTITIES:]
    return message.SerializeToString()


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="*")
    args = parser.parse_args()
    cfg = config.feeds_config()
    key = config.api_key()
    if not key:
        logger.error("TVOD_API_KEY not set; add it to .env first")
        return 2
    modes = args.modes or list(config.enabled_modes())
    client = FeedClient(key, cfg["base_url"], auth_methods=cfg["auth_methods"],
                        max_calls_per_min=cfg["max_calls_per_min_per_mode"])
    FIXTURES.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    lines = [
        "# Day-one probe results",
        "",
        f"Probed {epoch_to_local(now.timestamp()):%Y-%m-%d %H:%M %Z} by `scripts/probe_feeds.py`.",
        "Fixtures saved to `tests/fixtures/` (trimmed to the first "
        f"{MAX_FIXTURE_ENTITIES} entities).",
        "",
        "| Mode | Feed | HTTP | Auth method | Bytes | Header ts (local) | Lag s | Entities |",
        "|---|---|---|---|---|---|---|---|",
    ]
    profiles: list[str] = []
    gate_failed = False
    for mode in modes:
        for feed in cfg["modes"][mode]["feeds"]:
            try:
                res = client.fetch(mode, feed)
            except AuthError as exc:
                lines.append(f"| {mode} | {feed} | 401/403 | all rejected | | | | |")
                logger.error(redact(str(exc)))
                gate_failed |= mode in config.study_config()["study"]["core_modes"]
                break
            except Exception as exc:  # noqa: BLE001
                lines.append(f"| {mode} | {feed} | error | | | | | {redact(str(exc))[:80]} |")
                continue
            msg = decode(res.content)
            ts = msg.header.timestamp if msg.header.HasField("timestamp") else None
            lag = f"{res.fetched_at - ts:.0f}" if ts else ""
            local = f"{epoch_to_local(ts):%Y-%m-%d %H:%M:%S}" if ts else "missing"
            lines.append(f"| {mode} | {feed} | {res.status} | `{res.auth_method}` | "
                         f"{res.n_bytes:,} | {local} | {lag} | {len(msg.entity):,} |")
            if feed == "trip-updates":
                prof = trip_update_profile(msg)
                profiles += [f"### {mode} trip updates", "", "| Field | Populated |", "|---|---|"]
                profiles += [f"| {k} | {v} |" for k, v in prof.items()] + [""]
            (FIXTURES / f"{mode}__{feed}.pb").write_bytes(trimmed(msg))
            logger.info("%s/%s: %s bytes, %d entities, auth %s", mode, feed, f"{res.n_bytes:,}",
                        len(msg.entity), res.auth_method)
    lines += ["", "## Trip-update field population", ""] + profiles
    lines += ["## Reading this table", "",
              "- **Auth method** is the first method in `config/feeds.yaml: auth_methods` that "
              "the gateway accepted (ADR-008).",
              "- **arrival.time vs arrival.delay** population decides the observed-arrival "
              "inference method per mode (ADR-004).",
              "- **Lag** = poll time minus `header.timestamp`; DTP caches responses ~30 s."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote %s", REPORT)
    if gate_failed:
        logger.error("GATE FAILED: a core mode rejected every auth method. Stop and report.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

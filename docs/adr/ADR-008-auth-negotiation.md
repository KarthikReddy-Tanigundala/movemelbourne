# ADR-008: Negotiate the API auth method at runtime

- **Status:** Accepted (2026-10-21)

## Context

DTP's own documentation disagrees on how the API key is sent (checked 2026-10-21):

| Source | Says |
|---|---|
| Per-mode OpenAPI specs (metro, tram, bus) | header `Ocp-Apim-Subscription-Key`, or query parameter `subscription-key` |
| GTFS-Realtime dataset page | "Header name is 'KeyID'" |
| V/Line OpenAPI spec | header `KeyId` |

An unauthenticated call returns HTTP 401. Hard-coding one method risks a collector that fails on
day one, or breaks silently when DTP tidies its gateway.

## Decision

`FeedClient` tries `ocp_header` → `keyid_header` → `query_param` (order in `config/feeds.yaml`) on
the first call per mode, caches the method that works, logs it, and re-negotiates once if a cached
method later returns 401/403. The winning method per mode is recorded in every coverage row and in
`docs/probe_results.md`.

Supporting rules:

- **Rate limiting.** A per-mode sliding-window limiter keeps us at ≤ 6 calls/min/mode, four times
  under the strictest published limit (24 per 60 s).
- **Retries.** Exponential backoff with jitter on 429/5xx and connection errors (tenacity).
- **Secret hygiene.** The key is registered with a logging filter that masks it, and any
  `subscription-key=` query value, in every message and traceback. Exception text from
  `requests` (which includes URLs) is redacted before re-raising. detect-secrets and gitleaks run
  in pre-commit and CI.

## Consequences

- If every method fails for a core mode, the probe exits non-zero and the collector stops polling
  that mode and exits non-zero after writing what it has. A new URL is never guessed.
- Unit tests cover fallback, caching, re-negotiation, retries and redaction with a fake session.

# Provenance policy (M6)

## Four sources

| Source | Meaning | May be counted as a live call? |
| --- | --- | --- |
| `LIVE` | A real `tools/call` executed against the provider during that run | Yes |
| `REPLAY_FROM_LIVE` | Offline replay / fault injection over a frozen real response | **No** |
| `SYNTHETIC` | Synthetic or mock data, illustrative only | **No** |
| `UNKNOWN` | Classification evidence insufficient | **No** |

Classification uses directory, declared label and derivation link
(`origin_response_sha256`). A `LIVE` label outside a live-run directory is
classified `UNKNOWN`, never accepted by default.

## Non-destructive correction

The M5 pilot had **35 replay traces + 48 step files** carrying `source=LIVE`.
M6 produced a derived index with:

* `declared_source`, `corrected_source`, `correction_reason`;
* `file_sha256` (bytes) and `data_sha256` (canonical JSON);
* `execution_time`, `upstream_task`, `derived_from`;
* before/after aggregate digests proving **0 sealed files modified**.

Measured: 690 declared `LIVE` → 606 corrected `LIVE`; 83 replay files plus one
sanitised public excerpt relabelled to `REPLAY_FROM_LIVE`. Any statistic built
from the corrected index reports `live_call_count_claimable = 606` and sets
`replay_must_not_be_counted_as_live = true`.

## Capture boundary for future calls

`capture.py` records:

* request/response JSON-RPC bytes as observed by the MCP client;
* `request_id` + `correlation_id` + independent SHA-256 digests;
* a redacted copy with its own digest;
* the executor's `consumed` record and the `ExecutionRecord` digest;
* immutable filenames; a pre-existing target is refused, never overwritten;
* structured `CaptureFailure` on write failure.

It is explicitly labelled `MCP_CLIENT_OBSERVABLE` and carries a boundary note
stating it is **not** the provider's raw HTTP response. New captures never
retroactively become historical raw records.

## Snapshot integrity

A preflight snapshot is immutable and bound to one run identity, one log
version and one harness fingerprint. A complete before/after comparison is
refused when the preflight snapshot is missing or when the run manifest,
execution log and result summary are incomplete.

## Cost ledger

Four fields only: `credits_reserved`, `credits_observed`,
`credits_estimated`, `credits_unknown`. The gate must run **before** a call and
issues a single-use permit; a call recorded without a permit is refused.
`credits_observed` is `null` unless the provider reports it. 514 reserved is
never reported as consumption.

# Failure taxonomy (Sprint 0 design)

This file defines how the offline harness classifies failures. It is a **design taxonomy**, not a
log of real Geoapify incidents. The only observed failure source available in Sprint 0 is deliberate
fault injection against synthetic fixtures.

## Principles

1. A failure is evidence, not something to hide. Every failed task gets a trace record with a
   status, an error code, a human-readable reason, and the calls that completed before the stop.
2. Do not retry blindly. Retrying a malformed fixture or a failed oracle hides the local defect.
3. Never turn a mock error into a statement about a live provider. Use the `source` and `error`
   fields to keep the boundary visible.
4. Keep the first failure. Do not overwrite a failed trace with a later successful one.

## Mock and harness classes

| Code | Kind | Typical trigger | Retry in Sprint 0? |
| --- | --- | --- | --- |
| `INJECTED_TOOL_ERROR` | tool | `--inject-failure tool_error` | No; intentional fault path |
| `MAX_TOOL_CALLS_EXCEEDED` | budget | A chain would exceed `--max-tool-calls` | No; change the scenario or limit deliberately |
| `BUDGET_UNITS_EXCEEDED` | budget | A call would exceed `--max-budget-units` | No; investigate the configured budget |
| `FIXTURE_ERROR` | fixture | Missing/mismatched step response, bad fixture shape | No; repair the fixture |
| `ARGUMENT_REFERENCE_ERROR` | argument | A `$steps...` reference cannot resolve | No; repair the tool chain or prior output |
| `MOCK_ARGUMENT_CONTRACT_MISMATCH` | argument (recorded as `tool` by the runner, see note) | Mock call arguments differ from the contract derived from the task's reference chain (wrong value, missing/extra key, type error, wrong cross-step reference) | No; fix argument passing or the reference chain |
| `MOCK_ARGUMENT_COORDINATE_RANGE` | argument (recorded as `tool`) | `lat`/`lon` argument is out of range or non-finite | No; fix the coordinate |
| `ORACLE_MISMATCH` | evaluation | One or more criteria do not match recorded steps | No; inspect actual and expected values |
| `EVALUATION_ERROR` | evaluation | A trace has no usable `steps` object | No; repair the trace producer |
| `INTERNAL_ERROR` | harness | Unexpected exception not classified above | No; fix the harness and add a regression test |

The runner catches unexpected exceptions at the task boundary so one task does not destroy the
whole evidence file. The catch is a diagnostic boundary, not permission to ignore defects.

> **Note on `kind`:** the two `MOCK_ARGUMENT_*` codes are raised as
> `ArgumentContractError(ToolExecutionError)`, and `runner.py` currently hardcodes
> `kind="tool"` for that branch. The specific code is always preserved, so use `error.code`
> rather than `error.kind` to classify these. Fixing the label is a small future change that
> would require its own test (work order risk R5).

## G0.1 evidence-integrity findings (`evaluate` only, not runner failures)

These codes are **not** task failures. They are findings from the independent integrity and
argument-contract passes in `evaluate` (implemented in `geoagent_reliability_lab/trace_integrity.py`
and `geoagent_reliability_lab/argument_contract.py`). Two levels exist:

- **reject** — the record is internally contradictory or its provenance is not admissible; it must
  not be counted as a passed evidence record (CLI exit 1).
- **warn** — suspicious but not contradictory (for example validator version drift, the known P2
  gap where argument errors carry no `step_id`, or repeated task IDs in one file).

Main families (full list with rules: `geoagent_reliability_lab/trace_integrity.py` and
`geoagent_reliability_lab/argument_contract.py`):

| Family | Examples | Meaning |
| --- | --- | --- |
| Identity/provenance | `TRACE_MODE_UNKNOWN`, `TRACE_SOURCE_INCONSISTENT`, `TRACE_FIXTURE_PROVENANCE_INCONSISTENT` | A mock trace must declare `synthetic_mock`, `network=false`, `credential_used=false`; a record claiming to be live is not admissible |
| Status coherence | `TRACE_STATUS_TAMPERED`, `TRACE_PASS_WITH_ERROR`, `TRACE_FAIL_WITHOUT_ERROR` | `status`/`passed`/`error`/`error_reason` must agree |
| Calls ↔ steps | `TRACE_STEPS_WITHOUT_CALLS`, `TRACE_MISSING_STEP_FOR_CALL`, `TRACE_OK_CALL_INCONSISTENT` | Each successful call must have exactly one matching step and vice versa |
| Budget arithmetic | `TRACE_BUDGET_CALL_COUNT_MISMATCH`, `TRACE_BUDGET_SPEND_MISMATCH`, `TRACE_BUDGET_LIMIT_VIOLATED` | Counters must be recomputable from the recorded calls |
| Failure paths | `TRACE_ERROR_STEP_MISMATCH`, `TRACE_EVALUATION_WITH_FAILED_CALL` | A failure must point at the call that actually failed |
| Arguments | `TRACE_ARGUMENTS_CONTRACT_MISMATCH`, `TRACE_ARGUMENT_COORDINATE_RANGE`, `TRACE_ARGUMENT_PROVENANCE_MISMATCH` | Recorded arguments must match the derived contract and the steps they were resolved from |
| File accounting | `TRACE_ID_DUPLICATE`, `TRACE_TASK_ID_REPEATED`, `TRACE_TIMESTAMP_NONMONOTONIC` | Whole-file evidence accounting |

**Boundary:** these checks prove internal consistency, not reality. A fully self-consistent forgery
is still possible (there are no signatures or external attestation). Do not present
`integrity_ok=true` as proof that a live provider behaved correctly.

## Future live-adapter classes (not implemented)

These are **Pending** placeholders for a future transport. They must not be used in Sprint 0 traces
unless a real, explicitly labelled live run produced them.

| Planned code | Meaning | Likely first action |
| --- | --- | --- |
| `AUTH_MISSING` | Required environment variable is absent | Stop; do not fabricate a key |
| `AUTH_REJECTED` | Provider rejects credentials | Stop; never print the key |
| `RATE_LIMITED` | Provider asks the client to slow down | Respect documented limits/backoff |
| `TIMEOUT` | No response within the recorded limit | Inspect budget and transport |
| `TRANSPORT_ERROR` | Connection/DNS failure | Distinguish local network from provider status |
| `HTTP_ERROR` | Non-success response | Preserve status and a redacted body |
| `MALFORMED_RESPONSE` | Response violates the adapter contract | Preserve raw shape (redacted) and fail the task |

Do not invent these codes in mock traces. The mock adapter has no HTTP client, so it cannot produce
a real timeout, rate limit, or authentication failure.

## Severity guidance

| Severity | Meaning | Example |
| --- | --- | --- |
| P0 | Prevents trustworthy execution or leaks a secret | Credential written to a trace; path traversal; fabricated "live" result |
| P1 | Invalidates a claimed result or blocks the main workflow | Registry count drift; missing fixture; oracle mismatch |
| P2 | Localized quality or usability defect | Confusing error text; missing optional report field |

A passing mock suite is not a P0/P1 closure for live integration. The live boundary remains
unverified until real tests exist.

## What to capture in a failure report

- task ID and step ID;
- trace ID and timestamp;
- error code, kind, and reason;
- budget limits and calls used;
- the last successful response (if any);
- expected versus actual for each failed criterion;
- whether the run was `synthetic_mock` or live;
- one concrete next action and a regression test to add.

## Redaction rules for future live work

Never put any of the following in a trace, report, issue, screenshot, or commit:

- API keys or environment values;
- request signatures or authorization headers;
- a provider's full response if it contains account data;
- local absolute paths that reveal unrelated projects.

Use placeholders such as `[REDACTED]` and preserve only the fields needed to reproduce the failure.

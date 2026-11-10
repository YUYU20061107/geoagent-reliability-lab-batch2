# Tutorial: first offline run of GeoAgent Reliability Lab

This walkthrough is for a first-time contributor. It uses only the Python standard library, makes
no network request, and never reads an API key.

> **Read this first:** the runner is a mock. A passing task means the synthetic fixture and the
> declared checks agree. It is not evidence that Geoapify, a live map service, or a real-world
> location behaves the same way.

## 0. Prerequisites

- Python 3.11 or newer
- A checkout of this repository
- No API key, account, network connection, or paid service

To check your interpreter:

```bash
python --version
```

## 1. Confirm the registry and fixtures

From the repository root:

```bash
python -m geoagent_reliability_lab validate
```

Look for these facts in the output:

- exactly **18 tasks**;
- category counts `G=3, P=3, R=4, S=4, M=4`;
- fixture coverage over all task steps;
- `mode: synthetic_mock`;
- no API key or network use.

If this command fails, read the registry/fixture error before changing code. A failed validation is
not a Geoapify failure; it is a local schema or coverage problem.

List the tasks:

```bash
python -m geoagent_reliability_lab list
python -m geoagent_reliability_lab list --category R
```

The important IDs for the requested capabilities are:

- reverse geocoding: `G-002`, `G-003`;
- route distance matrix: `R-002`, `R-004`;
- spatial relation: `S-001`–`S-004`;
- geometric measurement: `M-001`–`M-004`.

## 2. Inspect one task and its fixture

Open `tasks/tasks.json` and find `G-001`. Notice the separation:

- `input_spec.sample` is the task input;
- `reference_tool_chain` is the abstract call plan;
- `success_criteria` is the machine oracle;
- `source.kind` is `synthetic`;
- `assumptions` and `dynamic_data_handling` state what the fixture does not prove.

Then open `fixtures/mock_responses.json` and find `responses["G-001"]["geocode"]`. Every result is
marked `"synthetic": true`. The fixture store is a local script, not a recording of a live API.

## 3. Run a successful mock task

```powershell
python -m geoagent_reliability_lab mock run --task G-001 --trace-out artifacts/traces/tutorial-g001.jsonl
```

The command writes one JSON line and prints a task/pass/fail summary. The exact exit code is the
evidence to record; do not copy a summary from this document as if you had run it.

Inspect the trace:

```bash
python -c "import json,pathlib; print(json.dumps(json.loads(pathlib.Path('artifacts/traces/tutorial-g001.jsonl').read_text().splitlines()[0]), indent=2))"
```

Check that the trace contains:

- `task_id`, `timestamp`, `mode`, `validator_version`;
- `params`;
- `tool_calls` with arguments and a response;
- `checks` with actual values;
- `status: "pass"` and `passed: true`.

Try the two-call reverse-geocode chain:

```powershell
python -m geoagent_reliability_lab mock run --task G-003 --trace-out artifacts/traces/tutorial-g003.jsonl
```

## 4. Reproduce a failure on purpose

Failure paths are part of the test harness. Inject a synthetic tool error:

```powershell
python -m geoagent_reliability_lab mock run --task G-003 --inject-failure tool_error --inject-failure-task G-003 --trace-out artifacts/traces/tutorial-tool-error.jsonl
```

The command should exit nonzero. In the trace, confirm `status: "fail"`, an error code such as
`INJECTED_TOOL_ERROR`, a reason, and the failed call. This is an injected mock error, not a claim
that a real service is broken.

Stop the same chain before its second call:

```powershell
python -m geoagent_reliability_lab mock run --task G-003 --max-tool-calls 1 --trace-out artifacts/traces/tutorial-budget.jsonl
```

Confirm that only the first call appears and that the error code is
`MAX_TOOL_CALLS_EXCEEDED`. The budget hook is local and testable; it is not a statement about
Geoapify quota or pricing.

## 5. Evaluate independently

The original run already evaluated the task. To prove that evaluation can be separated from
execution, re-evaluate the saved trace:

```powershell
python -m geoagent_reliability_lab evaluate --trace artifacts/traces/tutorial-g003.jsonl
```

This command reads `steps` from the trace and applies the registry criteria again. It deliberately
ignores the saved `passed` field. If you edit a saved step response to a wrong value, the
re-evaluation should fail even if the file still claims the earlier run passed.

## 6. Run the unit tests

```bash
python -m unittest discover -s tests -v
```

Record the actual number of tests, failures, and errors from your terminal. Do not report a count
from this tutorial as your own result.

## 7. Add another synthetic task safely

1. Add one task object to `tasks/tasks.json` with a unique ID and a complete schema.
2. Keep the category totals at G 3, P 3, R 4, S 4, M 4 if you are changing the official registry;
   adding a nineteenth task is intentionally rejected by the current validator.
3. Add a fixture response for every step under the same task ID.
4. Mark all values `synthetic` and state why the reference is valid only in the fixture world.
5. Run `validate`, then your task, then the full suite.
6. Add a unit test for a new behavior, not only a new data row.

A task is not ready if its expected answer depends on unstated live data, an unverified API schema,
or a coordinate you invented but did not label as synthetic.

## 8. What not to claim

Do not write any of the following based on this tutorial:

- "Geoapify returned this route."
- "Our benchmark result is 100%."
- "The geocoder is accurate."
- "The API is integrated."
- "The submission passed final acceptance."

Those claims require a separate, explicitly labelled live adapter, real reference answers, recorded
runs, and independent verification. Sprint 0 proves only that the offline harness can validate its
own synthetic contracts and preserve failure evidence.

For future integration, the official reference points are the
[Geoapify website](https://www.geoapify.com/) and the
[Geoapify API documentation](https://apidocs.geoapify.com/). They are linked for orientation only;
Sprint 0 did not fetch or verify them.

## 9. Next step

A separate, deliberately minimal two-step demo now exists at
[`examples/geoapify_mcp_two_step.py`](../examples/geoapify_mcp_two_step.py), with its own tests and
an [English walkthrough](REAL_MCP_WALKTHROUGH.md). It does **not** replace the mock adapter, does not
hard-code credentials, and does not turn synthetic traces into "real" evidence. Its default path is
fully offline and SYNTHETIC; an opt-in `--live` mode requires explicit approval and was not run as
part of this release. Keep the mock suite green, keep every failure trace, and keep the distinction
between a tool-level success, a consumed response field, a semantic verdict, and independent
geographic truth.

The published summary of a separate historical real MCP pilot is at
[`LIVE_FB10_RESULTS.md`](LIVE_FB10_RESULTS.md). It is a different evidence stream and does not change
anything in this tutorial. Scientific and reproducibility boundaries are listed in
[Known limitations](../KNOWN_LIMITATIONS.md).

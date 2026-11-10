# Reproduction

This repository provides a **self-contained offline reproduction path**. Historical private sealed M5-S0 results and the external frozen M3.2 layer are not required to run it.

## Environment

Python 3.12 (tested), standard library only; no API account, network access, private directories, virtual environment or installed package is required.

All commands below run from the repository root.

## 1. Reproduce the benchmark and core

~~~bash
python -m unittest discover -s tests -v
python -m geoagent_reliability_lab validate
python -m geoagent_reliability_lab list
python tools/run_regression.py
~~~

The registry contains 18 synthetic tasks (G=3, P=3, R=4, S=4, M=4) and 25 step fixtures. The current clean candidate passed **137/137 discovered unit tests** on CPython 3.12 during assembly. The M6 regression suite separately exercises 39 offline cases.

## 2. Run and independently evaluate synthetic examples

~~~bash
python -m geoagent_reliability_lab mock run --task G-003 --trace-out artifacts/traces/geocode-chain.jsonl
python -m geoagent_reliability_lab evaluate --trace artifacts/traces/geocode-chain.jsonl
~~~

The independent evaluator keeps criterion checks, trace integrity and argument contracts distinct. It rejects malformed or inconsistent traces instead of treating recorded PASS values as authoritative.

## 3. Reproduce the portable two-step MCP demonstration offline

~~~bash
python examples/geoapify_mcp_two_step.py
python -m unittest tests.test_public_mcp_demo -v
~~~

The default response source is SYNTHETIC, real network tools/call count is 0, and no key is read. The field-lineage test verifies that the returned coordinates are the values passed to the downstream simulated request. It does **not** claim live provider validation.

## 4. Optional live demonstration

An optional real MCP request requires both a GEOAPIFY_API_KEY environment variable and the --live --authorize-two-calls flags. See [the walkthrough](docs/REAL_MCP_WALKTHROUGH.md) for conditions, expected costs and stop semantics.

Never re-execute an interrupted live request blindly: an attempted request may have reached the provider even without a recorded reply. Do not publish raw responses without data review.

## 5. Historical results and boundaries

The [live pilot summary](docs/LIVE_FB10_RESULTS.md) records ten real calls on November 9 and a separate two-call R1 on November 10. These were performed in a **different internal workspace**, not by the default public offline commands. Only reviewed summaries are included; exact byte-for-byte reproduction of old provider responses is not possible from this public tree.

Historic M5-S0 sealed engineering experiments depended on a separate frozen M3.2 layer. That older cleanroom route is **not bundled** or claimed to run here. The standalone M6 implementation and tests supplied here reproduce the public algorithms and synthetic error cases without those private files.

## 6. Validating the public release

~~~bash
python tools/verify_release.py
python -m unittest discover -s tests -v
~~~

The verification tool checks the declared release manifest. To preserve reproducibility, do not change files after the manifest has been generated.

## What a passing run means

Passing synthetic and regression tests demonstrates code-level contracts and reproduction of supplied fixtures. It is **not proof of live Geoapify geographic accuracy**, independent truth, or completion of internal REAL18 scoring.

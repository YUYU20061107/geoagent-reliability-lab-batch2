# Walkthrough | A geographic Agent that actually passes values between tools

## Step 1. Verify the offline environment

From the **repository root** (a plain clone is enough), run:

~~~bash
python -m unittest tests.test_public_mcp_demo -v
python examples/geoapify_mcp_two_step.py --out my_synthetic_result.json
~~~

Both commands are self-contained: Python 3.11+ standard library only, files in this repository only. No external workspace, no frozen M3.2 layer and no environment variable is required.

The default execution uses only in-process SYNTHETIC responses. It never reads an API key and never opens a socket. The tests cover no-key startup, explicit live approval, missing fields, coordinate bounds, tool allowlist, the two-call cap, and the distinction between a synthetic result and a real response. To run the repository's full offline unit suite instead, use `python -m unittest discover -s tests -v`.

## Step 2. Understand the two tools

Call A: geocode_address, query "Unter den Linden 1, Berlin".

The program finds the first response item in structuredContent.results, extracts numeric lat and lon, checks that both are finite and within legal geographic ranges, and records a SHA-256 fingerprint of the response bytes.

Call B: reverse_geocode_coordinates, with lat and lon copied from the **actual** Call A response. There is no hardcoded coordinate fallback in the live path and no unresolved reference string is sent. The resulting report records a source digest and the resolved arguments.

The technical dispatch-lineage verdict means only that source values were used as intended. It does not establish independent geographic accuracy.

## Step 3. Optional real run

Obtain a free-plan key from [Geoapify](https://www.geoapify.com/), configure GEOAPIFY_API_KEY as an environment variable, and explicitly approve up to two calls:

~~~bash
python examples/geoapify_mcp_two_step.py --live --authorize-two-calls --out my_private_live_result.json
~~~

Real mode sends a session initialization, lists the actual available tools, then makes up to two MCP tools/call requests with standard TLS validation. It does not retry, redirect, or silently increase its reservation ceiling.

This mode was **not** executed for the 2026-11-10 staging release. Do not run it as part of
acceptance or reproduction: no new provider call is authorised here. Every published real result
comes from the historical pilot documented in [LIVE_FB10_RESULTS.md](LIVE_FB10_RESULTS.md).

The reported credits_reserved is a pre-spend bound, **not actual consumption**. credits_observed remains null without direct provider metering. An interrupted in-flight request may have used quota. Inspect it manually rather than resending automatically.

## Step 4. Interpret outcomes

- LIVE: submitted to the real MCP endpoint.
- SYNTHETIC: local deterministic example only.
- PASS for dispatch lineage: upstream returned field was used in the downstream request.
- UNKNOWN for independent geographic Oracle: no accepted external true answer is supplied.
- STOPPED: a gate, schema, transport or response invariant failed.

Read [the real integration results](LIVE_FB10_RESULTS.md) for both milestones: the first ten-call batch found a geometry consumption-proof defect in our Agent, whereas the subsequent independent R1-PILOT-01 two-call live run successfully passed real geocode-derived coordinates to reverse geocoding. Independent geographic truth remained UNKNOWN.

The larger repository's benchmark and evaluation tools demonstrate more extensive negative controls than this deliberately minimal public example.

## Scope inside this repository

This walkthrough is the portable, self-contained reviewer path. The clean public repository includes Sprint 0, the independently runnable M6 core and this MCP example. Historical private M5-S0 sealed evidence is intentionally excluded (see [Reproduction notes](../REPRODUCTION.md)).

The [feedback overview](../GEOAPIFY_FEEDBACK.md) and [detailed MCP findings](GEOAPIFY_MCP_FEEDBACK.md) distinguish direct pilot observations, suggestions and Agent-side defects. Research limits are listed in [Known limitations](../KNOWN_LIMITATIONS.md).

[Geoapify API reference](https://apidocs.geoapify.com/)

# Tutorial | Reliable geospatial Agent workflows

The central question is not "Did the API respond?" but "Did the next Agent step actually use the returned data, and can an independent reader verify that?"

## The three checks

1. **Argument contract:** Were the correct tool and parameter shape used?
2. **Consumption and lineage:** Did the next step use the exact fields produced by the previous step?
3. **Geographic truth:** Is the inferred place, route or relation independently correct?

These questions require separate evidence. The first two may pass even when the third remains UNKNOWN.

## Exercise A: Inspect a synthetic multi-step task

~~~bash
python -m geoagent_reliability_lab list
python -m geoagent_reliability_lab mock run --task G-003 --trace-out artifacts/traces/chain.jsonl
python -m geoagent_reliability_lab evaluate --trace artifacts/traces/chain.jsonl
~~~

Task G-003 is a synthetic geocode-to-reverse sequence. The mock registry and fixtures are illustrative: they do not represent measured Geoapify accuracy.

The evaluator re-evaluates the trace using declared success criteria, independently of the runner's own outcome field.

## Exercise B: Verify an actual value dependency

~~~bash
python examples/geoapify_mcp_two_step.py
~~~

In offline mode, the demonstration extracts the first geocode response's numeric latitude and longitude. It then builds a reverse-geocode request using those extracted values. It records request/response fingerprints and labels the outcome SYNTHETIC. No static coordinate fallback is used.

To understand the optional real mode and the meaning of field-lineage PASS, read [the MCP walkthrough](docs/REAL_MCP_WALKTHROUGH.md).

## Exercise C: Why a successful tool can still fail

The November 9 LIVE-FB-10 pilot recorded ten successful tool exchanges but a semantic conflict in the final Agent execution proof. The transform_geometry response was GeoJSON that the then-current consumption-proof extractor did not account for, resulting in a FAIL/UNKNOWN-safe final outcome rather than an invented successful answer.

The November 10 R1 pilot separately demonstrated that true live cross-step geocode-to-reverse value transfer could succeed. The independent geographic Oracle still remained UNKNOWN.

Review the comparison in [the live pilot report](docs/LIVE_FB10_RESULTS.md).

## Follow-up reading

- [Results](RESULTS_REPORT.md)
- [Error taxonomy](FAILURE_TAXONOMY.md)
- [M6 provenance policy](docs/M6_PROVENANCE_POLICY.md)
- [Geoapify tool feedback](docs/GEOAPIFY_MCP_FEEDBACK.md)

[Geoapify](https://www.geoapify.com/) provides the underlying MCP and geospatial APIs used in the independently authorized live pilots.

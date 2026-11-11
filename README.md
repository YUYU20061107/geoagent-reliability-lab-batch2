# GeoAgent Reliability Lab

**An evidence-aware reliability lab for multi-step geospatial AI agents.**

GeoAgent Reliability Lab tests a failure mode that ordinary API demos often overlook: a successful tool response does not prove that an AI agent correctly understood, consumed, and passed the result into its next action. The project separates transport outcomes, argument validity, response consumption, provenance, and geographic truth.

Developed for the [Geoapify Open Geospatial Program](https://www.geoapify.com/open-geospatial-program/), Batch #2. This is an independent developer project, not an official Geoapify accuracy benchmark.

## Try it in two minutes

**Requirements:** Python 3.12 and the standard library. No API key or network is required.

~~~bash
python -m unittest discover -s tests -v
python -m geoagent_reliability_lab validate
python examples/geoapify_mcp_two_step.py
~~~

The demonstration prints a clearly labelled SYNTHETIC two-step chain with zero network calls. The tests cover the synthetic benchmark, the public M6 reliability core, and the portable MCP example.

~~~bash
python -m geoagent_reliability_lab mock run --task G-003 --trace-out artifacts/traces/geocode-chain.jsonl
python -m geoagent_reliability_lab evaluate --trace artifacts/traces/geocode-chain.jsonl
python tools/run_regression.py
~~~

The evaluator independently checks the declared task criteria, trace integrity, and argument contract. An accepted synthetic trace is **not** a finding about a real geographic provider.

## What is included

| Area | Files | Scope |
| --- | --- | --- |
| Synthetic task benchmark | geoagent_reliability_lab/, tasks/, fixtures/, tests/ | 18 fixed tasks, 25 step responses, executable runner, independent evaluator |
| Reliability and evidence core | geoagent_m6/, tests/test_phase*.py | Multi-step executor, source and consumption provenance, semantic validation, failure injection, offline regression |
| Portable MCP chain | examples/geoapify_mcp_two_step.py | Geocode → reverse geocode with actual upstream latitude/longitude, source-labelled results, strict two-call ceiling |
| Documentation | TUTORIAL.md, REPRODUCTION.md, RESULTS_REPORT.md, FAILURE_TAXONOMY.md, AI_WORKFLOW.md | Setup, evaluation, error handling, study results and AI development process |
| Geoapify feedback | GEOAPIFY_FEEDBACK.md, docs/GEOAPIFY_MCP_FEEDBACK.md | Separate direct MCP observations from agent-side bugs and untested proposals |

This clean public version intentionally excludes historical M5-S0 sealed evidence, raw live response archives, personal filesystem paths, authorization documents, private ledgers, and the previous private Git history. Historical sealed experiments are discussed only at the level supported by their reviewed summaries.

## Main evidence-backed findings

**LIVE-FB-10, November 9, 2026:** Ten actual Geoapify MCP tools/call requests across eight tools. At tool-exchange level all ten succeeded, while task-level internal verdicts were **6 PASS / 3 UNKNOWN / 1 FAIL**. The overall agent execution record was **SEMANTIC_CONFLICT / SAFE_ABSTENTION**: a geometry result had not been demonstrably consumed. The original aggregate report was later reconstructed from preserved step records; the disclosure is retained.

**R1-PILOT-01, November 10, 2026:** A separately authorized, two-call live run executed geocode_address followed by reverse_geocode_coordinates. The reverse request used the actual coordinate values from the preceding live geocode response: **52.5172707, 13.3978233**. Technical field-lineage checks passed, while the **independent geographic Oracle remained UNKNOWN**. The two R1 calls are not added to LIVE-FB-10's ten-call statistics.

**LIVE-REPEAT-12X3, November 11, 2026:** A separate bounded experiment made 36 real MCP tools/call requests, three for each of the 12 observed tools. All 36 were tool-level successes; the original internal checks yielded **33 PASS / 3 UNKNOWN / 0 FAIL**. All three UNKNOWN cases were time-zone response normalization gaps. The three original captured time-zone replies subsequently normalized successfully in a strictly offline adapter fix. This is not a geographic accuracy claim. See the [repeatability pilot](docs/LIVE_REPEAT_12X3_20261111.md).

**Formal research governance is unchanged:** NO_GO, REAL18 0/18, G10 CLOSED, batch_2_authorized=false. These internal governance values are not vendor acceptance decisions.

See [live results](docs/LIVE_FB10_RESULTS.md), [results overview](RESULTS_REPORT.md), and [known limitations](KNOWN_LIMITATIONS.md).

## Optional real MCP demo

To run the portable *new* two-step demonstration against the live Geoapify MCP service, configure GEOAPIFY_API_KEY securely in your environment and explicitly opt in:

~~~bash
python examples/geoapify_mcp_two_step.py --live --authorize-two-calls --out my_private_live_result.json
~~~

This command may make **up to two real tools/call requests** and use quota. It validates the current tool catalogue, refuses unexpected or missing coordinate fields, and does not retry automatically. The example's declared credit reservation is a budget bound, **not measured billing**; credits_observed remains null when no provider metering is available. Do not commit the key or unreviewed live outputs. The default command without --live is always offline.

Read the [step-by-step MCP walkthrough](docs/REAL_MCP_WALKTHROUGH.md) before using the live option.

## Read the project

- [Tutorial](TUTORIAL.md)
- [Reproduction and test commands](REPRODUCTION.md)
- [Results and evidence tiers](RESULTS_REPORT.md)
- [November 11 real MCP repeatability pilot](docs/LIVE_REPEAT_12X3_20261111.md)
- [Failure taxonomy](FAILURE_TAXONOMY.md)
- [AI prompts and development workflow](AI_WORKFLOW.md)
- [Geoapify MCP/OpenAPI feedback](GEOAPIFY_FEEDBACK.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
- [Security and attribution](SECURITY_AND_ATTRIBUTION.md)
- [Version and source provenance](SOURCE_PROVENANCE.md)

## License and references

MIT License for project-authored source code. Any external map data retains its original licensing and attribution requirements. No OpenStreetMap database extract or private Geoapify response archive is included.

[Geoapify](https://www.geoapify.com/) · [Geoapify API documentation](https://apidocs.geoapify.com/) · [Open Geospatial Program](https://www.geoapify.com/open-geospatial-program/)

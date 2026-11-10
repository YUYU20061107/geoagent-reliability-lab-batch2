# LIVE-FB-10 | Real Geoapify MCP pilot

Historical pilot date: 2026-11-09. Evidence tier: actual MCP client-observable messages, step records and spend ledger. This is a **publication-safe summary**, not a raw capture bundle.

> **Scope.** This pilot ran in a separate local workspace, outside this repository. This file is the reviewed, publication-safe summary of that separate evidence stream; it is **not** part of the M5-S0 sealed payload and does not revise any result in [`RESULTS_REPORT.md`](../RESULTS_REPORT.md). The repository's own conclusion remains `NO_GO`, REAL18 `0/18`, and `provider_acceptance = NOT_LIVE_VERIFIED` for the offline harness. The ten verdicts below are declared internal criteria of that historical pilot and are not merged into REAL18. `UNKNOWN` is never upgraded to `PASS`. No raw provider capture, credential, account data or private workspace path is published here.

| Metric | Finding |
| --- | --- |
| Actual MCP tools/call attempts | 10 |
| Tool-level successful results | 10 |
| Distinct tools | 8 |
| Declared test faces | 5 |
| Immutable step records / captures / attempts | 10 / 10 / 10 |
| Capture SHA256 verification | 10 / 10 |
| Credits reserved (pre-spend, not billed) | 10.0 |
| Credits observed | null, no usable consumption metric |
| Per-task criteria | PASS 6 / UNKNOWN 3 / FAIL 1 |
| Overall executor | SEMANTIC_CONFLICT; SAFE_ABSTENTION |
| Formal REAL18 score | 0 / 18, unchanged |

## Ten distinct results

| ID | Tool | Verdict | Grounded limit |
| --- | --- | --- | --- |
| fb01_catalog | get_timezone | PASS | Live catalogue contract only |
| fb02_geo_a | geocode_address | PASS | Captured response consumed in smoke |
| fb03_rev_a | reverse_geocode_coordinates | PASS | Fixed-anchor consistency, not a true chained request |
| fb04_geo_b | geocode_address | PASS | Self-consistency of coordinate and response |
| fb05_search | search_places | PASS | Declared sample checks |
| fb06_route_a | calculate_route | PASS | Metric route constraints |
| fb07_measure | measure_geometry | UNKNOWN | Scalar response did not declare units |
| fb08_relate | evaluate_spatial_relation | UNKNOWN | Missing epsilon/tolerance semantics |
| fb09_transform | transform_geometry | FAIL | GeoJSON response not consumed by then-current executor |
| fb10_route_b | calculate_route | UNKNOWN | Snapping not independently verified |

The provider returned successful tool-level data in all ten calls. This **does not mean the Agent passed ten tasks** and does not imply provider correctness.

## Important negative result

The transform_geometry response was a GeoJSON Feature/Polygon, but the Agent's original consumption-proof extractor recognized number/boolean scalar envelopes and recorded zero consumed paths for this geometry. Consequently:

- all_steps_consumed = false
- integrity = SEMANTIC_CONFLICT
- Oracle = UNKNOWN
- evaluator = SAFE_ABSTENTION
- no final verified answer

This is an **agent-side consumption defect**, not proof of a Geoapify bug. An offline adapter fix and synthetic replay were later verified. Neither changed the original FAIL.

The original pilot's reverse geocode used a fixed anchor. A separate later R1 experiment first tested dynamic upstream-to-downstream coordinates offline, then independently executed and verified the two-step dependency on real Geoapify MCP on 2026-11-10 (documented below). Neither result changes the first-batch verdict.

## Reconstruction disclosure

A later authorization-expiration check overwrote the original top-level aggregate report. The live execution summary was reconstructed from unchanged durable captures, step records, ledger and run manifest, and labelled RECONSTRUCTED_FROM_IMMUTABLE_EVIDENCE. One historical SHA256 manifest entry for an offline acceptance report drifted; another path inventory omitted the "steps" directory layer. The original sealed manifest was not revised. Do not mistake these integrity limitations for a clean external audit.

Capture class: MCP_CLIENT_OBSERVABLE, not Geoapify downstream raw HTTP bodies. credits_observed is unknown, not zero. PASS/UNKNOWN/FAIL are declared internal criteria, not a performance percentage.

No private raw captures, account credentials, or unreviewed response bodies are included in this supplement.

## Separate R1-PILOT-01 real two-step verification (2026-11-10)

**Do not merge this outcome into the historical LIVE-FB-10 verdicts.** R1 is a new, separately authorized run with its own run ID and evidence namespace. It is the project's primary technical demonstration of real cross-step field transfer; LIVE-FB-10 remains the separate ten-call capability survey.

| Dimension | LIVE-FB-10 | R1-PILOT-01 |
|---|---|---|
| Run identity | Historical ten-call pilot, 2026-11-09 | Separately authorised two-call run, 2026-11-10 |
| Source | Separate local workspace, outside this repository | Separate authorised live run, outside this repository |
| Evidence tier | `LIVE` client-observable messages; aggregate `RECONSTRUCTED_FROM_IMMUTABLE_EVIDENCE` | `LIVE` client-observable two-call exchange with verified field lineage |
| Real `tools/call` count | 10 (8 distinct tools, 5 declared test faces) | 2 (`geocode_address` → `reverse_geocode_coordinates`) |
| Verdicts | 6 PASS / 3 UNKNOWN / 1 FAIL; overall `SEMANTIC_CONFLICT` / `SAFE_ABSTENTION` | Engineering `PASS`, executor integrity `SUCCESS`, independent geographic Oracle `UNKNOWN` |
| Formal governance | `NO_GO` / REAL18 `0/18` / `G10 CLOSED` / `batch_2_authorized=false` | Same, unchanged |

The two R1 calls are excluded from the ten-call statistics above.

| Field | Independently checked result |
| --- | --- |
| Real MCP calls | 2, both sent to provider |
| Workflow | geocode_address → reverse_geocode_coordinates |
| Input | Unter den Linden 1, Berlin |
| Real first response | lat 52.5172707; lon 13.3978233 |
| Actual second request arguments | lat 52.5172707; lon 13.3978233 |
| Field provenance | 2 verified lineage edges, matching dispatched arguments |
| Executor integrity | SUCCESS; both steps consumed |
| Credit reservation | 2.0, soft-stop reached as designed; hard cap 3.0 |
| Observed provider credits | null (not measured) |
| Engineering outcome | **PASS**, according to prespecified R1 technical criteria |
| Independent geographic Oracle | **UNKNOWN; SAFE_ABSTENTION** |
| Formal REAL18 | 0/18, unchanged |

Formal governance is unchanged by R1: `NO_GO / REAL18 0/18 / G10 CLOSED /
batch_2_authorized=false`. R1 establishes technical dispatch lineage on live MCP; it is not an
independently verified geographic answer and is not merged into REAL18.

The geocode result was read from the **same live run** and resolved before reverse geocoding. The downstream request contained numeric latitude/longitude rather than a fixed Berlin coordinate or an unresolved reference expression. This is real step-to-step field transfer, unlike the initial batch's fixed-anchor reverse call.

The R1 report also records two preceding network-path failures with zero booked tools/call attempts and zero captures. They were investigated without broadening the authorized two-call ceiling. A functional local HTTP proxy subsequently permitted standard verified TLS connections.

R1's original report remains separate in the internal workspace. Its published SHA256 manifest lists five checked artifacts (three matching report/attempt files and two capture files, 5/5), **not** an exhaustive hash inventory of the authorization and ledger files. Authorization was revoked after execution.

This result establishes **technical dispatch lineage on live MCP**, not independent truth of the returned geographic location. No new provider requests were needed to prepare this public summary.

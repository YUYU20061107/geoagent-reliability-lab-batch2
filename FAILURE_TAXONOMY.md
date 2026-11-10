# Failure taxonomy

GeoAgent treats an Agent response, its tool transport, the Agent's consumption of data, and the geographic truth of an answer as separate verification layers.

| Class | Example | Evidence | Outcome |
| --- | --- | --- | --- |
| Tool unavailable | Tool absent in live catalogue | Actual tools/list plus declared workflow | BLOCKED |
| Parameter contract | Wrong field, missing operation, bad coordinate order | Parsed tool schema / local contract | FAIL or BLOCKED |
| Authentication / quota | HTTP 401, 403, 402, 429 | Transport error code, no made-up response | STOPPED |
| Network uncertainty | Timeout after an attempted call | Attempt record and any durable capture | STOPPED; manual reconciliation |
| Response shape | Flattened data vs GeoJSON or typed scalar | Observed response structure | FAIL if unsupported; preserve actual source |
| Missing consumption | A successful response with no demonstrated downstream read | Consumption proof and step lineage | FAIL / SEMANTIC_CONFLICT |
| Value lineage | Downstream argument differs from authenticated upstream field | Captured source digest, resolved value, transmitted parameter | FIELD_LINEAGE_MISMATCH |
| Independent truth | Snapping or geometric epsilon not validated by external authority | Oracle source absent | UNKNOWN / SAFE_ABSTENTION |
| Evidence integrity | A declared capture or dependency is missing or altered | SHA256 and record references | FAIL / REFUSE |
| Budget / scope | Too many attempted calls or reserved credits | Call gate and cost ledger | STOPPED |
| Synthetic overclaim | Mock result labelled as real | Mode/source flags and egress evidence | REJECT |
| Incomplete replay | A recorded PASS cannot be independently recomputed | Independent evaluator output | UNKNOWN or FAIL |

**PASS** is specific to the exact criterion being evaluated; it cannot be used as an umbrella claim of geographic accuracy.

## A concrete live case

On November 9, 2026, the transform_geometry call returned successfully, but the Agent's older executor recorded no consumed GeoJSON paths. Its overall execution remained SEMANTIC_CONFLICT / SAFE_ABSTENTION rather than a fabricated verified answer.

A subsequent separate November 10 pilot proved technical geocode-to-reverse field dispatch on live Geoapify MCP. It did not provide an external geographic Oracle, so geographic correctness remained UNKNOWN.

## Recommended response to failures

Preserve the first failure code and the original evidence. Do not use a fixture or reconstruct missing arguments to silently turn an incomplete real chain into a success. Do not automatically resend after ambiguous transport failure. Distinguish scientific UNKNOWN from system-level FAIL.

Detailed module-level rules appear in [the M6 provenance policy](docs/M6_PROVENANCE_POLICY.md) and in [the baseline failure taxonomy](docs/FAILURE_TAXONOMY.md).

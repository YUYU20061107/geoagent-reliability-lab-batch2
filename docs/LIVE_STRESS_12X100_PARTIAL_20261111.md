# Partial 12 x 100 Live MCP Stress Test | November 11, 2026

GeoAgent Reliability Lab ran a separately authorized, bounded real-MCP stress experiment with a target of 100 actual calls per tool, covering all 12 tools observed in the Geoapify MCP catalogue (1,200 planned calls). The experiment was intentionally stopped after intermittent transport failures. This is a **partial live stress-test result**, not a completed 1,200-call benchmark.

## Verified outcome

| Measure | Result | Interpretation |
| --- | ---: | --- |
| Planned MCP tools/call attempts | 1,200 | 12 tools x 100 each |
| Actual attempts in the authorization ledgers | 232 | Four distinct execution segments |
| Successful, durably captured tool replies | 228 | 228/232 attempted; not 228/1,200 completed |
| Transport failures without a recorded reply | 4 | Delivery/billing status uncertain; never retried |
| Cases never attempted | 968 | No result or verdict assigned |
| Internal functional smoke checks, received replies only | 228 PASS / 0 UNKNOWN / 0 FAIL | Basic schema, plausibility, response and geometry invariants |
| Response SHA256 fingerprints matching captures | 228/228 | Exact bytes retained in private workspace |
| Private inventory entries verified | 482/482 | Four private inventories, no checksum mismatch |
| Duplicate attempted case identifiers across segments | 0 | No replay of ambiguous requests |
| Locally reserved credits across segments | 269.0 | Reservation ledger, NOT observed provider billing |
| Actual provider-billed credits | Unknown | No verified provider metering |
| Temporary execution grants | 4/4 revoked | No live calls remain authorized |

All 12 tool types received successful responses. The observed tool-level success ratio across attempted requests was 228/232 (about 98.3%). That figure **describes this interrupted execution only**, not a confidence interval or the reliability or geographic accuracy of Geoapify services.

## Per-tool execution counts

| Geoapify MCP tool | Attempted | Captured successful replies | Ambiguous transport failures |
| --- | ---: | ---: | ---: |
| `geocode_address` | 20 | 20 | 0 |
| `geocode_structured_address` | 20 | 20 | 0 |
| `reverse_geocode_coordinates` | 20 | 19 | 1 |
| `get_timezone` | 19 | 18 | 1 |
| `search_places` | 19 | 19 | 0 |
| `list_place_categories` | 20 | 20 | 0 |
| `calculate_route` | 19 | 19 | 0 |
| `calculate_route_matrix` | 19 | 18 | 1 |
| `combine_geometries` | 19 | 19 | 0 |
| `evaluate_spatial_relation` | 19 | 18 | 1 |
| `measure_geometry` | 19 | 19 | 0 |
| `transform_geometry` | 19 | 19 | 0 |

The experiment's planned workload mixed repeated requests with varying locations and arguments. However, **most variable-input cases were never reached**; the successful replies are weighted toward early baseline cases. The parameterless `list_place_categories` tool naturally repeats the same request. The current experiment must not be characterized as having tested 100 varied inputs per tool.

## What happened and what did not

The initial execution segment booked 78 attempted calls and captured 76 successful replies. A second, non-retrying continuation booked 82 attempts and captured 81 successful replies. A third segment used one MCP session, booked 60 attempts, and captured all 60 successful replies. A fourth segment booked 12 attempts, captured 11 successful replies, and stopped after another transport fault.

The four failures had the reason code `NETWORK_ERROR` and affected `get_timezone`, `calculate_route_matrix`, `evaluate_spatial_relation`, and `reverse_geocode_coordinates`. They were **not** recorded as provider semantic failures, and it is unknown whether the requests reached the remote service or incurred charges. No automatic retry was performed; all four case IDs remain accounted for as attempted.

The independent local review checked that attempted case IDs did not repeat across segments, every captured response matched its recorded SHA256, authorization grants were revoked, and the 228 received replies met the specified internal smoke-test criteria. These are engineering checks, not an independent geographic truth Oracle.

## Scientific and publication limits

- The result is **232 of 1,200 attempted**, not 1,200 tested or passed.
- The 228 PASS outcomes refer only to internal engineering smoke checks performed on captured successful responses.
- Independent truth of geographic coordinates, route optimality, place identity, and geometry tolerances remains **UNKNOWN**.
- Observed transmission faults cannot be attributed to Geoapify without further network/transport evidence.
- The formal internal research gate remains **NO_GO / REAL18 0/18 / G10 CLOSED / batch_2_authorized=false**; historical LIVE-FB-10, R1, 12 x 3, and 12 x 5 outcomes are unchanged.
- Private MCP response bodies, authorization grants, local paths, and cost ledgers are excluded from the public repository. Public readers can inspect the summarized findings and rerun offline code, but cannot independently replay historical live bytes from this repository.

## Related material

[Results overview](../RESULTS_REPORT.md) · [36-call pilot](LIVE_REPEAT_12X3_20261111.md) · [Known limitations](../KNOWN_LIMITATIONS.md) · [Offline reproduction](../REPRODUCTION.md)

[Geoapify](https://www.geoapify.com/) provides the MCP tools used for these separately scoped real API calls.

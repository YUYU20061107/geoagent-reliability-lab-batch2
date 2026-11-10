# Geoapify MCP and OpenAPI feedback

All observations below come from the real ten-call MCP pilot and a subsequent separate two-call R1 live data-flow test unless they are explicitly identified as suggestions or our own limitations. The R1 run verified technical upstream-to-downstream coordinate dispatch but did not establish independent geographic correctness. We do not claim an unverified provider defect.

> **Scope.** This document is one of **two distinct** feedback documents. [`../GEOAPIFY_FEEDBACK.md`](../GEOAPIFY_FEEDBACK.md) contains seven interface asks derived purely from offline protocol design by this repository's M5-S0 layer, which never made a live call. This document instead records observations from a separate historical real MCP pilot (summarised in [`LIVE_FB10_RESULTS.md`](LIVE_FB10_RESULTS.md)) plus the separate R1 two-call run. Neither document supersedes the other, and this document is **not** an acceptance test or measured evaluation of Geoapify.

## Verified integration observations

The real MCP session returned a live tools/list catalogue with 12 tool definitions. Ten tools/call attempts across eight different tools completed successfully at tool-transport level. Real tool schemas exposed parameter mistakes before sending requests: search_places expected a category and anchor latitude/longitude rather than a generic query, and geometric tools used an operation discriminator.

Forward geocoding, reverse geocoding, place search, routing, measurement, relation and geometry transformation returned structured outputs that were not identical in shape.

## Requested clarifications

| Topic | Observed issue or open question | Request |
| --- | --- | --- |
| Units | measure_geometry returned a typed numeric data field without explicit unit | Include units, CRS and distance model in response |
| Relation semantics | evaluate_spatial_relation returned a boolean without epsilon/tolerance semantics | Document predicate tolerances and boundary rules |
| Geometric result types | transform_geometry returned a GeoJSON feature, unlike scalar data envelopes | Publish complete examples for typed scalar versus GeoJSON results |
| Tool schemas | search_places and geometry operations require discriminated argument shapes | Publish versioned schemas and examples for each operation |
| Credit observability | Pilot did not observe per-call credit use in available headers | Provide a documented usage endpoint or distinguish charges from quota remaining |
| Contract drift | Published static schema may diverge from live tools/list | Offer tool/schema versioning and compatibility guidance |
| Location identity | Cross-endpoint place_id stability was not independently tested | Specify stable-ID scope, lifecycle and equivalence semantics |
| Reliable testing | Real geography and live results change over time | Offer a reproducible, fixed geographic MCP example suite |

## Explicitly agent-side defects

The pilot's transform_geometry call succeeded, but our consumption-proof extractor failed to record how GeoJSON data was read. The Agent correctly refused to produce a verified final answer. We repaired our adapter in a later offline postmortem, but did not claim the Geoapify service failed.

Similarly, the point_on_line epsilon question and some route-snapping interpretations are UNKNOWN without an independent Oracle; these are not established provider errors.

## Main lesson

A tool-level 200/OK, a valid normalized response, a consumed response field, a semantic task verdict, and independent geographic correctness are five **different** claims. Agent evaluation should keep them separate.

[Geoapify](https://www.geoapify.com/) · [Geoapify API](https://apidocs.geoapify.com/)

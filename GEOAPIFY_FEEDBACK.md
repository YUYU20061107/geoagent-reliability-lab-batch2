# Geoapify MCP / OpenAPI feedback

This feedback combines direct observations from an independently authorized MCP pilot with separate, explicitly unverified improvement proposals. It does not assign provider bugs without an accepted external Oracle.

## Actual MCP observations

- The live MCP tools/list response contained **12 tool definitions**.
- Ten tools/call operations across eight tools returned tool-level success in the initial pilot.
- Live parameter schemas helped prevent invalid requests. For example, search_places used category and geographic anchor fields rather than a generic query string, and geometry operations required an operation discriminator.
- Response shapes varied: geocoding and place results could use flattened result objects; scalar geometry calculations could use typed numeric/boolean envelopes; geometry transformation could return GeoJSON structures.
- No per-call provider credits figure was observed in the available response headers, so actual consumed credits were recorded as UNKNOWN rather than zero.
- A separate live R1 run on November 10 verified that coordinates returned from real geocode_address were actually sent to reverse_geocode_coordinates.

## Concrete suggestions

| Topic | Observation or uncertainty | Suggested improvement |
| --- | --- | --- |
| Units and coordinate reference | A measurement returned a numeric value without an explicit unit in its observed response | Return units, CRS and distance model with computed numbers |
| Predicate tolerance | A point-on-line predicate returned a boolean without an explicitly observed epsilon | Document exact tolerance and boundary semantics |
| Response-shape families | Scalar, flattened-object and GeoJSON responses require distinct consumers | Publish complete live examples of each canonical result family |
| Tool schemas | Valid parameters depend on tool and operation subtype | Expose operation-specific, versioned request schemas with valid examples |
| Quota reporting | Per-request credit charges were not exposed in observed headers | Supply a documented credit-use field or usage endpoint |
| Data consistency | Stable place-ID rules across endpoints were not independently tested | Specify identity scope, cross-endpoint equivalence and ID lifetime |
| Reproducible testing | Dynamic live data can change between runs | Offer a small stable test suite with known answer shapes |

## Defect ownership

**Agent-side failure, not a proven Geoapify bug:** transform_geometry succeeded, but our earlier consumption-proof extractor did not record how the returned GeoJSON was used. The Agent halted with SAFE_ABSTENTION instead of misreporting task success. An offline fix was later verified without retroactively changing the historical live verdict.

**Unknown provider-correctness questions:** geometry tolerances, route snapping, geographic point accuracy, and stable place-ID equivalence were not independently proven.

## What a good developer API enables

Reliable Agent engineering benefits from more than a success/failure HTTP code. Stable tool schema versions, explicit source/units/CRS semantics, structured failure details and safe reproducible test cases make an evidence-aware multi-step workflow significantly easier to build.

See [the detailed MCP feedback](docs/GEOAPIFY_MCP_FEEDBACK.md) and [the published pilot summary](docs/LIVE_FB10_RESULTS.md).

[Geoapify](https://www.geoapify.com/) · [API documentation](https://apidocs.geoapify.com/)

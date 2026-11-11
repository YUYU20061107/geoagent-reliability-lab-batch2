# Results and evidence

## Offline public benchmark

| Experiment | Scope | Result | Evidence limit |
| --- | --- | --- | --- |
| Sprint 0 task registry | 18 fixed synthetic tasks, 25 registered tool steps | Registry validation PASS | All mock geographic data are synthetic |
| Public MCP two-step | Geocode → reverse geocode | SYNTHETIC dispatch lineage PASS | No network call in default mode |
| Public M6 reliable executor | Semantic constraints, consumption, provenance, capture, regression | 39/39 regression cases; included unit tests PASS | Offline generated/supplied fixtures |
| Public test discovery | Whole clean candidate, CPython 3.12 | 137/137 at original release; 141/141 after the offline time-zone adapter update | Not an independent geographic benchmark |

## Historical live experiment LIVE-FB-10 (2026-11-09)

- **Ten real Geoapify MCP tools/call requests**, eight distinct tools, five declared test faces.
- Ten successful tool-level exchanges.
- **Per-task internal criteria:** 6 PASS / 3 UNKNOWN / 1 FAIL.
- **Overall executor:** SEMANTIC_CONFLICT; SAFE_ABSTENTION; no verified final answer.
- Agent-side negative finding: a GeoJSON transform result returned successfully but lacked demonstrated consumption.
- **credits_reserved = 10.0; credits_observed = null.**

The original aggregate report was overwritten by an authorization-lapse check and explicitly reconstructed using preserved durable evidence. This disclosure is retained. Original captures and the internal ledger are not published, so this public tree supports inspection of the reviewed summary, not byte-for-byte reconstruction of the historical provider exchange.

## Separate live experiment R1-PILOT-01 (2026-11-10)

- **Two real MCP tools/call requests:** geocode_address → reverse_geocode_coordinates.
- Upstream actual geocode result latitude **52.5172707** and longitude **13.3978233** was used in the second request.
- Two dispatch-lineage edges verified; execution integrity SUCCESS.
- **Technical engineering PASS** under the prespecified R1 criteria.
- **Independent geographic Oracle UNKNOWN; SAFE_ABSTENTION.**
- **credits_reserved = 2.0; credits_observed = null.**

R1 is not added to LIVE-FB-10's ten-call statistics. The R1 SHA256 inventory was verified for the five artifacts it lists, not described as a signature over every file of the run.

## Separately authorized LIVE-REPEAT-12X3 experiment (2026-11-11)

A new pilot executed **three actual calls for each of the 12 observed MCP tools**, 36 calls total. All **36/36 tool-level exchanges** succeeded. The initial internal checks were **33 PASS / 3 UNKNOWN / 0 FAIL**. All three UNKNOWN results were for the unsupported get_timezone response shape in the then-current Agent adapter. A later **offline-only** fix normalized the original three captured time-zone responses successfully, without changing their original live verdicts.

Three new geocode-to-reverse chains independently verified downstream request arguments against the same-run upstream response fingerprints. The private evidence audit verified 77 inventoried files, with zero SHA256 mismatches. Credits reserved were 42.0 (hard bound 60), while actual provider billing remained unobserved. This is a technical repeatability check, not an independent geographic Oracle.

Read [the 12-tool, 36-call report](docs/LIVE_REPEAT_12X3_20261111.md) for the full evidence boundaries.

## Scientific boundary

PASS, FAIL and UNKNOWN represent declared checks, not a statistically validated provider error rate. In particular, returned coordinates, snapping and geometry tolerances were not established against an accepted independent truth set.

Internal formal governance remains NO_GO / REAL18 0/18 / G10 CLOSED / batch_2_authorized=false. The status is not a Geoapify program acceptance decision.

For the step-level breakdown, see [LIVE_FB10_RESULTS.md](docs/LIVE_FB10_RESULTS.md). For requested API and MCP clarifications, see [GEOAPIFY_FEEDBACK.md](GEOAPIFY_FEEDBACK.md).

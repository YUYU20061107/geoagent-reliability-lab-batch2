# Known limitations

## Independently verified scope

- The 18-task benchmark and 25 tool steps use **synthetic fixtures**.
- The public M6 executor/core and its tests run offline with supplied synthetic data.
- The portable MCP example runs offline by default; its optional real mode is separately enabled.
- Historical LIVE-FB-10 and R1-PILOT-01 real calls are described in reviewed publication-safe summaries, not with raw response archives.

## Limitations of scientific interpretation

1. No accepted external geographic Oracle was provided for the complete benchmark. Engineering PASS on field lineage is **not** a provider accuracy result.
2. LIVE-FB-10's ten tool-level exchanges succeeded, but the final Agent result had SEMANTIC_CONFLICT / SAFE_ABSTENTION. It must not be advertised as ten successful Agent tasks.
3. R1's two actual tools/call requests established real upstream-to-downstream argument transfer; they did not prove that the coordinates or reverse-geocoded location were independently correct.
4. Geometry predicate epsilon and route-snapping interpretation were unresolved in the pilot.
5. credits_reserved is a local pre-spend budget figure; credits_observed remains null without direct provider metering.
6. Sample geography and synthetic fixtures can share modeling assumptions with the evaluator, limiting independence.

## Limitations of published evidence

1. The original LIVE-FB-10 top-level report was overwritten during a later authorization-lapse check. Its replacement was explicitly reconstructed from preserved immutable records. Reconstruction does not retroactively recover the original aggregate bytes.
2. A historical frozen SHA256 manifest has documented path/hash drift. Old sealed evidence is not silently changed, signed anew, or included in this public repository.
3. R1's disclosed five-entry SHA256 inventory covered selected execution and capture files, not its entire runtime directory.
4. Raw provider response bodies, private credentials, local authorization files and spend ledgers were excluded for publication safety. Therefore a reader can reproduce the source code and fresh tests, but not the historical byte-for-byte live exchanges.
5. Historical M5-S0 experiments required an external frozen M3.2 layer and were deliberately excluded from the clean self-contained public delivery.

## Formal governance and evaluation

Internal status remained **NO_GO / REAL18 0/18 / G10 CLOSED / batch_2_authorized=false** throughout the reported engineering pilots. Earlier research checks L3 0 PASS / 7 UNKNOWN and L4 0 PASS / 9 FAIL have not been upgraded by the public snapshot.

This project's internal research gate is separate from Geoapify's review of an open-source deliverable.

See [Results](RESULTS_REPORT.md), [Reproduction](REPRODUCTION.md), and [Security and attribution](SECURITY_AND_ATTRIBUTION.md).

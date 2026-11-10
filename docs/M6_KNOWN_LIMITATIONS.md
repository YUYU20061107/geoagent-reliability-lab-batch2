# Known limitations (accurate research boundaries)

1. **No real provider calls in M6.** `provider_calls = 0`, `network = false`.
   All M6 results are offline. The next real-call round requires a new explicit
   authorisation; nothing here releases it.

2. **22/22 is a shape-classification result**, not Geoapify accuracy, not a
   success rate, and not an independent replication of the M5 live pilot.

3. **No provider HTTP raw bytes exist** in the historical evidence pack. It
   stores parsed MCP payloads plus `response_sha256` and byte length. M6's
   capture pipeline records *MCP-client-observable JSON-RPC message bytes* for
   future calls only; it cannot and does not backfill history.

4. **P2-S4 remains `SEMANTIC_CONFLICT_UNRESOLVED`.** Without a documented
   provider tolerance contract, documented predicate semantics and at least
   three independent samples, no provider bug is claimed. `provider_bug_claims = 0`.

5. **P3-X6 recovery candidates are unvalidated.** Bounded snapping radii
   (50/150/300 m) and alternative modes are explicit proposals only; testing
   them requires an authorised live round.

6. **P2-M5 area-change figure (~62.9%) is upstream-reported**, not
   independently remeasured by M6. M6 fixes the interface (explicit units) and
   adds local area/topology/shape checks; the original failure is retained.

7. **Oracle independence is methodological, not organisational.** The public
   Oracle uses externally declared specs and mathematical identities. It is not
   an official external Oracle and does not constitute L3/L4 acceptance.
   Historical L3 `0 PASS / 7 UNKNOWN`, L4 `0 PASS / 9 FAIL` are unchanged.

8. **Stale 741-entry manifest is a blocker.** `m5s0/PAYLOAD_MANIFEST.sha256`
   hashes pre-normalisation CRLF bytes. M6 did not regenerate it or rewrite
   sealed files to force a match. The post-normalisation
   `RELEASE_SHA256SUMS.txt` is the current byte reference (785/785 in both
   clone environments).

9. **Historical provenance correction is derived, not in-place.** 35 replay
   traces and 48 step files were relabelled in a derived index only; all 825
   sealed files remained byte-identical.

10. **Public subset is not the full sealed verification.** See
    `REPRODUCTION.md` §3. The two are explicitly not equivalent.

11. **Governance is unchanged.**
    `NO_GO / REAL18 0/18 / G10 CLOSED / batch_2_authorized=false`.
    No research protocol freeze, no formal scoring, no public release approval.

12. **No claim about credits.** The historical 514 credits is a reservation
    ceiling. `credits_observed` stays `null` when the provider reports nothing.

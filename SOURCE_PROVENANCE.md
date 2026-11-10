# Source provenance

The public delivery was assembled as a new, standalone Git repository. **No prior private Git history was copied.**

| Component | Source baseline | Publication treatment |
| --- | --- | --- |
| Sprint 0 benchmark, evaluation code and tests | Private staging snapshot at commit 3437768b21a5a37a330a7a5dd80e9814e913e67d | Source code and selected fixtures only |
| Portable Geoapify MCP example and tested walkthrough | Same staging snapshot | Explicitly bounded, offline by default |
| M6 reliability/evidence core and synthetic regression tests | Independent engineering-core commit fb82d7916b343d28efef084cf0b61c5199955946 | Self-contained Python modules and non-private synthetic fixtures only |
| Historical Geoapify live pilot results | LIVE-FB-10 and R1-PILOT-01 reviewed summaries | Plain-language results only; no raw provider response or spend ledger |

The M5-S0 sealed evidence tree and external frozen M3.2 dependency are not part of this public snapshot. The older private branch's hash-sealed archives were not edited or re-signed.

The source commit references identify the internal code baselines used for assembly; they are **not an external independent attestation** of the provider's geographic correctness. The new public repository's own commit hashes identify the actual publicly reviewable source.

The independently reproducible scope is defined in [REPRODUCTION.md](REPRODUCTION.md). Scientific and evidence limits are documented in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

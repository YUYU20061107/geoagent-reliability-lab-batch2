# AI-assisted development workflow

This project used multiple AI coding agents under a human-directed engineering process. AI agents were not treated as independent truth oracles. Their code and recommendations were subject to regression checks, bounded authorization, source classification and review.

## Working method

1. **Problem framing:** Specify geospatial Agent tasks separately from tool-level transport success.
2. **Interface contracts:** Define task IDs, parameter shapes, required geographic data, source types and success criteria before implementation.
3. **Test-first implementation:** Use offline synthetic fixtures, malformed arguments and failure injections to establish deterministic regression tests.
4. **Bounded live integration:** Only run real Geoapify MCP calls when a specific budget, tool allowlist and approval scope are in force.
5. **Evidence verification:** Record actual call counts, consumed response fields, dependency values, replay provenance and unresolved failures.
6. **Release review:** Remove or exclude private source captures, credentials and machine-identifying data. Reproduce the documented public workflow from a clean checkout.

## Representative prompts / instructions

The following are **sanitized summaries of actual task instructions**, not verbatim transcripts of private chats:

> Design an 18-task geospatial Agent reliability benchmark spanning geocoding, places, routing, matrices, spatial relations and geometry. Separate an independent evaluator from the runner; use synthetic fixtures and transparent failure evidence.

> Ensure every real tools/call is checked against a tool whitelist, a limited call count and a reserved-credit budget. Do not retry automatically. Preserve the original transport fault and do not record incomplete calls as success.

> Add field lineage so the downstream step consumes values from a verified upstream response, not a preset geographic coordinate. Reject missing, non-finite, out-of-range or unverified references without sending another request.

> Present PASS / FAIL / UNKNOWN honestly. A successful MCP reply must not be counted as independent geographic correctness; publish an Agent-side failure even when the underlying tool returned data.

> Prepare a fully English, reviewer-facing, standard-library-only public project. Keep sealed historical evidence private and verify the result from a clean checkout before publishing.

## Roles and accountability

The human project lead supplied research goals, budgets, publication decisions and final approval boundaries. AI-assisted engineering produced candidate modules, tests, documentation and controlled workflow changes. Cross-agent reviews, deterministic test results, byte-level evidence checks and explicit unresolved limitations are recorded as distinct evidence types.

An AI evaluator agreeing with an AI-generated fixture is not independent geographic ground truth. For that reason, the research retains UNKNOWN when an accepted external Oracle is absent.

## Tools and methods

- Python standard library for the runnable public benchmark, MCP example and testing.
- Git and GitHub for version history, pull-request review and release reproducibility.
- Geoapify MCP for the separately authorized real integration pilots.
- Hash-based integrity and fail-closed decisions for evidence-sensitive steps.
- Synthetic negative controls for dropped, altered, mismatched and unconsumed tool responses.

## Disclosure and security

Original private chat transcripts, account details, API credentials, raw MCP captures, private spend ledgers and old local-machine paths are not distributed. The public snippets above communicate the actual workflow constraints without reproducing private operational details.

[Geoapify](https://www.geoapify.com/) · [Geoapify API](https://apidocs.geoapify.com/)

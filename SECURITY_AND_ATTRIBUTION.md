# Security and attribution

## Credentials

The default offline example does not load an API key or open a network connection.

Optional live mode reads GEOAPIFY_API_KEY from the environment and requires both --live and --authorize-two-calls. The example limits its own tools/call attempts to two, does not retry automatically and avoids embedding credentials in source. Users should obtain their own Geoapify key and review account usage before enabling live mode.

**Do not commit** tokens, .env files, internal authorization documents, private ledgers or raw provider response archives. Local outputs whose names start with my_ are ignored by Git.

## Privacy-preserving publication

This public edition was assembled from explicit, reviewed source-code and documentation allowlists with a **new Git history**. Historical private Git commits, sealed M5-S0 payloads, original live captures, local paths and private account records are deliberately excluded.

The README, tutorials and published results are English-language documents. The small synthetic fixture collection may include illustrative international address strings to test Unicode handling; these are not user identities or captured private data.

## Provider and geographic data attribution

Project-authored source code is distributed under the MIT License. External geographic provider responses, map tiles and OpenStreetMap-derived databases remain governed by their own terms and attribution rules. This release includes no OpenStreetMap database dump or raw private Geoapify response archive.

The published synthetic fixtures are not represented as real-world geographic ground truth.

## Research transparency

LIVE, SYNTHETIC, REPLAY and RECONSTRUCTED evidence types must not be conflated. Any claims derived from actual pilot provider requests are limited to the separately documented engineering observations and preserved outcome categories.

The original private research artifacts remain outside this repository and are not modified by the release assembly.

[Geoapify](https://www.geoapify.com/) · [Open Geospatial Program](https://www.geoapify.com/open-geospatial-program/)

# W0 package independent review

Review date: 2026-10-01. Scope: W0 scripts and fixed scenario/check/budget metadata, plus local in-memory negative probes. No business-repository edits, live requests, production queries, paid calls, publication, or release approvals.

## Findings and disposition

1. **Fixed and retested:** `verify_gates()` originally read `check.cases`, while all checks use `acceptance_cases`. It raised `KeyError`. The corrected code self-checks 29 checks, 14 criteria, and 14 scenarios.
2. **Fixed and retested:** `declared_refs()` originally treated a schema/property map key named `$ref` as a reference. Two narrow probes produced non-string reference targets. The corrected map-aware walker now returns no references for these literal names. Add the reserved-name shape to the fixed fixture matrix to retain regression coverage.
3. **Fixed and retested:** the original `verify_inventory()` froze operation-ID membership but not each ID's association with `(provider,path,method,status)`. Swapping two AgentMail IDs and flipping an inventory row status initially passed. The final verifier freezes full identity tuples and inventory rows and checks provider endpoint counts; both negative probes now fail with the intended association errors. Stored facts-hash equality remains a consistency check, not a recomputation of the runtime semantic hash; exact archived bytes are separately locked.
4. **Fixed and inspected:** the final verifier compares exact file membership under both package roots against the manifest, excluding only manifest/result/archive and Python bytecode caches. This prevents an added expected fixture from silently changing the frozen oracle or consumer expectation set.

The initial fixture self-check passed 11 cases, 77 literal assertions, and 69 independent Draft202012 schema instances. It imports no composer, runtime projection, or consumer implementation. Exact consumer equality compares JSON booleans distinctly from numeric zero/one. Unresolved local/external refs have explicit incomplete expectations. This is an oracle self-check; it does not show actual consumers preserve these values.

## Scope and readiness review

`scenarios.json` records C01-C14 as unexecuted procedures with fixed expected outcomes. `checks.json` separates CodeReady and ReleaseReady; planned, missing, unavailable, and not_assessed are explicitly non-passing. Known website failures and homepage budgets remain required. GitHub branch protection, operators, actual required-check contexts, deployment, and source-gap approval are unknown rather than inferred from local workflow text.

`budgets.json` freezes the 3,600-second candidate, 14,400-second convergence, hourly version monitoring, daily refresh, and 30-day manual/pinned review targets. Its proof status is NOT_PROVED. Website discovery stale windows and several unset job limits exceed the frozen convergence target; nominal cron spacing and job timeout are correctly distinguished from a delivery guarantee. The package can preserve these findings, but an unconditional statement that W0's feasible budget closure is complete would be incorrect. Implementation needs the stated concrete W3 timing/cache changes and operator evidence.

`replay.py` checks the locked Docs revision and clean working tree, reads a byte-locked archive, writes only a fresh local output directory, and explicitly uses an unapproved diagnostic debt baseline. Its receipt says offline implementation replay, not independent semantic or release acceptance. Replay equality and determinism cannot approve debt or replace hand-reviewed semantic expectations. Page generation is disabled, so this replay does not verify generated EN/ZH page or navigation behavior.

## Final archive check

The final archive contains 4,242 allowlisted regular files, compressed to 7,832,762 bytes, SHA-256 `f2b35c81df49b3a31053f3b4e8978778e52556d2d36536c23f4d7f28f8e0f02f`. The manifest records all members with byte hashes, exact code revisions, offline/reconstructed provenance, unapproved identity review, and source freshness not_assessed. It preserves input pages as fixed local material; replay still does not regenerate or validate them.

The full final verifier passed independently: 2,162 inventory endpoints, 1,979 projected endpoints, 1,991 facts operations, 1,930 composed-output operations, 102 request gaps and 62 response gaps; 11 fixture cases, 77 assertions, 69 schema instances, 29 checks and 14 scenarios. Consumer and release remain not_assessed, content remains pending_debt. This is package-integrity and oracle-self-check evidence only.

The archive's `sanitization.json` records four exact Waveinflu input/lineage redactions, original/sanitized hashes and pointers, using `example@example.invalid`. Every listed sanitized file matches its receipt hash. The upstream mirror, saved provider input, and expected replay output contain no Gmail literal. A scoped scan across every archived member found no database/Redis URI, AWS/GitHub token, JWT, private-key payload, or Gmail literal. The public source examples and documentary PEM-marker prose identified in the source audit remain intact. Source-reference metadata is portable and identifies repository/commit/path plus archived_path instead of requiring the old temporary worktree.

No remaining package-integrity or privacy blocker was identified in this review. Runtime/source freshness, actual consumer semantic adapters, page generation, approved debt, feasible timing, publication, deployment, and live convergence are explicitly outstanding. After this review file changes, the parent must refresh its manifest hash and rerun the verifier.

## Final oracle strengthening

After the archive review, the fixture owner added complete fixed schema/body/response declaration graphs and a literal `$ref` property case. The escaped reference target now uses a valid `$defs` name. Final local verification records 12 cases, 78 assertions, 72 schema instances and 26 consumer/negative outputs. Both positive OpenAPI 3.0 and 3.1 documents pass the independent standard validator. Actual consumer outputs remain unassessed. The parent added this disposition and reruns the package and negative tests after refreshing hashes.

## Timing remediation proposal disposition

The independent arithmetic review of `timing-remediation.md` confirms Docs 40 minutes (20 minutes margin), Website 137 minutes (103 minutes margin), MCP 162 minutes (78 minutes margin), and Router 145 minutes (95 minutes margin). The external 60-minute / 4-hour deadlines remain fixed. The document and linked budget metadata correctly describe design caps with operator evidence, implementation, and W4 measurements pending; they do not imply current delivery guarantees or a passed timing check.

Before W3 records effective limits, interpret the 15-minute queue allowance as the aggregate across all serial jobs on its path. Also keep MCP's 10-minute homepage proxy/HTTP content window distinct from the authoritative latest-version signal, whose lifetime is capped at five minutes: version checks must invalidate that content or explicitly label it outdated. These are implementation-proof obligations within the frozen proposal, not permission to expand the external deadline. No arithmetic or scope-claim blocker was found in the proposal itself.

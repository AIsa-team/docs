# Source definition review and bounded acquisition

The 67 source files in the frozen W0 input are review inputs, not approved
current production definitions. The code-only PR contains no formal source
registry, upstream graph, coverage baseline or genuine source receipts.
The existing draft policy split is 18 automatic / 48 manual / 1 pinned; these
counts do not approve a source or a maintenance policy.

Each source needs a named provider integration owner and Docs review owner.
Review one source, or at most three official acquisitions, per batch. Start
with sources related to enabled request/response gaps, then complete remaining
definitions. For every operation, compare current public method/path, server
prefix, request parameters/body/defaults/constraints, successful response
statuses/payloads and errors against the provider's authoritative definition
and the actual runtime binding. ANY expansion and asynchronous lifecycle routes
must retain runtime identity and admission rules. Provider documentation cannot
override runtime pricing, availability or routing.

47 of the 67 current authority URLs point to historical AIsa Docs JSON. Those
files prove preservation history; reading them again cannot prove official
freshness. Their provider owners must supply current official documentation or
OpenAPI and review full definitions. The Cloudsway Full Search source is a
dated supplier article and requires current owner evidence. The pinned Twitter
delete source is the owning service's fixed Python route/schema code; its AST
converter reads declarations without importing or executing that service.

Official acquisition is already available through `scripts/import_upstream.py`.
Write its candidate only into a fresh temporary root, never the formal checkout:

```bash
python scripts/import_upstream.py \
  --root /private/tmp/aisa-source-review-agentmail \
  --provider agentmail-official \
  --url https://docs.agentmail.to/openapi.json --write
```

This performs unauthenticated HTTPS documentation reads. It invokes no provider
business endpoint, uses no paid/model translation and creates no formal review
receipt. `fetched_at` records actual acquisition, while importer policy fields
remain proposals. A candidate write to that isolated temporary directory is
not publication or approval. Fetch failure, changed/removed definitions or a
converter rejection remains a blocked review, with last-good formal input intact.

Compare candidate source bytes and semantic request/response changes using
`upstream_semantics.compare_contracts`; evaluate retained removals separately.
Owner review must bind the exact source hash, verified authority, maintenance
policy revision and official evidence. Manual/pinned sources require the real
named reviewer, immutable review ref and actual confirmed review time. Never
manufacture receipts from a local reread, proposed policy or manual timestamp.
Independent debt review must approve the exact declaration-bound gap set, not
merely its count. Recompute all gaps from current complete Runtime facts before
selecting a real Git coverage baseline.

Before publication, run the formal candidate gate with actual Runtime evidence,
genuine source receipts and the independently selected baseline. Retain the
producer's exact publication commit, aggregate hash and closed file graph.
Only a subsequent separate publication/consumer activation acceptance can prove
the normal and lost-dispatch timing budgets. Code CI and draft acquisition do
not advance that state.

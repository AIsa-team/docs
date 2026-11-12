# Tool summary and description quality

The 2026-11-12 baseline is Docs commit
`5ebac5c42f5c9d5bb1a725f6c1e7376c39e829d0`: 6,456 unique operations in 556
provider files. This is a published-file inventory, not proof of live Router availability.

Run the read-only inventory for every provider (the aggregate is excluded):

```sh
python3 scripts/audit_tool_prose.py --output /tmp/tool-prose-audit
```

The CSV preserves every operation's original prose, public identity and source
file hash. It flags 3,563 descriptions containing no nonpricing prose and 957
machine-style summaries at this baseline. Its 522 Purpose-derived title
candidates are drafts, not reviewed or applied changes. Missing Runtime bindings
are not evidence that a contract is a hand-maintained static input.

## First reviewed batch

`tool-prose-changes-20261112.json` records four static-input amendments:
AccuWeather location autocomplete, API Ninjas sentiment analysis, Crawl4AI
ChatGPT answers and SerpApi Amazon product pages. Wording comes from existing
published input constraints and descriptions. No output fields, authentication
requirements or capabilities were invented from operation IDs.

Only operation summary/description and amendment provenance change. Original
source metadata is retained as `prior_source`; acquisition dates and source
review receipts are not refreshed. The Composio importer now preserves captured
tool descriptions, including when a subsequent source acquisition rebuilds the
mirror. Runtime descriptions continue to take precedence over mirror text.

Canonical Docs publication projects Runtime's verified native contracts. These
static inputs therefore need the normal reviewed schema bundle and Runtime
contract publication before customer pages change. This PR does not rewrite
published JSON, create review receipts, or claim that publication has happened.
The AIsaServices companion adds guarded generated prose for seven operations;
its nonblank descriptions match this batch where they overlap.

## Remaining work and validation

This batch is not completion of the 6,456-tool semantic review. Continue through
all providers, prioritizing empty descriptions. Resolve raw Runtime values
before selecting the edit location; a generated description can be a mirror
fallback even though its summary is Runtime-owned. Keep adequate prose unchanged.
API-Sports AFL games is deferred because its season/league requirements need
clarification. Social/Commerce have a separate existing description PR.

For each batch, compare source identities and all non-prose contract fields,
run import/composition tests, and verify that re-generation retains the wording.
Only after publication should the same search evaluation queries be replayed;
these checks alone do not demonstrate a ranking improvement.

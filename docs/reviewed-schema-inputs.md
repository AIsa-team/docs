# Reviewed Git schema inputs (bundle v3)

This is a non-formal build input path for the existing Composer. It does not
activate a worker lock, approve a source policy, publish a contract, or renew a
review/authorization clock. Existing v1/v2 inputs without an input context keep
their original formal-origin and artifact checks.

A schema change must not require a new formal publication made using that same
schema before the worker can build it. The order is:

1. Review actual schema, registry and policy changes through the existing source
   process. Commit the original complete receipt packet and the context below.
2. Export a v3 candidate from the **merged** immutable input Git commit R. The
   existing source-only CI checks current source authorization and runs the same
   Composer against a fresh acquired Runtime snapshot. This is not formal output.
3. Independently review R, the exact bundle manifest digest and the existing
   Composer code/source-manifest digests in the Services build lock.
4. The existing worker build reconstructs the input from Git, verifies that
   reviewed digest, compiles through the same Composer, and follows normal deploy.
5. The normal Docs publisher consumes the new canonical Runtime bytes and still
   runs actual formal assessment, current source authorization, export/replay,
   origin, previous-publication lineage, main CAS and consumer notices.

No production input context/receipt or worker lock is added by this code change.
A first real snapshot/promotion is a separate reviewed change.

## Two Git evidence files

`docs/schema-inputs/source-receipts.json` is the original complete existing
`schema_version: 1` packet containing `receipts` and `attempts`. A summary or
freshly invented review time is not a substitute. The fixed path is intentional.

`docs/schema-inputs/context.json` has exactly:

```json
{
  "schema_version": 1,
  "kind": "aisa-reviewed-schema-input-context",
  "historical_formal_ref": "<full earlier formal Git SHA F>",
  "source_receipts_path": "docs/schema-inputs/source-receipts.json",
  "source_receipts_sha256": "<original packet SHA-256>",
  "source_checked_at": "<original input source assessment time>"
}
```

The context does not name its own containing commit. R is supplied externally,
so a squash merge cannot leave a pre-merge PR SHA inside the recipe. These files
are reconstruction inputs, not an approval certificate. Only the independently
reviewed Services lock authorizes the input ref and resulting bundle digest.

Schema/registry/policy authority comes from R. Historical native documents,
page bindings, gaps and alias proofs come from explicit F. The independently
reviewed baseline stays code-pinned. New schemas are not required to match F's
old formal file hashes. Historical native/proof bytes still must match exactly.
Unsupported overlays, unknown roles, unsafe paths, dangling references, baseline
changes and file/byte limits remain rejected.

```sh
python scripts/export_schema_input_bundle.py --repo . --docs-ref "$R" \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --bundle-version 3 --output /tmp/reviewed-input-bundle
```

There is no `--source-receipts` override in v3. Export twice to new directories
and compare the manifest/member bytes. Offline reconstruction preserves original
receipt bytes and original assessment time; it returns current source freshness
as `not_assessed`. It never calls an old Actions run or artifact.

## Source-only CI and publication boundaries

The existing `artifact-contracts` job selects the input-candidate check only if
its fixed Git diff includes a changed context and consists exclusively of that
context/receipt, registry, upstream JSON and the two existing policy paths. At
least one actual authority input must change. A registry-only change may reuse
an unchanged still-valid original receipt. A real schema/policy review cannot be
replaced by changing an assessment time.

The input gate independently repeats this classification, validates the actual
recipe/packet, authenticates F as the real prior formal context, checks real
current source authorization and runs the single Composer. Mixing code, native
JSON, pages, publication current/origin or other files uses the original actual
candidate gate. An input candidate never emits a formal current or origin.

Canonical input assessment version 2 uses explicit `source_input_provenance`
with kind `reviewed_git_input`; it cannot claim `source_formal_provenance`.
The original input-context/receipt hashes bind both frozen and current input
maps at the two Git paths above. Current `.cache/source-reviews.json` has its own
hash and current observations. Historical input receipts cannot renew it.

Compatible Website/MCP/Router validators and the pinned MPP verifier must be
merged before activating a v3 worker lock. Version 1 formal input reports remain
valid. A Git ref containing a v3 context is deliberately rejected by the v2
exporter. For a fully assessed version 2 input report, the publisher omits only
the obsolete per-formal v2 artifact supply; all real formal publication gates
remain. Other modes still require successful v2 export/upload before push.

## Remaining retention limit

Git reconstruction removes the fixed v3 input's dependency on a 90-day Actions
bundle artifact. It does not make every historical formal origin permanent:
`schema_input_view_files` still authenticates the prior formal run/readiness
artifact, and monitor selection authenticates the first same-contract origin.
A missing old artifact can still block those paths. No unsigned API snapshot or
tar mirror is accepted in their place. Durable standard provenance archival is a
separate follow-up, not implemented here.

## Validation

```sh
python -m unittest scripts.tests.test_reviewed_schema_inputs \
  scripts.tests.test_schema_input_bundle scripts.tests.test_canonical_input_assessment \
  scripts.tests.test_canonical_import scripts.tests.test_canonical_formal \
  scripts.tests.test_schema_bundle_supply scripts.tests.test_runtime_publication \
  scripts.tests.test_contract_change_scope
```

Fixtures use real temporary Git commits and the actual exporter/loader/Composer,
with external Runtime/formal-authentication boundaries explicitly mocked. They
are not evidence of a production price change, new approval, formal release,
automatic deployment or a real lost-notification recovery.

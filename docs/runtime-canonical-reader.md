# Runtime canonical artifact reader compatibility

This change only prepares the existing Docs Runtime reader to validate and save
an explicitly versioned canonical graph in the same immutable artifact as its
facts. It does not enable production artifact construction, publication, or
consumer selection. Old fact-only artifacts retain the same acquisition,
receipt, file layout, and stage inputs.

## File protocol

The outer Runtime manifest and revision hash encoding are unchanged. Its exact
sorted file list binds every original byte. Media types remain
`application/json`; the total limit stays 64 MiB and the count stays 512.

| File | Limit | Meaning |
| --- | --- | --- |
| `index.json`, `providers/<provider>.json` | 8 MiB each | Original closed Runtime facts graph |
| `contracts/native/<provider>.json` | 8 MiB each | Complete canonical native documents |
| `contracts/openapi.json` | 32 MiB | Complete aggregate, the only larger-file exception |
| `contracts/readiness.json` | 1 MiB | Passed compilation report, not new source authorization |
| `contracts/manifest.json` | 1 MiB | Exact canonical graph and build/source binding |

If any `contracts/` member exists, all three singleton files and at least one
native file are mandatory. Unknown roles, unsupported versions, duplicate or
unsafe names, partial graphs, invalid original hashes, and oversized members
fail closed. The HTTP read exception applies only to the exact immutable
release aggregate URL, not arbitrary matching suffixes or provider files.

The canonical manifest has exactly these fields:

```json
{
  "protocol_version": "aisa-runtime-canonical-v1",
  "generation": 864,
  "source_digest": "<64 hex>",
  "compiler_revision": "<40 hex Services revision>",
  "bundle_manifest_sha256": "<64 hex>",
  "docs_ref": "<40 hex>",
  "composer_revision": "<40 hex>",
  "source_manifest_sha256": "<64 hex Composer source file manifest>",
  "files": [
    {"path": "contracts/native/example.json", "bytes": 123, "sha256": "<64 hex>"},
    {"path": "contracts/openapi.json", "bytes": 456, "sha256": "<64 hex>"},
    {"path": "contracts/readiness.json", "bytes": 789, "sha256": "<64 hex>"}
  ]
}
```

`files` is sorted, complete, and excludes the canonical manifest itself, which
is bound by the outer manifest. It uses full paths and no duplicate role or
endpoint inventory. Generation is uint64, not boolean. Generation, Services
compiler, and source digest must equal the acquired outer current identity;
all remaining pins require their complete lowercase hexadecimal representation.

## Validation and authority

The existing fresh current-before/current-after, exact manifest revision,
body hash, ETag, no-redirect, and stable live-category checks remain. The facts
validator still requires the exact index/provider closure and no pending facts.
Canonical files have strict duplicate-key and finite/precision-preserving JSON
checks, local context-aware reference closure, unique canonical IDs across
native documents, and the same operation-ID set in native and aggregate graphs.
The native comparison reuses the existing `remove_v2_path_mirrors` rule; the
aggregate must already have removed those mirrors. Business example/default
values are not mistaken for schema references.

Path Item reference chains are resolved with the existing Composer resolver
before enumerating IDs, including escaped JSON pointers; unresolved or cyclic
public-object references fail closed. Root and effective public-operation
security requirements resolve named schemes through the same authentication
helper used by the existing MDX renderer. Enabled operations and ordinary
disabled operations cannot reference a missing scheme.

The renderer already preserves one precise historical exception: an operation
with both `x-aisa-status: disabled` and
`x-aisa-contract-state: retained_legacy` may retain a missing security-scheme
name. This reader reuses that rule; it does not invent a Bearer definition or
change the fixed historical bundle. Such findings are reported explicitly in
`canonical_validation.historical_security_debt` in the acquisition receipt and
public shadow binding, with provider, path, method, operation ID, scheme and
document. `security_status` is `historical_debt`, not `passed`. The fixed corpus
has three Agentmail historical operations with an unresolved `Bearer` name,
appearing in both native and aggregate documents (six declaration findings).
Receipt replay recomputes this result. Fact-only receipts gain no such field.

This reader verifies graph integrity and operation identities. It does **not**
recompile aggregate transformations or claim complete native/aggregate field
equivalence. The producer must validate that they came from the same compile.
It also cannot prove that the manifest's self-described bundle or Composer is
approved by a deployment. A consuming policy must match independently expected
build/bundle pins. The future API producer must bind that identity into its
source digest before producing the artifact. Neither production change is
implemented here.

Readiness must report a passed compile with no global errors, missing inputs,
or blocked providers. A historical compiler report does not renew source review
TTL, create a new observation clock, or authorize publication. Existing source
policy checks remain the responsibility of the formal consuming gate.

All original immutable files are saved. Canonical files stay under `contracts/`;
only original provider facts get the existing flat CLI aliases. The offline
public shadow loader validates the entire artifact before returning only the
original index/provider facts and category to stage. It never flattens canonical
native filenames over facts. The private PublicationSnapshot adapter remains
facts-only.

## Compatibility and rollout

No workflow changes are included. Merge reader compatibility before an API
starts serving new canonical artifacts. Existing Docs main-based acquisition
workflows then have the compatible reader; any tool pinned to an older code
revision must be upgraded separately before it reads the new graph. Old readers
intentionally reject it rather than silently ignoring canonical members.

The current Services MPP delivery workflow checks out Docs history at main but
its verifier code is pinned independently to
`5b6736dc4c9d27712e763146252ff62f1f6369c3` in both
`.github/workflows/sync-payment-discovery.yml` and
`scripts/payment-discovery/docs-verifier.lock.json`. `prepare.py` runs that
verifier and reads MPP bytes from the selected authenticated formal commit;
it does not run `fetch_runtime_release.py`. A new Docs formal commit does not
update this fixed verifier. A future MPP verifier change needs its own reviewed
pin update. Docs formal publication and consumer transitions remain separate
from this reader-only PR.

## Validation

```sh
PYTHONPATH=scripts/tests python -m unittest \
  scripts.tests.test_runtime_contract_artifact \
  scripts.tests.test_fetch_runtime_release \
  scripts.tests.test_shadow_compile_bundle
```

Negative tests cover wrong roles and versions, missing/extra/duplicate members,
wrong identity/digest/byte length, operation identity mismatches, native identity
overlap, mirror scope, unresolved references, unsafe paths, non-finite or
unsupported numbers, failed readiness, role-specific and total size limits.
An intentional different-summary fixture passes, documenting that identity
closure is not field equivalence. Existing acquisition tests retain moving
current/category, stale metadata, hash, ETag, and legacy format coverage.

A separate offline fixture wrapped the actual R864 facts and fixed full 6fb
compile in a synthetic future outer manifest: 133 immutable files, 74 native
documents, 2,007 aggregate operations, and 40,486,518 member bytes. Acquisition
and save preserved every byte; the shadow stage received only 57 facts/category
files. Network and subprocess were forbidden. This is not a genuine production
publication, current build approval, or source authorization.

After the independent authentication/Path Item review fixes, the same 133-file
fixture still preserved all original artifact bytes and the same outer revision;
it explicitly reported the three disabled Agentmail operations above. Extracting
the shared authentication helper left all 4,014 English/Chinese request blocks
byte-for-byte unchanged. Missing auth on enabled/ordinary-disabled operations,
forged freeform limitation text, and different IDs hidden in Path Item references
are negative regressions, not silently accepted forms.

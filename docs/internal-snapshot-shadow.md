# Internal PublicationSnapshot offline shadow

The public historical-acquisition CLI and the internal snapshot CLI now call
one `compile_verified_inputs` implementation. That core uses the existing
Composer, page-link projection, and aggregate consolidator. Public input
verification and its default manifest/output bytes are unchanged.

The internal adapter removes a circular dependency for future pending-generation
compilation: it accepts projected Runtime facts without requiring a publication
of those facts to already exist. It does not fetch `current`, require a public
acquisition receipt, or fabricate either one. This change is an offline shadow
component; no worker, production workflow, image, or current pointer is changed.

## Private transport and trust boundary

`snapshot.json` is the metadata of Go `apicontract.PublicationSnapshot` with
each `json.RawMessage Content` externalized into a separate original-byte file:

```json
{
  "schema_version": "1",
  "generation": 864,
  "source_digest": "<64 lowercase hex characters>",
  "compiler_revision": "<40 lowercase hex characters>",
  "files": [
    {"name": "index.json", "media_type": "application/json", "sha256": "<original content hash>"},
    {"name": "providers/example.json", "media_type": "application/json", "sha256": "<original content hash>"}
  ]
}
```

The directory contains exactly this envelope and its listed files. File names
must be sorted and unique. The adapter checks the caller's independently trusted
envelope SHA-256, generation, source digest, and API compiler revision. It checks
strict JSON (including duplicate keys), original member hashes, the closed
index/provider graph, no pending projections, and the existing 512-file,
8 MiB-per-file, 64 MiB-total facts limits. Metadata is limited separately to
1 MiB. Generations are uint64; booleans are not integers. Unexpected files,
paths, symlinks, and non-regular files are rejected. The supported provider
namespace matches the existing Docs loader (lowercase IDs, bounded to 120
characters); otherwise valid Go inputs outside that subset fail closed.

The metadata is a **private transport envelope, not a Go-validation receipt**.
Python checks transport integrity and reuses the existing public-loader graph
validation; it does not duplicate Go's full projected-field allowlist or
Go-specific facts-hash serialization. An arbitrary caller-made envelope cannot
prove that `ValidatePublicationSnapshot` ran. A future trusted Go materializer
must call the existing validator *inside its own export function*, before
writing any transport, and must deliver the expected pins through the trusted
worker boundary. This PR does not implement that production materializer.

Do not JSON-decode and re-encode `Content` to export it: float formatting and
Go HTML escaping can change the byte hash. Only the original raw bytes are
written and checked. After verification, all Composer inputs come from retained
verified bytes in a private temporary directory; source paths are not reread.

For discovery only, `category.json` is derived as
`{"apis":[{"id":"<id from the verified index>"}]}`. The Composer already
discovers index providers after category discovery. No marketing metadata,
endpoint inventory, price, or permission is inferred. No unversioned marketing
API request is needed.

## CLI and output

```sh
python scripts/internal_publication_snapshot.py \
  --bundle /inputs/reviewed-schema-bundle \
  --bundle-sha256 <independently-trusted-bundle-manifest-sha256> \
  --docs-ref <full-frozen-docs-sha> \
  --snapshot /inputs/private-publication-snapshot \
  --snapshot-sha256 <independently-trusted-envelope-sha256> \
  --generation <expected-uint64> \
  --source-digest <expected-source-sha256> \
  --compiler-revision <expected-api-build-sha> \
  --output /artifacts/new-shadow-directory
```

The Python `compile_snapshot` API performs the same checks. Its internal
`compile_verified_inputs` function assumes verified inputs and is not an
authentication boundary. The public `compile_shadow` API still requires the
original public acquisition and all its independent pins.

The shared core retains its atomic new-output-directory behavior and readiness
checks. A v2 schema bundle produces `native/*.json`, `aggregate/openapi.json`,
and `readiness.json`. The internal manifest has schema version 2 and kind
`aisa-internal-snapshot-shadow-contract-graph`; a v1 bundle has schema version 1
and kind `aisa-internal-snapshot-shadow-native-graph`, with its existing
aggregate gap. Both use the explicit scope
`existing_composer_offline_shadow_only_not_formal_publication`.

The internal `runtime` binding records the envelope digest, original generation,
source digest, compiler revision, discovery source, and validation limitations.
It contains no artifact revision, acquisition receipt, new observation clock,
or claim of current freshness. Existing source receipts are replayed at their
original historical clock; this does not approve a pending generation's current
source governance or renew review TTL. The shared `readiness.json` is that
historical offline readiness result, not a production authorization.

Identical original-byte inputs produce identical shadow outputs. The diagnostic
manifest intentionally binds the exact envelope bytes, so even whitespace in
that envelope changes its shadow identity. A future Go materializer should use
one fixed encoding and sorted files. This is not a decision to use transport
whitespace or acquisition timestamps as future formal publication identity.

## Validation and remaining work

```sh
python -m unittest discover -s scripts/tests -p test_internal_publication_snapshot.py
python -m unittest discover -s scripts/tests -p test_shadow_compile_bundle.py
python -m unittest discover -s scripts/tests -p test_fetch_runtime_release.py
```

Tests cover independent pins, uint64/boolean separation, original escaped and
numeric byte preservation, duplicate JSON keys, closed and incomplete graphs,
hash tampering, exact file membership, path and symlink/FIFO rejection, all
resource limits, no network/subprocess acquisition, and explicit reuse of the
one core. Synthetic unit fixtures test transport rules and do not claim Go
validation. The complete corpus validation separately uses a real R864 snapshot
that was passed through Go `ValidatePublicationSnapshot` before export.

The fixed v2 6fb bundle has digest
`17590e3c917bce9467d250e5abfb006bf828f62ad0d3e96d6e33929c89a65c31`.
Its R864 private transport contains 56 original files and envelope digest
`c3f2a3dd8b4395911025cb96ee48f850bd2a8b8871c72addbbbac2aeec0d73bc`.
Independent review confirmed all 56 original Content files equal the public
acquisition bytes and that the fixture exporter called Go validation before
writing. Network/subprocess-forbidden complete replay produced:

- Public mode: all 77 output files unchanged from the previous implementation,
  including manifest
  `8ce3b3c1a5188dd65a6f41a889d6619203d974787fa3e1a6648829044f8efdca`.
- Internal mode: all 74 native documents, all 2,007 aggregate operations, and
  readiness bytes equal public mode. Only manifest kind/runtime differ.
- Two internal runs: all 77 output files byte-identical, manifest
  `a80694721776dbf43d26fe3154ce0ce2732c2ba0aa8ac61998d6c55f13db02a9`.

No request/response schema, price, HTTP method, link, alias, or derived hash
was excluded from the comparison. The public category originally listed 52 IDs;
deriving discovery from all 55 verified index providers preserved complete
output. This is fixed-input offline equivalence, not a production freshness
or pending-generation authorization proof.

Production source governance, trusted materialization, compiler/build and bundle
identity, rollout fencing, publication authority and consumer output protocol
upgrades remain separate work. No public receipt verifier or production
consumer is instructed to accept this private shadow kind.

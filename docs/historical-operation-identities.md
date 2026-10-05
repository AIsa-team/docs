# Published locale operation identity compatibility

This is a derived compatibility protocol, not approval of source definitions,
debt exceptions, unpublished identities, execution permissions or publication.
The runtime/DB canonical ID and current route remain authoritative. No additional
wire operation, endpoint or executable tool is created for an alias.

## Operation metadata

Root provider JSON and the aggregate retain the canonical `operationId`.
Operations with an already-published different Chinese ID additionally carry:

```json
{
  "x-aisa-identity": {
    "schema_version": 1,
    "canonical_operation_id": "get_edinet_documents",
    "historical_aliases": [{
      "operation_id": "getEdinetDocuments",
      "locale": "zh",
      "published_ref": "cf10c7c23c44b2a7666f2d1946cad106a42e326d",
      "source_file": "openapi/zh/edinet.json",
      "source_sha256": "41707f0811e00ce951315621989decb027259048c3a7a331c9d3f035586baa14",
      "canonical_source_file": "openapi/edinet.json",
      "canonical_source_sha256": "288bc100a3e41d50606fa122d6f2a5d6ab2a71b7d4de8b3cb4eea7dbb940dac4",
      "public_path": "/apis/v1/edinet/documents.json",
      "method": "GET"
    }],
    "sha256": "sha256:<digest of the other three metadata fields>"
  }
}
```

Chinese provider JSON retains **`operationId: getEdinetDocuments`**, with the same
`x-aisa-identity` metadata. Chinese page frontmatter stores that actual machine
ID. A vanilla SDK generator reading Chinese JSON therefore still receives its
published operation ID. Canonical association is explicit, rather than relying
on SDKs recognizing a vendor extension while silently renaming the real ID.
Paths/methods and all public request/response/auth/pricing declarations must be
identical to the canonical operation after normalizing only this proved ID and
allowed prose translations. Historical path/method in the proof is provenance;
it never overrides current runtime routing if the endpoint subsequently moves.
Existing page URLs remain bound to the current operation.

## Proof and collision rules

Metadata and each proof have closed shapes; unknown/missing fields fail. IDs use
`[A-Za-z0-9_.-]{1,255}`; refs are full40hex Git SHAs; file hashes are full64hex
SHA-256. Proof files are exactly root/Chinese `openapi/*.json` paths, without
traversal. Locale is currently only `zh`. A proof must read the exact two Git
blobs, match their byte hashes, find the same historical absolute public path
and HTTP method in both, and prove both the canonical and historical IDs. Its
Git revision must be reachable from the independently fixed publication base.
A hash-shaped string or local working-tree reread is not a publication proof.

An alias cannot equal any current canonical ID, belong to multiple canonicals,
or invent a new ID absent from the Chinese proof. Multiple different historical
ZH IDs for one canonical require an explicit further disposition and currently
fail. A known published alias cannot be removed from a generated operation.
Changed source hashes, refs, ownership, IDs or wire declarations fail strict
validation. Source approval remains a separate formal gate.

## Digest and publication binding

The `sha256` field is `sha256:` plus SHA-256 of UTF-8 canonical JSON for exactly
`schema_version`, `canonical_operation_id`, `historical_aliases`: recursively
sort object keys, preserve array order, use compact `,`/`:` separators, emit
Unicode directly, and add no whitespace/newline. Metadata has integer/string
values only. `scripts/identity_compatibility.py:metadata` is the reference helper;
`scripts/tests/fixtures/published-locale-identities.json` supplies all27 real
pinned historical proofs and expected metadata digests.

Provider `info.x-aisa-document.identity_compatibility_hash` hashes the canonical
ID -> metadata object. It is included in `document_hash`; observation times
are absent. The original proof is retained across releases so Git SHA changes
alone do not churn identity metadata. Aggregate OpenAPI retains operation-level
metadata unchanged. Existing formal publication `files_sha256` binds root and
Chinese JSON, pages/navigation, aggregate and source graph; source locks still
require the exact Docs commit, aggregate content hash and genuine producer
receipt. Aliases cannot weaken those checks.

## Consumer resolution

Validate the closed metadata shape, its digest, canonical ID match and global
canonical/alias namespace when reading the **verified canonical root/aggregate**.
The formal Docs producer has already verified the historical Git blobs; the
consumer verifies that exact receipt-bound file graph, not a newly supplied
untrusted alias file. Build an alias -> canonical **details-only** index.
Return both requested historical identity and canonical identity in details
when useful. Keep search/tools/use/authorization/pricing tied to canonical
operations and existing execution rules. Never create a second executable tool
for a historical alias or map an alias to an arbitrary path.

## Generation and validation

`pull_openapi.stage` reads immutable history from the fixed published base;
formal candidate evaluation supplies `--published-ref`. Standalone Chinese
regeneration/validation accepts an explicit full immutable base:

```bash
python scripts/runtime_localize_openapi_zh.py generate --published-ref <published-sha>
python scripts/runtime_localize_openapi_zh.py validate --published-ref <published-sha>
```

These commands operate only when explicitly run by the operator. This code
change does not regenerate or approve tracked production source assets. The
27-row fixture is previously published identity evidence, not authorization for
the pending production identity UPDATE.

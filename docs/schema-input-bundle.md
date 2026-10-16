# Schema input bundle, version 1

This is the first W4 migration component: a language-neutral package of existing
reviewed schema inputs and historical compatibility evidence. It does not add a
compiler, change Runtime ownership, publish a contract, or switch any consumer.
The production Composer and all current publication gates remain in place.

## Export and validate

Run with the existing Docs Python dependencies and a repository containing the
full frozen commit and alias history. Neither command accesses the network.

```sh
python scripts/export_schema_input_bundle.py \
  --repo . \
  --docs-ref 6fbf9940d876920d7bae05de2e9df5b2f4c0a139 \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --source-receipts /trusted/original-source-reviews.json \
  --output /artifacts/schema-inputs

python scripts/schema_input_bundle.py /artifacts/schema-inputs \
  --manifest-sha256 <independently-pinned-manifest-sha256> \
  --docs-ref 6fbf9940d876920d7bae05de2e9df5b2f4c0a139 \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c

python -m unittest scripts.tests.test_schema_input_bundle
```

The export destination must be new. All source bytes come from Git objects at
the exact commit, except the explicitly supplied original receipt packet.
Uncommitted working files are not inputs. The receipt packet is the real
`source-reviews.json` cache containing `schema_version`, `receipts`, and
`attempts`; a report summary cannot substitute for it. Missing or incompatible
receipts fail the complete historical governance replay. No receipt, review
clock, upstream fetch, or approval is created by exporting.

The printed manifest digest is an export result, not an authentication token.
A consumer must obtain the digest and Docs SHA through an independently trusted
release/review channel and run reviewed verifier code. Copying a digest from an
untrusted package provides no authentication.

## Package and authority

`manifest.json` has exact fields `schema_version: 1`,
`kind: aisa-schema-input-bundle`, `docs_ref`, `baseline_ref`, `authority`, and
sorted `files`. Each file has `path`, `role`, SHA-256, and byte count. Unknown
roles, duplicate keys/members, extra or missing files, symlinks, path escapes,
non-finite JSON numbers, and unsupported registry inputs are rejected. Bounds
are 512 files, 32 MiB per file, and 192 MiB total. Parsing uses the bytes already
checked against the manifest; path-based governance helpers receive a private
copy of those same verified bytes.

| Path | Role and use |
| --- | --- |
| `input/openapi/registry.yaml` | Existing source ownership and mappings |
| `input/openapi/upstream/*.json` | Original normalized upstream schema bytes, including source metadata |
| `input/openapi/*.json` | Historical canonical compatibility documents and separate coverage/pending inventories |
| `input/openapi/policies/...` and `input/docs/deferred-age-response-rebinding-20261012.json` | Existing approved deferral policy and its binding |
| `input/docs/publication/current.json` and `formal-contract-readiness.json` | Historical formal identity, input hashes, and original governance assessment |
| `baseline/openapi/coverage.json` | Independent reviewed debt baseline, never supplied by the candidate |
| `identity/aliases.json` and `proofs/<original-ref>/openapi/...` | Canonical namespace, historical aliases, and original Git proof bytes |
| `evidence/source-receipts.json` | Unchanged real source receipt packet |
| `evidence/git-validation.json` | Exporter's Git checks, explicitly not independently authenticated offline ancestry |

Original documents intentionally retain historical prices, status, capability,
and application properties named `price` or `status`. Recursive stripping would
corrupt legitimate schemas and invalidate original proof hashes. The manifest
explicitly declares these historical values **not current Runtime authority**.
A future compiler must combine these inputs with a separately authenticated
Runtime snapshot; it must not use this bundle as a source of current prices,
admission, payment capability, or freshness. Full aggregated output, pages,
payment evidence, and Runtime facts are not supplied as new production authority.

Version 1 explicitly rejects provider `pin`/`pins`/`overlay`/`overlays` registry
fields and any Git tree member under `openapi/overlays/`. The frozen corpus has
none. Supporting them requires an explicit format/validation change; they must
not silently disappear from a supposedly complete input package.

## Trust, identity, and clocks

The independent baseline is exactly
`78ef376841ead8cde10a79651958790be5a0531c`, coverage SHA-256
`e0ef2fdf591d0f6b400d6bf1107bf32a31cc1a3453784dc3962cb66a15d16dbd`.
It is a separately approved candidate commit, **not an ancestor of the published
Docs commit**. Its authority comes from the controlled repository
`RUNTIME_CONTRACT_BASELINE_REF` setting and trusted review/build process, not
from a candidate's self-written assessment. The exporter reads this exact Git
blob; the verifier pins both ref and bytes, and checks that the historical
formal assessment used that same baseline. This does not approve new debt.

Every alias proof retains its original commit, source and canonical file hashes,
public path, HTTP method, locale, and operation IDs. The exporter verifies that
each proof commit is an ancestor of the fixed Docs commit. The offline verifier
checks all included bytes and identities, namespace collisions, and missing or
orphan proof files. It cannot independently establish Git ancestry or reviewer
authenticity without external trusted Git/release evidence. The bundled
attestation states this limit explicitly.

The full source governance report is recomputed at its original `checked_at`
from unchanged schemas and real receipts/attempts, and must match with JSON
types preserved. Export time is not a review time. Validation reports
`current_source_freshness: not_assessed`; a historical passing replay neither
extends TTLs nor authorizes a new publication. A future compiler must retain the
existing current-time review/expiry rules. Identical inputs produce identical
manifest and member bytes: there is no export timestamp, local absolute path,
or new receipt inside the package.

## Recorded validation and next boundary

Two complete exports of the fixed 6fb corpus produced identical 206-member
packages (60,287,272 member bytes), covering 111 upstream sources, 45 registry
providers, 2,007 historical canonical operations, and 27 alias proofs. Digest:
`c8f2ceda7de703795d9577df5355cff74d1d11c1cf644a13d55337e621de941b`.
The original governance clock is `2026-10-15T18:14:38.124664+00:00`.
These are measured fixture results, not hard-coded expected counts.

Tests cover independent pins, raw-byte tampering, duplicate keys/members,
namespace/role/path violations, symlinks, missing inputs, original alias
ref/hash/method/identity mismatch, conflicting aliases, verified-byte reuse,
and preservation of instance `$ref` values while rejecting external schema
references. Full-corpus export additionally exercises the existing reference
closure, identity, deferral, and source-governance checks.

Independent review repeated the complete verifier and rejected 11 modified
package variants even after recomputing their envelope hashes, including forged
receipt clocks, wrong alias IDs, altered baseline bytes, and dangling schema
references. This verifies structural/historical checks beyond checksum failure.

Separately, the **existing** Python Composer was replayed twice offline against
fixed 6fb and Runtime generation 864: 56 Runtime manifest members matched, all
111 original source observations were retained, all 74 native root documents
matched, and repeated staged bytes were identical. Full runs including pages
took 87.117 and 88.453 seconds, with process peak RSS about 731 and 796 MiB.
An isolated synthetic Ahrefs price change from 0.08 to 0.08123 then propagated
through both languages while preserving all other native schema fields and all
111 upstream source files. This is an oracle and price-separation check for the
existing implementation, **not** a new compiler equivalence test, production
price change, or measurement of a future worker. The synthetic facts were never
published or represented as an authenticated Runtime snapshot.

The next decision is how to execute the single authoritative compiler within
the Runtime publishing boundary. Reusing the existing Python Composer in a
restricted offline worker invocation and a Go migration both require measured
cost/compatibility evaluation. This format does not choose an implementation
language or introduce a second producer. Output-size roles, compiler identity,
mixed-worker rollout fencing, current-time source governance, and consumer
cutover remain separate reviewed work.

## Reviewed input promotion

[Bundle v3](reviewed-schema-inputs.md) separates a reviewed fixed Git schema
input from its historical formal compatibility context. It preserves the
existing v1/v2 path; a context-bearing ref must use explicit v3 rather than
being exported as a formal v2 input. No production input or worker lock is
activated by this support code.

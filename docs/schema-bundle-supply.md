# Schema input bundle CI supply

The existing Docs publisher retains a version 2 schema input bundle for each new
formal commit. This is a build input for the single Composer, not a new publisher,
Runtime price authority, source approval, or proof of current freshness. Worker
production integration and a reviewed worker input lock are separate changes.

## Publication ordering and failure behavior

`pull-openapi.yml` uses its existing full Git checkout and the exact
`.cache/source-reviews.json` used by that run:

1. The existing `Commit contract mirrors and coverage` step records the original
   publication origin and creates a local commit. Its name and budget clock stay
   unchanged. It now outputs a candidate SHA, not a published SHA.
2. `schema_bundle_supply.py build` exports version 2 from that exact local commit
   and original source receipts, verifies the entire bundle, and creates a stable
   archive. The commit must have the assessed base as its sole parent and bind
   the same producer attempt, formal pointer, and contract release.
3. `actions/upload-artifact@v4` retains the two-file packet as
   `schema-input-bundle-v2-RUN_ID-RUN_ATTEMPT`. Missing files or upload failure fail
   the job; there is no overwrite or error bypass.
4. The final push step verifies that local HEAD is still the same commit and that
   remote main is still the assessed base. It never rebases the assessed graph.
   Only a successful push emits `docs_commit` for the existing consumer notices.

Export, validation, upload, or concurrent-main failure leaves the last published
commit unchanged and prevents notifications. An uploaded candidate whose push
failed is not a formal publication. The unchanged `publication_origin` verifier
requires both a successful compose job and actual main ancestry; tests exercise
failed-push and unpushed-candidate rejection. A successful local commit step alone
has never been sufficient evidence. Origin still attributes the original named
step; the later successful compose job now also proves supply and push completed.

A no-op run retains the existing publication clock and emits no new supply. A
previous publication cannot be reconstructed using a later receipt cache: bundle
validation replays the exact formal report's original `checked_at`. No receipt or
review timestamp is regenerated for transport.

## Packet and external pins

The artifact contains only `supply.json` and `bundle.tar.gz`. The envelope is:

```json
{
  "schema_version": 1,
  "kind": "aisa-schema-bundle-supply-candidate",
  "scope": "verified_build_input_not_publication_or_current_source_authorization",
  "bundle": {
    "schema_version": 2,
    "manifest_sha256": "<independently reviewed SHA-256>",
    "docs_ref": "<full Docs commit>",
    "baseline_ref": "78ef376841ead8cde10a79651958790be5a0531c",
    "source_receipts_sha256": "<original receipt SHA-256>",
    "source_checked_at": "<original formal assessment time>",
    "archive": {"path": "bundle.tar.gz", "sha256": "<SHA-256>", "bytes": 123}
  },
  "producer": {
    "repository": "AIsa-team/docs",
    "workflow": ".github/workflows/pull-openapi.yml",
    "run_id": "<numeric run ID>",
    "run_attempt": 1,
    "assessed_base": "<full parent SHA>",
    "origin_sha256": "<original release-origin.json SHA-256>"
  }
}
```

A consumer must obtain its expected bundle/archive hashes, Docs ref, and producer
attempt from an independently reviewed lock. Reading these values from the
candidate itself does not establish trust. The upload's artifact ID is available
from GitHub after upload, so it is not invented inside this pre-upload packet.

The next build consumer must authenticate the actual GitHub run, jobs, artifacts,
formal report, and main ancestry, using pinned reviewed verifier code. In a full
trusted Docs checkout whose HEAD is fetched main, the existing
`publication_origin.inspect_publication(root, docs_ref, historical=True)` performs
that historical formal-origin and full graph verification via authenticated `gh`.
The consumer must also compare the resulting producer attempt, assessed base,
and original origin file hash to the packet. In particular, `assessed_base` and
`origin_sha256` are declarations inside the offline packet, not independently
verified GitHub facts. Historical mode does not authorize current source use.

After that external authentication, download and verify the independently pinned
packet, using the existing CI token access to Docs artifacts where available:

```sh
gh run download "$RUN_ID" --repo AIsa-team/docs \
  --name "schema-input-bundle-v2-$RUN_ID-$RUN_ATTEMPT" --dir packet
python scripts/schema_bundle_supply.py verify --input packet \
  --bundle-sha256 "$BUNDLE_SHA256" --archive-sha256 "$ARCHIVE_SHA256" \
  --docs-ref "$DOCS_REF" --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" \
  --output verified-bundle
```

The output directory must not exist. Validation extracts into a private temporary
directory, rejects unsafe paths, links, duplicate/extra members and oversized
content, then verifies the existing bundle's complete roles, hashes, identities,
references and historical source replay. Only successful validation exposes the
original bundle atomically. No network or GitHub authentication occurs in this
helper. No new App credential or permission system is introduced by this change.

## Stable inputs and retention

The archive preserves original bytes. Members are sorted, regular files with
fixed ownership, mode and timestamp; gzip has no filename or current timestamp.
Identical bundle bytes produce identical archive bytes in the pinned build
environment. Producer-specific metadata is outside the archive. All original
source receipt clocks remain intact.

A worker lock should select an independently reviewed bundle, not follow every
candidate automatically. New Runtime prices are separate facts consumed by the
Composer; they do not require replacing the schema bundle or approving its
historical price bytes as current prices. A later formal Docs commit can generate
a different candidate because its history/presentation inputs differ. That does
not force a worker lock update. Current source governance and production identity
remain separate integration requirements.

Artifacts are retained for 90 days, subject to repository/platform retention.
This is not permanent rebuildability. The archive SHA and two-file interface can
support a future digest-addressed durable release asset; this change creates no
GitHub release or automatic promotion. A build must fail if its pinned artifact
is unavailable rather than silently select a replacement.

## Verification

Run the focused tests with the repository's Python dependencies installed:

```sh
python -m unittest discover -s scripts/tests -p test_schema_bundle_supply.py
python -m unittest discover -s scripts/tests -p test_publication_origin.py
python -m unittest discover -s scripts/tests -p test_publication_review_regressions.py
```

A local historical replay used genuine Docs commit
`6fbf9940d876920d7bae05de2e9df5b2f4c0a139` and its original receipt. Two complete
exports produced identical packets. The 208 extracted bundle files matched the
original version 2 bundle byte for byte. Bundle manifest SHA was
`17590e3c917bce9467d250e5abfb006bf828f62ad0d3e96d6e33929c89a65c31`;
archive SHA was
`a3442b6e79e46d8330223099548f25b03fbc126ee3e1cc7a978a9f9046511044`
(5,469,435 bytes). The assessment time remained
`2026-10-15T18:14:38.124664+00:00`. These are local transport replay results, not a
claim that the historical GitHub run uploaded this newly introduced artifact.
The new supply workflow must run on a subsequent genuine formal publication to
establish the first actual CI artifact.

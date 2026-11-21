# Runtime publication compatibility for Tasks and removed internal operations

This consumer change is required before Services #1531 and #1533 reach
production. It does not publish Task pages or prices; that renderer remains in
Docs #386.

The optional `tasks/catalog.json` member belongs to the immutable outer Runtime
release. Its bytes receive the same manifest, SHA-256, ETag, JSON and size checks
as other members. It is saved with the acquisition, but never enters the Raw
provider inventory, flat provider inputs, canonical inner manifest or operation
counts. Releases without the member continue to work. Other `tasks/*` names
remain invalid.

After canonical acquisition, input verification and readiness pass, page
projection can remove a generated page whose old operation identity no longer
exists anywhere in the complete native graph. The old page must match its prior
native contract, including a published locale alias. Its header must contain
only generator-managed fields, and its body must contain the generated contract
block with no authored content outside managed blocks. Manual pages, custom
headers/prose and editorial archives are retained for review. Missing providers
are not treated as proof of removal. Moved identities and existing disabled Raw
operations retain their pages.

Projection returns deletion plans alongside byte updates. Staging validates all
output paths before applying either, removes navigation links to deleted pages,
and records the removed names in its report. Existing formal publication and
reference validation remain required; failure does not publish a partial site.

Validation:

```sh
python -m unittest scripts.tests.test_canonical_import \
  scripts.tests.test_runtime_contract_artifact scripts.tests.test_fetch_runtime_release \
  scripts.tests.test_runtime_publication
python -m unittest discover -s scripts/tests
```

The implementation was also replayed against manifest-verified production
TikHub facts/native bytes at revision
`b961e0ac483342893ac66d8e2a2c03ac2345178cb0963c1b1cc632fac844cc74`
and actual main bilingual pages. Removing the one confirmed internal operation
left all 956 Raw operations, including 154 disabled operations, unchanged. The
two obsolete generated pages were selected for removal and the dangling
reference check passed afterward. This was a provider-scoped offline replay,
not a production deployment or a new complete Go snapshot. A Go-produced Task
catalog fixture passed both facts-only and canonical acquisition with unchanged
Raw provider counts; legacy releases without Tasks also passed.

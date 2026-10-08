# Reviewed response source converters

These helpers retain provider-authored types rather than turning examples into
schemas. `wrapper_cloudsway_reference.py` and `wrapper_twitter_reference.py` are
used by the existing `import_upstream.py` dispatch. The Twitter importer enriches
only its existing delete request contract. `response_reference` additionally
returns the owning service's post response declaration, but that response-only
record is not a complete post request source.

The Similarweb and BytePlus helpers are offline review tools. For example, from
the repository root with already captured public reference bytes:

```python
import json
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from import_similarweb_response_reference import convert_reference

document, provenance = convert_reference(
    Path('/private/tmp/similarweb-segments.html').read_bytes(),
    '/v5/segment-analysis/segments/traffic-and-engagement',
    'https://docs.similarweb.com/api-v5/similarweb-api/website-analysis-api/website-segments/segments',
)
Path('/private/tmp/similarweb-candidate.json').write_text(
    json.dumps({'document': document, 'provenance': provenance}, indent=2) + '\n'
)
```

Use `import_byteplus_response_reference.convert_reference(raw_bytes)` for the
BytePlus reference. Its output deliberately has only a `PullPostsResult`
component and an incomplete 200 response: the page's typed table does not
establish the complete top-level envelope. Do not attach this root-path source
to all BytePlus actions.

Before any source is accepted, compare the current route, origin, method and
selectors with the captured declaration, review the raw-byte hash, and replay
with the unmodified Runtime facts. A typed source alone cannot clear a Runtime
owned response gap. Never synthesize `x-aisa-passthrough`, use examples as an
empty-body declaration, or insert a response through `previous` to bypass that
boundary. These helpers do not import identities, compile or rebind Profiles,
change production, or approve a publication.

Validation:

```sh
python -m unittest discover -s scripts/tests -p test_nonfred_responses.py -v
python -m unittest discover -s scripts/tests -p test_wrapper_references.py -v
```

## Independent Runtime response transport

Composer 12 accepts a response-only public mirror only when the Runtime operation
explicitly supplies `x-aisa-response-passthrough: true`, together with matching
64-character SHA256 values in `x-aisa-response-upstream-path-sha256` and
`x-aisa-response-upstream-origin-sha256`. The origin hashes the lowercase scheme
and host (including an explicit port); the path hash covers the executor's full
base prefix plus target path. Current producer scope excludes query-selected and
encoded-path targets. Request validation ownership remains unchanged.

The source metadata must contain `kind: manual`, `path_space: public`,
`response_only: true`, both `upstream_path_sha256` and `upstream_origin_sha256`,
and the normal complete provenance. Its public path and HTTP method must match.
A response-only source cannot discover an ANY request method or supply request
parameters/body. Ambiguous, absent or changed bindings leave response debt open.
Explicit Runtime `false` forbids both source response copying and historical
response inheritance while preserving any response schema owned by Runtime.

Prepare a reviewed candidate with
`wrapper_twitter_reference.convert_response_only_reference(routes_bytes,
schemas_bytes, reviewed_current_origin_sha256)` for Twitter post, or
`import_similarweb_response_reference.convert_response_only_reference(raw_bytes,
expected_v5_path, canonical_source_url, exact_public_path)` for Similarweb.
These return `(document, metadata)`; record normal acquisition provenance before
reviewing an artifact. They do not fetch, approve, register, or publish anything.
The Twitter origin pin is a reviewed deployment binding, not a claim that the
owning repository declares its deployment hostname.

`test_independent_response_sources.py` uses clearly synthetic next-projection
facts. Passing these tests does not change W0 debt or prove a current production
projection. Run with `python -m unittest discover -s scripts/tests -p
test_independent_response_sources.py -v`.

## Migrate an existing public response declaration

When new Runtime transport descriptors make anonymous historical inheritance
unusable, use `prepare_response_source_migration.py` to prepare explicit sources.
`plan` compares a pinned, published AIsa document with new Runtime facts and
records each old response hash, current request/profile fingerprint, immutable
operation identity, and path/origin pins. Transformed routes, incomplete
responses, and identity mismatches remain blocked.

```sh
python scripts/prepare_response_source_migration.py plan --published OLD.json --facts CURRENT.json --source-url https://github.com/AIsa-team/docs/blob/FULL_REVISION/openapi/PROVIDER.json --source-revision FULL_REVISION --output REVIEW.json
python scripts/prepare_response_source_migration.py prepare --published OLD.json --facts CURRENT.json --review REVIEW.json --output /private/tmp/response-migration-candidates
```

The plan defaults every route to `review_decision: pending`. Before preparation,
a reviewer must compare the public response semantics with the current owning
handler or provider contract, then explicitly choose
`accept_existing_public_response` and record `review_evidence` per accepted row.
Supply the original `source_verified_at`; migration time is not acquisition
proof. Existing source approval, artifact publication and deployment remain
separate. The tool does not register sources or set an approval flag. A schema
that happened to be inherited before is not automatically authoritative for the
current binding.

Preparation rejects source byte changes, response changes, request/profile
changes, identity changes, target-path changes and origin changes after review.
The generated mirrors contain only responses and remain subject to the normal
Runtime descriptor and publication checks. Never disable a mismatch check to
make a historical test pass; provide the reviewed fixture source explicitly.

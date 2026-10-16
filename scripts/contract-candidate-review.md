# Reviewing source candidates

Candidate generation does not publish documentation, approve identities or
change runtime Profiles. These tools write separate review packets. Keep the
official source bytes, acquisition hashes, exact upstream path and effective
server together when reviewing a candidate; a similar public route is not a
source mapping.

The composer keeps response examples but requires an explicit schema for every
declared success media type before clearing response debt. Explicit no-content
responses remain distinct from examples, missing schemas and unconstrained
schemas. FRED references that omit requiredness/type or response schemas retain
those gaps; the importer does not infer declarations from examples.

## Frozen Polymarket replay

From the repository root, replay the fixed public fixtures without networking:

```sh
python scripts/close_polymarket_catalog.py \
  --plan scripts/tests/fixtures/polymarket-targets-snapshot-20261008.json \
  --archive scripts/tests/fixtures/w0-package/scripts/api-contract-acceptance/data/full-catalog.tar.gz \
  --current-mapping scripts/tests/fixtures/polymarket-current-binding-map-20261008.json
```

Add `--write-candidates` to save a separate `docs/polymarket-closure-20261008`
packet. The dated mapping fixture is historical evidence, not a new production
read. Root, path and operation server declarations are checked. Existing IDs
and aliases stay reserved, and all official methods are considered for `ANY`.
Unmatched paths remain blocked; the tool cannot rebind a route to another API.

## Brave and Parallel packets

`brave_parallel_candidates.py --packet DIRECTORY --capture-static` explicitly
fetches allowlisted static references. `--packet DIRECTORY --bindings FILE`
builds from captured evidence offline. An optional `--current-map FILE` joins a
complete sanitized route-binding readback. Capture hashes and converter output
are checked before construction. An archived Parallel operation proves its
historical declaration, not current provider support.

Readback fields named `profile_binding_metadata_matches` establish only the
recorded revision/ownership tuple. They are not a full `ValidateBinding` proof,
public wire-contract projection, source approval or permission to import IDs.
Formal publication still requires the actual locked Runtime inputs and the
existing artifact readiness checks. Code-only CI does not grant that approval.

## Additional bounded source candidates

`import_duffel_reference.py DIRECTORY --fetched-at TIMESTAMP` reads saved official
v2 reference pages and the hash-locked provider SDK, and writes a manual source
to stdout. Its fixture tests document the required files. The source declares
nine operations; it does not invent the two historical GET search-result/rates
routes or claim that changing them to POST preserves behavior.

`prepare_route_migrations.py --current-map FILE --write` prepares ten
finite route decisions from locked public sources. Seven alternatives are
intentional migrations, not aliases. A target-only update would invalidate the
current immutable Profile binding. The packet contains no executable migration,
new Profile, permission to apply, or claim that archived SDK code proves current
provider support. See `docs/routing-debt-resolution-20261008/README.md`.

Source-only improvements must be replayed through the real composer before
subtracting debt. In particular, request validation ownership does not establish
response passthrough: a typed provider response cannot fill a Runtime-owned
response without an explicit response transport declaration and matching origin
and path hashes. Response-only mirrors never establish request fields or ANY
methods, and explicitly transformed responses cannot inherit old provider payloads.
See `scripts/response-source-candidates.md` for the separate response candidates.
The immutable W0 catalog remains the regression baseline; refreshed source
candidates are assessed separately.

## Validation

Consumer agreement must also be checked against source-to-Runtime input
forwarding. Before accepting a unified candidate, run:

```sh
python scripts/audit_request_input_forwarding.py \
  --root REVIEWED_INPUT_ROOT \
  --runtime-dir VERIFIED_RUNTIME_CAPTURE \
  --output request-input-forwarding.json
```

The root contains the reviewed registry and upstream sources; the capture
contains each catalog's Runtime facts JSON. The check scans every configured
provider, including expanded ANY methods, and exits nonzero for unforwarded
query fields or unverifiable source operations. Optional fields count too.
All consumers can agree while still omitting a required business input such as
an identity or pagination cursor. This check changes no Profile or publication
debt. It establishes query forwarding only; body semantics, provider acceptance
and live adoption require their own evidence. Cached captures do not establish
current production state.

```sh
python -m unittest discover -s scripts/tests -v
python -m unittest discover -s scripts/tests/w3_verification -v
```

The runtime-contract workflow also replays the entire immutable W0 catalog,
checks identity sets, EN/ZH publication surfaces and idempotence, and retains
the diagnostic receipt. A successful code check can coexist with unresolved
source/schema debt; inspect the receipt rather than interpreting the process
exit status as publication readiness.

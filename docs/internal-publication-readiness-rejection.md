# Private adapter readiness rejection protocol

The private `internal_publication_snapshot.py` adapter can describe a completed
readiness rejection. This does not authorize an expected failure, image push,
publication, source promotion, or deployment. The ordinary successful artifact
protocol is unchanged. A rejection happens before canonical payload, aggregate,
and manifest construction; it does not verify those successful paths.

After the full `stage` returns, the compiler validates the closed readiness
report and composition summary. A known, structurally complete rejection raises
`ReadinessRejected`. Other exceptions, unknown report shapes or reason codes,
and temporary-directory cleanup failures do not produce this protocol. The
private adapter additionally binds its verified bundle and snapshot pins. Only
after cleanup completes, it emits one compact JSON object and LF on stdout,
with no stderr, then exits **78**. The entire frame is at most **4096 bytes**.
The public historical-shadow CLI still exits with an error, without this frame.

The closed frame has exactly these fields:

| Field | Value/type |
| --- | --- |
| `schema_version` | integer `1` |
| `scope` | `aisa-internal-snapshot-readiness-rejection` |
| `status` | `readiness_rejected` |
| `normalization` | `complete_readiness_multiset_v1` |
| `bundle_manifest_sha256` | lowercase hex64 |
| `docs_ref` | lowercase hex40 |
| `snapshot_sha256` | lowercase hex64 |
| `generation` | uint64 |
| `source_digest` | lowercase hex64 |
| `compiler_revision` | lowercase hex40 |
| `diagnostic_sha256` | lowercase hex64 |
| `provider_count` | uint32 |
| `blocked_provider_count` | uint32 |
| `diagnostic_entry_count` | uint32 |

These pins describe the actual transport verified by the child. They do not
assert an authenticated original production source, a Composer code revision,
all five compiler-input pins, an expected diagnostic oracle, or a CI lease/run.
A caller must independently establish those identities. A caller must validate
every known pin, the exact exit code, stream limits, empty stderr, and a closed
single-frame schema, including duplicate-key rejection. A validated rejection
must still be a compiler error with no artifact and cannot reach publication.

The diagnostic preimage is canonical JSON (sorted object keys, UTF-8, compact
separators, finite numbers, final LF) of:

```json
{"normalization":"complete_readiness_multiset_v1","report":{},"blocked_summary":[]}
```

`report` contains every original report field and value. Only these declared
multisets are sorted by each entry's canonical bytes, retaining duplicates:

- Top-level `global_errors`, `blocked_providers`, `missing_inputs`, and
  `legacy_route_overlaps`.
- Each provider's `errors`, `missing_inputs`, and all six request/response
  `new_pending`, `existing_pending`, and `deferred_pending` arrays.
- `blocked_summary`, containing `{provider, blocked}` for every blocking
  composition-summary entry, including reasons absent from report rows.

All arrays inside individual entries and metadata retain their original order.
In particular, `previous=[provider,path,method]` and nested Runtime pricing arrays
are positional. No field, reason, parameter/location string, policy metadata,
missing input, identity-retention collateral, or duplicate is silently dropped.
Unknown schema fields or reason-code enums fail closed. The existing known
`unclassified_contract_error` remains in the full digest with its exact reason;
it is not reclassified or accepted as an expected root.

Policy metadata has a closed typed structure, including request/response scope
and optional rebinding/effective scope. This validates structure without granting
policy authority; the existing bundle loader authenticates the policy bytes.
Runtime binding identities and revision/pricing object types are checked.
Business keys inside revision/pricing objects remain opaque finite JSON and are
hashed without dropping values or changing array order.

Counts describe entries, not physical root endpoints. `provider_count` is the
provider-object count, and `blocked_provider_count` preserves the blocked-list
multiplicity. `diagnostic_entry_count` sums top-level errors/missing/overlaps,
each provider's errors/missing/six pending arrays, and blocking-summary entries.
Zero counts are allowed; no relationship between these counts grants readiness.
The frame exposes no raw diagnostic values. Shared cross-language fixtures are
in `scripts/tests/fixtures/readiness-rejection-v1*.json`.

Validation:

```sh
python3 -m unittest discover -s scripts/tests -p 'test_readiness_rejection.py' -v
python3 -m unittest discover -s scripts/tests -v
```

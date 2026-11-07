# Production gateway source definitions

This candidate adds real provider definitions for production operations that had
no upstream request source. It does not publish a canonical Runtime release or
mark the full catalog ready. Unknown tools remain pending.

- Composio: 460 request schemas and 460 successful response schemas, from the
  retained official Connect metadata. The entire applied production inventory's
  670 input and output hashes match the capture. The capture's acquisition time
  was not retained; importing or reviewing it today does not make that a fresh
  acquisition.
- Treg: 361 request definitions from the immutable official repository commit
  in `../current-source-review-20261107/gateway-source-review.json`. All 622 missing operations were found by reading both
  provider YAML and extended YAML files. The 261 remaining operations have
  explicit reasons in the assessment, including additional admission rules,
  unstructured nested inputs, retired status, and unreviewed serialization.
- Firecrawl: the remaining detailed descriptors are present, but their full
  validation semantics are not established by the public SDK or gateway
  envelope. No generic free-form body is substituted for a tool contract.

The public HTTP boundary matters. Composio callers send the tool arguments at
the JSON root; the server adds the internal envelope. The server returns the
one completed tool response's `data` value. The imported output schema therefore
projects `properties.data`, preserving its original definition references.
Treg's named `/call/{operation-id}` interface receives upstream path slots as
caller query parameters, not as additional segments in the branded public URL.

The Composer now understands the Runtime's existing `open_query` flag.
`request_wins=false` can coexist with forwarding unknown business query inputs:
fixed target values remain owned by the server. The same strict interpretation
is used by composition and the independent forwarding audit. Fixed selectors
remain hidden from caller inputs; closed, ignored, malformed and conflicting
query policies do not gain forwarding permission.

The two mirrors are automatically indexed by `public_mirror_index`; no provider
registry redirect is needed. Existing formal exports and publication pointers
are unchanged. Source maintenance review requires an independently attributed
receipt tied to each exact source content hash, policy revision, and immutable
review commit. Source review is separate from canonical publication readiness.

Reproduction uses `scripts/prepare_composio_public_reference.py` and
`scripts/prepare_treg_public_reference.py` with the hash-verified private Runtime
snapshot, its same-snapshot pending inventory, the pinned Services checkout,
and the captured source evidence. Both commands require explicit input hashes
and refuse existing output files. Composio additionally requires the verified
production schema-pin audit and `--include-responses` for the response projection.
Treg checks its capture against the original YAML bytes, SHA256 and Git blob
identities before converting. No reproduction step executes supplier tools.

Validation:

```sh
PYTHONPATH=scripts:scripts/tests python3 -m unittest \
  test_request_input_forwarding test_runtime_contracts test_upstream_selectors \
  test_composio_public_reference test_treg_public_reference test_relayer_request_auth
```

The fixed production snapshot was replayed with the real Composer for every
added operation. See the assessment for counts and remaining limitations;
focused composition is not a claim that the full formal catalog is ready.

# SimilarWeb private-capture shape attestations

`keywords.json` and `demographics.json` are value-free shape projections of two
actual AIsa HTTP 200 captures from November 11, 2026. Production response payloads
remain private, in accordance with the repository README. These files preserve
only the exact request query, observation timestamp, status, capture hashes, and
response types, field names, array counts and date-format check results. They
are not raw response payloads or required-field declarations.

The separate `*-example.json` files contain explicitly synthetic queries and
response values created for documentation. They are not production captures.
Their hashes must not be described as actual capture hashes.

`capture_hashes.record_file_sha256` hashes the private supplied file bytes;
`record_canonical_hash` and `body_canonical_hash` hash canonical JSON of that
private record and body, respectively. `raw_body_sha256` is the response-byte
hash recorded during capture and is not recomputed from serialized examples.

`scripts/amend_similarweb_observed_responses.py` extracts and pins the complete
shape attestation. It replays limited amendments against the unchanged official
declarations in `../similarweb-response-20261111/` and validates the synthetic
examples. It keeps documentation acquisition time separate from observation
time. `validate_private_response` additionally checks real private capture bytes
against both the attestation and final schema, with `FormatChecker`; CI cannot
repeat that private validation using the committed fixtures alone.

Evidence, precise before/after changes, and private validation results are in
`docs/current-source-review-20261110/similarweb-observed-keywords-demographics-20261111.json`.
Run the public focused checks from the repository root:

```sh
PYTHONPATH=scripts:scripts/tests python -m unittest test_similarweb_observed_responses test_similarweb_response_reference test_nonfred_responses
```

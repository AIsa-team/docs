# Supplier authentication acceptance

Consumer equality is insufficient: all consumers can consistently omit a
supplier's required authentication. Run `scripts/audit_supplier_auth.py` as an
independent acceptance check alongside request forwarding and publication
readiness. It does not change source authority or approve pending debt.

```sh
python scripts/audit_supplier_auth.py \
  --root . --runtime-dir /path/to/verified-runtime-acquisition \
  --metadata /path/to/read-only-transport-metadata.json \
  --credential-formats /path/to/server-side-format-inspection.json \
  --output /path/to/supplier-auth-audit.json
```

Metadata contains Provider IDs, configured auth names/locations, recognized
scheme names, encrypted-credential presence, hashes of upstream origins and
fixed header names. Format inspection, when available, happens on the server:
return only prefix/encoding categories and ciphertext hashes, never credentials.
Both reads must bind the same verified Runtime generation and source digest.
The report binds the exact checker, metadata, sources and Runtime files.

OpenAPI security alternatives are OR; fields within each alternative are AND.
Header names are case insensitive; query names are case sensitive. An operation
can override document security, including an unauthenticated alternative.
Bearer/Basic header presence alone cannot establish its encoding. A static
signature header cannot establish a per-request signer. Origin mismatches,
unsupported flows/scopes and missing sources remain unverified. A historical
AISA mirror and Runtime-managed request metadata establish no supplier auth
authority. Runtime-owned handlers require separate implementation review.

`transport_shape_compatible_key_validity_unverified` means only the documented
transport shape can be produced. It says nothing about key validity, account
scope, entitlement, provider availability or successful business execution.
The command fails when confirmed gaps or incomplete coverage remain.

The 2026-10-17 audit found 21 Parallel methods with `Authorization` configured
instead of the official `x-api-key`, plus 13 CLOB methods requiring a five-header
authentication group absent from generic injection. Live read-only Parallel
controls returned 401 with the stored raw Authorization value and 404 for a
nonexistent run using the same stored key in `x-api-key`; no job was created.
This supports a configuration repair, not a business-success claim. CLOB's
signed orders and account-bound authentication still need an ownership design
and verified request signing; do not expose a shared account through generic
caller business headers. The separate Relayer signer repair does not resolve
CLOB authentication.

Production configuration changes require separate review and activation. A
three-field auth patch must not be sent as the entire `SaveProvider` input:
that API replaces additional fields. Preserve the exact current record, use
the existing transaction/audit/publication/cache path, and verify adoption.

Validation: `PYTHONPATH=scripts:scripts/tests python -m unittest test_supplier_auth_audit`.

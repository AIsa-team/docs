# Akta response bindings

Four response-only public bindings derive verbatim responses and referenced components from `openapi/upstream/akta-official.json` at Docs `f81b180650fdc2a877e1feb5327e94da4324b4ec` (raw SHA256 `e8a0061971891051743a08793392e559128cb545c92ae9ad8ad0d88625831612`). The authority is the official `https://docs.akta.pro/openapi.json`, originally acquired at the timestamp retained in that source. Creating these files does not represent a new fetch or a successful manual review.

The official server is `https://api.akta.pro/api`; its `/v1/...` paths bind to `/api/v1/...`, with no trailing slash. The public `/apis/v1/akta/...` routes, GET methods, origin hashes and path hashes are explicit. The only copied parameters are official path-template declarations required for valid source OpenAPI; `response_only` keeps them out of request and method discovery. No response types, required fields, defaults or success statuses are inferred. Error responses are copied as declared but the composer imports only eligible success responses.

These sources require the separately reviewed D1 target correction before they match Runtime. Existing actual trailing-slash targets must remain pending. No Runtime change, SQL execution, Profile rebinding, registry request source change, validator change or publication is part of this commit. Maintenance is manual with repository ownership and a 30-day review period; independent receipts are required before source-governance acceptance.

Rebuild in an empty directory:

```sh
python scripts/prepare_akta_response_bindings.py --source openapi/upstream/akta-official.json --output /tmp/akta-response-candidates
PYTHONPATH=scripts:scripts/tests python -m unittest scripts.tests.test_akta_response_bindings scripts.tests.test_independent_response_sources
```

The focused tests prove all four fixed-target responses are typed without changing request/pricing/identity fields, old trailing-slash targets and wrong origins remain pending, and response-only sources cannot select an ANY method. A separate full Runtime candidate replay is required to assess total remaining gaps.

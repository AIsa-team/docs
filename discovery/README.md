# MPP discovery pilot

`openapi.json` is a generated OpenAPI 3.1 payment discovery document for three
Polymarket GET operations: holders, open interest, and live volume. It is a
small initial catalog, not a claim that every AIsa API accepts MPP.

## Generate and check

From the docs repository root (Python standard library only):

```sh
python3 scripts/generate_payment_discovery.py
python3 -m unittest discover -s scripts/tests -p 'test_payment_discovery.py'
npx mppx discover validate discovery/openapi.json
```

The generator reuses request/response definitions from
`openapi/polymarket-data.json`, retains reachable schema references, removes
account-specific pricing/authentication metadata, and adds canonical
`x-payment-info.offers` and a `402` response. The existing consolidated YAML
and its publication workflow are unchanged.

## Pricing evidence and limitations

`payment-evidence.json` records public, unauthenticated HTTP 402 observations
from 2026-10-10. All three advertised Tempo charge offers returned amount
`440` in the token's base units and chain ID `4217`. The token address is copied
from the live challenge; no token decimals or ticker are inferred here.
No credentials, signed challenges, payment IDs, or private keys are stored.

No payment was made and successful paid responses have not been verified.
Schemas come from the existing reviewed API documentation, not these probes.
The live 402 challenge always overrides this advisory pricing snapshot.

Before publishing or refreshing, fetch each selected route without credentials
or a payment header and confirm an HTTP 402 with a Tempo charge challenge.
Decode its `request` base64url JSON and compare amount, currency, chain and
intent against current production configuration. Review the fixed-price
contract: a quote for one request is not proof of request-independent pricing.
Refresh the evidence timestamps and offers after review. The source SHA-256
pin deliberately rejects source changes until their schemas and eligibility
are reviewed; do not update the hash solely to bypass this check.

This pilot supports a single provider and fixed-price GET operations. Adding
other providers, parameter-dependent prices, or sessions requires extending
the generator and evidence model, not copying these prices to other routes.

## Publish and register

1. Validate the file and verify at least one controlled paid request for each
   selected endpoint before advertising it as fully tested.
2. Deploy the generated JSON at `https://api.aisa.one/openapi.json`, either as
   a static file or through api-service, and add the corresponding nginx route.
   Return 200, `Content-Type: application/json`, and an appropriate short cache
   lifetime, such as `Cache-Control: public, max-age=300`. No API key required.
3. Validate the deployed URL with `mppx discover validate` and verify that the
   served artifact matches this file. A docs repository commit does not deploy
   the API-domain route; that release is a separate AIsaServices change.
4. Enter `api.aisa.one` on https://mppscan.com/register and choose Add API.
5. Send the discovery URL to Mercator for ingestion confirmation. MPPScan
   registration does not guarantee Mercator or the curated MPP directory
   listing; the latter has its own submission process.

Reference: https://mpp.dev/advanced/discovery

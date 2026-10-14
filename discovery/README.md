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

MPPScan additionally expects `x-payment-info.price` and `protocols`. The
generator emits these alongside canonical `offers`, plus `info.x-guidance`.
USD price hints use the reviewed source's fixed USD estimate; raw token units
are not treated as USD. GET input schemas remain query parameters, not invented
JSON request bodies. Both forms are understood by `@agentcash/discovery` 1.7.5.
After deploying, run `npx --yes @agentcash/discovery@1.7.5 discover https://api.aisa.one`
and ensure every pilot route has an MPP protocol and a price. The mppx validator
alone does not check MPPScan's additional classification requirements.

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

## Multi-provider expansion (v2)

The implementation and candidate inventory are maintained in
`AIsaServices/docs/mpp-fixed-rollout.md` and
`AIsaServices/packages/mppcatalog/allowlist.json`. The existing pilot artifact
remains the published fallback until runtime activation is verified.

After backend `mpp-catalog verify` and refreshing/composing runtime source docs:

1. Run `scripts/probe_payment_discovery.py --runtime-plan <plan.json>
   --allowlist <runtime-allowlist.json> --server https://api.aisa.one
   --environment production --output <new-evidence.json>`. No payment is sent.
2. Run `scripts/generate_payment_discovery.py --allowlist <runtime-allowlist.json>
   --runtime-plan <plan.json> --evidence <new-evidence.json>
   --output <candidate.json> --report <report.json>`.
3. Validate with `mppx@0.13.4 discover validate <candidate.json>` and
   `node scripts/validate_payment_catalog.mjs <candidate.json>
   <path-to-@agentcash/discovery@1.7.5/dist/index.js>`.
4. Review per-provider counts, blockers, source hashes/revisions, deterministic
   runtime pricing provenance and output SHA. Only then copy into the runtime's
   static deployment directory through the normal release workflow.

V2 requires matching runtime profile, pricing and PAYG policy revisions. It
never reads an estimated docs price as the final USD quote. Known Tempo token,
chain and six-decimal denomination are validated against every observed 402.
Provider-specific component namespaces preserve refs without collisions. GET
parameters and real read-only POST bodies retain their schemas and serialization
rules. ANY-method runtime facts expose `mpp_methods`; the composer applies that
list separately to each public operation.

Known MPPScan UI GET-input warnings remain separate from parser correctness;
no synthetic GET body is introduced. Challenge observations are not proof of a
successful paid call. Live paid acceptance uses a separately approved wallet and
budget. The original no-argument generator is retained only to reproduce the
three-operation pilot from its historical evidence; it does not expand scope.

The initial review identified 182 read-only candidates. The executable allowlist
contains 149 operations across 18 providers; the sibling `blocked.json` records
33 schema blockers (FRED and Financial analyst-estimates). When present beside
the allowlist, these blockers are included in the generation report. Missing
public upstream metadata on runtime-validated Semrush operations is checked
against the verified runtime plan and matching contract revisions.

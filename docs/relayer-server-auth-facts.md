# Relayer server authentication facts

`x-aisa-upstream-auth` is a closed, versioned Runtime description of the existing
`polymarket_relayer_v1` server authentication driver. It is not a supplier or
account authorization check. No credential value or owner assertion is public.

For Provider `polymarket-relayer`, only POST `/submit` and GET `/transactions`
can use it. The checker binds the official locked Relayer source URL and HTTPS
origin, exact upstream path/method and selected credential scheme. Its public
selector digest covers exactly the fixed origin, `auth_location=header`, and
`credential_scheme`, serialized as sorted compact JSON. Complete private
Provider configuration remains bound by the Runtime publication source digest.

The official source declares optional API-key and Builder alternatives. After
validating the complete selected group, composition omits these server-managed
credential parameters from caller input. The upstream mirror stays unchanged;
the descriptor stays in the public operation. Required unused alternatives,
unknown schemes, malformed descriptors and mismatched paths/origins fail closed.
Business headers, body/query validation and response provenance keep their
existing checks. The independent forwarding audit uses the same finite check.

`/relayer/api/keys` is not supported by the shared-credential driver. It gets no
server-auth descriptor, retains its native physical/ANY identity, and stays
pending. This change does not claim a deployed API supports the new facts, nor
close a current-source root without a new authenticated Runtime capture. A new
Docs code pin/source manifest is necessary before any future strict qualification;
historical QCCB evidence does not qualify this new checker.

Run the bounded offline controls with:

```sh
PYTHONPATH=scripts:scripts/tests python -B -m unittest scripts.tests.test_upstream_auth_transports scripts.tests.test_request_input_forwarding
```

## Request-owned key listing

`x-aisa-request-auth` describes only GET `/apis/v1/polymarket/relayer/api/keys`
on the existing Provider72/Endpoint2278. Its eight closed fields are
`schema_version: 1`, `driver: polymarket_relayer_key_list_caller_v1`,
`scheme: polymarket_relayer_api_key`, `credential_source: caller_request_headers`,
`upstream_method: GET`, exact official origin/path SHA256 and the ordered
`required_headers: [RELAYER_API_KEY, RELAYER_API_KEY_ADDRESS]`.
Both headers remain visible and required. Platform authentication remains
independent. The existing ANY Profile is an upper bound; the implemented
code-owned adapter refines the actual native operation to GET without changing
the immutable operationID, Profile revision, price or database configuration.

The composer and independent forwarding audit bind this descriptor to the
locked official key-list GET and exact server, check both required Runtime header
schemas, and recognize only that pair as forwarded. This does not widen
`x-aisa-upstream-auth`, ordinary business CallerHeaders or unknown query/header
permissions. Builder and Gamma are not implemented for key listing. The adapter
rejects query/body, duplicate or mixed credential groups before payment; it
freezes the pair through payment and dispatch and binds opaque request identity.
These facts establish a caller transport, not live key validity, ownership or
production readiness. The other two authenticated Relayer operations still need
an actual trusted Provider scheme selection to emit their server-auth facts.

Run the focused regression with:

```bash
PYTHONPATH=scripts:scripts/tests python -m unittest discover -s scripts/tests -p 'test_relayer_request_auth.py'
```

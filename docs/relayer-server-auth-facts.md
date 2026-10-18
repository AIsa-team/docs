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

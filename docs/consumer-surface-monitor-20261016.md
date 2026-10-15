# Public consumer acceptance coverage

The existing `check_contract_revisions.py --all-surfaces` check now compares
`https://api.aisa.one/openapi.json` with the **payment subset** at
`discovery/openapi.json` in the independently selected formal Docs commit.
It never compares that payment endpoint with the full ordinary API catalogue.
The expected bytes must match that commit's passed publication manifest.

The static consumer is a byte-for-byte mirror, so serialization changes fail
the exact-byte check. An additional complete JSON comparison distinguishes
formatting drift from endpoint, HTTP method, parameter, payment amount, currency,
or other contract drift. Business schema properties are not filtered by name.
Absent formal payment evidence or an unavailable public endpoint cannot pass.

An unavailable Website no longer suppresses independent Runtime/Router
comparisons. The overall assessment remains `not_assessed` when evidence is
missing; independently detectable mismatches are retained in the same report.
Existing timing, two-observation escalation and last-good publication policies
are unchanged. No new monitor or service is introduced.

This check still verifies MCP loaded-source provenance and its llms index,
not authenticated MCP `get_details` output. Router native/executable schema
checks and MCP adapter checks must report their own field-level scope rather
than treating source hashes as complete execution evidence.

Validation:

```sh
python3 -m unittest scripts.tests.test_public_surface_checks scripts.tests.test_contract_revisions
```

Regressions cover payment price, parameter, HTTP method and path drift, exact
mirror bytes, missing evidence, and Router drift while Website is unavailable.
The release acceptance command continues to require the independently recorded
formal SHA, selection file and original budget start. Never reset that clock to
make a delayed deployment pass.

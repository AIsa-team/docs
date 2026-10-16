# Request-contract and consumer repair batch

## Outcome and boundaries

The Runtime request contract must describe what the gateway accepts and sends.
Composition must preserve the selected source's useful request explanations
without replacing Runtime constraints, defaults, prices, or operation identity.
Every consumer must preserve those declarations through its actual request
builder, and an ordinary Runtime release must reach the public consumers.

The 2026-10-16 audit records 2,058 Runtime facts and 2,010 public operations.
The combined ledger has 2,108 rows, including unpublished facts. A row marked
consistent is evidence for its checked dimensions, not proof of provider success.
The later reachable-field example scan supplements the original top-level
example scan; its failures must remain visible in the batch report.

## This Docs change

- Keep missing source descriptions and compatible examples when Runtime replaces
  a request parameter or body field. Runtime constraints and defaults still win.
  Copy examples only when validation declarations match, allowing an integer
  example when the source says number and Runtime says integer. An explicitly
  labelled source default follows the declared Runtime default in retained prose.
- Remove stale API monetary rates without deleting product-price filter examples,
  batch-size limits, first-N behavior, or conditional provider-usage warnings.
  Reconcile an unqualified Free claim only against a positive, available
  fixed-success customer reference. Provider cost alone does not imply a customer
  price, and a usage estimate does not establish a fixed charge.
- Restore the missing FRED current-maintenance receipt by copying the existing
  reviewed receipt exactly. Do not renew its original acquisition/review clock.
- Increment Composer's version so its existing input/version hash invalidates
  cached documents when the projection behavior changes.

## Joint batch acceptance

1. Compile the same verified complete Runtime acquisition and reviewed source
   bundle with the old and new Composer. Record every changed operation. Identity,
   method, availability, auth, prices, and non-target request/response constraints
   must stay unchanged.
2. Validate restored examples against the resulting schema independently. Recheck
   all reachable request examples after the provider source repairs are included.
3. Run the existing publication readiness, source-maintenance, source-governance,
   and finite approved-debt gates. A request-only repair must not invalidate an
   unchanged approved unknown response. It must not approve any new response debt.
4. Test actual MCP and Router request builders with fake HTTP transports. Allowed
   open-body fields must reach the body unchanged; closed-body violations and
   obsolete flattened arguments must fail before sending. Path and query/header
   locations, arrays, omission, and required constraints must remain correct.
5. Review the full Website and Sales catalogs, both languages, and all JSON/YAML
   and llms exports. Verify success-based billing and existing-Job settlement
   conditions, not only numeric amounts and units.
6. After normal deployment, pin the new Runtime generation, formal publication,
   and each actual consumer version. Verify automatic adoption from live outputs.
   A merged PR, scheduled job, or healthy deployment is not adoption evidence.

Closed-query profile repairs and caller-header ownership require separate exact
production-configuration review. This batch does not write production profiles,
prices, admission rules, or refunds. Previously approved finite debt and expired
or unobserved checks do not become passing checks through this document.

## Local validation

```sh
PYTHONPATH=scripts:scripts/tests python -m unittest discover -s scripts/tests -p 'test_*.py'
```

Full-catalog replay uses `shadow_compile_bundle.compile_shadow` with the existing
verified Runtime acquisition, reviewed bundle manifest, and acquisition receipt
hash. It runs offline and does not send provider requests. Keep its report distinct
from the final production acceptance report.

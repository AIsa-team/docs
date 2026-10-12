# Payment discovery binding and publication closure

This review migrates only the three previously reviewed Polymarket GET operations
from whole-provider hashing to `sha256-selected-payment-contracts-v2`. The frozen
before/after fixtures reproduce the a51129d generation transition. The generated
payment catalog is unchanged. Original observation dates, offers, chain IDs and
raw source hash remain unchanged; no new challenge or payment was performed.
The adjacent JSON records the reviewed source and migration comparison.

The code-defined projection covers the selected origin, route, method, runtime
binding, status, effective security and schemes, pricing/revisions, request and
response contracts and their transitive local component references. MPP must
explicitly permit the selected GET method. Global compiler/facts metadata,
unrelated operations and unused components are excluded. Real changes report
the affected projection paths and require review; evidence cannot choose its
own exclusions. The legacy algorithms remain supported only for their frozen
historical inputs; the active evidence uses the new strict method projection.

Publication generates discovery after composing contracts and before final
assessment. The final checker rebuilds discovery, and the manifest hashes both
its review input and output. Export requires the payment subgate and unchanged
bytes; concurrent main changes retain the existing refusal to publish.

Review-input edits trigger the code CI's current-candidate payment check. Edits
to `discovery/openapi.json` additionally require the existing formal artifact
gate. This migration changes no generated catalog or active publication pointer;
the existing publisher alone will generate the next complete formal release.

Validation:

```sh
python -m unittest discover -s scripts/tests -v
python scripts/generate_payment_discovery.py --check
python scripts/tests/fixtures/w0-package/scripts/api-contract-acceptance/verify.py
python -m unittest discover -s scripts/tests/w3_verification -v
```

The payment unit tests read frozen fixtures, allowing a broken generated main
to reach regeneration while the post-generation candidate gate still refuses
inconsistent or method-disabled output. This is not a relaxation of publication
integrity or an assertion that the historical 402 checks verified successful
payment or response bodies.

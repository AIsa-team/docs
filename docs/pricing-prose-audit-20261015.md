# Pricing prose audit, 2026-10-15

The Runtime contract is the source for published pricing. Handwritten and
provider descriptions had become a second price list: Ahrefs domain-rating,
for example, described a $0.02 charge while Runtime published $0.08.

The audit covered all upstream OpenAPI prose, English/Chinese API pages and
guides, and llms.txt. Numeric billing claims were also present in parameter and
response descriptions, not only operation descriptions. The projection removes
250 affected prose fields across these 16 source files without editing the
original source documents or their review receipts:

| Source | Affected prose fields |
| --- | ---: |
| ahrefs | 2 |
| byteplus-search | 3 |
| chat-image-generation | 1 |
| cnpja | 3 |
| dataforseo-official | 10 |
| dataforseo | 24 |
| firecrawl | 1 |
| foreplay | 5 |
| jina | 3 |
| openai-images-generations | 1 |
| openmeteo | 13 |
| oxylabs | 4 |
| perplexity-openapi | 4 |
| semrush | 19 |
| tikhub | 155 |
| websearch | 2 |

These are source-field counts, not counts of incorrect prices or unique live
endpoints. Sources may be unused or reused in multiple public operations.
The 16 remaining source fields containing monetary amounts describe units,
product price filters, market/settlement values, minimum top-ups, or response
examples; they are preserved. JSON instance data and fenced examples remain
unchanged. Signup credit claims are product policy, not endpoint prices, and
are outside this endpoint-pricing correction.

Handwritten Akta endpoint price tables are cleaned during page generation;
their section/credit columns remain available. The Chinese Duffel guide's
independent rates and service multipliers are replaced with a reference to the
current endpoint pricing. llms.txt contains no numeric rate claim and links to
the same endpoint documentation. MCP and website sales consumers will receive
the cleaned descriptions through the existing formal publication graph.

Validation:

- `python -m unittest discover -s scripts/tests -v`: 624 tests, OK, 3 skipped.
- `python scripts/generate_payment_discovery.py --check`: passed.
- Frozen W0 integrity verification and five W3 policy tests: passed.
- Full frozen catalog generation and idempotent replay: passed; 1,930 composed
  operations across 42 providers, identical identity sets, and no execution
  metadata changes. This is an offline diagnostic, not live acceptance.
- Actual Runtime acquisition is pinned to artifact
  `ab2f7346cefe5658eceb70e9296e54a73aa022b866c0a3f199ed2ed4a6e17074`,
  compiler `61f788ae67374a1a0d63281e9d1610f31494c0c6`.
- Both `/apis/v1/dataforseo/v3/serp/google/languages` and the existing path
  without `/v3` returned HTTP 200, provider status 20000, 129 results and
  `X-AISA-Customer-Cost-Micros-USD: 0` in authenticated live checks.

Publication is separate from this code validation. The latest observed Docs
publisher run, 38738508815, still failed formal readiness because the enabled
DataForSEO `dataforseo_labs/google/historical_search_volume/live` operation is
missing from the pinned provider mirror. The operation exists in the current
official source, but importing and reviewing that source is a separate contract
change. This pricing correction does not waive that gate, replace publication
receipts, or claim that the website and MCP have already adopted new artifacts.

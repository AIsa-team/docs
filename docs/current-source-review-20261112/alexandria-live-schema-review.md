# Production verification of five Alexandria operations

On 2026-11-12 (Asia/Singapore), the dedicated E2E key was used for 23 serial business requests to `https://api.aisa.one`: 11 returned HTTP 200 and 12 returned HTTP 400. All requests completed without retries. No business requests were sent to dev. The exact requests, status, response-body digest, request ID, profile binding, and original official descriptor digest are in [the evidence record](alexandria-live-schema-review.json).

This review covers the five operations below. It does not establish correctness for the rest of the Alexandria catalog. The original official descriptors remain the source for documented fields; these production calls establish the actual public envelope and resolve the concrete request disagreements. Firecrawl documents its discovery and execution mechanism in the [official Alexandria reference](https://docs.firecrawl.dev/features/alexandria).

| POST route under `/apis/v1/` | Successful production request | Rejected requests | Observed response and correction |
| --- | --- | --- | --- |
| `pubmed-ncbi-nlm-nih-gov/publications/related` | `pmid="37742320", kind="similar", include_summaries=false, limit=2` | Summaries enabled; `kind=cited_in`; `kind=references`: all 400 | Object with two string `ids`, empty `results`, relationship/source metadata and `total_count=99`. Replaced the populated-summary example and unsupported-mode guidance; encoded the object and field types. |
| `web-archive-org/captures/history` | `url="https://firecrawl.dev", limit=2` | Bare domain; extra `date`: both 400 | Object with two capture objects, available years, normalized URL, `mode="oldest"`, and two null date-related values. Corrected the URL example and removed date-selection guidance. |
| `datalegion/companies/enrich-base` | `domain="google.com"` | Extra `name`; extra `social_url`: both 400 | Object with `matches`, nested `company` and `match_metadata`; `total` omitted. Closed request to domain and documented the observed object structure, including nullable address fields. |
| `datalegion/people/enrich-base-no-contact` | The provider's published social URL example | Extra `first_name`: 400 | Object with `matches`, nested `person` and `match_metadata`; `total` omitted. Closed request to social_url and documented nested records and observed nullable fields. No returned personal values are committed. |
| `wikipedia/articles/lookup` | `name="Marie_Curie", project="enwiki", limit=1` with each of the four body modes, or fields alone | Invalid body; fields together with body=none; 51 fields: 400 | Direct article array. Body keys matched the requested formats; fields-only returned exactly the selected fields. Added body enum, fields maxItems=50, and fields/body mutual exclusion. Added an actual two-field response example. |

## Wikipedia boundary evidence

- `body=none`: 200; no `article_body`.
- `body=wikitext`: 200; `article_body.wikitext` present.
- `body=html`: 200; `article_body.html` present.
- `body=both`: 200; both body formats present.
- `body=not-a-format`: 400 with the provider's explicit allowed-values error.
- `fields=["name","identifier"]` together with `body=none`: 400 with the explicit instruction to pass fields or body, not both.
- 50 copies of `name` together with `body=none`: 400 for that same mutual exclusion.
- 51 copies of `name` together with `body=none`: 400 specifically stating that fields takes at most 50 values and received 51.
- `fields=["name","identifier"]` without body: 200, with exactly those two fields.
- 50 copies of `name` without body: 200, with the name field. The limit is on supplied entries; repeated names are not prohibited by the schema.
- `fields=["name","article_body.wikitext"]` without body: 200, with those selected fields.

The body default is documented in prose rather than as a schema default, so clients do not automatically inject body when sending fields. The composer retains the supplier's exclusion only for two forwarded fields that Runtime does not declare or govern; conflicting or unsupported conditional rules still fail composition.

## Schema validation and scope

All 11 complete successful response bodies were validated locally against the final **composed** schemas. Scalar payloads and incorrect known container/field types are rejected. Wikipedia projections remain valid because article properties are optional. Data Legion's published illustrative person example remains labelled illustrative; the company example is explicitly an excerpt of the actual production response.

The schemas cover evidenced fields and leave additional properties open. Field presence is not inferred from a successful sample. Wayback's two date-related fields were observed only as null, so their descriptions record that fact without inventing an unobserved non-null type. Raw responses are retained privately with the local probe evidence; personal response values and the E2E key are not part of this PR.

The local JSON Schema installation lacks an optional URI-format validator. The Wayback conclusion therefore relies on the actual production 400/200 pair, with the Runtime URI declaration preserved; format-blind example validation is not claimed as URI evidence.

These changes update reviewed sources and their hash-bound receipts. Generated native JSON is produced by the existing dev workflow after an approved merge. This PR does not change the production Runtime, worker collection, or main publication state.

## Offline checks

The complete suite passed 1,177 tests (one existing skip); the 11 policy-fixture tests and frozen-input integrity check passed. The final source refinements were rechecked with 50 targeted tests and all 11 full captured successful payloads. Navigation, canonical page slugs, preserved dev navigation and model snapshot checks passed. A pre-existing download-redirect test was corrected to identify the Docs environment independently of the playground API origin.

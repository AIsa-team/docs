# Financial, Kalshi and Querit source freshness review

This candidate is based on Docs `39a5e2c41269c0baf1757b44f421293c59042713`.
It includes the unified JSON/llms producer and consumer-monitor work. The change
adds only official source updates, their actual acquisition receipts and the
regenerated affected publication files. It does not export a formal pointer,
change Runtime configuration or renew any unchanged source by assertion.

## Acquisition and declaration review

The official sources were fetched again on 2026-10-15 at 15:12 UTC using the
existing importers. Their declaration content hashes match the independently
captured 12:42 UTC upstream-review workflow artifact (`38736581460`). Their
existing automatic maintenance policies and policy hashes are unchanged.
`financial-kalshi-querit-review.json` records before/after source metadata,
operation declaration hashes and exact semantic field changes.

- Financial: four upstream GET financial-statement operations add optional
  `exchange` (string, enum `LSE`) and `isin` (string) query parameters.
- Kalshi: `GET /events/multivariate` adds optional `tickers`; `GET
  /events/{event_ticker}` adds optional boolean `exclude_markets`, default false.
- Querit: `filters.languages.include.items.enum` adds `russian`.

There are no upstream operations added or removed, no uncertain comparisons,
no removed request fields, and no response declaration changes. No upstream
execution or backward-compatibility claim is made.

## Effect on AIsa's actual publication

Comparison of effective generated requests against the parent commit shows:

- Financial: `/apis/v1/financial/financials` and
  `/apis/v1/financial/financials/cash-flow-statements` receive the new optional
  query parameters. The other upstream changes do not create Runtime routes.
- Querit: `POST /apis/v1/querit/search` receives the additional language enum.
- Kalshi: no current published AIsa request declaration changes; the source
  update renews the reviewed mirror and provenance without enabling new routes.
- All three providers retain exactly the same structured prices and response
  declarations as the parent publication.

The generated bilingual provider JSON and pages, aggregate JSON/YAML, llms index,
coverage bindings and sales projection use these same reviewed inputs. Existing
request/response debt remains separately tracked; this change does not approve
new pending declarations.

## Validation

Using immutable Runtime artifact
`ab2f7346cefe5658eceb70e9296e54a73aa022b866c0a3f199ed2ed4a6e17074`
and existing reviewed baseline `78ef376841ead8cde10a79651958790be5a0531c`:

- Full page generation with `pull_openapi.py --readiness-mode pr` passes;
  blocked providers and global errors are empty.
- Source-governance assessment passes with every source fresh and no scoped
  failures. The local cache combines the actual upstream-review workflow's
  receipts with committed review receipts and these three new acquisitions;
  timestamps are not synthesized.
- Payment discovery's existing reviewed three-operation binding check passes.
- Full formal candidate assessment passes with no blocked providers, global
  errors or missing inputs; all source observations are fresh.

This is a reviewed candidate, not a formal release or online convergence result.
The formal publisher must reacquire current Runtime and independently assess and
bind the exact graph after merge. It must retain the original convergence clock.

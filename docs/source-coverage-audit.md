# Missing manual mirror source audit

This audit starts with the public inventory captured on 2026-09-29: 1,878 routes in 49 catalog entries. The existing `coverage-sources.json` labels 202 routes in 20 catalogs `mirror_missing`. That label only tests exact public-path manual mirrors; it does **not** mean 202 official upstream schemas are absent. Catalog display methods are not runtime HTTP method declarations.

No endpoint handler, pricing, request validation, provider registration, or published root OpenAPI is changed by this audit. New files are reviewed official sources. The results below join their schemas to a production read-only runtime projection captured on 2026-09-30; they do not establish deployment.

## Source inventory

| Catalog | Input gaps | Composed paths | Pending | Source |
| --- | ---: | ---: | ---: | --- |
| agentmail | 6 | 6 | 0 | `openapi/upstream/agentmail-official.json` |
| aisa-twitter | 1 | 0 | 1 | No acquired official schema |
| brave-answer | 1 | 1 | 0 | `openapi/upstream/brave-official.json` |
| brave-search | 11 | 11 | 0 | `openapi/upstream/brave-official.json` |
| byteplus-market-insight | 6 | 6 | 0 | Runtime handler DTO declarations |
| coingecko | 2 | 2 | 0 | `openapi/upstream/coingecko-official.json` |
| dataforseo | 8 | 8 | 0 | `openapi/upstream/dataforseo-official.json` |
| financial | 9 | 3 | 6 | `openapi/upstream/financial-official.json` |
| fred | 35 | 32 | 3 | `openapi/upstream/fred-official.json` |
| kalshi-unauthorized | 2 | 2 | 0 | `openapi/upstream/kalshi-official.json` |
| parallel.ai | 21 | 20 | 1 | `openapi/upstream/parallel.ai.json` |
| polymarket-bridge | 5 | 5 | 0 | `openapi/upstream/polymarket-bridge.json` |
| polymarket-clob | 40 | 38 | 2 | `openapi/upstream/polymarket-clob.json` |
| polymarket-data | 13 | 12 | 1 | `openapi/upstream/polymarket-data.json` |
| polymarket-gamma | 24 | 24 | 0 | `openapi/upstream/polymarket-gamma.json` |
| polymarket-relayer | 7 | 7 | 0 | `openapi/upstream/polymarket-relayer.json` |
| querit | 1 | 1 | 0 | `openapi/upstream/querit-official.json` |
| search | 2 | 0 | 2 | No acquired official schema |
| similarweb | 6 | 6 | 0 | Runtime declarations |
| youtube | 2 | 0 | 2 | Official SearchAPI mirrors; runtime selector missing |

The six existing official files cover providers containing 110 of the 202 source-audit gaps. The five new OpenAPI files correspond to providers containing another 27 gaps, and the Brave structured reference supplies another 12, but file presence does not prove every upstream route exists. Similarweb accounts for six runtime-owned product contracts. FRED now contributes 32 strict official-table contracts and Querit contributes one. BytePlus contributes six contracts from its actual runtime handler DTOs. SearchAPI engine-specific mirrors are acquired, but they remain pending when runtime facts do not identify an engine.

## Newly acquired official sources

Brave: `openapi/upstream/brave-official.json`, [official index](https://api-dashboard.search.brave.com/llms.txt), 12 paths / 16 HTTP operations. `scripts/import_brave_reference.py` discovers reference pages and method variants, decodes only the structured `apiSpec` JSON graph, and preserves upstream schemas. It never executes remote JavaScript or reads session fields. Per-page and aggregate source hashes are retained; `import_source` dispatch makes the existing refresh workflow repeat this conversion. The resulting document passed the OpenAPI validator and all 12 input gaps compose against actual runtime paths. Converted document hash: `sha256:2783e7beff4b638324dad207e9ca7972218f29f069aefb60116c3790967b2134`.

- `agentmail-official.json`: [https://docs.agentmail.to/openapi.json](https://docs.agentmail.to/openapi.json), 99 upstream paths, `sha256:0d92c1ea4e45cc47a32d7cccd79a1781b8ef674b4ddb38b4206cb1c77b2020d5`.
- `coingecko-official.json`: [https://raw.githubusercontent.com/coingecko/coingecko-api-oas/main/pro-api.json](https://raw.githubusercontent.com/coingecko/coingecko-api-oas/main/pro-api.json), 102 upstream paths, `sha256:ebe084a9fabd9e16ebd83ee8c14864b7e57fda974dd58e1845eda47c5512f1fd`.
- `dataforseo-official.json`: [https://raw.githubusercontent.com/dataforseo/OpenApiDocumentation/master/openapi_specification.yaml](https://raw.githubusercontent.com/dataforseo/OpenApiDocumentation/master/openapi_specification.yaml), 564 upstream paths, `sha256:0d5d0e0b0978ebfcdad08f511a6c89019eeef721ce4fb97d01c5883be836f5ca`.
- `financial-official.json`: [https://docs.financialdatasets.ai/api/openapi.json](https://docs.financialdatasets.ai/api/openapi.json), 67 upstream paths, `sha256:a0eeab28dd7bbdf114b13e1533748d91c34949b39016f3fc586dcb679acc1507`.
- `kalshi-official.json`: [https://docs.kalshi.com/openapi.yaml](https://docs.kalshi.com/openapi.yaml), 100 upstream paths, `sha256:a38548b7d60bd47fce253733d38f6f756b64ae8c1820eea73ec166f66bb8b9e1`.

AgentMail contains all six missing path templates under `/v0`. DataForSEO contains all eight missing path templates under `/v3`, with request bodies preserved. Kalshi includes `GET /markets/{ticker}` and `GET /markets/{ticker}/orderbook`. CoinGecko includes `/ping` and `/exchanges/{id}/volume_chart`; both input paths now compose using the actual upstream binding and official server prefix. Financial Datasets currently includes the three KPI operations, but several older public routes are absent and institutional ownership uses a different upstream name. Similar names are not treated as verified mappings.

The official DataForSEO YAML uses an unquoted `=` enum scalar. The importer now preserves YAML's equality scalar as the literal string `=` using a SafeLoader constructor; it does not enable arbitrary YAML object construction.

## Remaining documentation sources

- [FRED official endpoint documentation](https://fred.stlouisfed.org/docs/api/fred/) lists the FRED and GeoFRED APIs. No community-authored OpenAPI is substituted for an official source.
- [Brave official machine-readable documentation index](https://api-dashboard.search.brave.com/llms.txt) links twelve API reference pages with parameter tables. Their companion `/__data.json` resources expose the structured specification used by the official pages; the reproducible importer now consumes these resources.
- [Financial Datasets official index](https://docs.financialdatasets.ai/llms.txt) identifies `/api/openapi.json` as the official specification location.

## Runtime evidence and remaining work

All 202 input paths were found in the 52-provider runtime projection, incorporating the production read-only facts and async declarations. The exact path intersection of the original 202-row source audit with the final full-runtime coverage report contains **184 composed paths: 172 using official request schemas and 12 using runtime declarations. 18 remain pending; none are absent from the report.** These are counts of input public paths, not counts of expanded HTTP operations or a claim of complete provider response schemas. `ANY` means runtime accepts an unspecified method; publication expands only methods evidenced by the selected specification.

The final full-runtime local verification reports **42 provider outputs, 1,924 composed operations and 1,933 consolidated operations**. Its validator failure list is empty. The remaining runtime operation gaps are **18 enabled and 90 disabled**; the 18 enabled paths are exactly the 18 pending members of this original 202-path audit. These full-runtime counts are separate from the source-audit path counts. Local report SHA-256: `19d47f057a6d720f7fab4763c4f53edb1e12bb5382830490722be1e63759729b` (`report.json` under the final real-contract verification evidence directory). This is local contract validation, not deployment or paid-provider execution evidence.

The composer now resolves server path prefixes with operation > path > root precedence, detects ambiguous effective paths, and preserves reference sibling constraints as intersections. This resolves CoinGecko's `/api/v3` prefix (2 paths) and Polymarket Relayer's schema annotation siblings (1 path). Mixed runtime-owned fields retain runtime authority; unsupported closed-object intersection flattening stays explicitly pending.

Pending reasons and concrete next steps:

- **10 paths absent from the acquired provider specification:** Financial Datasets 6 (`/crypto/prices`, `/crypto/prices/snapshot`, `/financials/segmented-revenues`, `/institutional-ownership`, `/company/facts/ticker`, `/earnings/press-releases`); Parallel 1 (`/v1beta/tasks/runs/{run_id}/events`, while the source has `/v1/...`); CLOB 2 (`/order/{orderID}` and `/trades`, while the source has `/data/order/{orderID}` and `/data/trades`); Polymarket Data 1 (`/public-search`). Obtain official contracts for the exact runtime routes or separately correct runtime configuration after owner review. Similar paths or another provider's endpoint are not silently substituted.
- **FRED 3:** `/fred/series/search` omits an explicit required/optional declaration for `search_text`; `/geofred/shapes/file` omits it for `shape`; `/geofred/regional/data` has an unsupported `region_type` enumeration declaration. The strict official-table importer publishes the other 32 paths and records these exact pending reasons instead of guessing.
- **YouTube catalog 2 (Airbnb/eBay):** official engine-specific schemas are acquired and source-locked, but current production-derived facts have target `/api/v1/search` with no engine selector and `request_wins=true`. The composer correctly reports `ambiguous upstream source for path and selector`. Do not infer an engine from the public route label.
- **Search 2:** the opaque full/smart wrapper request contracts are still absent; obtain the actual wrapper DTO/specification. The configured engine identifier is intentionally redacted below.
- **AIsa Twitter 1:** the opaque OAuth wrapper request contract is still absent; obtain its handler DTO or exact wrapper specification. Querit is now composed from the official reference tables.

The final path classification joins `coverage-sources.json` entries marked `mirror_missing` to every row under `report.json.coverage.providers` by exact public path. A path is counted as composed only when its report rows are all composed; any pending row keeps the path pending. It does not call paid provider endpoints, change runtime bindings, or write production data.

## Route-by-route runtime results

`Composed` means the selected request contract is publishable by the composer with these real runtime facts. All pending reasons remain visible, including incomplete official declarations and missing runtime engine selectors. Display methods from the original catalog are not used as runtime evidence.

### agentmail

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/agentmail/api-keys/{api_key_id}` | DELETE, GET, PATCH | provider | `/v0/api-keys/{api_key_id}` | Composed |
| `/apis/v1/agentmail/domains/{domain_id}` | DELETE, GET, PATCH | provider | `/v0/domains/{domain_id}` | Composed |
| `/apis/v1/agentmail/domains/{domain_id}/verify` | POST | provider | `/v0/domains/{domain_id}/verify` | Composed |
| `/apis/v1/agentmail/domains/{domain_id}/zone-file` | GET | provider | `/v0/domains/{domain_id}/zone-file` | Composed |
| `/apis/v1/agentmail/inboxes/{inbox_id}/api-keys` | GET, POST | provider | `/v0/inboxes/{inbox_id}/api-keys` | Composed |
| `/apis/v1/agentmail/inboxes/{inbox_id}/api-keys/{api_key_id}` | DELETE, PATCH | provider | `/v0/inboxes/{inbox_id}/api-keys/{api_key_id}` | Composed |

### aisa-twitter

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/twitter/delete_twitter` | ANY | provider | `/delete_twitter` | Pending: no official schema |

### brave-answer

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/brave/chat/completions` | POST | provider | `/res/v1/chat/completions` | Composed |

### brave-search

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/brave/images/search` | GET | provider | `/res/v1/images/search` | Composed |
| `/apis/v1/brave/llm/context` | GET, POST | provider | `/res/v1/llm/context` | Composed |
| `/apis/v1/brave/local/descriptions` | GET | provider | `/res/v1/local/descriptions` | Composed |
| `/apis/v1/brave/local/place_search` | GET | provider | `/res/v1/local/place_search` | Composed |
| `/apis/v1/brave/local/pois` | GET | provider | `/res/v1/local/pois` | Composed |
| `/apis/v1/brave/news/search` | GET, POST | provider | `/res/v1/news/search` | Composed |
| `/apis/v1/brave/spellcheck/search` | GET | provider | `/res/v1/spellcheck/search` | Composed |
| `/apis/v1/brave/suggest/search` | GET | provider | `/res/v1/suggest/search` | Composed |
| `/apis/v1/brave/videos/search` | GET, POST | provider | `/res/v1/videos/search` | Composed |
| `/apis/v1/brave/web/rich` | GET | provider | `/res/v1/web/rich` | Composed |
| `/apis/v1/brave/web/search` | GET, POST | provider | `/res/v1/web/search` | Composed |

### byteplus-market-insight

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/byteplus/mkt-insight/CreateMonitorTask` | POST | runtime | `/` | Runtime declaration |
| `/apis/v1/byteplus/mkt-insight/DisableSubsTask` | POST | runtime | `/` | Runtime declaration |
| `/apis/v1/byteplus/mkt-insight/GetMonitorTask` | POST | runtime | `/` | Runtime declaration |
| `/apis/v1/byteplus/mkt-insight/PullPosts` | POST | runtime | `/` | Runtime declaration |
| `/apis/v1/byteplus/mkt-insight/UpdateMonitorTask` | POST | runtime | `/` | Runtime declaration |
| `/apis/v1/byteplus/mkt-insight/UpdateSubsStatus` | POST | runtime | `/` | Runtime declaration |

### coingecko

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/coingecko/api/{id}/volume_chart` | GET | provider | `/api/v3/exchanges/{id}/volume_chart` | Composed |
| `/apis/v1/coingecko/ping` | GET | provider | `/api/v3/ping` | Composed |

### dataforseo

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/dataforseo/dataforseo_labs/google/competitors_domain/live` | POST | provider | `/v3/dataforseo_labs/google/competitors_domain/live` | Composed |
| `/apis/v1/dataforseo/dataforseo_labs/google/domain_intersection/live` | POST | provider | `/v3/dataforseo_labs/google/domain_intersection/live` | Composed |
| `/apis/v1/dataforseo/dataforseo_labs/google/domain_metrics_by_categories/live` | POST | provider | `/v3/dataforseo_labs/google/domain_metrics_by_categories/live` | Composed |
| `/apis/v1/dataforseo/dataforseo_labs/google/historical_serps/live` | POST | provider | `/v3/dataforseo_labs/google/historical_serps/live` | Composed |
| `/apis/v1/dataforseo/dataforseo_labs/google/page_intersection/live` | POST | provider | `/v3/dataforseo_labs/google/page_intersection/live` | Composed |
| `/apis/v1/dataforseo/dataforseo_labs/google/ranked_keywords/live` | POST | provider | `/v3/dataforseo_labs/google/ranked_keywords/live` | Composed |
| `/apis/v1/dataforseo/on_page/instant_pages` | POST | provider | `/v3/on_page/instant_pages` | Composed |
| `/apis/v1/dataforseo/on_page/pages` | POST | provider | `/v3/on_page/pages` | Composed |

### financial

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/financial/crypto/prices` | ANY | provider | `/crypto/prices` | Pending: path absent |
| `/apis/v1/financial/crypto/prices/snapshot` | ANY | provider | `/crypto/prices/snapshot` | Pending: path absent |
| `/apis/v1/financial/financials/segmented-revenues` | ANY | provider | `/financials/segmented-revenues` | Pending: path absent |
| `/apis/v1/financial/institutional-ownership` | ANY | provider | `/institutional-ownership` | Pending: path absent |
| `/apis/v1/financial/company/facts/ticker` | ANY | provider | `/company/facts/ticker` | Pending: path absent |
| `/apis/v1/financial/earnings/press-releases` | ANY | provider | `/earnings/press-releases` | Pending: path absent |
| `/apis/v1/financial/kpi/guidance` | GET | provider | `/kpi/guidance` | Composed |
| `/apis/v1/financial/kpi/metrics` | GET | provider | `/kpi/metrics` | Composed |
| `/apis/v1/financial/kpi/non-gaap` | GET | provider | `/kpi/non-gaap` | Composed |

### fred

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/fred/category` | GET | provider | `/fred/category` | Composed |
| `/apis/v1/fred/category/children` | GET | provider | `/fred/category/children` | Composed |
| `/apis/v1/fred/category/related` | GET | provider | `/fred/category/related` | Composed |
| `/apis/v1/fred/category/related_tags` | GET | provider | `/fred/category/related_tags` | Composed |
| `/apis/v1/fred/category/series` | GET | provider | `/fred/category/series` | Composed |
| `/apis/v1/fred/category/tags` | GET | provider | `/fred/category/tags` | Composed |
| `/apis/v1/fred/related_tags` | GET | provider | `/fred/related_tags` | Composed |
| `/apis/v1/fred/release` | GET | provider | `/fred/release` | Composed |
| `/apis/v1/fred/release/dates` | GET | provider | `/fred/release/dates` | Composed |
| `/apis/v1/fred/release/related_tags` | GET | provider | `/fred/release/related_tags` | Composed |
| `/apis/v1/fred/release/series` | GET | provider | `/fred/release/series` | Composed |
| `/apis/v1/fred/release/sources` | GET | provider | `/fred/release/sources` | Composed |
| `/apis/v1/fred/release/tables` | GET | provider | `/fred/release/tables` | Composed |
| `/apis/v1/fred/release/tags` | GET | provider | `/fred/release/tags` | Composed |
| `/apis/v1/fred/releases` | GET | provider | `/fred/releases` | Composed |
| `/apis/v1/fred/releases/dates` | GET | provider | `/fred/releases/dates` | Composed |
| `/apis/v1/fred/series` | GET | provider | `/fred/series` | Composed |
| `/apis/v1/fred/series/categories` | GET | provider | `/fred/series/categories` | Composed |
| `/apis/v1/fred/series/observations` | GET | provider | `/fred/series/observations` | Composed |
| `/apis/v1/fred/series/release` | GET | provider | `/fred/series/release` | Composed |
| `/apis/v1/fred/series/search` | ANY | provider | `/fred/series/search` | Pending: incomplete official declaration |
| `/apis/v1/fred/series/search/related_tags` | GET | provider | `/fred/series/search/related_tags` | Composed |
| `/apis/v1/fred/series/search/tags` | GET | provider | `/fred/series/search/tags` | Composed |
| `/apis/v1/fred/series/tags` | GET | provider | `/fred/series/tags` | Composed |
| `/apis/v1/fred/series/updates` | GET | provider | `/fred/series/updates` | Composed |
| `/apis/v1/fred/series/vintagedates` | GET | provider | `/fred/series/vintagedates` | Composed |
| `/apis/v1/fred/source` | GET | provider | `/fred/source` | Composed |
| `/apis/v1/fred/source/releases` | GET | provider | `/fred/source/releases` | Composed |
| `/apis/v1/fred/sources` | GET | provider | `/fred/sources` | Composed |
| `/apis/v1/fred/tags` | GET | provider | `/fred/tags` | Composed |
| `/apis/v1/fred/tags/series` | GET | provider | `/fred/tags/series` | Composed |
| `/apis/v1/geofred/regional/data` | ANY | provider | `/geofred/regional/data` | Pending: incomplete official declaration |
| `/apis/v1/geofred/series/data` | GET | provider | `/geofred/series/data` | Composed |
| `/apis/v1/geofred/series/group` | GET | provider | `/geofred/series/group` | Composed |
| `/apis/v1/geofred/shapes/file` | ANY | provider | `/geofred/shapes/file` | Pending: incomplete official declaration |

### kalshi-unauthorized

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/kalshi/markets/{ticker}` | GET | provider | `/markets/{ticker}` | Composed |
| `/apis/v1/kalshi/markets/{ticker}/orderbook` | GET | provider | `/markets/{ticker}/orderbook` | Composed |

### parallel.ai

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/parallel/chat/completions` | POST | mixed | `/v1beta/chat/completions` | Composed |
| `/apis/v1/parallel/extract` | POST | provider | `/v1/extract` | Composed |
| `/apis/v1/parallel/findall/ingest` | POST | provider | `/v1beta/findall/ingest` | Composed |
| `/apis/v1/parallel/findall/runs/{findall_id}` | GET | provider | `/v1beta/findall/runs/{findall_id}` | Composed |
| `/apis/v1/parallel/findall/runs/{findall_id}/cancel` | POST | provider | `/v1beta/findall/runs/{findall_id}/cancel` | Composed |
| `/apis/v1/parallel/findall/runs/{findall_id}/events` | GET | provider | `/v1beta/findall/runs/{findall_id}/events` | Composed |
| `/apis/v1/parallel/findall/runs/{findall_id}/result` | GET | provider | `/v1beta/findall/runs/{findall_id}/result` | Composed |
| `/apis/v1/parallel/findall/runs/{findall_id}/schema` | GET | provider | `/v1beta/findall/runs/{findall_id}/schema` | Composed |
| `/apis/v1/parallel/monitors/{monitor_id}` | GET | provider | `/v1/monitors/{monitor_id}` | Composed |
| `/apis/v1/parallel/monitors/{monitor_id}/cancel` | POST | provider | `/v1/monitors/{monitor_id}/cancel` | Composed |
| `/apis/v1/parallel/monitors/{monitor_id}/events` | GET | provider | `/v1/monitors/{monitor_id}/events` | Composed |
| `/apis/v1/parallel/monitors/{monitor_id}/update` | POST | provider | `/v1/monitors/{monitor_id}/update` | Composed |
| `/apis/v1/parallel/tasks/groups` | POST | provider | `/v1/tasks/groups` | Composed |
| `/apis/v1/parallel/tasks/groups/{taskgroup_id}` | GET | provider | `/v1/tasks/groups/{taskgroup_id}` | Composed |
| `/apis/v1/parallel/tasks/groups/{taskgroup_id}/events` | GET | provider | `/v1/tasks/groups/{taskgroup_id}/events` | Composed |
| `/apis/v1/parallel/tasks/groups/{taskgroup_id}/runs/{run_id}` | GET | provider | `/v1/tasks/groups/{taskgroup_id}/runs/{run_id}` | Composed |
| `/apis/v1/parallel/tasks/runs/{run_id}` | GET | provider | `/v1/tasks/runs/{run_id}` | Composed |
| `/apis/v1/parallel/tasks/runs/{run_id}/events` | GET | provider | `/v1/tasks/runs/{run_id}/events` | Composed |
| `/apis/v1/parallel/tasks/runs/{run_id}/input` | GET | provider | `/v1/tasks/runs/{run_id}/input` | Composed |
| `/apis/v1/parallel/tasks/runs/{run_id}/result` | GET | provider | `/v1/tasks/runs/{run_id}/result` | Composed |
| `/apis/v1/parallel/v1beta/tasks/runs/{run_id}/events` | ANY | provider | `/v1beta/tasks/runs/{run_id}/events` | Pending: path absent |

### polymarket-bridge

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/polymarket/deposit` | POST | provider | `/deposit` | Composed |
| `/apis/v1/polymarket/quote` | POST | provider | `/quote` | Composed |
| `/apis/v1/polymarket/status/{address}` | GET | provider | `/status/{address}` | Composed |
| `/apis/v1/polymarket/supported-assets` | GET | provider | `/supported-assets` | Composed |
| `/apis/v1/polymarket/withdraw` | POST | provider | `/withdraw` | Composed |

### polymarket-clob

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/polymarket/batch-prices-history` | POST | provider | `/batch-prices-history` | Composed |
| `/apis/v1/polymarket/book` | GET | provider | `/book` | Composed |
| `/apis/v1/polymarket/books` | GET, POST | provider | `/books` | Composed |
| `/apis/v1/polymarket/builder/trades` | GET | provider | `/builder/trades` | Composed |
| `/apis/v1/polymarket/cancel-all` | DELETE | provider | `/cancel-all` | Composed |
| `/apis/v1/polymarket/cancel-market-orders` | DELETE | provider | `/cancel-market-orders` | Composed |
| `/apis/v1/polymarket/clob-markets/{condition_id}` | GET | provider | `/clob-markets/{condition_id}` | Composed |
| `/apis/v1/polymarket/data/orders` | GET | provider | `/data/orders` | Composed |
| `/apis/v1/polymarket/fee-rate` | GET | provider | `/fee-rate` | Composed |
| `/apis/v1/polymarket/fee-rate/{token_id}` | GET | provider | `/fee-rate/{token_id}` | Composed |
| `/apis/v1/polymarket/heartbeats` | POST | provider | `/heartbeats` | Composed |
| `/apis/v1/polymarket/last-trade-price` | GET | provider | `/last-trade-price` | Composed |
| `/apis/v1/polymarket/last-trades-prices` | GET, POST | provider | `/last-trades-prices` | Composed |
| `/apis/v1/polymarket/markets-by-token/{token_id}` | GET | provider | `/markets-by-token/{token_id}` | Composed |
| `/apis/v1/polymarket/midpoint` | GET | provider | `/midpoint` | Composed |
| `/apis/v1/polymarket/midpoints` | GET, POST | provider | `/midpoints` | Composed |
| `/apis/v1/polymarket/order` | DELETE, POST | provider | `/order` | Composed |
| `/apis/v1/polymarket/order-scoring` | GET | provider | `/order-scoring` | Composed |
| `/apis/v1/polymarket/order/{orderID}` | ANY | provider | `/order/{orderID}` | Pending: path absent |
| `/apis/v1/polymarket/orders` | DELETE, POST | provider | `/orders` | Composed |
| `/apis/v1/polymarket/price` | GET | provider | `/price` | Composed |
| `/apis/v1/polymarket/prices` | GET, POST | provider | `/prices` | Composed |
| `/apis/v1/polymarket/prices-history` | GET | provider | `/prices-history` | Composed |
| `/apis/v1/polymarket/rebates/current` | GET | provider | `/rebates/current` | Composed |
| `/apis/v1/polymarket/rewards/markets/current` | GET | provider | `/rewards/markets/current` | Composed |
| `/apis/v1/polymarket/rewards/markets/multi` | GET | provider | `/rewards/markets/multi` | Composed |
| `/apis/v1/polymarket/rewards/markets/{condition_id}` | GET | provider | `/rewards/markets/{condition_id}` | Composed |
| `/apis/v1/polymarket/rewards/user` | GET | provider | `/rewards/user` | Composed |
| `/apis/v1/polymarket/rewards/user/markets` | GET | provider | `/rewards/user/markets` | Composed |
| `/apis/v1/polymarket/rewards/user/percentages` | GET | provider | `/rewards/user/percentages` | Composed |
| `/apis/v1/polymarket/rewards/user/total` | GET | provider | `/rewards/user/total` | Composed |
| `/apis/v1/polymarket/sampling-markets` | GET | provider | `/sampling-markets` | Composed |
| `/apis/v1/polymarket/sampling-simplified-markets` | GET | provider | `/sampling-simplified-markets` | Composed |
| `/apis/v1/polymarket/simplified-markets` | GET | provider | `/simplified-markets` | Composed |
| `/apis/v1/polymarket/spread` | GET | provider | `/spread` | Composed |
| `/apis/v1/polymarket/spreads` | POST | provider | `/spreads` | Composed |
| `/apis/v1/polymarket/tick-size` | GET | provider | `/tick-size` | Composed |
| `/apis/v1/polymarket/tick-size/{token_id}` | GET | provider | `/tick-size/{token_id}` | Composed |
| `/apis/v1/polymarket/time` | GET | provider | `/time` | Composed |
| `/apis/v1/polymarket/trades` | ANY | provider | `/trades` | Pending: path absent |

### polymarket-data

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/polymarket/closed-positions` | GET | provider | `/closed-positions` | Composed |
| `/apis/v1/polymarket/holders` | GET | provider | `/holders` | Composed |
| `/apis/v1/polymarket/live-volume` | GET | provider | `/live-volume` | Composed |
| `/apis/v1/polymarket/oi` | GET | provider | `/oi` | Composed |
| `/apis/v1/polymarket/positions` | GET | provider | `/positions` | Composed |
| `/apis/v1/polymarket/public-search` | ANY | provider | `/public-search` | Pending: path absent |
| `/apis/v1/polymarket/traded` | GET | provider | `/traded` | Composed |
| `/apis/v1/polymarket/v1/accounting/snapshot` | GET | provider | `/v1/accounting/snapshot` | Composed |
| `/apis/v1/polymarket/v1/builders/leaderboard` | GET | provider | `/v1/builders/leaderboard` | Composed |
| `/apis/v1/polymarket/v1/builders/volume` | GET | provider | `/v1/builders/volume` | Composed |
| `/apis/v1/polymarket/v1/leaderboard` | GET | provider | `/v1/leaderboard` | Composed |
| `/apis/v1/polymarket/v1/market-positions` | GET | provider | `/v1/market-positions` | Composed |
| `/apis/v1/polymarket/value` | GET | provider | `/value` | Composed |

### polymarket-gamma

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/polymarket/comments` | GET | provider | `/comments` | Composed |
| `/apis/v1/polymarket/comments/user_address/{user_address}` | GET | provider | `/comments/user_address/{user_address}` | Composed |
| `/apis/v1/polymarket/comments/{id}` | GET | provider | `/comments/{id}` | Composed |
| `/apis/v1/polymarket/events/keyset` | GET | provider | `/events/keyset` | Composed |
| `/apis/v1/polymarket/events/slug/{slug}` | GET | provider | `/events/slug/{slug}` | Composed |
| `/apis/v1/polymarket/events/{id}` | GET | provider | `/events/{id}` | Composed |
| `/apis/v1/polymarket/events/{id}/tags` | GET | provider | `/events/{id}/tags` | Composed |
| `/apis/v1/polymarket/markets/keyset` | GET | provider | `/markets/keyset` | Composed |
| `/apis/v1/polymarket/markets/slug/{slug}` | GET | provider | `/markets/slug/{slug}` | Composed |
| `/apis/v1/polymarket/markets/{id}` | GET | provider | `/markets/{id}` | Composed |
| `/apis/v1/polymarket/markets/{id}/tags` | GET | provider | `/markets/{id}/tags` | Composed |
| `/apis/v1/polymarket/public-profile` | GET | provider | `/public-profile` | Composed |
| `/apis/v1/polymarket/series` | GET | provider | `/series` | Composed |
| `/apis/v1/polymarket/series/{id}` | GET | provider | `/series/{id}` | Composed |
| `/apis/v1/polymarket/sports` | GET | provider | `/sports` | Composed |
| `/apis/v1/polymarket/sports/market-types` | GET | provider | `/sports/market-types` | Composed |
| `/apis/v1/polymarket/tags` | GET | provider | `/tags` | Composed |
| `/apis/v1/polymarket/tags/slug/{slug}` | GET | provider | `/tags/slug/{slug}` | Composed |
| `/apis/v1/polymarket/tags/slug/{slug}/related-tags` | GET | provider | `/tags/slug/{slug}/related-tags` | Composed |
| `/apis/v1/polymarket/tags/slug/{slug}/related-tags/tags` | GET | provider | `/tags/slug/{slug}/related-tags/tags` | Composed |
| `/apis/v1/polymarket/tags/{id}` | GET | provider | `/tags/{id}` | Composed |
| `/apis/v1/polymarket/tags/{id}/related-tags` | GET | provider | `/tags/{id}/related-tags` | Composed |
| `/apis/v1/polymarket/tags/{id}/related-tags/tags` | GET | provider | `/tags/{id}/related-tags/tags` | Composed |
| `/apis/v1/polymarket/teams` | GET | provider | `/teams` | Composed |

### polymarket-relayer

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/polymarket/deployed` | GET | provider | `/deployed` | Composed |
| `/apis/v1/polymarket/nonce` | GET | provider | `/nonce` | Composed |
| `/apis/v1/polymarket/relay-payload` | GET | provider | `/relay-payload` | Composed |
| `/apis/v1/polymarket/relayer/api/keys` | GET | provider | `/relayer/api/keys` | Composed |
| `/apis/v1/polymarket/submit` | POST | provider | `/submit` | Composed |
| `/apis/v1/polymarket/transaction` | GET | provider | `/transaction` | Composed |
| `/apis/v1/polymarket/transactions` | GET | provider | `/transactions` | Composed |

### querit

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/querit/search` | POST | provider | `/v1/search` | Composed |

### search

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/search/full` | ANY | provider | `/search/{configured-engine}/full` | Pending: no official schema |
| `/apis/v1/search/smart` | ANY | provider | `/search/{configured-engine}/smart` | Pending: no official schema |

### similarweb

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/similarweb/keyword-analysis/keywords/overview` | GET | runtime | `None` | Runtime declaration |
| `/apis/v1/similarweb/segment-analysis/segments/traffic-and-engagement` | GET | runtime | `None` | Runtime declaration |
| `/apis/v1/similarweb/segment-analysis/segments/traffic-sources` | GET | runtime | `None` | Runtime declaration |
| `/apis/v1/similarweb/website-analysis/websites/conversion-rates` | GET | runtime | `None` | Runtime declaration |
| `/apis/v1/similarweb/website-analysis/websites/conversion-rates/aggregated` | GET | runtime | `None` | Runtime declaration |
| `/apis/v1/similarweb/website-analysis/websites/traffic-by-demographics/aggregated` | GET | runtime | `None` | Runtime declaration |

### youtube

| Public path | Composed/pending method | Boundary | Upstream path | Result |
| --- | --- | --- | --- | --- |
| `/apis/v1/airbnb/search` | ANY | provider | `/api/v1/search` | Pending: runtime engine selector absent |
| `/apis/v1/ebay/search` | ANY | provider | `/api/v1/search` | Pending: runtime engine selector absent |

## Follow-up: 16 remaining non-FRED/Brave/BytePlus paths

This read-only follow-up checks the actual runtime binding, existing AIsaServices declarations, current official specifications and official SDK/reference material. It does not test provider execution or assert that an undocumented legacy alias is broken. No business route, method, request validator or price was changed.

### Official sources acquired: one resolved path and two selector gaps

| Public path | Evidence | Remaining implementation work |
| --- | --- | --- |
| `/apis/v1/querit/search` | The [official client](https://github.com/querit-ai/querit-python/blob/6480c778590c843f40b9f07aeb8507b3ca73907a/querit/client.py) sends JSON `POST /v1/search`, exactly matching the runtime upstream path. The [official request dataclasses](https://github.com/querit-ai/querit-python/blob/6480c778590c843f40b9f07aeb8507b3ca73907a/querit/models/request.py) establish typed request construction, but the [current coding-agent reference](https://www.querit.ai/en/docs/reference/post-for-coding-agents) documents additional fields absent from this SDK revision. | Resolved by `scripts/import_querit_reference.py` and `querit-official.json`: strict source-locked table conversion now composes the real runtime POST operation with identity, pricing and status preserved. SDK reflection alone would not have been complete: its serializers transform nested filter shapes and its request dataclass omits `highlights`, `needContent`, `chunksPerDoc` and `filters.vertical`. The documentation describes `count` as server default, so the SDK's client-side default must not be presented as the server default. No external credential or paid request is needed to obtain this contract. |
| `/apis/v1/airbnb/search` | The [official Airbnb reference](https://www.searchapi.io/docs/airbnb-api) links a valid [OpenAPI document](https://www.searchapi.io/openapi/airbnb.yaml). It declares `GET /search` with server path `/api/v1` and `engine=airbnb`. | Official source is imported and locked. Current production-derived profile facts expose `/api/v1/search` without an engine selector and allow caller query overrides (`request_wins=true`). The missing discriminator leaves this path explicitly pending; it cannot be selected from the public label. |
| `/apis/v1/ebay/search` | The [official eBay reference](https://www.searchapi.io/docs/ebay-search-api) links a valid [OpenAPI document](https://www.searchapi.io/openapi/ebay_search.yaml). It declares the same `GET /search` and `/api/v1` server prefix, with `engine=ebay_search`. | Official source is imported and locked, but the runtime facts likewise have no engine selector. Composition reports ambiguity. Do not merge both engine-specific parameter sets under one upstream operation or infer the engine from the public label. |

Both SearchAPI source files passed the OpenAPI validator. Raw source SHA-256: Airbnb `47f4f1864e4ca8c7b7e02810562286a2afb7d1dd8279f5a678948c13ebfd7c2a`; eBay `3c332528aec6011970d2dd9d8f2e3b3d0c5ff53a74ad4410db1819a78b1ad363`. These sources have since been imported as `searchapi-airbnb.json` and `searchapi-ebay-search.json`; source availability alone does not resolve their runtime selection ambiguity. The AIsaServices `docs/onboarding/searchapi/*-batch.v1.json` profiles deliberately declare an opaque body; they are billing/request-pass-through contracts, not engine-specific DTOs.

### Runtime bindings without an exact current official operation (10 paths)

| Runtime upstream path | Official evidence | Required decision or input |
| --- | --- | --- |
| Parallel `/v1beta/tasks/runs/{run_id}/events` | The [official events reference](https://docs.parallel.ai/api-reference/tasks/stream-task-run-events.md) and [current OpenAPI](https://docs.parallel.ai/public-openapi.json) declare `/v1/tasks/runs/{run_id}/events`. | Obtain the official legacy beta operation/alias contract or have the runtime owner separately review a version migration. The composer must not silently replace beta with v1. |
| CLOB `/order/{orderID}` | [Official CLOB OpenAPI](https://docs.polymarket.com/api-spec/clob-openapi.yaml) declares `GET /data/order/{orderID}`. `/order` exists for POST/DELETE and is not this GET operation. | Confirm whether a legacy alias is officially supported, or review the missing `/data` runtime prefix separately. |
| CLOB `/trades` | The same official CLOB source declares `GET /data/trades`; [Data API OpenAPI](https://docs.polymarket.com/api-spec/data-openapi.yaml) has `/trades` in a different service. | Confirm the actual provider/service and exact supported path. Do not borrow a same-named Data API schema for CLOB. |
| Polymarket Data `/public-search` | Absent from [Data API OpenAPI](https://docs.polymarket.com/api-spec/data-openapi.yaml); present in [Gamma OpenAPI](https://docs.polymarket.com/api-spec/gamma-openapi.yaml). | Confirm service ownership/legacy alias or separately correct provider binding. The current runtime fact identifies the Data provider; the composer cannot change that fact. |
| Financial `/crypto/prices` | Absent from [current official OpenAPI](https://docs.financialdatasets.ai/api/openapi.json) and its [official documentation index](https://docs.financialdatasets.ai/llms.txt). | Obtain the exact retained crypto API contract or a provider retirement/migration decision. Absence from current docs does not prove the legacy endpoint is disabled. |
| Financial `/crypto/prices/snapshot` | Same exact-route absence as above. | Same requirement; do not substitute stock or macro price schemas. |
| Financial `/financials/segmented-revenues` | Absent from the current official OpenAPI. Other financial statement/search operations do not establish equivalence. | Obtain the exact operation contract or a separately reviewed route migration/retirement decision. |
| Financial `/institutional-ownership` | Current official OpenAPI declares `/institutional-holdings`, `/institutional-holdings/investors` and `/institutional-holdings/tickers`, not the bound path. | Confirm the legacy alias and its exact query/response contract, or review a runtime route change. Similar subject matter is not sufficient mapping evidence. |
| Financial `/company/facts/ticker` | The [official documentation page with this slug](https://docs.financialdatasets.ai/api/company/facts/ticker.md) explicitly declares the API operation as `GET /company/facts`, with a ticker query parameter. `/company/facts/tickers` is a separate list operation. | Confirm whether the runtime path mistakenly copied the documentation slug or is an intentional legacy alias. This cannot be repaired by a docs-only prefix adjustment. |
| Financial `/earnings/press-releases` | Absent from the current official OpenAPI; `/earnings` exists but is a different documented operation. | Obtain exact legacy contract/alias evidence or a separately reviewed route migration/retirement decision. |

### Opaque wrapper contracts not declared in AIsaServices (3 paths)

| Public path | Repository/runtime finding | Required input |
| --- | --- | --- |
| `/apis/v1/search/full` | Runtime passes through to `/search/{configured-engine}/full`, with no declared body/parameters. `docs/onboarding/searchapi/search-batch.v1.json` declares an opaque request. `packages/websearch` belongs to the separate Anthropic/OpenAI search products and is not this handler. | Identify the actual upstream wrapper service/owner and obtain its request DTO or published schema. A SearchAPI billing-account association does not establish that its `/api/v1/search` contract applies to this distinct path. The configured engine identifier remains redacted. |
| `/apis/v1/search/smart` | Same findings, with `/smart` instead of `/full`. | Same source/owner requirement; do not infer smart/full body equivalence. |
| `/apis/v1/twitter/delete_twitter` | Runtime binds `/delete_twitter` with no declared request body/parameters. `services/backend-service/internal/maintenance/twitter_delete_endpoint.go` creates the endpoint and an opaque metering profile; it does not implement the upstream OAuth action or its request DTO. | Obtain the `aisa-twitter` wrapper handler/DTO or its official contract. X's native delete endpoint cannot be substituted because this wrapper may have different OAuth inputs and wire shape. |

Of these 16 follow-up paths, **Querit is now composed; 2 SearchAPI paths have acquired official schemas but missing runtime selection evidence; 10 need exact legacy alias evidence or an explicit runtime-owner migration decision; 3 need the upstream wrapper contract/source location**. Together with the 3 FRED declaration gaps, the final enabled pending total is 18. The runtime-generated facts should carry safe query selectors where necessary, while retaining credential and configured-engine redaction.

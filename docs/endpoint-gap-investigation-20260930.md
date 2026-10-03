# Follow-up investigation of the 18 enabled contract gaps

This investigation supersedes the earlier blanket classification of all 18 as
missing contract evidence. It uses the same production read-only runtime snapshot,
current official sources, pinned owning-service code, primary historical sources,
and unauthenticated read-only upstream probes. It does not change runtime
execution, validation, pricing, provider bindings or production data.

## Result

Six request contracts are now composed. Twelve remain pending: six have concrete
upstream path/retirement evidence; six still need precise contract or alias
evidence. Contract availability and live execution health are separate axes.
In particular, recovering a historical contract does not make a retired route
healthy or erase an earlier failed request.

### Six recovered request contracts

| Public operation | Evidence and fix | Health boundary |
| --- | --- | --- |
| `/apis/v1/airbnb/search` | Official SearchAPI schema; explicit source binding retains required caller `engine=airbnb`. No runtime default is invented. | Request forwarding is supported by runtime facts; no paid request executed. |
| `/apis/v1/ebay/search` | Official SearchAPI schema; explicit source binding retains required caller `engine=ebay_search`. | Same boundary; other engine modes are outside the documented request contract, not forbidden by runtime. |
| `/apis/v1/twitter/delete_twitter` | Owning service's pinned `POST /delete_twitter` handler and `DeleteTweetRequest`: required `aisa_api_key` and `tweet_id`, string lengths 1..64 after tweet-ID trimming; normalized bounds are recorded separately from raw JSON Schema limits. | No deletion sent; deployed wrapper version not verified. The earlier local checkout was stale. |
| `/apis/v1/search/smart` | Current official Cloudsway parameter tables, exact GET method and required `q`, with typed optional fields. Public mapping is checked against a digest of the private runtime path. | CLI repository records earlier authenticated and unauthenticated HTML 404s. Current AIsa end-to-end health was not re-tested. |
| `/apis/v1/search/full` | Complete OpenAPI embedded in a 2025-11-20 AWS article coauthored by Cloudsway engineers. Exact GET and ten query fields retained; source labeled historical. | Same earlier CLI 404 evidence. A historical schema does not verify current service availability. |
| `/apis/v1/parallel/v1beta/tasks/runs/{run_id}/events` | Exact official archived beta OpenAPI, pinned at `8b7c637`; request and reference closure recovered without rewriting target to GA. | Beta remains a legacy route; authenticated current availability not verified. |

SearchAPI sources: [Airbnb](https://www.searchapi.io/docs/airbnb-api),
[eBay](https://www.searchapi.io/docs/ebay-search-api).
Twitter owner: [handler](https://github.com/AIsa-team/AisaTwitterAuthService/blob/9481772229feb96eed7fef509234d089cd0d7ec3/app/api/routes/twitter.py#L122),
[request type](https://github.com/AIsa-team/AisaTwitterAuthService/blob/9481772229feb96eed7fef509234d089cd0d7ec3/app/schemas/twitter.py#L163).
Cloudsway: [current smart reference](https://docs.infra-agent.ai/Smart_Search/Cloudsway_Smart_Search/api/),
[primary historical full contract](https://aws.amazon.com/cn/blogs/china/building-enterprise-level-with-bedrock-agentcore-and-strands/),
[earlier CLI failure record](https://github.com/AIsa-team/cli/blob/b3dba0282f5a6089b8bad99782804e5b2b4d5af0/docs/known-issues.md#L18).
Parallel: [exact archived OpenAPI](https://raw.githubusercontent.com/parallel-web/parallel-llms-txt/8b7c637e75390bf1588eabc3a646dca1080719e4/public/docs/docs-legacy-openapi.json.md).

### Six upstream maintenance findings

These probes address the official upstream services directly, not an authenticated
AIsa gateway request. They corroborate the configured upstream path in the earlier
snapshot; they do not establish the currently deployed gateway/base configuration.

| Configured upstream operation | Observed response and corroboration | Required next action |
| --- | --- | --- |
| Financial `/company/facts/ticker` | 404 JSON explicitly says the endpoint does not exist. `/company/facts` instead returns a missing ticker/CIK validation response. | Review correcting the target to `/company/facts`; the current path appears to copy a documentation page slug. Preserve public path and ID. |
| Financial `/financials/segmented-revenues` | 404 JSON explicitly says endpoint does not exist. Current spec contains `/financials/income-statements/segments` and other segment routes. | Compare intended data, parameters and response before selecting a replacement. |
| Financial `/institutional-ownership` | 410 explicitly says deprecated and directs callers to institutional-holdings. | Review migration to `/institutional-holdings`, including response/pricing compatibility. |
| Financial `/earnings/press-releases` | 404 JSON explicitly says endpoint does not exist. Current `/earnings` is not proof of equivalent press-release content. | Obtain the intended replacement contract or make an explicit retirement decision. |
| Polymarket CLOB `/order/{orderID}` | A synthetic ID gives plaintext 404; `/data/order/{id}` enters JSON 401 authentication. Official old and current SDKs use `/data/order/`. | Strong missing-prefix evidence; check signing/auth path compatibility before correcting target. The 401 does not prove a successful signed request. |
| Polymarket Data `/public-search` | Data host returns plaintext 404; Gamma host same path returns JSON 200. Official spec assigns the operation to Gamma. | Review provider rebind to Gamma with public identity retained and pricing/auth associations checked. |

No target/provider correction was applied. These are runtime configuration
changes and cannot be disguised as documentation-only fixes.

Sources: [Financial OpenAPI](https://docs.financialdatasets.ai/api/openapi.json),
[company facts reference](https://docs.financialdatasets.ai/api/company/facts/ticker),
[institutional migration destination](https://docs.financialdatasets.ai/api/institutional-holdings),
[CLOB official SDK paths](https://github.com/Polymarket/py-clob-client-v2/blob/main/py_clob_client_v2/endpoints.py),
[Data OpenAPI](https://docs.polymarket.com/api-spec/data-openapi.yaml),
[Gamma OpenAPI](https://docs.polymarket.com/api-spec/gamma-openapi.yaml).

### Six remaining contract-evidence findings

| Operation | Evidence now available | Exact remaining uncertainty |
| --- | --- | --- |
| FRED `/fred/series/search` | Official parameter text exists. | `search_text` lacks an explicit type and required/optional declaration. |
| GeoFRED `/geofred/shapes/file` | Nine official shape values exist. | Whether `shape` is required is not stated. |
| GeoFRED `/geofred/regional/data` | Official nested `region_type` enum is now parsed correctly. | The next real gap is `frequency` required/optional status. |
| Financial `/crypto/prices` | Current route returns 400 missing ticker. Official MCP code issues an exact five-field GET request. | The client proves a supported request profile, not all provider parameters or omission defaults. |
| Financial `/crypto/prices/snapshot` | Current route returns 400 missing ticker. Official MCP code explicitly sends ticker. | An official request example exists; no complete current provider contract was found. |
| CLOB `/trades` | Both `/trades` and `/data/trades` return identical 401; official SDK names `/data/trades`. | Authentication may precede routing or a legacy alias may exist. No exact alias contract is established. |

FRED importer repairs also prevent conditional prose such as `Default: If ...`
from becoming an invented literal default. Its existing 32 composed contracts
remain unchanged; the three uncertain routes remain pending. Sources:
[series/search](https://fred.stlouisfed.org/docs/api/fred/series_search.html),
[shapes](https://fred.stlouisfed.org/docs/api/geofred/shapes.html),
[regional/data](https://fred.stlouisfed.org/docs/api/geofred/regional_data.html).
The exact official crypto client is
[Financial MCP](https://github.com/financial-datasets/mcp-server/blob/fe853352ccee2105ea6677fb493eaff5ce2ffa3b/server.py#L276).

## Handling future missing definitions

The intake process is documented in [runtime contracts](../scripts/RUNTIME_CONTRACTS.md#resolving-a-missing-contract).
A missing declaration gets an identified owner/source, not just an aggregate count:
recover the actual DTO or official contract, repair a converter if it missed valid
declarations, or explicitly bind a known caller mode. Preserve existing publication
while a refresh is unresolved; a new unsupported contract stays pending.

Keep contract composition, source age and execution health distinct. A 404/410
requires endpoint maintenance, not an invented schema. Unknown requiredness needs
provider clarification or an authorized validation request. Source bindings and
private-wrapper path digests are checked and included in document identity, so a
later upstream-path or source-selection change cannot silently reuse the old mapping.
The digest does not validate upstream host/provider identity.

The Twitter source repository is private. Routine generation uses its locked
mirror; updating that source revision requires authorized source access. No
credentials, private account endpoint values, or raw authenticated requests are
included in these mirrors.

## Verification

The full snapshot now composes 1,930 operations across 42 grouped outputs;
consolidation contains 1,939 operations. The six recovered contracts retain their
existing operation IDs. Enabled pending paths decrease from 18 to 12; disabled
pending paths remain 90. All generated provider and consolidated OpenAPI documents
validate, and a repeat composition changes no outputs. No diagnostic generated
specification has been published or deployed.

The docs regression suite ran 105 tests (104 passed; one optional cached FRED
check skipped); the separate FRED cache run passed all 11 tests. MCP loaded
65/65 servers and found/read details for all 1,918 enabled data contracts.
Router contains all 1,918 in its 1,919-entry catalog, with all 251 existing
execution restrictions retained. No search/details check executes a provider
operation. In particular, no tweet deletion was performed.

All three runtime-to-docs E2E tests also passed with OpenAPI validation enabled,
including automatic discovery after management creates a new provider and a
subsequent endpoint.

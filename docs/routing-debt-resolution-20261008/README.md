# Bounded route migration candidates

`prepare_route_migrations.py` converts six pinned public official sources into
seven intentional migration alternatives for ten existing routing debts. It
performs no network requests, database actions, Profile compilation, rebinding,
business requests, or publication. All decisions remain `UNAPPROVED`.

The command accepts a sanitized, independently captured read-only metadata map:

```sh
python scripts/prepare_route_migrations.py --current-map /path/to/current-map.json --write
python -m unittest discover -s scripts/tests -p test_route_migrations.py -v
```

The optional output is `route-decisions-NOT-APPROVED.json` in this directory.
Production capture inputs and generated operational reports are evidence, not
source fixtures, and are not committed here. The offline public fixture archive
is pinned by SHA256, requires an exact member inventory, and never executes SDK
code. No `--apply` mode exists.

| Existing endpoint | Concrete decision |
| --- | --- |
| Financial 1683 | Review migration from `/company/facts/ticker` to `/company/facts`. |
| Financial 1694 | Review migration from `/institutional-ownership` to `/institutional-holdings`, including response compatibility. |
| Financial 1702 | Review migration from `/financials/segmented-revenues` to `/financials/income-statements/segments`, including response compatibility. |
| Financial 1684, 1685 | Obtain a current exact crypto contract or retire admission. Official historical MCP code establishes GET request shape for trailing-slash paths only; it does not prove current support, slashless aliases, all allowed methods, or response schemas. |
| Financial 1686 | Obtain an exact earnings press-release contract or retire admission. Neither `/earnings` nor `/search` is treated as equivalent. |
| Polymarket 2220, 2227 | Review the `/data/order/{orderID}` and `/data/trades` targets together with client L2 signature paths. |
| Polymarket 2251 | Review migration of `/public-search` from Data API to Gamma, including provider ownership and response compatibility. |
| Parallel 1801 | Obtain current support proof for beta events or migrate intentionally to the existing GA route represented by endpoint 1793. |

Alternative operations, referenced components, authentication declarations,
effective production servers, method inventory, source byte hashes, and schema
hashes are included for review. Alternative schemas never close a debt on the
old target. Historical SDK argument defaults remain client behavior, not
provider validation constraints.

Current metadata verification requires matching endpoint/provider/public paths,
origin and raw target hashes, enabled state, verified immutable Profile metadata,
and positive independent Profile and compiled-contract revisions. These two
revision values are different identities and need not be equal. New captures
verify the independently known official origin through SHA256; an explicit
legacy `authority_equal_expected` value must also be true if supplied. Raw
Profile JSON hashes are not equated with stored canonical compiler hashes.
Metadata checks do not claim compiler validation or complete current public wire
facts.

Changing an endpoint target alone would invalidate its immutable Profile.
Proposals therefore contain no new Profile binding and no executable SQL.
Closing any migration requires the full wire comparison, an approved new bound
Profile, an atomic transition with rollback, and explicit confirmation of exact
production SQL. The helper performs none of those mutations.

Official source inputs:

- [Financial datasets OpenAPI](https://financialdatasets.ai/openapi.json)
- [Financial historical MCP server](https://github.com/financial-datasets/mcp-server/blob/08e7a3dbb949d3d99bbd6d6f3a22e5f02973ec58/server.py)
- [Polymarket CLOB OpenAPI](https://docs.polymarket.com/api-spec/clob-openapi.yaml)
- [Polymarket Data OpenAPI](https://docs.polymarket.com/api-spec/data-openapi.yaml)
- [Polymarket Gamma OpenAPI](https://docs.polymarket.com/api-spec/gamma-openapi.yaml)
- [Parallel OpenAPI](https://docs.parallel.ai/public-openapi.json)

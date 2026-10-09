# Bounded WP2 authority and route review

This review covers the fixed G001-G061 inventory once. No provider business
requests, SQL, Profile compilation/rebinding, retirement, or source adoption was
performed. The exact source/route membership and missing input are in
`scope-review.json`; raw document acquisition times and byte hashes are in
`acquisition.json`. Original downloaded public files are retained locally under
`/private/tmp/aisa-wp2-authority-20261009/raw` for independent review. These are
inspection records, not source-maintenance approval receipts.

| Fixed scope | Finding | Required input or bounded action |
| --- | --- | --- |
| FRED 35 | Existing strict converter still obtains 32 request contracts, three incomplete requests, no authoritative typed success responses. | Requiredness/type declarations for search_text/shape; frequency requiredness/default; complete response declarations for the other 32. Do not infer from samples. |
| BytePlus 6 | PullPosts has a typed ResultStruct, but no complete response envelope declaration; other five actions lack typed complete success contracts. | Exact action/version response definitions, including ResponseMetadata. No switch to another API version. |
| Similarweb 5 | Missing array-item declarations, named children under array nodes, or missing exact production authority association. One fresh demographics fetch failed TLS; old evidence is not relabelled fresh. | Correct owning field declarations/server association for these five exact v5 operations. |
| Duffel Flights 2 | Official v2 page mentions itineraries but its structured resource fields do not establish the itineraries response variant used by these routes. | An owning typed itinerary variant for both offer-request operations. |
| TikHub 2 | Export operation's official OpenAPI success schema remains `{}`; exact YouTube route is absent from that current spec. | Binary/content-type or payload declaration for export; exact legacy YouTube declaration or an explicitly approved product decision. |

No additional route can honestly be closed by registering a new source from
these current inputs. This is a finite missing-input result, not a request to
repeat the same search or open another engineering phase. Existing source
maintenance and all enabled-content gates remain unchanged.

## Nine historical routes

`historical-nine-decisions.json` retains the earlier dated narrow readback and
compatibility comparison. Its observed counts are historical, not refreshed by
this review; zero observed rows do not authorize retirement.

- 1683/G012: exact E1 SQL is now approved to root. `/company/facts/ticker` to
  `/company/facts` preserves public ANY, identity and pricing; GET source binding
  is the expected single closure. Actual execution/readback and a fresh full
  Docs assessment remain root-owned, and are not asserted here.
- 1682/G011 analyst-estimates: retain behavior; recorded successful use makes
  replacing it with another financial endpoint inappropriate. Obtain its exact
  owning legacy response definition.
- 1684/G013 crypto/prices and 1685/G014 crypto snapshot: the official MCP tools
  demonstrate legacy tool declarations, but do not establish the current exact
  full wire/response aliases. Retain behavior pending that evidence.
- 1686/G015 press releases: `/earnings` is not a prose press-release equivalent.
  Preserve the existing route unless the user selects a versioned replacement
  with its changed query and response contract.
- 1702/G016 segmented revenues: the proposed segmented income-statement route
  changes required period/ticker-or-CIK inputs and response envelope; migration
  requires that explicit compatibility choice.
- 1694/G017 institutional ownership: `/institutional-holdings` changes query
  selection/cursor semantics. Prepare an explicit migration instead of silently
  treating the newer route as an alias.
- 3880/G009 and 3881/G010 Duffel Stays: the documented fetch-all-rates action is
  POST and returns a full SearchResult. It cannot silently replace both existing
  GET contracts. Choose a new explicit action or obtain legacy GET authority;
  no automatic retirement or POST-through-GET change is authorized.

## DEC3: CLOB source matching is not runtime failure

The actual gate for endpoints 2220/G053 and 2227/G054 is
`upstream_operation_missing`: the current paths `/order/{orderID}` and `/trades`
do not match the official CLOB spec paths `/data/order/{orderID}` and
`/data/trades` at the same declared origin. Fresh official OpenAPI and owning
Python/TypeScript SDK constants agree on those `/data` paths; the bounded review
found no official declaration that the shorter paths are legacy aliases.

That does **not** establish that either current route fails or that existing
Polymarket usage is unsuccessful. Root's separate 09:49:39 UTC narrow readback
found 482 successful HTTP200 and five HTTP401 calls under the Polymarket public
prefix over 30 days; neither exact normalized template had a matched usage row.
Those aggregate observations cannot prove the behavior or authentication needs
of either individual route. No provider request was made to test that claim.

Keep current behavior and identify the missing authority precisely. No new
private-account credential system, route deactivation, or authentication/header
change follows from this documentation gap. An owning alias declaration could
permit a source-only closure; otherwise any proposed target repair remains a
separate, explicit compatibility review and user decision.

# Facebook and TikTok full response check

All **59 catalog operations** were called through AIsa: **29 Facebook** and **30 TikTok**. The earlier three calls plus this expanded run total **93 business/validation calls**. This is representative response verification, not exhaustive acceptance.

| Result | Operations |
| --- | ---: |
| Declared schema matched; no undeclared fields observed | 48 |
| Actual 200 received; AIsa candidate response schema absent | 7 |
| Success response unavailable (HTTP 502) | 1 |
| Declared constraints passed; response fields missing from docs | 3 |

All 51 operations with candidate schemas returned at least one successful sample that passed their declared JSON Schema constraints. Three operations still have undocumented fields:

- `facebook.profiles.posts`: `data.posts[].publishTime` and `data.posts[].topComments[].publishTime` (observed on both pages).
- `tiktok.profiles.handle`: `data.profile.accountCreatedAtUnix`.
- `tiktok.profiles.handle.following`: `data.accounts[].accountCreatedAtUnix`. The first empty following result hid this gap; a second public profile returned records and exposed it.

The recorded values of these missing timestamp fields were integers. These findings are not a claim about requiredness, nullability or all future values. The provider-authored source definitions were retained for review.

## The eight existing Facebook routes

Official JustOneAPI documents exist for all five underlying functions. Every downloaded OpenAPI defines the outer response and leaves `data` as `{}`. The seven successful AIsa routes returned `code`, `data`, `message`, `recordTime` and `requestId`; the captured business codes were zero.

Four POST operations matched the official outer schema. The three `-v1` GET operations did **not**: their `requestParams.query` values were strings and `requestParams.body` was null, while the official schema specified objects. This does not validate the unconstrained business data. `get-profile-id` returned HTTP 502 twice (`origin_bad_gateway`), so no success sample was obtained.

| AIsa route suffix (under `/apis/v1/facebook/`) | Official upstream documentation |
| --- | --- |
| POST `get-comment-replies` | [Comment Replies](https://docs.justoneapi.com/en/api/facebook/comment-replies-v1) |
| POST `get-post-comments`; GET `get-post-comments-v1` | [Post Comments](https://docs.justoneapi.com/en/api/facebook/post-comments-v1) |
| POST `get-profile-id` | [Get Profile ID](https://docs.justoneapi.com/en/api/facebook/get-profile-id-v1) |
| POST `get-profile-posts`; GET `get-profile-posts-v1` | [Get Profile Posts](https://docs.justoneapi.com/en/api/facebook/get-profile-posts-v1) |
| POST `search-post`; GET `search-post-v1` | [Post Search](https://docs.justoneapi.com/en/api/facebook/post-search-v1) |

## Per-operation coverage

| Operation | Result | Calls | Success samples | Next-page samples |
| --- | --- | ---: | ---: | ---: |
| `GET /apis/v1/facebook/ad-library/ads` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/ad-library/ads/search` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/ad-library/companies/ads` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/ad-library/companies/search` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/events` | Sample match | 3 | 2 | 1 |
| `GET /apis/v1/facebook/events/details` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/events/search` | Sample match | 2 | 2 | 1 |
| `POST /apis/v1/facebook/get-comment-replies` | AIsa schema absent | 1 | 1 | 0 |
| `POST /apis/v1/facebook/get-post-comments` | AIsa schema absent | 2 | 2 | 0 |
| `GET /apis/v1/facebook/get-post-comments-v1` | AIsa schema absent | 2 | 2 | 0 |
| `POST /apis/v1/facebook/get-profile-id` | HTTP 502 | 2 | 0 | 0 |
| `POST /apis/v1/facebook/get-profile-posts` | AIsa schema absent | 1 | 1 | 0 |
| `GET /apis/v1/facebook/get-profile-posts-v1` | AIsa schema absent | 1 | 1 | 0 |
| `GET /apis/v1/facebook/groups` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/groups/posts` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/marketplace/items` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/marketplace/locations/search` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/marketplace/search` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/posts` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/posts/comments` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/posts/comments/replies` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/posts/transcript` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/profiles` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/facebook/profiles/events` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/profiles/photos` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/facebook/profiles/posts` | Undocumented fields | 2 | 2 | 1 |
| `GET /apis/v1/facebook/profiles/reels` | Sample match | 3 | 3 | 1 |
| `POST /apis/v1/facebook/search-post` | AIsa schema absent | 1 | 1 | 0 |
| `GET /apis/v1/facebook/search-post-v1` | AIsa schema absent | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/ad-library/ads` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/ad-library/ads/search` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/collections/videos` | Sample match | 2 | 1 | 0 |
| `GET /apis/v1/tiktok/feed/trending` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/live` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/music/{clipId}/videos` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/products` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/products/reviews` | Sample match | 2 | 2 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}` | Undocumented fields | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/audience` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/engagement` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/followers` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/profiles/{handle}/following` | Undocumented fields | 2 | 2 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/live` | Sample match | 4 | 4 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/region` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/showcase-products` | Sample match | 2 | 2 | 0 |
| `GET /apis/v1/tiktok/profiles/{handle}/videos` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/search` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/search/hashtags` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/search/suggestions` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/search/top` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/shop/products` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/shop/products/search` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/songs` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/users/search` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/videos` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/videos/comments` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/videos/comments/replies` | Sample match | 2 | 2 | 1 |
| `GET /apis/v1/tiktok/videos/download` | Sample match | 1 | 1 | 0 |
| `GET /apis/v1/tiktok/videos/transcript` | Sample match | 1 | 1 | 0 |

## Evidence and limits

The [JSON report](facebook-tiktok-full-response-check-20261110.json) contains all 59 coverage rows, sanitized sample results, schema/response digests, the five official document URLs and hashes, and the independent JustOneAPI envelope checks.

TikTok Live was exercised using IDs from the official example and returned `lookupStatus: found`. Available pagination was exercised using returned cursors. The two initially reported routes also returned HTTP 400 when the required URL was omitted. This does not cover every error or parameter combination.

Known customer settlement headers sum to **USD 1.961315**, including the earlier USD 0.042. Four calls had no settlement header; absence does not prove zero charge. No wallet reconciliation is claimed.

The PR remains a draft. These results do not authorize merging, promotion or publication.

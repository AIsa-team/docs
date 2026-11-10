# AIsa customer API response verification

The final generated documentation now defines successful responses for all
59 scoped operations: 29 Facebook and 30 TikTok. The previously published AIsa
documents had 59 empty success schemas. The corrected English and Chinese
provider documents and the consolidated JSON/YAML contain the new definitions.
This is a draft change, not a production publication.

The acceptance criterion is what a customer receives from the AIsa API.
The [validation report](aisa-final-response-validation.json) checks 101 actual
successful responses across all 59 operations against the final generated AIsa
OpenAPI files: zero schema mismatches and zero missing fields within declared
field structures. The complete request record contains 106 calls, including
five previously recorded unsuccessful validation/diagnostic requests.

## Eight Facebook operations

All eight have successful, nonempty business responses. Their schemas include
the observed business fields, not just the outer envelope. Optional fields are
not made required from samples; null-only values and native detail dictionaries
remain open rather than inventing unobserved types.

| Route under `/apis/v1/facebook/` | Successful samples | Nonempty samples |
| --- | ---: | ---: |
| POST `get-comment-replies` | 3 | 1 |
| POST `get-post-comments` | 7 | 1 |
| POST `get-profile-id` | 1 | 1 |
| POST `get-profile-posts` | 1 | 1 |
| POST `search-post` | 2 | 2 |
| GET `get-post-comments-v1` | 3 | 1 |
| GET `get-profile-posts-v1` | 2 | 2 |
| GET `search-post-v1` | 2 | 2 |

The reply check changed only `comment_id`, keeping the same `post_id` and
`expansion_token`: the parent comment's opaque `comment_id` returned an empty
list; its numeric-string `legacy_comment_id` returned one reply. Both customer
pages now instruct callers to use `legacy_comment_id` as the request's
`comment_id`. These are two representations of the parent comment, not two
interchangeable parameters.

The three GET definitions now declare `requestParams.query` values as strings
and `requestParams.body` as null. Comments and replies declare `reactions_count`
as a string; posts declare it as an integer. Success and nonzero business-code
responses are separate schema branches so an error's `data` is not forced into
the successful result structure.

## Other response corrections

Four fields returned by AIsa are now documented as integers:

- Facebook profile posts: `data.posts[].publishTime`.
- Facebook profile posts: `data.posts[].topComments[].publishTime`.
- TikTok profile: `data.profile.accountCreatedAtUnix`.
- TikTok following: `data.accounts[].accountCreatedAtUnix`.

Existing TikTok native `details` and `product` maps explicitly allow arbitrary
keys. Their raw native keys are not an enumerated field contract. This does not
mean the enclosing API response is an empty schema.

## Validation and limits

The [eight-route evidence](aisa-customer-response-check.json) records sample
hashes, sample counts, fields with only null/empty observations, the reply-ID
comparison, and source bindings. Raw customer response bodies, API keys, request
IDs and cursors remain outside Git. The [final replay](aisa-final-response-validation.json)
records each sample's match against the generated customer document.

The four English/Chinese provider documents pass OpenAPI validation. All 59
consolidated responses match the provider documents. Regression tests check the
final files, concrete invalid field types, source recomposition, unchanged POST
request/pricing/error contracts, and matching Chinese response structures.

The current release's Facebook/TikTok provider-file hashes match the complete
verified acquisition used for composition. A new full-release acquisition timed
out; no current full-release acquisition is claimed. Full repository staging
reported a separate Twitter readiness failure and thousands of unrelated
changes; only the scoped generated files were applied. No gate, formal
publication receipt or production API behavior was changed. Passing these
samples does not claim exhaustive coverage of every data variant or error.

This review supersedes the earlier eight-route envelope-only review and its
empty-comment/reply limitations. Keep the PR draft; do not merge automatically.

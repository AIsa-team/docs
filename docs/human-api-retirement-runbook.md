# Legacy X human documentation retirement

The fixed eight method/path entries in `docs/human-api-retirements.json` are an editorial retirement policy. They are not runtime facts, a provider-wide ban on Twitter data, or formal publication authorization.

`pull_openapi.stage(with_pages=True)` applies the policy after generation. `sync_prod_runtime_docs.generate` reapplies it after historical navigation preservation. Both replace regenerated legacy pages (including newly selected slugs for those exact routes) with non-executable archived pages and remove their active navigation links. The existing eight URLs remain reachable as migration notices; no OpenAPI playground is attached. The bilingual migration guide is authored separately.

Do not edit `openapi/*.json`, `reference-contracts/*.json`, upstream source receipts, immutable snapshots or current publication pointers to simulate a runtime disable or new Social catalog publication. Their historical bytes remain unchanged in this change. The strict Composer/readiness gates are unchanged. Removing this editorial policy requires explicit review; a stale snapshot with enabled old routes must not restore their instructions.

Replacement route mapping was checked against Services candidate `b5c8537d1da3616ea6a933e3e1a075b929c52499`: Social Connect, posts/media operations and the five X-specific action routes. The guide distinguishes reviewed capabilities from deployment and formal discovery. Release coordination must verify the corresponding Social service/catalog activation and the separate ToolRouter retirement before claiming end-to-end cutover. Existing legacy credentials need fresh Social Connect authorization; no automatic token or native-ID alias is permitted.

Validation: run `test_human_api_retirements.py`, `test_prod_runtime_docs.py`, `check_nav_integrity.py`, and `validate_prod_reference_pages.py`; check that formal contract/source/publication files have no diff. New aliases introduced by generation are tested by method/path rather than an assumed filename. No provider calls or fresh runtime capture are needed for this editorial change.

## Overseas social reference retirement (2026-11-08)

`docs/human-api-retirements-social-overseas.json` is a second editorial policy loaded by the same `apply_retirements` (every `docs/human-api-retirements*.json` file is read; a route may appear in only one policy). It covers exactly the 147 overseas `/apis/v1/tikhub/...` method/path entries disabled in production by the 2026-11-08 overseas retirement manifest (Instagram, TikTok, X, YouTube, LinkedIn, Reddit, Threads, Telegram). Domestic routes (Douyin, Xiaohongshu, Weibo, Bilibili and others) and the overseas routes outside that manifest are not listed and keep their pages unchanged.

This policy supplies its own bilingual `notice` and `replacement_label` instead of a shared `guide`. Each row carries a `replacement` (method, path and reference page) naming the neutral AIsa endpoint with the same function; the archived page shows the retired route and links to that replacement in the same language. A policy without `notice` keeps the legacy X text and guide link byte-for-byte. Replacement pages were resolved from the `openapi:` frontmatter of the generated API reference pages; `test_human_api_retirements.py` checks that every replacement page exists in both languages, stays in navigation and is not itself retired, and that the committed archives and navigation are a fixed point of all policies.

As with the X retirement, this does not edit `openapi/*.json`, `reference-contracts`, receipts, snapshots or publication pointers. The validation list above applies unchanged.

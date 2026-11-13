"""Frozen catalog prose for pricing cleanup regressions; never publication input."""

BUSINESS_PRICE_DESCRIPTIONS = {'/apis/v1/notion-com/developer-documentation/get-pricing': "Notion's plans and prices from "
                                                            'www.notion.com/pricing in one call: each plan '
                                                            'card (Free, Plus, Business, Enterprise) with '
                                                            'its description, the price as displayed, and '
                                                            'both the monthly-billing and annual-billing '
                                                            "list prices from the page's embedded price "
                                                            'table (annual as the yearly total and per '
                                                            'month), so no billing toggle is needed. Also '
                                                            'other priced products on the page (Notion AI '
                                                            'add-on, AI credit packs, Sites custom domains, '
                                                            'the student plan) and the feature comparison '
                                                            "grid (section, feature, tooltip and each plan's "
                                                            'value or check mark). Prices are in the '
                                                            'currency the page serves (USD for US '
                                                            'visitors).\n'
                                                            '\n'
                                                            'The response contains the tool result '
                                                            'directly.\n'
                                                            '\n'
                                                            'The provider identifies `plans` as the primary '
                                                            'payload key.\n'
                                                            '\n'
                                                            '| Documented field | Provider type | '
                                                            'Description |\n'
                                                            '| --- | --- | --- |\n'
                                                            '| `annual_price` | number | Per seat per year '
                                                            'when billed annually. |\n'
                                                            '| `annual_price_id` | string |  |\n'
                                                            '| `annual_price_per_month` | number | '
                                                            'annual_price / 12. |\n'
                                                            '| `description` | string |  |\n'
                                                            '| `display_price` | string | Price as shown on '
                                                            'the card, e.g. `$10` (annual billing per member '
                                                            'per month) or `Custom pricing`. |\n'
                                                            '| `display_unit` | string | e.g. `per member / '
                                                            'month`. |\n'
                                                            '| `key` | string | Lowercase plan id, e.g. '
                                                            '`plus`. |\n'
                                                            '| `monthly_price` | number | Per seat per month '
                                                            'when billed monthly. |\n'
                                                            '| `monthly_price_id` | string |  |\n'
                                                            '| `plan` | string |  |\n'
                                                            '| `recommended` | boolean |  |\n'
                                                            '\n'
                                                            '\n'
                                                            "These are the provider's documented fields. "
                                                            'Field requiredness, nullability and nested '
                                                            'object structures are specified only where the '
                                                            'descriptions explicitly say so.',
 '/apis/v1/play-google-com/media/app': 'One Android app on Google Play: title, summary, description, '
                                       'developer (name, id, page, website, support email), icon, header '
                                       'image, screenshots, categories, content rating, install counts, '
                                       'price and in-app purchase range, release and last-update dates, '
                                       "version, what's new, privacy policy link, aggregate rating with "
                                       'histogram and review count, chart badge, and the `Similar apps` '
                                       'cluster the page embeds. Written reviews come from `app_reviews`.\n'
                                       '\n'
                                       'The response contains the tool result directly.\n'
                                       '\n'
                                       '| Documented field | Provider type | Description |\n'
                                       '| --- | --- | --- |\n'
                                       '| `categories` | object[] | Store categories of the app (name, '
                                       'category id, URL). |\n'
                                       '| `chart` | object | Top-chart badge when the page shows one. |\n'
                                       '| `content_rating` | string | Content rating label (`Everyone`, '
                                       '`Teen`). |\n'
                                       '| `content_rating_notes` | string | Content rating descriptor '
                                       '(`Users Interact`). |\n'
                                       '| `currency` | string | ISO 4217 currency of the storefront. |\n'
                                       '| `description_html` | string | Full description as the store '
                                       'carries it (HTML line breaks). |\n'
                                       '| `developer_email` | string | Developer support email as listed on '
                                       'the store page. |\n'
                                       '| `developer_id` | string | Numeric developer id when the page '
                                       'carries one. |\n'
                                       '| `developer_name` | string |  |\n'
                                       '| `developer_url` | string | Developer page '
                                       '(`/store/apps/developer?id=<name>`); feed the name to '
                                       '`developer_apps`. |\n'
                                       '| `developer_website` | string | Developer website link. |\n'
                                       '| `free` | boolean | True when the store price is zero. |\n'
                                       '| `header_image_url` | string | Feature graphic. |\n'
                                       '| `icon_url` | string | App icon. |\n'
                                       '| `in_app_purchases` | string | In-app purchase price range as '
                                       'displayed (`$0.40 - $199.99 per item`); null when none. |\n'
                                       '| `installs_display` | string | Install bucket as displayed '
                                       '(`10,000,000,000+`). |\n'
                                       "| `installs_estimate` | number | The store's install count estimate "
                                       'behind the bucket. |\n'
                                       '| `installs_min` | number | Lower bound of the install bucket. |\n'
                                       '| `observed_at_ms` | number | When the program read the source, '
                                       'milliseconds since the Unix epoch. |\n'
                                       '| `package` | string |  |\n'
                                       '| `price_display` | string | Price as displayed; null for free apps '
                                       '(the store shows an empty label). |\n'
                                       '| `price_micros` | number | Store price in micros of `currency`; 0 '
                                       'for free apps; null when the page carries no offer. |\n'
                                       '| `privacy_policy_url` | string | Privacy policy link. |\n'
                                       '| `rating` | object | Aggregate rating across all devices (record '
                                       'slot 51); null when the store shows no ratings for the app. |\n'
                                       "| `recent_changes_html` | string | What's new text (HTML line "
                                       'breaks). |\n'
                                       '| `released` | string | Release date as displayed. |\n'
                                       '| `released_at_ms` | number | Release timestamp, milliseconds since '
                                       'the Unix epoch. |\n'
                                       '| `screenshots` | string[] |  |\n'
                                       '| `similar` | object[] | Related app clusters the detail page shows '
                                       'inline (`Similar apps`), up to the items the page embeds. |\n'
                                       '| `source_url` | string | Store page the data was read from. |\n'
                                       '| `summary` | string | Short promotional line. |\n'
                                       '| `title` | string |  |\n'
                                       '| `updated` | string | Last update date as displayed. |\n'
                                       '| `updated_at_ms` | number | Last update timestamp, milliseconds '
                                       'since the Unix epoch. |\n'
                                       '| `url` | string | Canonical store details URL. |\n'
                                       '| `version` | string | Current version string; null when the store '
                                       'says it varies with device. |\n'
                                       '\n'
                                       '\n'
                                       "These are the provider's documented fields. Field requiredness, "
                                       'nullability and nested object structures are specified only where '
                                       'the descriptions explicitly say so.',
 '/apis/v1/littlecaesars-com/restaurants/get-delivery-fee': 'Delivery fee quote for a US street address '
                                                            '(POST /api/v1/store/{n}/can-deliver, the order '
                                                            "app's delivery eligibility check): the delivery "
                                                            'fee, service fee rate, small order fee and its '
                                                            'threshold, minimum order and estimated delivery '
                                                            'time. Without `location_number` the delivering '
                                                            'store is resolved first (POST '
                                                            '/api/v1/search/find-delivery-store). No cart, '
                                                            'order or payment is created. An address the '
                                                            'site will not deliver to returns `fee_status: '
                                                            'not_deliverable` with null fees.\n'
                                                            '\n'
                                                            'The response contains the tool result '
                                                            'directly.\n'
                                                            '\n'
                                                            '| Documented field | Provider type | '
                                                            'Description |\n'
                                                            '| --- | --- | --- |\n'
                                                            '| `address_validated` | boolean | True when the '
                                                            'site accepted the address for delivery. |\n'
                                                            '| `currency` | string |  |\n'
                                                            '| `delivery_address` | object | The address '
                                                            'that was quoted, as sent. |\n'
                                                            '| `delivery_fee` | number | Delivery fee in USD '
                                                            '(deliveryFees.vendorFee, the amount the order '
                                                            "app's fee disclaimer quotes). Null when no fee "
                                                            'is published or the address is not deliverable. '
                                                            '|\n'
                                                            '| `estimated_delivery_time` | string | Delivery '
                                                            'estimate as the site words it, e.g. 33-38 min. '
                                                            '|\n'
                                                            '| `fee_status` | string | available: a fee was '
                                                            'quoted. not_published: the store accepted the '
                                                            'address but returned no fee. not_deliverable: '
                                                            'no store delivers to the address. |\n'
                                                            '| `lce_delivery_fee` | number | Additional '
                                                            'Little Caesars delivery fee component '
                                                            '(lceDeliveryFee), 0 when none. |\n'
                                                            '| `location_number` | number | Store that '
                                                            'quoted the fee; null when no store delivers to '
                                                            'the address. |\n'
                                                            '| `minimum_order_amount` | number | Minimum '
                                                            'delivery subtotal (minimumDeliveryThreshold), 0 '
                                                            'when none. |\n'
                                                            '| `observed_at_ms` | number | Milliseconds '
                                                            'since the Unix epoch when this result was '
                                                            'fetched. |\n'
                                                            '| `quote_type` | string |  |\n'
                                                            '| `service_fee_rate` | number | Service fee as '
                                                            'a fraction of the order subtotal '
                                                            "(lceServiceFee, 0.12 = 12%). The order app's "
                                                            'disclaimer caps it at $4.00. |\n'
                                                            '| `small_order_fee` | number | Fee added to '
                                                            'orders under small_order_fee_threshold, unless '
                                                            'a promotion waives it. |\n'
                                                            '| `small_order_fee_threshold` | number | '
                                                            'Subtotal under which the small order fee '
                                                            'applies. |\n'
                                                            '| `source` | string | The endpoint that '
                                                            'answered. |\n'
                                                            "| `status_message` | string | The site's "
                                                            'message when the address is not deliverable. |\n'
                                                            '| `store_source` | string | Whether the store '
                                                            'came from the input or was resolved from the '
                                                            'address. |\n'
                                                            '\n'
                                                            '\n'
                                                            "These are the provider's documented fields. "
                                                            'Field requiredness, nullability and nested '
                                                            'object structures are specified only where the '
                                                            'descriptions explicitly say so.'}

SUPPLIER_CREDIT_DESCRIPTIONS = {'source_commit': '8547b4f3972a9c0f8a4b29290a70b9e3ff605984',
 'scope': 'Public API request descriptions and billing prose, before credit tariff cleanup',
 'cases': [{'page': 'api-reference/companyenrich/companyenrich-enrich-by-properties.mdx',
            'before': 'Expandable response fields. Repeat the parameter to request multiple expansions. '
                      'Supported values: workforce (adds the workforce field; costs 5 credits per company).'},
           {'page': 'api-reference/companyenrich/companyenrich-people-search-scroll.mdx',
            'before': '1-100. THIS IS THE PRICE — 2 credits per person returned'},
           {'page': 'api-reference/companyenrich/companyenrich-enrich-companies.mdx',
            'before': 'Expandable response fields. Repeat the parameter to request multiple expansions. '
                      'Supported values: `workforce` (adds the `workforce` field; costs 5 credits per '
                      'company).'},
           {'page': 'api-reference/companyenrich/companyenrich-find-similar-companies.mdx',
            'before': 'Expandable response fields. Supported values: workforce (adds the workforce field; '
                      'costs 5 more credits per company).'},
           {'page': 'api-reference/companyenrich/companyenrich-companies-search-scroll.mdx',
            'before': '1-100. THIS IS THE PRICE — 1 credit per company returned'},
           {'page': 'api-reference/pinterest/get_pinterest-pin.mdx',
            'before': 'If we have a response in the cache that is this many days old or newer, return the '
                      'cached response (0 credits, with "cached": true and a "cached_at" timestamp). '
                      'Otherwise, scrape a live result (1 credit). [See the Caching page for '
                      'details.](https://docs.scrapecreators.com/caching)'},
           {'page': 'api-reference/crustdata/crustdata-companies-enrich.mdx',
            'before': 'field groups to return; technographics adds 2 credits when data is returned'},
           {'page': 'api-reference/prospeo/prospeo-bulk-enrich-people.mdx',
            'before': 'Request mobile enrichment for every record. WARNING: each found mobile costs 10 '
                      'credits and also includes email enrichment.'},
           {'page': 'api-reference/prospeo/prospeo-bulk-enrich-people.mdx',
            'before': 'Return only records with a verified mobile. Setting true enables enrich_mobile and '
                      'may cost 10 credits per found mobile.'},
           {'page': 'api-reference/prospeo/prospeo-enrich-person.mdx',
            'before': 'Request mobile enrichment. WARNING: a found mobile costs 10 credits and also includes '
                      'email enrichment.'},
           {'page': 'api-reference/prospeo/prospeo-enrich-person.mdx',
            'before': 'Return a record only when it has a verified mobile. Setting true enables '
                      'enrich_mobile; a found mobile may therefore cost 10 credits.'},
           {'page': 'api-reference/search/post_firecrawl-map.mdx',
            'before': 'List the URLs reachable from a starting page, without fetching any content. `url` and '
                      '`limit` are both required (limit 1 to 100000). Returns `success`, a request `id`, and '
                      '`links[]` with `url` and `title` — note these are **objects with a title**, unlike '
                      '[`post_tavily_map`](/api-reference/search/post_tavily-map) which returns bare '
                      'strings. Measured at about 9 seconds. Billed 1 credit per discovered link, so `limit` '
                      'is a cost control, not just a page control. Use it to size a site before paying to '
                      'crawl it, then fetch only what matters with '
                      '[`post_firecrawl_scrape`](/api-reference/search/post_firecrawl-scrape). When you want '
                      'content and structure in one pass, '
                      '[`post_firecrawl_crawl`](/api-reference/search/post_firecrawl-crawl).'},
           {'page': 'api-reference/people-data-labs/people-data-labs-companies-search.mdx',
            'before': 'records to return, 1-100, default 1 — you pay 1 credit per record'},
           {'page': 'api-reference/people-data-labs/people-data-labs-people-search.mdx',
            'before': 'records to return, 1-100, default 1 — THIS IS THE PRICE DIAL: you pay 1 credit per '
                      'record'},
           {'page': 'api-reference/people-data-labs/people-data-labs-company-search.mdx',
            'before': 'Request 1-2 companies per call, costing 50 credits per returned company. PDL supports '
                      '1-100 upstream, but Exchange authorization is capped at 100 credits, so callers must '
                      'use size 1 or 2.\n'
                      '\n'
                      'Provider reference: minimum 1; maximum 100; default 1.'},
           {'page': 'api-reference/oriane/oriane-tiktok-posts-search.mdx',
            'before': 'Response detail and fixed price per nonempty call: basic 35 credits, default 50 '
                      'credits, full 65 credits. Empty results cost zero. Result limit does not change the '
                      'tier price.\n'
                      '\n'
                      'Provider reference: allowed values ["basic", "default", "full"]; default "default".'},
           {'page': 'api-reference/findymail/findymail-search-reverse-email.mdx',
            'before': 'true returns the enriched profile instead of just the profile URL — and DOUBLES the '
                      'price to 2 credits'},
           {'page': 'api-reference/supadata/supadata-search-youtube.mdx',
            'before': 'Maximum number of results to return. Default is 10, max is 5000. Costs 1 credit per '
                      'page of about 20 results.'},
           {'page': 'api-reference/fullenrich/fullenrich-people-search.mdx',
            'before': 'Records per page, up to 6. Each returned record costs 5 credits. Use pagination for '
                      'more.\n'
                      '\n'
                      'Provider reference: minimum 1; maximum 6; default 2.'},
           {'page': 'api-reference/seranking/seranking-google-keywords-ideas.mdx',
            'before': 'COST DIAL — rows to return; default 100 at 10 credits each = 1,000 credits'},
           {'page': 'api-reference/predict-leads/predict-leads-get-similar-companies.mdx',
            'before': 'Maximum similar-company records on this page (1-50). Each returned record costs 1 '
                      'credit; default 5.'},
           {'page': 'api-reference/predict-leads/predict-leads-companies-similar.mdx',
            'before': 'default 20, max 50 — PRICE DIAL: 1 credit per company returned'},
           {'page': 'api-reference/predict-leads/predict-leads-technologies-list.mdx',
            'before': 'default 100, max 1000 — PRICE DIAL: this route is 3 credits PER RECORD, the most '
                      'expensive in the file'},
           {'page': 'api-reference/cnpja/get_cnpja-office-lookup.mdx',
            'before': '**Billing: per call (1 credit per lookup).** Current prices are on '
                      '[aisa.one/api](https://aisa.one/api). The "not registered" **HTTP 404** result '
                      'returns a valid JSON body and is still billed 1 credit; only 429, 5xx, and network '
                      'errors are not billed. (A **400** validation error is a client-side rejection.)'},
           {'page': 'api-reference/tomba/tomba-companies-emails-list.mdx',
            'before': 'Start with 10 (the default): 1 and 10 both cost 1 credit. Non-empty pages cost '
                      'ceil(limit/10) credits even when partially filled. Tested values: 1, 10, 20, 50; 30 '
                      'is rejected. Check meta.total before requesting more pages'},
           {'page': 'api-reference/instagram/get_instagram-post.mdx',
            'before': 'Set to true to download the video/images and get back permanent Supabase URLs. Costs '
                      '10 credits if media is found, 1 credit otherwise.'},
           {'page': 'api-reference/instagram/get_instagram-media-transcript.mdx',
            'before': "Paid opt-in, enabled only by the literal query value 'true' "
                      '(allow_long_transcription=true). Defaults to false when omitted; other values do not '
                      'enable paid mode. By default, successful AI transcription of videos up to 120 seconds '
                      '(two minutes, inclusive) costs a flat 1 credit per request. Over 120 seconds, videos '
                      'cannot be AI-transcribed by default. Set allow_long_transcription=true to opt into '
                      'paid AI with no fixed duration cap: ALL successful AI transcriptions in this mode '
                      'cost 10 credits per started minute, including short videos: 10 * '
                      'ceil(duration_seconds / 60). For example, 177 seconds costs 30 credits and an '
                      'opted-in 60 seconds costs 10 credits. Empty AI results and errors cost 0 credits for '
                      'AI transcription. This flag does not force AI and does not enable transcription or AI '
                      'fallback by itself. Keep get_transcript=true or use_ai_as_fallback=true where '
                      'required by the endpoint. Returned native captions still cost 1 credit on dedicated '
                      'transcript routes, even for long videos with this flag; on detail routes they leave '
                      'the base price unchanged. These routes remain synchronous. Allow at least 30 seconds '
                      'on your client. Paid long transcription can exceed resource limits or timeouts, so '
                      'successful transcription of long videos is not guaranteed.\n'
                      '\n'
                      'Provider reference (supplier schema): `{"default":false,"type":"boolean"}`.'},
           {'page': 'api-reference/instagram/get_instagram-media-transcript.mdx',
            'before': 'If we have a response in the cache that is this many days old or newer, return the '
                      'cached response (0 credits, with "cached": true and a "cached_at" timestamp). '
                      'Otherwise, scrape a live result (By default, successful AI up to 120 seconds costs a '
                      'flat 1 credit per request; over 120 seconds requires allow_long_transcription=true, '
                      'which bills ALL successful AI at 10 credits per started minute, including short '
                      'videos; empty AI results and errors cost 0 credits). [See the Caching page for '
                      'details.](https://docs.scrapecreators.com/caching)'},
           {'page': 'api-reference/instagram/get_instagram-post-comments.mdx',
            'before': 'Set to true to include replies for every returned comment. This always costs 15 '
                      'credits because each comment requires a separate Instagram replies request. You will '
                      'still be charged 15 credits if no replies are returned. This is much slower and may '
                      'time out at 29 seconds.'}]}

SUPPLIER_CREDIT_OPERATIONS = {'source_ref': '8547b4f3972a9c0f8a4b29290a70b9e3ff605984',
 'cases': [{'source': 'openapi/adyntel.json',
            'path': '/paths//apis/v1/adyntel/tiktok-ads-library-search-company/post/requestBody/content/application/json/schema/properties/influencer_ads/description',
            'before': 'Adds one credit when true.',
            'retain': ['true']},
           {'source': 'openapi/olostep.json',
            'path': '/paths//apis/v1/olostep/web-map-search/post/description',
            'before': 'Olostep bills one credit for the first 1,000 returned URLs and another credit per '
                      'additional 1,000. Requiring top_n <= 1,000 makes the platform hold exact. Unbounded '
                      "mapping is available through a team's own raw Olostep tool.",
            'retain': ['top_n <= 1,000', 'Unbounded mapping']},
           {'source': 'openapi/olostep.json',
            'path': '/paths//apis/v1/olostep/web-map-search/post/requestBody/content/application/json/schema/properties/top_n/description',
            'before': "The 1,000-URL cap keeps this request inside Olostep's first one-credit map band.",
            'retain': ['1,000-URL cap']},
           {'source': 'openapi/olostep.json',
            'path': '/paths//apis/v1/olostep/web-scrape/post/description',
            'before': 'This is the fixed one-credit surface. Olostep parsers and LLM extraction are not '
                      'accepted by this catalog tool; a team can call them directly through its own raw '
                      'Olostep tool.',
            'retain': ['Olostep parsers and LLM extraction are not accepted']},
           {'source': 'openapi/olostep.json',
            'path': '/paths//apis/v1/olostep/web-scrape/post/requestBody/content/application/json/schema/properties/formats/description',
            'before': 'Structured parsers, JSON extraction and llm_extract are deliberately excluded because '
                      'they have separate variable credit prices.',
            'retain': ['Structured parsers, JSON extraction and llm_extract']},
           {'source': 'openapi/olostep.json',
            'path': '/paths//apis/v1/olostep/web-search/post/description',
            'before': 'The five-credit base search is exposed. scrape_options is deliberately excluded '
                      'because it adds one or more scrape credits for every returned page.',
            'retain': ['scrape_options is deliberately excluded']},
           {'source': 'openapi/leadmagic.json',
            'path': '/paths//apis/v1/leadmagic/b2b-ads-search/post/description',
            'before': 'at least one of company_domain | company_name is required. Cost VERIFIED 2026-08-13 '
                      'as 0.2 credit per ad + a 0.2 base (= 0.2 x (ads+1)): a 5-ad response cost 1.20 '
                      'credits, a 24-ad response 5.00. Responses appear to cap near 24 ads, so a full page '
                      'is ~5 credits. The response header X-Credits-Max-Cost shows the reserved amount '
                      'before committing',
            'retain': ['company_domain | company_name is required', 'cap near 24 ads', 'X-Credits-Max-Cost']},
           {'source': 'openapi/leadmagic.json',
            'path': '/paths//apis/v1/leadmagic/people-phone-find/post/description',
            'before': 'at least one identifier is required. This is the most expensive endpoint in the file '
                      'at 5 credits a hit — and mobile numbers are regulated contact data (TCPA / CASL), so '
                      'treat the result accordingly',
            'retain': ['at least one identifier is required',
                       'mobile numbers are regulated contact data (TCPA / CASL)']},
           {'source': 'openapi/influencersclub.json',
            'path': '/paths//apis/v1/influencersclub/creators-audience-overlap/post/description',
            'before': 'returns per-creator overlap and unique-audience percentages plus report totals '
                      '(total_followers, total_unique_followers). The body echoes credits_cost and '
                      'credits_left. One flat credit whether you compare 2 creators or 10 — batch the '
                      'comparison',
            'retain': ['per-creator overlap', 'credits_cost', 'credits_left', 'compare 2 creators or 10']},
           {'source': 'openapi/influencersclub.json',
            'path': '/paths//apis/v1/influencersclub/creators-enrich-full/post/description',
            'before': 'everything the profile (0.2) and analytics (0.8) tiers return, in one 1-credit call — '
                      'the same price as calling both. Use profile alone for contact lists and analytics '
                      'alone for vetting; full when you need both',
            'retain': ['everything the profile', 'analytics', 'Use profile alone for contact lists']},
           {'source': 'openapi/scrape-creators.json',
            'path': '/paths//apis/v1/instagram/post/get/description',
            'before': 'Returns full metadata for one public post or reel identified by its URL, under '
                      'data.xdt_shortcode_media: shortcode, is_video, video_url, video_duration, has_audio, '
                      'display_url, dimensions, accessibility_caption, edge_media_to_caption for the caption '
                      'text, and owner. Measured at about 197 KB. Setting download_media=true also mirrors '
                      'the media to permanent storage and costs ten credits rather than one, so leave it off '
                      'unless the files are needed. For the comment thread call get_instagram_post_comments '
                      'with the same URL, and for the spoken words in a video call '
                      'get_instagram_media_transcript.',
            'retain': ['download_media=true',
                       'permanent storage',
                       'leave it off unless the files are needed']},
           {'source': 'openapi/scrape-creators.json',
            'path': '/paths//apis/v1/instagram/post/get/parameters/1/description',
            'before': 'Set to true to download the video/images and get back permanent Supabase URLs. Costs '
                      '10 credits if media is found, 1 credit otherwise.',
            'retain': ['permanent Supabase URLs', 'if media is found']},
           {'source': 'openapi/context-dev.json',
            'path': '/paths//apis/v1/context-dev/web-search/post/requestBody/content/application/json/schema/properties/numResults/description',
            'before': 'The curated tool requests ten results at most, bounding the search at one credit.',
            'retain': ['ten results at most']},
           {'source': 'openapi/hunter.json',
            'path': '/paths//apis/v1/hunter/companies-emails/get/parameters/6/schema/description',
            'before': 'emails to return, default 10, max 100 — THIS IS THE PRICE DIAL: 1 search credit per '
                      '10 returned',
            'retain': ['emails to return, default 10, max 100']},
           {'source': 'openapi/hunter.json',
            'path': '/paths//apis/v1/hunter/people-enrich/get/description',
            'before': 'one of email | linkedin_handle is required (Hunter answers 400 when neither is sent; '
                      'treg does not pre-check this). To go the other way (name → email) use '
                      'hunter.people.email.find, which costs a full search credit. GET '
                      '/combined/find?email=… returns the person AND their company in one call at the same '
                      '0.2 rate',
            'retain': ['one of email | linkedin_handle is required',
                       'GET /combined/find',
                       'person AND their company']},
           {'source': 'openapi/serper.json',
            'path': '/paths//apis/v1/serper/google-serp-news/post/requestBody/content/application/json/schema/properties/tbs/description',
            'before': 'Google date filter. A valid but over-restrictive value can return HTTP 200 with an '
                      'empty news array and still costs one credit.',
            'retain': ['Google date filter', 'HTTP 200 with an empty news array', 'billed']},
           {'source': 'openapi/serper.json',
            'path': '/paths//apis/v1/serper/google-serp-shopping/post/description',
            'before': "Answers arrive in shopping. Serper's current playground fixes a shopping page at 40 "
                      'results and charges two credits.',
            'retain': ['Answers arrive in shopping', '40 results']},
           {'source': 'openapi/serper.json',
            'path': '/paths//apis/v1/serper/web-search/post/description',
            'before': 'Answers arrive primarily in organic. A successful HTTP 200 costs one credit even when '
                      'organic is empty; HTTP failures are unbilled. Catalog calls accept one query, while '
                      "Serper's array mini-batch remains available through a team's raw BYOK tool.",
            'retain': ['HTTP 200', 'even when organic is empty', 'HTTP failures are unbilled']},
           {'source': 'openapi/apollo.json',
            'path': '/paths//apis/v1/apollo/people/bulk_match/post/description',
            'before': 'Enrich up to 10 people in one call. Body takes `details`, an array of the same '
                      'identifier objects `post_apollo_people_match` accepts. Returns `matches` alongside '
                      '`status`, `total_requested_enrichments`, `unique_enriched_records`, `missing_records` '
                      'and `credits_consumed` — read `missing_records` rather than assuming every input '
                      'matched. Costs one credit per record enriched, not per call. Use this over a loop of '
                      'single calls: same credits, one round trip. For a single person '
                      '`post_apollo_people_match` is simpler.',
            'retain': ['Enrich up to 10 people', 'one round trip', 'post_apollo_people_match']},
           {'source': 'openapi/oriane.json',
            'path': '/paths//apis/v1/oriane/instagram/post-lookup/post/description',
            'before': "Resolve a canonical Instagram post/video URL against Oriane's index. Instagram uses "
                      'the post shortcode; TikTok uses the numeric video ID. Empty results do not trigger '
                      'ingestion. Choose projection: basic 35 credits, default 50 credits, full 65 credits '
                      'per nonempty call. Search limit is at most 100; URL lookup targets one record. Empty '
                      'results cost zero.',
            'retain': ['Choose projection: basic',
                       'default',
                       'full',
                       'at most 100',
                       'Empty results cost zero']},
           {'source': 'openapi/prospeo.json',
            'path': '/components/schemas/Manual576A0Ea506F3_connect_PROSPEO_ENRICH_PERSON/properties/only_verified_mobile/description',
            'before': 'Return a record only when it has a verified mobile. Setting true enables '
                      'enrich_mobile; a found mobile may therefore cost 10 credits.',
            'retain': ['Return a record only when it has a verified mobile',
                       'Setting true enables enrich_mobile']},
           {'source': 'openapi/icypeas.json',
            'path': '/paths//apis/v1/icypeas/companies-enrich/get/description',
            'before': 'SYNCHRONOUS — the company arrives in `result`, including a structured postal address '
                      'and an employee-count history. At 0.5 credit this is the cheapest company record in '
                      'this file',
            'retain': ['SYNCHRONOUS', 'structured postal address', 'employee-count history']},
           {'source': 'openapi/icypeas.json',
            'path': '/paths//apis/v1/icypeas/people-enrich/get/description',
            'before': 'SYNCHRONOUS — the profile arrives in `result`, with `worksFor` (current roles) and '
                      '`alumniOf` (past roles) as arrays. The dearest of the scrape routes at 1.5 credits',
            'retain': ['SYNCHRONOUS', 'worksFor', 'alumniOf']},
           {'source': 'openapi/icypeas.json',
            'path': '/paths//apis/v1/icypeas/people-identity-resolve/post/description',
            'before': 'SYNCHRONOUS — the URL comes back in `result` with status FOUND or NOT_FOUND. THE MOST '
                      'EXPENSIVE ROUTE HERE at 10 credits a hit; resolve in bulk only when the profile is '
                      'genuinely worth it',
            'retain': ['SYNCHRONOUS', 'FOUND or NOT_FOUND']},
           {'source': 'openapi/icypeas.json',
            'path': '/paths//apis/v1/icypeas/people-identity-resolve-bulk/post/description',
            'before': 'SYNCHRONOUS — results come back in `data`, one entry per input address, in order. '
                      'Same 10-credit-per-hit rate as the single route, so a full 50-address call can cost '
                      '500 credits: check the addresses are worth it first',
            'retain': ['one entry per input address, in order']},
           {'source': 'openapi/icypeas.json',
            'path': '/paths//apis/v1/icypeas/scrape-bulk/post/description',
            'before': 'SYNCHRONOUS — `data` comes back one entry per URL, in order, each with the same '
                      'record shape as the single routes. Serves BOTH people and companies; the price '
                      'follows the type (1.5 credits per profile, 0.5 per company)',
            'retain': ['one entry per URL', 'Serves BOTH people and companies']},
           {'source': 'openapi/crustdata.json',
            'path': '/paths//apis/v1/crustdata/companies-enrich/post/description',
            'before': 'supply one identifier family. Base enrichment is 2 credits per matched company; '
                      'technographics can raise it to 4.',
            'retain': ['supply one identifier family']},
           {'source': 'openapi/crustdata.json',
            'path': '/paths//apis/v1/crustdata/people-enrich/post/description',
            'before': 'supply profile URLs or business emails. Base profile costs 1 credit; all add-ons can '
                      'bring one record to 7.',
            'retain': ['supply profile URLs or business emails']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/google-keywords-ideas/get/description',
            'before': 'Three sibling endpoints share this exact parameter shape and price and differ only in '
                      'how\n'
                      'they pick the ideas: /v1/keywords/related (semantically related, this entry),\n'
                      '/v1/keywords/similar (same-SERP overlap) and /v1/keywords/questions (question '
                      'phrasings).\n'
                      '/v1/keywords/longtail is the cheap one at 1 credit per keyword, but returns bare '
                      'strings\n'
                      'with no metrics.',
            'retain': ['/v1/keywords/longtail', 'returns bare strings', 'with no metrics']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/google-keywords-ideas/get/parameters/3/schema/description',
            'before': 'COST DIAL — rows to return; default 100 at 10 credits each = 1,000 credits',
            'retain': ['rows to return', 'default 100']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/web-anchors-list/get/parameters/0/schema/description',
            'before': 'COST DIAL — 1 to 10,000, one credit per returned anchor',
            'retain': ['1 to 10,000']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/web-backlinks-list/get/description',
            'before': 'returns a `backlinks` array. For bulk extraction use /v1/backlinks/raw instead — same '
                      '1-credit-per-row price but a cursor (`next`) and a 100,000 ceiling per page.',
            'retain': ['backlinks', 'cursor (`next`)', '100,000 ceiling per page']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/web-backlinks-list/get/parameters/0/schema/description',
            'before': 'COST DIAL — 1 to 10,000, and every returned row costs a credit',
            'retain': ['1 to 10,000']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/web-linking-domains-list/get/description',
            'before': 'returns a `refdomains` array. /v1/backlinks/refdomains/count is the 2-credit way to '
                      'get just the total when you do not need the list.',
            'retain': ['/v1/backlinks/refdomains/count', 'get just the total']},
           {'source': 'openapi/seranking.json',
            'path': '/paths//apis/v1/seranking/web-linking-domains-list/get/parameters/0/schema/description',
            'before': 'COST DIAL — 1 to 10,000, one credit per returned domain',
            'retain': ['1 to 10,000']},
           {'source': 'openapi/predict-leads.json',
            'path': '/paths//apis/v1/predict-leads/technologies-detail/get/description',
            'before': '1 credit flat — the cheap way to resolve a technology name to its UUID before calling '
                      'the reverse lookup',
            'retain': ['resolve a technology name to its UUID']},
           {'source': 'openapi/predict-leads.json',
            'path': '/paths//apis/v1/predict-leads/technologies-list/get/description',
            'before': 'the ~54,000-row technology dictionary behind the detection endpoints. Expensive per '
                      'record — resolve one name with /technologies/{id_or_fuzzy_name} (1 credit flat) '
                      'instead of listing when you can',
            'retain': ['~54,000-row technology dictionary', '/technologies/{id_or_fuzzy_name}']},
           {'source': 'openapi/tomba.json',
            'path': '/paths//apis/v1/tomba/people-phone-find/get/description',
            'before': 'supply exactly one of email / domain / linkedin. THE MOST EXPENSIVE ROUTE HERE at 5 '
                      'credits',
            'retain': ['supply exactly one of email / domain / linkedin']},
           {'source': 'openapi/search1api.json',
            'path': '/paths//apis/v1/search1api/web-crawl/post/description',
            'before': "A target page's 404 or 410 costs Search1API one credit; treg cannot prove that charge "
                      'from the error body, so its shared tier absorbs it.',
            'retain': ['404 or 410', 'shared tier absorbs it']},
           {'source': 'openapi/sixtyfour.json',
            'path': '/paths//apis/v1/sixtyfour/people-email-verify/post/description',
            'before': 'VALID and INVALID verdicts cost 0.1 credit; UNKNOWN is free. The response does not '
                      'report cost_credits.',
            'retain': ['VALID and INVALID verdicts are billed', 'UNKNOWN is free', 'cost_credits']}]}

# SimilarWeb response declaration projections

These fixtures project the official pages retrieved on 2026-11-11 through public Jina Reader with `X-Return-Format: html`. The direct documentation host returned HTTP 403. The reader is the retrieval transport, not the schema authority. `manifest.json` records the official and retrieval URLs, reader-returned byte hashes, publication timestamps, and fixture hashes.

Each HTML fixture retains the canonical URL, the selected Theneo section identity, endpoint, schema version, update timestamp, its complete unchanged `responses` declarations, and the matching section's production-origin declaration. Navigation, branding, client scripts, and unrelated request/UI data are omitted. These are test projections, not original full HTML.

The declared malformed arrays are deliberately retained. Keywords, conversion rates, and demographics label the numeric `data` prototype as an array while declaring named children inside it. Demographics also has empty array prototypes under `meta.request.age_buckets` and `meta.request.metrics`; the latter declares matching enum lists on the outer and prototype arrays. The tests require strict conversion to fail and permit only explicitly listed incomplete paths to keep their outer type with unconfirmed items. Matching enum lists survive only as an unconfirmed annotation, with no item-type or enum enforcement. Segments Marketing Channels has a valid nullable object item and five distinct response media declarations.

Provider numeric examples represented as strings, and date-only examples marked date-time, are also retained verbatim. They do not establish defaults, requiredness, or corrected types.

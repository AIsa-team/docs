# AgentMail eleven success responses: review candidate

The pinned owning generated OpenAPI formally declares HTTP 204 without content
for these eleven exact methods/paths. This is stronger evidence than the old
UI examples or SDK `None` return values. It is not an observed business response.
The hosted `https://docs.agentmail.to/openapi.json` declares description-only 200;
that conflict is explicit in the composite source metadata and needs independent
review before its maintenance receipt can be confirmed.

Owning repository: `agentmail-to/agentmail-docs` at
`a7936224861284c48b6a98f731aa5c76b47d1e32`, `openapi/openapi.yml`, raw SHA256
`fc782abbbdacce91c27397a78f3aaa5f2fd3d347d74937600541e799febdf223`.
The file was last changed in `8a1eea1abcb0c865be04b7fa54bf100e7b0432a0`
(2026-10-06). `fern/apis/api/generators.yml` declares `fernapi/fern-openapi`
0.3.0 and output `../../../openapi`. The repository's March `base-openapi.json`
and `current-openapi.json` are changelog scratch exports; they are not selected.

The preserved base is AIsa Docs `e98e7918260a821397fbd1062da8d1cd9d43bf29`,
`openapi/upstream/agentmail-official.json`, raw SHA256
`70ec3d05b562a1b19e442480c3c071607e3133780b898db05c1fcf548b7108aa`.
Its complete hosted request graph, authentication, components, remaining
responses, and five already-retained operations are unchanged. The composite
contains both exact input references and the original request-source metadata.
Its pinned/manual policy prevents an automatic refresh from silently replacing
it with the broader owning document.

A full resolved comparison found zero added operations, five removed operations
(the known retained set), 159 changed operations involving requests/auth/binding,
and an OpenAPI 3.1 versus 3.0 dialect difference. A whole-source replacement would
therefore exceed this fix. The composite replaces only eleven description-only
200 responses with the owning explicitly empty 204 responses. It never discovers
new methods, changes endpoint identities or prices, or alters the composer guard.

`actual-provider-replay.json` records local composition using actual public
artifact `a16e49bbde4db3b28a751d97b9d3b4a8485926a5bdca4fe79f44c961f854c381`:
AgentMail response pending 11 -> 0; request pending 0 -> 0. All method sets,
identities, request bodies/parameters, authentication and prices remain equal.
This does not approve the full Docs baseline or publish generated artifacts.

Reproduce from the two exact saved raw files (or retrieve their pinned URLs):

```sh
python scripts/prepare_agentmail_response_reference.py \
  --base /path/to/agentmail-locked-before.json \
  --raw /path/to/openapi.yml --fetched-at ACTUAL_ACQUISITION_TIMESTAMP \
  --output /path/to/new-candidate.json
python -m unittest discover -s scripts/tests -p test_agentmail_response_reference.py
```

The importer rejects different raw hashes, missing or aliased methods/paths,
additional successful statuses, or payload-bearing 204 declarations. No new
source review is inferred from regeneration. Independent approval and a receipt
bound to the new composite content/policy hashes remain separate steps.

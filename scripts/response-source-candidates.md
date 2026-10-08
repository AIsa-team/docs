# Reviewed response source converters

These helpers retain provider-authored types rather than turning examples into
schemas. `wrapper_cloudsway_reference.py` and `wrapper_twitter_reference.py` are
used by the existing `import_upstream.py` dispatch. The Twitter importer enriches
only its existing delete request contract. `response_reference` additionally
returns the owning service's post response declaration, but that response-only
record is not a complete post request source.

The Similarweb and BytePlus helpers are offline review tools. For example, from
the repository root with already captured public reference bytes:

```python
import json
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from import_similarweb_response_reference import convert_reference

document, provenance = convert_reference(
    Path('/private/tmp/similarweb-segments.html').read_bytes(),
    '/v5/segment-analysis/segments/traffic-and-engagement',
    'https://docs.similarweb.com/api-v5/similarweb-api/website-analysis-api/website-segments/segments',
)
Path('/private/tmp/similarweb-candidate.json').write_text(
    json.dumps({'document': document, 'provenance': provenance}, indent=2) + '\n'
)
```

Use `import_byteplus_response_reference.convert_reference(raw_bytes)` for the
BytePlus reference. Its output deliberately has only a `PullPostsResult`
component and an incomplete 200 response: the page's typed table does not
establish the complete top-level envelope. Do not attach this root-path source
to all BytePlus actions.

Before any source is accepted, compare the current route, origin, method and
selectors with the captured declaration, review the raw-byte hash, and replay
with the unmodified Runtime facts. A typed source alone cannot clear a Runtime
owned response gap. Never synthesize `x-aisa-passthrough`, use examples as an
empty-body declaration, or insert a response through `previous` to bypass that
boundary. These helpers do not import identities, compile or rebind Profiles,
change production, or approve a publication.

Validation:

```sh
python -m unittest discover -s scripts/tests -p test_nonfred_responses.py -v
python -m unittest discover -s scripts/tests -p test_wrapper_references.py -v
```

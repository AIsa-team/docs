# Reviewed source inputs, 2026-10-09

These declarations and receipts prepare the Docs candidate. They do not approve
Runtime compatibility, a pending-debt baseline, or publication. The source graph
contains 106 files: 47 historical public AIsa mirrors reviewed as historical
sources, plus official acquisitions, converted/pinned sources and explicitly
bound response declarations. This is not a claim of 106 newly fetched official
OpenAPI specifications.

`merged-source-reviews.json` is the reproducible receipt input. It preserves real
acquisition timestamps and immutable independent manual review references, keyed
by source content hash and maintenance policy revision. The separate source
receipt files and review reports in this directory retain its provenance. The
26 original response receipts remain in `docs/response-source-review-receipts.json`.
No approval is inferred from rereading a cache or from a converter timestamp.

Run from the Docs repository with its Python requirements installed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts:scripts/tests \
  python -m unittest discover -s scripts/tests -p 'test_*.py'

python scripts/check_contract_candidate.py --root "$PWD" \
  --facts-dir "$ACTUAL_COMPLETE_RUNTIME_FACTS" \
  --baseline-ref "$INDEPENDENTLY_REVIEWED_BASELINE_FULL_SHA" \
  --published-ref "$PUBLISHED_ARTIFACT_FULL_SHA" \
  --source-receipts docs/current-source-review-20261009/merged-source-reviews.json \
  --report "$READINESS_REPORT"
```

The latter command requires actual complete facts and a separately approved
baseline; this source review does not supply either. Hypothetical identity
overlays are diagnostic inputs only and cannot satisfy those requirements.
Receipt freshness remains time bounded. A later official acquisition or manual
review must replace the corresponding receipt when its policy requires it.

The offline source checks alone can be reproduced without any Runtime facts:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts python - <<'PY'
import json
from pathlib import Path
from source_governance import source_report
root = Path.cwd()
saved = json.loads((root / 'docs/current-source-review-20261009/merged-source-reviews.json').read_text())
report = source_report(root, saved['receipts'], attempts=saved['attempts'])
print(json.dumps(report, indent=2, sort_keys=True))
assert report['status'] == 'passed'
PY
```

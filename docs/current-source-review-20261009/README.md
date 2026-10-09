# Reviewed source inputs, 2026-10-09

These declarations and receipts prepare the Docs candidate. They do not approve
Runtime compatibility, a pending-debt baseline, or publication. The source graph
contains 107 files: 47 historical public AIsa mirrors reviewed as historical
sources, plus official acquisitions, converted/pinned sources and explicitly
bound response declarations. This is not a claim of 107 newly fetched official
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

python scripts/prepare_source_receipts.py \
  --reviewed docs/current-source-review-20261009/merged-source-reviews.json \
  --cache .cache/source-reviews.json

python scripts/check_contract_candidate.py --root "$PWD" \
  --facts-dir "$ACTUAL_COMPLETE_RUNTIME_FACTS" \
  --baseline-ref "$INDEPENDENTLY_REVIEWED_BASELINE_FULL_SHA" \
  --published-ref "$PUBLISHED_ARTIFACT_FULL_SHA" \
  --source-receipts .cache/source-reviews.json \
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

CI, source refresh and contract publication run the same receipt preparation
step after restoring their observation cache. Each source/policy key keeps the
newest actual review and newest acquisition attempt independently; a newer
failed fetch still blocks readiness. Conflicting equal-time observations and
malformed packets stop preparation. This step never creates an approval or
changes a timestamp. Receipt-only changes require the formal artifact check.

The PR artifact check now acquires the exact production Runtime release selected
by its tracked artifact/compiler pins, using `fetch_runtime_release.py`. It no
longer depends on a previously populated Runtime cache. Every immutable file is
hash-checked, the complete provider graph is checked, and the current release
must remain fresh and pinned before and after acquisition. A changed release or
failed acquisition stops the job; there is no stale-cache fallback. The dated
acquisition receipt is retained with the readiness report.

The published artifact reference and independently reviewed pending baseline
remain separate inputs. Recompose provider files/pages and the aggregate from
those inputs before formal assessment; acquiring real Runtime facts cannot
approve the existing aggregate or the outstanding definition gaps. The tracked
Runtime pins must be explicitly updated when selecting a later release.

The facts directory layout consumed by the existing CLI is `index.json`,
`category.json`, and one `<catalog-id>.json` per Runtime index provider (flatten
an exported `providers/` directory without altering document contents). Provider
`info.x-aisa-document.facts_hash` must equal its index entry. Any unavailable
provider needs its explicit Runtime inventory; a missing file is not an empty
catalog. Preserve the original snapshot receipt and artifact/source hashes next
to the export. Do not copy the historical W0 or hypothetical oracle into this
cache.

After the actual snapshot and separately reviewed baseline are available,
`pull_openapi.py --write` with the explicit `--facts-dir` and `--baseline-ref`
arguments above uses the existing
staging gate before writing the provider/page/coverage graph. Run
`runtime_consolidate_openapi.py --output openapi.yaml`, then the explicit
`check_contract_candidate.py` command above against the actual published
artifact reference. A code-only main commit is not evidence of a newer published
artifact. The GitHub workflows currently select PR base/HEAD as their historical
reference; the operator must verify that graph corresponds to the actual last
publication before relying on its retained-content assessment.

The Twitter POST response source is separately reviewed in
`twitter-post-independent-review.json`; its receipt points to the immutable
review commit and preserves the actual review time. It supplies responses only.
The existing independently pinned request mirror remains the method authority.

The AgentMail composite receipt is in
`../agentmail-response-review-20261009/reviewed-source-receipts.json`. It binds
independent review of both raw inputs and exactly eleven success replacements;
the hosted200/owning204 conflict and preserved request graph are recorded there.
This replaces the active source key without deleting historical receipts.

After explicitly approved D1/D2 SQL, the actual public Runtime is generation4,
artifact `f31344e2851df34e7f2c5feeb9bc5d745767d8ed2493ea0cf78f5b4a21d85258`, source `f04c0fa166386259559fba77a1875de2a60ead1e68a2a536860e640477210a8a`,
with unchanged compiler8d4. Both API snapshots/durable publication and all56 public
files passed actual SHA/200/304 readback. CI now pins this actual release.
The four Akta response-only sources remain bound to their exact canonical targets.
This input update does not approve a pending baseline or publish the Docs graph.

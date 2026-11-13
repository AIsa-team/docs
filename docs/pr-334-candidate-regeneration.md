# PR #334 candidate regeneration

The initial consolidation changed the Composer and reviewed upstream sources but
left the committed native graph and pages at the previous publication. The
artifact job correctly rejected that mixed state. Its 360 blocked providers were
not 360 independent code defects: regenerating with the same hash-verified raw
Runtime inputs cleared the request, response and coverage-binding mismatches.
The page renderer also replaced the obsolete cost/declaration blocks. The
payment discovery catalog must be regenerated after the native graph as well.
The aggregate JSON must use compact serialization: pretty-printing this catalog
produced a 113 MiB file that GitHub rejected. The consolidator now emits the same
values in compact JSON, with a CLI regression covering scalar fidelity and the
matching discovery outputs.

A full repeat also exposed archived aliases without OpenAPI frontmatter. The
generator now restores their temporary route binding during staging, allowing
the existing retirement policy to re-archive them before any file is written.
A three-pass regression proves they cannot regain request or pricing blocks.

## Reproduce through the existing generators

Use an isolated PR worktree. Pin the actual main publication used as the identity
baseline and acquire a new directory of public Runtime inputs. The following
commands prepare a review candidate; they never call the formal exporter or
write `docs/publication/current.json`, its formal assessment, or release origin.
They do not deploy the Runtime producer.

```sh
export RUNTIME_FACTS=/tmp/pr-334-runtime
export PUBLISHED_REF=f4acbef48c6ffa3796c2111d14d8f5a0b78a9283
python scripts/fetch_runtime_release.py --current --output "$RUNTIME_FACTS"
python scripts/prepare_source_receipts.py \
  --reviewed docs/schema-inputs/source-receipts.json \
  --cache .cache/source-reviews.json
python scripts/prepare_source_receipts.py \
  --reviewed docs/current-source-review-20261009/merged-source-reviews.json \
  --cache .cache/source-reviews.json

PYTHONPATH=scripts python - <<'PY'
import os
from pathlib import Path
from export_contract_publication import acquired_input
from check_contract_candidate import load_baseline
from pull_openapi import stage
from schema_input_bundle import REVIEWED_BASELINE

root = Path.cwd()
facts = Path(os.environ['RUNTIME_FACTS'])
# Recheck the complete acquisition, including flat Composer inputs.
acquired_input(facts)
context = {
    'offline': True,
    'unreviewed_runtime': True,
    'published_ref': os.environ['PUBLISHED_REF'],
    'baseline_coverage': load_baseline(root, REVIEWED_BASELINE),
}
# Use the same reviewed-source and explicit unreviewed-operation behavior as
# check_contract_candidate and the Runtime shadow compiler. No network fallback.
changes, summary = stage(root, facts, 'https://unused.invalid', with_pages=True,
                         readiness_context=context)
report = context['report']
if report['status'] != 'passed' or report.get('blocked_providers'):
    raise SystemExit('Composition failed; no generated files written')
for path, text in changes.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
PY
python scripts/runtime_consolidate_openapi.py --root "$PWD" --output openapi.yaml
python scripts/generate_payment_discovery.py --root "$PWD"
python scripts/check_contract_candidate.py --root "$PWD" \
  --facts-dir "$RUNTIME_FACTS" \
  --baseline-ref 78ef376841ead8cde10a79651958790be5a0531c \
  --published-ref "$PUBLISHED_REF" \
  --source-receipts .cache/source-reviews.json \
  --report /tmp/pr-334-candidate-readiness.json
```

Review the generated diff, run the normal code and docs checks, and repeat the
generation with unchanged inputs to establish stability. A failed final check
leaves only a local candidate for diagnosis; it grants no publication approval.
Freshness or hash failures must be resolved at acquisition, never ignored.

## Source-input and publication boundaries

The schema-input context binds the complete existing receipt packet, the actual
source assessment time and the prior formal Git context. Original review and
acquisition observations remain unchanged; this is a build-input recipe, not a
new source review or a formal publication receipt.

The Runtime producer must independently adopt the reviewed Composer/input bundle.
The canonical publisher then authenticates its exact bytes before the normal
publication path can proceed. The generated PR graph does not substitute for
that lock or claim that production has deployed it. No CI classification,
readiness baseline, accepted debt or publication gate is weakened by this fix.

## Verify production after the input promotion

This PR validates a candidate; the following release checks are separate work.

1. After the final Docs commit is merged, export its reviewed input bundle and
   Composer source manifest reproducibly. Update all four Services lock fields
   (`docs_ref`, `composer_revision`, `bundle_manifest_sha256`, and
   `source_manifest_sha256`) and the paired fixture bindings. Verify the package
   installed in the worker image and replay the authenticated catalog.
2. After the normal Services rollout, read `/public/api-contract/current` and
   require the deployed compiler inputs to equal those four reviewed pins.
   Require `fresh: true`, matching generation/published_generation, and a fully
   verified immutable canonical release from the strict acquisition reader.
3. Run the existing publisher in dry-run mode first. Inspect the actual
   `compose` job: staging, payment discovery, formal assessment and export must
   pass. A scheduled workflow can report success while `compose` fails because
   of `continue-on-error`; that is not publication. The subsequent normal
   publication must actually push the assessed commit and retain matching
   origin, acquisition and formal readiness evidence.
4. Confirm the documentation deployment uses that generated commit. Check the
   English/Chinese pages for each pricing family, the repaired credit examples,
   free/archive pages and absence of duplicate price markers. Repeat generation
   with the same inputs and require stable pages, including retired aliases.

No SQL, Runtime deployment, publisher invocation or main merge is performed by
these candidate-generation commands.

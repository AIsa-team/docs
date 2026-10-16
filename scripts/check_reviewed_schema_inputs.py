#!/usr/bin/env python3
"""Check a closed source-only input change, never formal output or approval."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from contract_change_scope import git_changed_paths, is_reviewed_input_change
from export_schema_input_bundle import export_reviewed_bundle
from prepare_source_receipts import merge_evidence
from publication_origin import inspect_publication
from schema_input_bundle import (INPUT_CONTEXT_MEMBER, canonical, load_bundle, regular_read,
                                 require, sha, strict_json)
from shadow_compile_bundle import compile_shadow
from source_governance import source_report


def assess_reviewed_input(root, facts, base, output, *, checked_at=None):
    root, facts, output = Path(root), Path(facts), Path(output)
    paths = git_changed_paths(root, base)
    require(paths is not None and is_reviewed_input_change(paths), 'Not a closed source-only input change')
    import subprocess
    ref = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    require(output.parent.is_dir() and not output.exists(), 'Input candidate output must be a new directory')
    output.mkdir()
    result = export_reviewed_bundle(root, ref, output / 'bundle')
    bundle = load_bundle(output / 'bundle', expected_manifest_sha256=result['manifest_sha256'], expected_docs_ref=ref)
    recipe = strict_json(bundle.contents[INPUT_CONTEXT_MEMBER])
    # This is the real previous formal context, independently authenticated now;
    # it is not used as approval for the new input schema or as its future source.
    previous = inspect_publication(root, recipe['historical_formal_ref'], historical=True)
    require(previous.get('expected_docs_ref') == recipe['historical_formal_ref'], 'Input history provenance differs')
    original = strict_json(bundle.contents['evidence/source-receipts.json'])
    cache = root / '.cache/source-reviews.json'
    current = strict_json(regular_read(cache.parent, cache.name)) if cache.exists() else original
    saved = merge_evidence(original, current)
    now = checked_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix='input-candidate-governance-') as folder:
        view = Path(folder)
        for name, raw in bundle.contents.items():
            if name.startswith('input/'):
                path = view / name.removeprefix('input/'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        governance = source_report(view, saved['receipts'], checked_at=now, attempts=saved.get('attempts', {}))
    require(governance['status'] == 'passed' and not governance['policy_errors'],
            'Current input source authorization did not pass')
    receipt_raw = regular_read(facts, 'acquisition-receipt.json')
    receipt = strict_json(receipt_raw)
    composed = compile_shadow(output / 'bundle', facts, bundle_sha256=result['manifest_sha256'], docs_ref=ref,
        artifact_revision=receipt['artifact_revision'], compiler_revision=receipt['compiler_revision'],
        runtime_receipt_sha256=sha(receipt_raw), output=output / 'candidate')
    report = {'schema_version': 1, 'status': 'passed',
        'scope': 'reviewed_input_candidate_only_not_formal_publication_or_promotion',
        'changed_paths': sorted(paths), 'input': result, 'source_governance': governance,
        'current_source_receipts_sha256': sha(canonical(saved)), 'composed_candidate': composed,
        'historical_formal_provenance': previous}
    (output / 'receipt.json').write_bytes(canonical(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--facts-dir', type=Path, required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assess_reviewed_input(args.root, args.facts_dir, args.base, args.output)
    except Exception as error:
        parser.exit(1, 'Reviewed input candidate rejected: ' + type(error).__name__ + '\n')
    print('Reviewed input candidate passed; no formal publication or input promotion')

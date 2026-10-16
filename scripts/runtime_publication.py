"""Select the verified Runtime mode and project canonical bytes for publication.

Fact-only releases keep the existing workflow commands. A canonical release that
fails any input or projection gate never falls back to local composition.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

from canonical_import import (schema_input_view_files, acquired_members,
                              project_metadata, project_surfaces)
from canonical_input_assessment import assess_canonical_inputs
from canonical_formal import assess_formal_canonical
from check_contract_candidate import load_baseline
from contract_readiness import check_readiness
from deferred_definitions import load_deferred_definitions
from export_contract_publication import acquired_input
from publication_origin import ORIGIN
from runtime_contract_artifact import MANIFEST, NATIVE, AGGREGATE, READINESS
from schema_input_bundle import (REVIEWED_BASELINE, canonical, regular_read,
                                require, safe_name, strict_json)


def verified_mode(facts):
    receipt, _ = acquired_input(Path(facts))
    # acquired_input revalidates the complete closed artifact; this is not a
    # file-exists probe or an optional flag that can bypass canonical validation.
    return 'canonical' if 'canonical_validation' in receipt else 'facts'


def publication_refs(root, baseline):
    require(baseline == REVIEWED_BASELINE, 'Canonical publication requires the reviewed baseline')
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    assessed = git('rev-parse', 'HEAD')
    previous = git('log', '-1', '--format=%H', 'HEAD', '--', ORIGIN)
    require(previous, 'No attributed previous formal publication')
    # The input gate authenticates this original publication historically. Its
    # expiry does not prevent a genuinely new, freshly assessed publication.
    return assessed, previous


def stage_canonical(root, facts, *, baseline, source_receipts=None, checked_at=None, write=False):
    root, facts = Path(root), Path(facts)
    require(verified_mode(facts) == 'canonical', 'Canonical stage requires a canonical Runtime artifact')
    assessed, previous = publication_refs(root, baseline)
    manifest = strict_json(regular_read(facts, MANIFEST))
    files, lineage = schema_input_view_files(root, root, manifest['docs_ref'], previous,
                                              compiler_inputs=manifest)
    receipt_path = Path(source_receipts) if source_receipts else root / '.cache/source-reviews.json'
    receipts = regular_read(receipt_path.parent, receipt_path.name)
    now = checked_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix='canonical-stage-input-') as directory:
        view = Path(directory)
        for name, raw in {**files, '.cache/source-reviews.json': receipts}.items():
            target = view / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        assessment = assess_canonical_inputs(view, facts, checked_at=now, repository=root)
        members = acquired_members(facts, assessment)
        require(canonical(strict_json(members[MANIFEST])) == canonical(manifest),
                'Canonical manifest changed during staging')
        native_raw = {Path(name).stem: raw for name, raw in members.items() if NATIVE.fullmatch(name)}
        native = {name: strict_json(raw) for name, raw in native_raw.items()}
        catalogs = {Path(name).stem: strict_json(raw) for name, raw in members.items() if name.startswith('providers/')}
        metadata = project_metadata(view, catalogs, strict_json(members['index.json']),
            strict_json(members['category.json']), native, strict_json(members[READINESS]))
        report = check_readiness(metadata['facts_by_provider'], native, metadata['coverage'],
            baseline_coverage=load_baseline(root, baseline), runtime_index=metadata['runtime_index'],
            deferred_definitions=load_deferred_definitions(view))
        require(report.get('status') == 'passed' and not any(report.get(key) for key in
            ('global_errors', 'missing_inputs', 'blocked_providers')), 'Canonical projection readiness failed')
        changes = project_surfaces(root, native_raw, members[AGGREGATE], metadata)
    # Validate every target before the first write. No publication pointer is
    # written here; fresh payment evidence and the full formal replay follow.
    for name in changes:
        safe_name(name)
        target = root
        for part in Path(name).parts:
            target = target / part
            require(not target.is_symlink(), 'Canonical output path contains a symlink')
        require(not target.exists() or target.is_file(), 'Canonical output is not a regular file')
    if write:
        for name, raw in changes.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    report.update(evaluation='runtime_canonical_projection_before_payment_and_formal_replay',
        scope='staging_only_not_formal_publication', baseline_ref=baseline,
        assessed_base=assessed, previous_formal_ref=previous,
        canonical_inputs=assessment, registry_lineage=lineage, projected_files=len(changes), dry_run=not write)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('mode', 'stage', 'assess'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--facts-dir', type=Path, required=True)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--source-receipts', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'mode':
            print(verified_mode(args.facts_dir))
            return 0
        require(args.report is not None, 'A non-public readiness report output is required')
        if args.action == 'stage':
            report = stage_canonical(args.root, args.facts_dir, baseline=args.baseline_ref,
                source_receipts=args.source_receipts, write=args.write)
        else:
            require(not args.write, 'Assessment does not write publication files')
            require(verified_mode(args.facts_dir) == 'canonical', 'Canonical assessment requires a canonical Runtime artifact')
            assessed, previous = publication_refs(args.root, args.baseline_ref)
            report = assess_formal_canonical(args.root, args.facts_dir,
                previous_formal_ref=previous, assessed_base=assessed, source_receipts=args.source_receipts)
        status = 0 if report.get('status') == 'passed' else 1
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        report = {'status': 'not_assessed', 'evaluation': 'runtime_canonical_' + args.action,
                  'missing_inputs': ['canonical publication validation failed'], 'error': str(exc)}
        status = 3
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(canonical(report) + b'\n')
    print(json.dumps({'status': report['status'], 'evaluation': report['evaluation']}))
    return status


if __name__ == '__main__':
    raise SystemExit(main())

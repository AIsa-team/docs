#!/usr/bin/env python3
"""Recompose frozen W0 inputs with W1/W2 code, without approving any debt.

The W0 archive stays immutable. Proposed maintenance policies come from an
explicit, hash-bound offline fixture; provider payloads stay sanitized.
The output is a diagnostic candidate, never a publication baseline or live proof.
"""
import argparse
import cProfile
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
import tarfile
import time

ARCHIVE_SHA256 = 'f2b35c81df49b3a31053f3b4e8978778e52556d2d36536c23f4d7f28f8e0f02f'


def apply_policy_fixture(root, fixture, policy_fields, validate_policy):
    """Apply only proposed declarations; never accept review/publication input."""
    if set(fixture) != {'schema_version', 'scope', 'archive_sha256', 'sources'} or fixture['schema_version'] != 1:
        raise ValueError('invalid offline policy fixture envelope')
    if fixture['archive_sha256'] != ARCHIVE_SHA256:
        raise ValueError('policy fixture is not bound to the frozen archive')
    paths = sorted((root / 'openapi/upstream').glob('*.json'))
    if set(fixture['sources']) != {path.name for path in paths}:
        raise ValueError('policy fixture must cover the exact frozen source set')
    prepared = []
    for path in paths:
        row = fixture['sources'][path.name]
        if set(row) != {'source_hash', 'authority_url', 'policy'}:
            raise ValueError('policy fixture cannot contain review receipts')
        document = json.loads(path.read_text())
        metadata = document['info']['x-aisa-source']
        if row['source_hash'] != metadata.get('content_hash') or row['authority_url'] != metadata.get('url'):
            raise ValueError(f'policy source binding mismatch: {path.name}')
        if not set(row['policy']) <= {*policy_fields, 'policy_revision'}:
            raise ValueError('policy fixture contains non-policy fields')
        metadata.update(row['policy'])
        if validate_policy(metadata):
            raise ValueError(f'invalid proposed source policy: {path.name}')
        prepared.append((path, document))
    for path, document in prepared:
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')


def reconcile(expected, candidate, coverage):
    """Compare complete identity sets with frozen evidence, not just totals."""
    previous = json.loads((expected / 'openapi/coverage.json').read_text())
    def rows(value):
        return {(provider, row['path'], row['method'], row.get('operation_id'), row['status'])
                for provider, entries in value['providers'].items() for row in entries}
    def operations(root):
        result = {}
        for path in (root / 'openapi').glob('*.json'):
            doc = json.loads(path.read_text())
            if not doc.get('info', {}).get('x-aisa-document', {}).get('composer_version'):
                continue
            for route, item in doc.get('paths', {}).items():
                for method, op in item.items():
                    if method in {'get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'trace'}:
                        result[(path.name, route, method, op.get('operationId'))] = op
        return result
    before, after = operations(expected), operations(candidate)
    fields = ('x-aisa-pricing', 'x-aisa-status', 'x-aisa-query-policy',
              'x-aisa-upstream-path', 'x-aisa-capabilities', 'x-aisa-passthrough')
    changed = [(identity, field) for identity, op in before.items() if identity in after
               for field in fields if op.get(field) != after[identity].get(field)]
    return {'coverage_rows': len(rows(coverage)), 'composed_operations': len(after),
            'coverage_identity_sets_equal': rows(previous) == rows(coverage),
            'operation_identity_sets_equal': before.keys() == after.keys(),
            'execution_metadata_changes': changed,
            'status': 'passed' if rows(previous) == rows(coverage) and before.keys() == after.keys() and not changed else 'failed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parents[2] /
                        'scripts/api-contract-acceptance/data/full-catalog.tar.gz')
    parser.add_argument('--profile', action='store_true', help='Save local composition profiling evidence')
    parser.add_argument('--with-pages', action='store_true', help='Validate actual full EN/ZH publication graph; remains diagnostic only')
    parser.add_argument('--policy-fixture', type=Path, default=Path(__file__).with_name('source-policy.fixture.json'),
                        help='Proposed source policies for offline testing; creates no review receipts')
    args = parser.parse_args()
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise SystemExit('frozen archive checksum mismatch')
    if args.output.exists():
        raise SystemExit('output must be a new directory')
    args.output.mkdir(parents=True)
    with tarfile.open(args.archive) as archive:
        archive.extractall(args.output, filter='data')
    sys.path.insert(0, str(args.docs_root / 'scripts'))
    from source_governance import POLICY_FIELDS, policy_errors, source_report
    from pull_openapi import stage
    candidate = args.output / 'candidate'
    shutil.copytree(args.output / 'input', candidate)
    if args.with_pages:
        # W0 intentionally omitted unrelated existing MDX. Supplement only
        # missing files with exact bytes from its already fixed Docs revision.
        fixture = args.docs_root / 'scripts/tests/fixtures/legacy-pages.tar.gz'
        if hashlib.sha256(fixture.read_bytes()).hexdigest() != '72bf4861f077f1293b993bdad05b7a563ff4ac62741463049099a7d4cdd82c85':
            raise ValueError('fixed legacy page fixture checksum mismatch')
        with tarfile.open(fixture) as pages:
            for member in pages.getmembers():
                if not member.isfile() or not member.name.endswith('.mdx'):
                    continue
                path = candidate / member.name
                if not path.is_file():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(pages.extractfile(member).read())
        identity_fixture = args.docs_root / 'scripts/tests/fixtures/legacy-page-identities.json'
        if hashlib.sha256(identity_fixture.read_bytes()).hexdigest() != 'f245bbd8ce97352c82ce20216bb6cb8939686d1a1a8bf50111a082a3242e8239':
            raise ValueError('fixed legacy page identity checksum mismatch')
        identities = json.loads(identity_fixture.read_text())
        if identities['docs_ref'] != '89296da5fac52ad51b360ca24005cc2f5a03daa0':
            raise ValueError('legacy page identities do not match frozen W0 revision')
        for name, row in identities['pages'].items():
            page = candidate / name
            text = page.read_text()
            if 'x-aisa-operation-id:' not in text:
                page.write_text(text.replace('---\n', '---\nx-aisa-operation-id: ' + json.dumps(row['operation_id']) + '\n', 1))
    apply_policy_fixture(candidate, json.loads(args.policy_fixture.read_text()), POLICY_FIELDS, policy_errors)
    context = {'offline': True}
    profiler = cProfile.Profile() if args.profile else None
    print('Frozen inputs prepared; composing diagnostic candidate.', flush=True)
    started = time.monotonic()
    if profiler:
        profiler.enable()
    changes, summary = stage(candidate, candidate / 'facts', 'https://api.aisa.one',
                             with_pages=args.with_pages, readiness_context=context)
    first_seconds = time.monotonic() - started
    if profiler:
        profiler.disable()
        profiler.dump_stats(str(args.output / 'composition.prof'))
    for path, content in changes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    repeat_context = {'offline': True}
    print('First composition written; checking idempotent replay.', flush=True)
    started = time.monotonic()
    repeat, _ = stage(candidate, candidate / 'facts', 'https://api.aisa.one',
                      with_pages=args.with_pages, readiness_context=repeat_context)
    repeat_seconds = time.monotonic() - started
    coverage = context['coverage']
    pending = [row for rows in coverage['providers'].values() for row in rows if row['status'] == 'pending']
    responses = [row for rows in coverage['response_gaps'].values() for row in rows]
    maintenance = source_report(candidate)
    full_set = reconcile(args.output / 'expected', candidate, coverage)
    receipt = {'scope': 'offline W1/W2 diagnostic candidate; no debt approval/publication/live execution',
        'archive_sha256': ARCHIVE_SHA256, 'composed_providers': len(summary),
        'policy_fixture_sha256': hashlib.sha256(args.policy_fixture.read_bytes()).hexdigest(),
        'policy_fixture_scope': 'proposed declarations only; no real review or publication approval',
        'coverage_schema_version': coverage['schema_version'],
        'request_gaps': len(pending), 'request_gap_statuses': dict(Counter(row.get('runtime_status') for row in pending)),
        'response_gaps': len(responses), 'response_gap_statuses': dict(Counter(row.get('runtime_status') for row in responses)),
        'all_request_source_fingerprints': all(row.get('source_binding_hash') for row in pending),
        'all_response_source_fingerprints': all(row.get('response_source_binding_hash') for row in responses),
        'repeat_changed_files': len(repeat), 'readiness': context['report']['status'],
        'local_composition_seconds': round(first_seconds, 3), 'local_repeat_seconds': round(repeat_seconds, 3),
        'global_errors': context['report']['global_errors'], 'missing_inputs': context['report']['missing_inputs'],
        'sources': len(maintenance['sources']), 'source_policy_errors': maintenance['policy_errors'],
        'source_freshness': maintenance['status'], 'policy_counts': dict(Counter(row['policy'] for row in maintenance['sources'].values()))}
    receipt['full_set_reconciliation'] = full_set
    if args.with_pages:
        from publication_surface import validate_surfaces, publication_hashes
        receipt['legacy_page_fixture'] = {'sha256': '72bf4861f077f1293b993bdad05b7a563ff4ac62741463049099a7d4cdd82c85',
            'page_identities_sha256': 'f245bbd8ce97352c82ce20216bb6cb8939686d1a1a8bf50111a082a3242e8239',
            'docs_ref': '89296da5fac52ad51b360ca24005cc2f5a03daa0', 'scope': 'fixed existing MDX/page identities; no contract authority'}
        subprocess.run([sys.executable, str(args.docs_root / 'scripts/runtime_consolidate_openapi.py'),
                        '--root', str(candidate), '--output', str(candidate / 'openapi.yaml')], check=True)
        import yaml
        from runtime_consolidate_openapi import validate_reference_closure
        validate_reference_closure(yaml.safe_load((candidate / 'openapi.yaml').read_text()))
        receipt['publication_surfaces'] = validate_surfaces(candidate)
        receipt['publication_files_sha256'] = publication_hashes(candidate)
        code_sha = subprocess.check_output(['git', '-C', str(args.docs_root), 'rev-parse', 'HEAD'], text=True).strip()
        lock = {'repository': 'AIsa-team/docs', 'commit': code_sha,
                'openapi_sha256': hashlib.sha256((candidate / 'openapi.yaml').read_bytes()).hexdigest(),
                'diagnostic_only': True, 'publication_verified': False, 'activatable': False,
                'code_revision_dirty': bool(subprocess.check_output(['git', '-C', str(args.docs_root), 'status', '--porcelain'], text=True)),
                'scope': 'actual fixed W0 candidate bytes; code revision is not an approved publication'}
        (args.output / 'diagnostic-docs.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, indent=2, sort_keys=True))
    # Unknown real reviews/debt are expected here, and are reported explicitly.
    return 0 if full_set['status'] == 'passed' and not receipt['global_errors'] and not receipt['missing_inputs'] and not repeat and not receipt['source_policy_errors'] and receipt['all_request_source_fingerprints'] and receipt['all_response_source_fingerprints'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

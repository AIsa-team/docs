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
import re
import shutil
import sys
import subprocess
import tarfile
import time
from urllib.parse import urlsplit

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


METHODS = {'get', 'post', 'put', 'delete', 'patch', 'head', 'options', 'trace'}
# Merged source guards: a supplier input Runtime does not forward is pending,
# never silently dropped. They are the only accepted cause of a blocked
# provider retaining its last-good document in this frozen replay.
SOURCE_GUARD_REASON_CODES = {'unforwarded_source_query', 'unforwarded_source_header'}
IDENTITY_BLOCK = re.compile(r"published identity changed or disappeared: (\S+) \(\('([^']+)', '([a-z]+)'\)\)")


def _row_key(provider, row):
    return (provider, row['path'], row['method'], row.get('operation_id'), row['status'])


def _route_operations(document):
    """Operations keyed by full public path, independent of server prefixes."""
    prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    return {(prefix + route, method): op for route, item in document.get('paths', {}).items()
            for method, op in item.items() if method in METHODS}


def _block_causes(provider, entries, frozen_entries, reason_code):
    """Classify new pending entries; only merged source guards may block."""
    known = {(row.get('path'), row.get('method'), row.get('reason')) for row in frozen_entries}
    guarded, identity, unaccepted = set(), [], []
    for row in entries:
        if (row.get('path'), row.get('method'), row.get('reason')) in known:
            continue
        match = IDENTITY_BLOCK.fullmatch(str(row.get('reason') or '')) if row.get('path') is None else None
        if match:
            identity.append((match.group(2), match.group(3).upper()))
        elif row.get('path') is not None and reason_code(row.get('reason')) in SOURCE_GUARD_REASON_CODES:
            guarded.add((row['path'], row['method']))
        else:
            unaccepted.append((provider, row.get('path'), row.get('method'), row.get('reason')))
    for path, method in identity:
        if (path, method) not in guarded and (path, 'ANY') not in guarded:
            unaccepted.append((provider, path, method, 'identity block not caused by a source guard'))
    return guarded, bool(identity), unaccepted


def _unforwarded_inputs(document, facts, row, helpers):
    """Independently list caller inputs a published operation exposes but Runtime drops."""
    effective_object, effective_public_operation = helpers
    item = facts['paths'].get(row['path'])
    if item is None:
        return None
    item = effective_object(item, facts)
    method = row['method'].lower()
    runtime = item.get(method, item.get('x-aisa-any'))
    if runtime is None:
        return None
    runtime = effective_public_operation(item, runtime, facts)
    forwarded = {(p['in'], p['name']) for p in runtime.get('parameters', [])}
    headers = {'accept', *(name.lower() for name in runtime.get('x-aisa-caller-headers', []))}
    query_passthrough = runtime.get('x-aisa-query-policy', {}).get('request_wins', False)
    auth = {'authorization', 'x-api-key', 'api-key'} | {
        scheme['name'].lower() for scheme in document.get('components', {}).get('securitySchemes', {}).values()
        if isinstance(scheme, dict) and scheme.get('name')}
    routes = _route_operations(document)
    targets = [(m, op) for (path, m), op in routes.items() if path == row['path'] and (method == 'any' or m == method)]
    exposed = []
    for actual, op in targets:
        for parameter in op.get('parameters', []):
            parameter = effective_object(parameter, document)
            name, place = parameter.get('name', ''), parameter.get('in')
            if place == 'header' and name.lower() not in auth | headers and ('header', name) not in forwarded:
                exposed.append((actual.upper(), op.get('operationId'), 'header', name))
            elif place == 'query' and not query_passthrough and name.lower() not in auth and ('query', name) not in forwarded:
                exposed.append((actual.upper(), op.get('operationId'), 'query', name))
    return exposed


def reconcile_ledger(previous, coverage, last_good, documents, pending, frozen_pending, facts, reason_code, helpers):
    """Account for every frozen and candidate coverage row by explicit rule.

    A row is either identical, or belongs to a provider whose recomposition was
    blocked solely by merged source guards and which retains its byte-equal
    last-good document. Retained rows stay pending; an ``x-aisa-any`` route may
    collapse to one ANY row only when the frozen per-method rows are exactly the
    retained last-good operations at that route. Fresh composed operations must
    not expose unforwarded inputs; retained ones may only keep exposures already
    published by the frozen last-good document, and are reported as such.
    """
    errors = []
    frozen = {provider: rows for provider, rows in previous['providers'].items()}
    current = {provider: rows for provider, rows in coverage['providers'].items()}
    frozen_keys = [_row_key(p, row) for p, rows in frozen.items() for row in rows]
    current_keys = [_row_key(p, row) for p, rows in current.items() for row in rows]
    for name, keys in (('frozen', frozen_keys), ('candidate', current_keys)):
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        errors.extend(('duplicate_coverage_row', name, *key) for key in duplicates)
    if set(frozen) != set(current):
        errors.append(('provider_set_changed', sorted(set(frozen) ^ set(current))))
    unchanged = set(frozen_keys) & set(current_keys)
    retained, causes, collapsed, exposures = {}, {}, [], {'composed': [], 'retained_preexisting': []}
    accounted_frozen, accounted_current = set(unchanged), set(unchanged)
    for provider in sorted(set(frozen) & set(current)):
        rows = current[provider]
        lost = [row for row in frozen[provider] if _row_key(provider, row) not in unchanged]
        added = [row for row in rows if _row_key(provider, row) not in unchanged]
        whole_retained = bool(rows) and all(row['status'] == 'pending' and row.get('publication_state') == 'retained' for row in rows)
        if whole_retained and (lost or added):
            guarded, identity_blocked, unaccepted = _block_causes(provider, pending.get(provider, []),
                                                                  frozen_pending.get(provider, []), reason_code)
            errors.extend(('unaccepted_block_cause', *item) for item in unaccepted)
            if not guarded or not identity_blocked:
                errors.append(('retention_without_source_guard_block', provider))
            if documents.get(provider) != last_good.get(provider) or provider not in last_good:
                errors.append(('retained_document_not_last_good', provider))
            causes[provider] = sorted(f'{path} {method}' for path, method in guarded)
            retained_ops = _route_operations(last_good.get(provider, {}))
            by_route = {}
            for row in lost:
                by_route.setdefault(row['path'], []).append(row)
            for row in added:
                mapped = [old for old in by_route.get(row['path'], [])
                          if (old['method'], old.get('operation_id')) == (row['method'], row.get('operation_id'))]
                if row['method'] == 'ANY' and not mapped:
                    fact = facts.get(provider, {}).get('paths', {}).get(row['path'], {}).get('x-aisa-any')
                    mapped = [old for old in by_route.get(row['path'], []) if old['method'] != 'ANY']
                    published = {(m.upper(), op.get('operationId')) for (path, m), op in retained_ops.items() if path == row['path']}
                    if not fact or fact.get('operationId') != row.get('operation_id'):
                        errors.append(('any_collapse_without_runtime_any', provider, row['path'], row.get('operation_id')))
                        mapped = []
                    elif {(old['method'], old.get('operation_id')) for old in mapped} != published or not published:
                        errors.append(('any_collapse_hides_retained_operation', provider, row['path'],
                                       sorted(published ^ {(old['method'], old.get('operation_id')) for old in mapped})))
                        mapped = []
                    else:
                        collapsed.append((provider, row['path'], sorted(old['method'] for old in mapped)))
                # binding_hash is not compared: its derivation changed after W0
                # even for unchanged rows. Runtime fact presence is the invariant.
                fact_item = facts.get(provider, {}).get('paths', {}).get(row['path'], {})
                if mapped and row['method'].lower() not in fact_item and 'x-aisa-any' not in fact_item:
                    errors.append(('retained_row_without_runtime_fact', provider, row['path'], row['method']))
                    mapped = []
                if mapped:
                    accounted_current.add(_row_key(provider, row))
                    accounted_frozen.update(_row_key(provider, old) for old in mapped)
            for row in lost:
                if row['status'] != 'composed':
                    continue
                kept = retained_ops.get((row['path'], row['method'].lower()))
                if kept is None:
                    errors.append(('retained_operation_missing', provider, row['path'], row['method'], row.get('operation_id')))
                elif kept.get('operationId') != row.get('operation_id'):
                    errors.append(('retained_identity_changed', provider, row['path'], row['method']))
            retained[provider] = {'frozen_rows': len(lost), 'candidate_rows': len(added),
                                  'retained_operations': len(retained_ops)}
        if provider not in facts:
            errors.append(('missing_runtime_facts', provider))
            continue
        document = documents.get(provider, {})
        for row in rows:
            exposed = _unforwarded_inputs(document, facts[provider], row, helpers)
            if exposed is None:
                if row['status'] == 'composed':
                    errors.append(('composed_without_runtime_fact', provider, row['path'], row['method']))
                continue
            if not exposed:
                continue
            if row['status'] == 'composed' or row.get('publication_state') != 'retained':
                exposures['composed'].extend((provider, row['path'], *item) for item in exposed)
                continue
            prior_document = last_good.get(provider, {})
            published = _route_operations(prior_document)
            for method, operation_id, place, name in exposed:
                prior = published.get((row['path'], method.lower()), {})
                if prior.get('operationId') != operation_id or not any(
                        (p.get('in'), p.get('name')) == (place, name)
                        for p in (helpers[0](raw, prior_document) for raw in prior.get('parameters', []))):
                    exposures['composed'].append((provider, row['path'], method, operation_id, place, name))
                else:
                    exposures['retained_preexisting'].append((provider, row['path'], method, operation_id, place, name))
    errors.extend(('unforwarded_input_exposed', *item) for item in exposures['composed'])
    unaccounted_frozen = sorted(set(frozen_keys) - accounted_frozen)
    unaccounted_current = sorted(set(current_keys) - accounted_current)
    errors.extend(('unaccounted_frozen_row', *key) for key in unaccounted_frozen)
    errors.extend(('unaccounted_candidate_row', *key) for key in unaccounted_current)
    return {'frozen_rows': len(frozen_keys), 'candidate_rows': len(current_keys), 'unchanged_rows': len(unchanged),
            'retained_frozen_rows': sum(row['frozen_rows'] for row in retained.values()),
            'retained_candidate_rows': sum(row['candidate_rows'] for row in retained.values()),
            'retained_providers': retained, 'source_guard_block_causes': causes,
            'any_collapsed_routes': collapsed,
            'retained_preexisting_unforwarded_inputs': len(exposures['retained_preexisting']),
            'retained_preexisting_unforwarded_input_providers': dict(Counter(item[0] for item in exposures['retained_preexisting'])),
            'unaccounted_frozen_rows': len(unaccounted_frozen), 'unaccounted_candidate_rows': len(unaccounted_current),
            'errors': [list(error) for error in errors], 'status': 'failed' if errors else 'passed'}


def reconcile(expected, candidate, coverage, last_good_root=None):
    """Compare complete identity sets with frozen evidence, not just totals."""
    previous = json.loads((expected / 'openapi/coverage.json').read_text())
    def rows(value):
        return {_row_key(provider, row) for provider, entries in value['providers'].items() for row in entries}
    def operations(root):
        result = {}
        for path in (root / 'openapi').glob('*.json'):
            doc = json.loads(path.read_text())
            if not doc.get('info', {}).get('x-aisa-document', {}).get('composer_version'):
                continue
            for route, item in doc.get('paths', {}).items():
                for method, op in item.items():
                    if method in METHODS:
                        result[(path.name, route, method, op.get('operationId'))] = op
        return result
    before, after = operations(expected), operations(candidate)
    fields = ('x-aisa-pricing', 'x-aisa-status', 'x-aisa-query-policy',
              'x-aisa-upstream-path', 'x-aisa-capabilities', 'x-aisa-passthrough')
    changed = [(identity, field) for identity, op in before.items() if identity in after
               for field in fields if op.get(field) != after[identity].get(field)]
    identical = rows(previous) == rows(coverage)
    result = {'coverage_rows': len(rows(coverage)), 'composed_operations': len(after),
              'coverage_identity_sets_equal': identical,
              'operation_identity_sets_equal': before.keys() == after.keys(),
              'execution_metadata_changes': changed}
    ledger_ok = identical
    if not identical and last_good_root is not None:
        import yaml
        from compose_openapi import effective_object, effective_public_operation
        from contract_readiness import reason_code
        from runtime_registry import combine_facts
        from pull_openapi import normalize_paths
        def documents(root):
            return {name: json.loads((root / f'openapi/{name}.json').read_text())
                    for name in coverage['providers'] if (root / f'openapi/{name}.json').is_file()}
        registry = yaml.safe_load((candidate / 'openapi/registry.yaml').read_text())['providers']
        facts = {}
        for provider in coverage['providers']:
            catalogs = (registry.get(provider) or {}).get('group', [provider])
            paths = [candidate / f'facts/{catalog}.json' for catalog in catalogs]
            if all(path.is_file() for path in paths):
                facts[provider] = normalize_paths(combine_facts(
                    {catalog: json.loads(path.read_text()) for catalog, path in zip(catalogs, paths)}, provider))
        def pending(root):
            return json.loads((root / 'openapi/pending.json').read_text()).get('providers', {})
        ledger = reconcile_ledger(previous, coverage, documents(last_good_root), documents(candidate),
                                  pending(candidate), pending(expected), facts, reason_code,
                                  (effective_object, effective_public_operation))
        result['coverage_ledger'] = ledger
        ledger_ok = ledger['status'] == 'passed'
    result['status'] = 'passed' if ledger_ok and before.keys() == after.keys() and not changed else 'failed'
    return result


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
    full_set = reconcile(args.output / 'expected', candidate, coverage, last_good_root=args.output / 'input')
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

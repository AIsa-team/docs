#!/usr/bin/env python3
"""Stage official mirror updates for review, retaining removed published routes."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from compose_openapi import METHODS, resolve
from upstream_semantics import compare_contracts, path_item
from runtime_consolidate_openapi import merge_components
from import_upstream import import_source
from source_governance import (POLICY_FIELDS, acquisition_receipt, observation,
                               policy_errors, receipt_key, source_report)


def inherited_parameters(item, operation, document):
    parameters = {}
    for values in (item.get('parameters', []), operation.get('parameters', [])):
        for raw in values:
            parameter = resolve(raw, document, preserve_recursive=True)
            parameters[(parameter['in'], parameter['name'])] = raw
    return list(parameters.values())


def preserve_removed(previous, updated, name):
    old_paths = {path: path_item(item, previous) for path, item in previous.get('paths', {}).items()}
    new_paths = {path: path_item(item, updated) for path, item in updated.get('paths', {}).items()}
    removed = [(path, method) for path, item in old_paths.items()
               for method in sorted(METHODS & item.keys()) if method not in new_paths.get(path, {})]
    if not removed:
        return updated, []
    result, old = copy.deepcopy(updated), copy.deepcopy(previous)
    # Materialize Path Item references before component renaming. Only removed
    # operations receive old inherited fields, so updated methods keep theirs.
    old['paths'] = copy.deepcopy(old_paths)
    result['paths'] = copy.deepcopy(new_paths)
    for path in {path for path, _ in removed}:
        item = result['paths'].get(path, {})
        if 'parameters' in item:
            for method in METHODS & item.keys():
                item[method]['parameters'] = inherited_parameters(item, item[method], updated)
            item.pop('parameters')
    result.setdefault('components', {})
    merge_components(result, old, name)
    for path, method in removed:
        item = old['paths'][path]
        operation = item[method]
        parameters = inherited_parameters(item, operation, result)
        if parameters:
            operation['parameters'] = parameters
        operation.setdefault('servers', copy.deepcopy(item.get('servers', old.get('servers', [{'url': '/'}]))))
        operation.setdefault('security', copy.deepcopy(old.get('security', [])))
        result.setdefault('paths', {}).setdefault(path, {})[method] = operation
    source = result['info']['x-aisa-source']
    source['retained_operations'] = [f'{method.upper()} {path}' for path, method in removed]
    source['converter'] = 'scripts/refresh_upstream.py@2'
    return result, source['retained_operations']


def source_evidence(source, checked_at):
    fetched_at = source.get('fetched_at')
    age = None
    if isinstance(fetched_at, str):
        try:
            fetched = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
            if fetched.tzinfo is not None:
                age = max(0, int((checked_at - fetched).total_seconds()))
        except (TypeError, ValueError):
            pass
    return {'url': source.get('url'), 'content_hash': source.get('content_hash'),
            'fetched_at': fetched_at, 'source_age_seconds': age,
            'converter': source.get('converter')}


def refresh(root, fetch=import_source, checked_at=None, receipts=None, attempts=None):
    checked_at = checked_at or datetime.now(timezone.utc)
    receipts = copy.deepcopy(receipts or {})
    attempts = copy.deepcopy(attempts or {})
    changes, report = {}, {'updated': {}, 'manual': [], 'pinned': {}, 'failed': {},
                           'checked_at': checked_at.isoformat(), 'checked': {},
                           'comparison_version': 'scripts/upstream_semantics.py@2',
                           'sources': {}, 'receipts': receipts, 'attempts': attempts, 'policy_errors': {}}
    for path in sorted((root / 'openapi/upstream').glob('*.json')):
        previous = json.loads(path.read_text())
        source = previous.get('info', {}).get('x-aisa-source', {})
        problems = policy_errors(source)
        if problems:
            report['policy_errors'][path.stem] = problems
        report['sources'][path.name] = observation(source, receipts, checked_at)
        if source.get('refresh_policy') == 'pinned':
            report['pinned'][path.stem] = source.get('refresh_reason', 'Explicitly pinned source; review a source revision update separately.')
            continue
        if source.get('kind') != 'provider_openapi' and source.get('refresh_policy') != 'automatic':
            report['manual'].append(path.stem)
            continue
        evidence, semantic, phase = None, None, 'source_acquisition'
        try:
            updated = fetch(path.stem, source['url'])
            updated_source = updated['info']['x-aisa-source']
            # Importers own acquisition metadata; the reviewed maintenance
            # policy survives a refresh and is never replaced by timestamps.
            for key in (*POLICY_FIELDS, 'policy_revision'):
                if key in source:
                    updated_source[key] = copy.deepcopy(source[key])
            updated_source.setdefault('url', source['url'])
            evidence = {'previous': source_evidence(source, checked_at),
                        'fetched': source_evidence(updated_source, checked_at)}
            if updated_source['content_hash'] == source.get('content_hash'):
                report['checked'][path.stem] = {'status': 'source_unchanged', **evidence}
                if not problems:
                    receipts[receipt_key(source)] = acquisition_receipt(source, checked_at)
                attempts[receipt_key(source)] = {'checked_at': checked_at.isoformat(), 'status': 'confirmed'}
                report['sources'][path.name] = observation(source, receipts, checked_at, 'unchanged')
                continue
            phase = 'semantic_comparison'
            semantic = compare_contracts(previous, updated)
            report['checked'][path.stem] = {'status': semantic['status'], **evidence}
            phase = 'retain_removals'
            retained, removed = preserve_removed(previous, updated, path.name)
            changes[path] = json.dumps(retained, indent=2, ensure_ascii=False) + '\n'
            report['updated'][path.stem] = {'removed_upstream_but_retained': removed,
                                          'semantic_changes': semantic,
                                          'candidate_semantic_changes': compare_contracts(previous, retained),
                                          **evidence}
            if not policy_errors(updated_source):
                receipts[receipt_key(updated_source)] = acquisition_receipt(updated_source, checked_at)
            attempts[receipt_key(updated_source)] = {'checked_at': checked_at.isoformat(), 'status': 'confirmed'}
            report['sources'][path.name] = observation(updated_source, receipts, checked_at, 'changed')
        except Exception as exc:
            attempts[receipt_key(source)] = {'checked_at': checked_at.isoformat(), 'status': 'fetch_failed', 'failure': type(exc).__name__}
            report['failed'][path.stem] = {'status': 'source_preserved',
                                         'failure': type(exc).__name__, 'phase': phase,
                                         'previous': source_evidence(source, checked_at),
                                         'compatibility': 'not_assessed'}
            if evidence is not None:
                report['failed'][path.stem]['fetched'] = evidence['fetched']
            if semantic is not None:
                report['failed'][path.stem]['semantic_changes'] = semantic
            report['sources'][path.name] = observation(source, receipts, checked_at, 'fetch_failed')
    report['status'] = 'failed' if report['failed'] or report['policy_errors'] or any(row['freshness'] == 'overdue' for row in report['sources'].values()) else (
        'not_assessed' if any(row['freshness'] != 'fresh' for row in report['sources'].values()) else 'passed')
    return changes, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--receipts', type=Path, help='Existing workflow receipt report/cache; no receipt inferred from fetched_at')
    parser.add_argument('--audit-only', action='store_true', help='Assess all source policies/receipts without fetching or writing')
    args = parser.parse_args()
    saved = json.loads(args.receipts.read_text()) if args.receipts and args.receipts.exists() else {}
    receipts = saved.get('receipts', {})
    attempts = saved.get('attempts', {})
    changes, report = ({}, source_report(args.root, receipts, attempts=attempts)) if args.audit_only else refresh(args.root, receipts=receipts, attempts=attempts)
    if args.write:
        for path, text in changes.items():
            path.write_text(text)
    rendered = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
    print(rendered)
    raise SystemExit(0 if report['status'] == 'passed' else (3 if report['status'] == 'not_assessed' else 1))

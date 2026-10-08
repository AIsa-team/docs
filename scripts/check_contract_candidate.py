#!/usr/bin/env python3
"""Check real PR outputs and reproduce candidates from public runtime evidence.

No production requests are made. Accepted debt comes only from the explicitly
selected reviewed Git revision, never the candidate's current coverage file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from contract_readiness import _body_contract, _operations, _parameter_contract, _schema_contract, check_readiness
from compose_openapi import resolve
from runtime_registry import published_documents


def load_baseline(root: Path, revision: str | None):
    if not revision:
        return None
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('readiness baseline must be a full reviewed Git commit SHA')
    value = subprocess.run(['git', 'show', f'{revision}:openapi/coverage.json'],
                           cwd=root, capture_output=True, text=True, check=True)
    coverage = json.loads(value.stdout)
    if not isinstance(coverage, dict) or not isinstance(coverage.get('providers'), dict):
        raise ValueError('reviewed baseline has no runtime provider coverage')
    return coverage


def effective_request(operation, document):
    """Local request semantics only; editorial and response data have no role."""
    result = {'parameters': dict(_parameter_contract(p, document) for p in operation.get('parameters', []))}
    if operation.get('requestBody') is not None:
        result['requestBody'] = _body_contract(resolve(operation['requestBody'], document, preserve_recursive=True))
    security = operation.get('security', document.get('security', []))
    result['security'] = sorted(
        (tuple(sorted((name, tuple(sorted(scopes))) for name, scopes in requirement.items())) for requirement in security),
        key=repr)
    names = {name for requirement in security for name in requirement}
    schemes = document.get('components', {}).get('securitySchemes', {})
    result['securitySchemes'] = {name: _schema_contract(resolve(schemes[name], document, preserve_recursive=True))
                                for name in names}
    return result


def effective_responses(operation, document):
    """Payload/protocol declarations and explicit response uncertainty."""
    responses = {str(status): _schema_contract(resolve(response, document, preserve_recursive=True))
                 for status, response in operation.get('responses', {}).items()}
    return {'responses': responses, 'pending': operation.get('x-aisa-response-pending')}


def assess_fresh_contracts(report, documents, recomposed_documents, coverage, expected_coverage=None):
    """Verify request/response declarations against fresh composition, never hashes."""
    if not isinstance(coverage, dict) or not isinstance(coverage.get('providers'), dict):
        return
    for provider, rows in coverage['providers'].items():
        if expected_coverage is not None:
            fields = ('binding_hash', 'source_binding_hash', 'response_source_binding_hash', 'runtime_status')
            expected_rows = {(r['path'], r['method']): r for r in expected_coverage.get('providers', {}).get(provider, [])}
            mismatch = coverage.get('schema_version') != 2 or any(
                any(row.get(k) != expected_rows.get((row.get('path'), row.get('method')), {}).get(k) for k in fields)
                for row in rows)
            if mismatch:
                result = report['providers'][provider]
                result['errors'].append({'code': 'fresh_debt_evidence_mismatch', 'provider': provider})
                result['status'] = report['status'] = 'failed'
                if provider not in report['blocked_providers']:
                    report['blocked_providers'].append(provider)
        actual_document = documents.get(provider, {})
        expected_document = recomposed_documents.get(provider, {})
        actual = dict(_operations(actual_document))
        expected = dict(_operations(expected_document))
        for row in rows:
            if row.get('status') != 'composed' or row.get('publication_state') == 'retained':
                continue
            key = (row.get('path'), str(row.get('method', '')).lower())
            code, detail = None, None
            try:
                if key not in expected:
                    code = 'fresh_request_recomposition_missing'
                elif key not in actual:
                    continue  # The primary checker reports the missing operation.
                elif effective_request(actual[key], actual_document) != effective_request(expected[key], expected_document):
                    code = 'composed_request_contract_mismatch'
                elif effective_responses(actual[key], actual_document) != effective_responses(expected[key], expected_document):
                    code = 'composed_response_contract_mismatch'
            except (ValueError, KeyError, TypeError) as exc:
                code, detail = 'unresolved_composed_request', str(exc)
            if code:
                result = report['providers'][provider]
                error = {'code': code, 'provider': provider, 'path': key[0], 'method': key[1].upper()}
                if detail is not None:
                    error['detail'] = detail
                result['errors'].append(error)
                result['status'] = report['status'] = 'failed'
                if provider not in report['blocked_providers']:
                    report['blocked_providers'].append(provider)


def verified_retained_coverage(root, coverage, documents, published_ref):
    """A candidate cannot certify its own historical publication state."""
    import copy
    from pull_openapi import normalize_paths, operations
    from compose_openapi import referenced_components, resolve
    def effective_operations(document):
        normalized = normalize_paths(document)
        result = {}
        for path, method, op in operations(normalized):
            value = copy.deepcopy(op)
            item = normalized['paths'][path]
            parameters = {}
            for parameter in item.get('parameters', []) + op.get('parameters', []):
                resolved = resolve(parameter, normalized, preserve_recursive=True)
                parameters[(resolved.get('in'), resolved.get('name'))] = parameter
            if parameters:
                value['parameters'] = list(parameters.values())
            value['security'] = op.get('security', normalized.get('security', []))
            value['servers'] = op.get('servers', item.get('servers', normalized.get('servers', [])))
            schemes = {name for requirement in value['security'] for name in requirement}
            result[(path, method)] = {'operation': value,
                                     'components': referenced_components(value, normalized),
                                     'security_schemes': {name: normalized.get('components', {}).get('securitySchemes', {}).get(name) for name in sorted(schemes)}}
        return result
    accepted = copy.deepcopy(coverage)
    if not isinstance(accepted, dict):
        return accepted
    if published_ref and not re.fullmatch(r'[0-9a-f]{40}', published_ref):
        raise ValueError('published reference must be a full independently selected Git SHA')
    for provider, rows in accepted.get('providers', {}).items():
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', provider):
            raise ValueError('invalid provider in candidate coverage')
        if not any(row.get('publication_state') == 'retained' for row in rows):
            continue
        current = effective_operations(documents.get(provider, {}))
        previous = {}
        if published_ref and any(row.get('publication_state') == 'retained' for row in rows):
            result = subprocess.run(['git', 'show', f'{published_ref}:openapi/{provider}.json'],
                                    cwd=root, capture_output=True, text=True)
            if result.returncode == 0:
                previous = effective_operations(json.loads(result.stdout))
        for row in rows:
            if row.get('publication_state') != 'retained':
                continue
            relevant = {key: op for key, op in current.items() if key[0] == row.get('path')
                        and str(row.get('method', '')).lower() in (key[1], 'any')}
            # No current operation means no false claim of published completeness.
            if relevant and any(previous.get(key) != op for key, op in relevant.items()):
                row.pop('publication_state', None)
    return accepted


def assess_candidate(root: Path, facts_dir: Path, baseline_ref: str | None = None,
                     published_ref: str | None = None):
    # Inspect committed/staged outputs before regeneration. Regeneration cannot
    # conceal a conflicting identity in the actual PR's publication graph.
    baseline = load_baseline(root, baseline_ref)
    actual = check_readiness({}, published_documents(root), {'providers': {}})
    if actual['global_errors']:
        return actual
    if not (facts_dir / 'index.json').exists():
        return {'schema_version': 1, 'status': 'not_assessed',
                'global_errors': [], 'blocked_providers': [], 'providers': {},
                'baseline_assessed': baseline is not None,
                'missing_inputs': ['locked public runtime index/facts'],
                'message': 'Restore runtime-contract evidence before assessing this candidate.'}
    from pull_openapi import stage
    context = {'baseline_coverage': baseline, 'offline': True, 'published_ref': published_ref}
    # stage only prepares an in-memory candidate. It does not write files.
    stage(root, facts_dir, 'https://unused.invalid', with_pages=False, readiness_context=context)
    coverage_path = root / 'openapi/coverage.json'
    coverage = json.loads(coverage_path.read_text()) if coverage_path.exists() else None
    documents = published_documents(root)
    coverage = verified_retained_coverage(root, coverage, documents, published_ref or baseline_ref)
    report = check_readiness(context['facts_by_provider'], documents,
                             coverage, baseline_coverage=baseline,
                             runtime_index=context['runtime_index'])
    assess_fresh_contracts(report, documents, context['recomposed_documents'], coverage, context['coverage'])
    staged = context['report']
    report['composed_candidate'] = staged
    if staged['status'] != 'passed' and report['status'] == 'passed':
        report['status'] = staged['status']
    report['baseline_ref'] = baseline_ref
    report['evaluation'] = 'actual_publication_graph_and_offline_composed_candidate'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--facts-dir', type=Path, help='Public runtime evidence restored from the existing contract cache')
    parser.add_argument('--baseline-ref', help='Independently reviewed Git SHA; absence grants no pending exemptions')
    parser.add_argument('--published-ref', help='PR base or independently selected previous publication Git SHA used only to verify retained contents')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--source-receipts', type=Path, help='Attributed source-maintenance receipts; defaults to workflow cache')
    args = parser.parse_args()
    try:
        report = assess_candidate(args.root, args.facts_dir or args.root / '.cache/runtime-contracts', args.baseline_ref, args.published_ref)
        from source_governance import source_report
        receipt_path = args.source_receipts or args.root / '.cache/source-reviews.json'
        saved = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        sources = source_report(args.root, saved.get('receipts', {}), attempts=saved.get('attempts', {}))
        report['source_governance'] = sources
        if sources['status'] != 'passed' and sources['sources']:
            if report['status'] != 'failed':
                report['status'] = sources['status']
            report.setdefault('missing_inputs', []).append('current source-maintenance evidence')
        from publication_surface import validate_surfaces, publication_hashes
        try:
            report['publication_surfaces'] = validate_surfaces(args.root, args.published_ref)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            report['status'] = 'failed'
            report.setdefault('global_errors', []).append({'code': 'publication_surface_mismatch', 'detail': str(exc)})
        aggregate_path = args.root / 'openapi.yaml'
        if aggregate_path.exists():
            import runtime_consolidate_openapi as consolidate
            import yaml
            previous_root = consolidate.OPENAPI_DIR
            try:
                consolidate.OPENAPI_DIR = str(args.root / 'openapi')
                expected = consolidate.build_unified_spec()
                consolidate.inject_x402_annotations(expected)
                consolidate.remove_v2_path_mirrors(expected)
            finally:
                consolidate.OPENAPI_DIR = previous_root
            raw = aggregate_path.read_bytes()
            try:
                consolidate.validate_reference_closure(yaml.safe_load(raw))
            except (KeyError, TypeError, ValueError) as exc:
                report['status'] = 'failed'
                report.setdefault('global_errors', []).append({'code': 'aggregate_unresolved_reference', 'detail': str(exc)})
            if yaml.safe_load(raw) != expected:
                report['status'] = 'failed'
                report.setdefault('global_errors', []).append({'code': 'aggregate_recomposition_mismatch'})
            report['publication_artifact'] = {'openapi_sha256': hashlib.sha256(raw).hexdigest(),
                'assessment_scope': 'formal producer artifact declarations and source maintenance; no execution',
                'source_hashes': {name: row['source_hash'] for name, row in sources['sources'].items()},
                'files_sha256': publication_hashes(args.root),
                'baseline_ref': args.baseline_ref, 'published_ref': args.published_ref}
        else:
            if report['status'] != 'failed':
                report['status'] = 'not_assessed'
            report.setdefault('missing_inputs', []).append('consolidated publication artifact')
    except Exception as exc:
        report = {'schema_version': 1, 'status': 'not_assessed', 'global_errors': [],
                  'missing_inputs': ['candidate evaluation failed'], 'error': str(exc)}
    rendered = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered)
    print(rendered)
    if report['status'] == 'not_assessed':
        return 3
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

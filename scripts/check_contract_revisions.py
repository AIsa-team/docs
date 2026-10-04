#!/usr/bin/env python3
"""Compare public contract revisions. No provider calls or credentials required."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
import yaml


def compare(documents, runtime, website, mcp, router):
    errors = []
    index = {provider['id']: provider.get('facts_hash') for provider in runtime.get('providers', [])}
    web = website.get('x-aisa-document', {}).get('providers', {})
    mcp_hashes = mcp.get('documentHashes', {})
    router_hashes = router.get('provider_document_hashes', {})
    for provider, metadata in documents.items():
        expected = metadata.get('document_hash')
        if not expected:
            continue  # Legacy is explicitly not a verified runtime projection.
        for surface, actual in [('website', web.get(provider, {}).get('document_hash')),
                                ('mcp', mcp_hashes.get(provider)), ('tool-router', router_hashes.get(provider))]:
            if actual != expected:
                errors.append(f'{provider}:{surface}:document_hash_mismatch')
        catalogs = metadata.get('catalogs') or {provider: {'x-aisa-document': {'facts_hash': metadata.get('facts_hash')}}}
        for catalog, info in catalogs.items():
            facts = info.get('x-aisa-document', {}).get('facts_hash')
            if not facts or index.get(catalog) != facts:
                errors.append(f'{provider}:{catalog}:facts_hash_mismatch')
    return sorted(set(errors))


def read_public(url):
    with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=20) as response:
        return json.load(response)


def update_state(errors, previous):
    counts = previous.get('consecutive', {})
    return {'checked_at': int(time.time()), 'consecutive': {error: counts.get(error, 0) + 1 for error in errors}}


def monitor_timing(assessment, current, previous, expected_ref, source_hash):
    """Retain first on-time completion only for this exact release identity.

    Every current public surface is still checked. This cache only avoids
    treating a completed release as forever overdue; strict acceptance ignores it.
    """
    from contract_activation import deadline
    if not expected_ref:
        return current, None
    identity = {'docs_ref': expected_ref, 'openapi_sha256': source_hash,
                'budget_start': current['budget_start'], 'phase': current['phase']}
    observed = previous.get('convergence_observation', {})
    retained = None
    if observed.get('identity') == identity:
        checked_at = observed.get('checked_at')
        if type(checked_at) is int and 0 < checked_at <= assessment['checked_at']:
            try:
                first = deadline(current['budget_start'], current['phase'],
                                 datetime.fromtimestamp(checked_at, timezone.utc))
                if not first['deadline_breached']:
                    retained = observed
            except (ValueError, OverflowError, OSError):
                pass
    if assessment['status'] == 'passed':
        if retained:
            first['current_elapsed_seconds'] = current['elapsed_seconds']
            first['observed_at'] = retained['checked_at']
            first['scope'] = 'first on-time convergence; current public surfaces revalidated'
            return first, retained
        if not current['deadline_breached']:
            retained = {'identity': identity, 'checked_at': assessment['checked_at']}
    return current, retained


def assess(documents, runtime=None, website=None, mcp=None, router=None,
           expected_docs_ref=None, failures=(), website_version=None,
           expected_openapi_sha256=None):
    """Strict, dated convergence evidence, separate from monitor escalation."""
    verified = {key: value for key, value in documents.items() if value.get('document_hash')}
    missing = list(failures)
    if not verified:
        missing.append('docs:no_runtime_composed_provider_metadata')
    surfaces = dict(runtime=runtime, website=website, mcp=mcp, router=router)
    missing.extend(f'{key}:publication_metadata_unavailable' for key, value in surfaces.items()
                   if not isinstance(value, dict))
    errors = []
    if expected_docs_ref and not re.fullmatch(r'[0-9a-f]{40}', expected_docs_ref):
        raise ValueError('expected docs revision must be a full Git SHA')
    if expected_openapi_sha256 and not re.fullmatch(r'[0-9a-f]{64}', expected_openapi_sha256):
        raise ValueError('expected aggregate content hash must be a full SHA-256')
    if expected_docs_ref or expected_openapi_sha256:
        if not isinstance(website_version, dict):
            missing.append('website:source_version_unavailable')
        if not expected_openapi_sha256:
            missing.append('docs:aggregate_content_hash_unavailable')
    if not missing:
        errors = compare(documents, **surfaces)
        represented = set()
        for provider, metadata in verified.items():
            represented.update(metadata.get('catalogs') or {provider: {}})
        for provider in runtime.get('providers', []):
            if provider['id'] not in represented:
                errors.append(f"{provider['id']}:docs:catalog_missing")
        for provider in runtime.get('pending_providers', []):
            missing.append(f"runtime:{provider['id']}:projection_pending")
        if expected_docs_ref:
            if mcp.get('docsRefs') != [expected_docs_ref]:
                errors.append('mcp:docs_revision_mismatch')
            if router.get('docs_commit') != expected_docs_ref:
                errors.append('tool-router:docs_revision_mismatch')
        if expected_docs_ref or expected_openapi_sha256:
            if website_version.get('mode') != 'formal':
                errors.append('website:source_mode_not_formal')
            if expected_docs_ref and website_version.get('docsRevision') != expected_docs_ref:
                errors.append('website:docs_revision_mismatch')
            if website_version.get('contentHash') != expected_openapi_sha256:
                errors.append('website:aggregate_content_hash_mismatch')
    return {'checked_at': int(time.time()),
            'status': 'not_assessed' if missing else ('failed' if errors else 'passed'),
            'scope': 'public_contract_convergence',
            'verified_providers': len(verified),
            'legacy_providers': len(documents) - len(verified),
            'expected_docs_ref': expected_docs_ref,
            'expected_openapi_sha256': expected_openapi_sha256,
            'missing_inputs': sorted(set(missing)), 'mismatches': sorted(set(errors))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--state', type=Path, default=Path('.cache/contract-revisions/state.json'))
    parser.add_argument('--acceptance', action='store_true', help='Fail immediately on missing evidence or any mismatch; does not update monitor state')
    parser.add_argument('--evidence-dir', type=Path, help='Offline public metadata: runtime.json, website.json, mcp.json, router.json')
    parser.add_argument('--expected-docs-ref', help='Full immutable docs SHA required in MCP and Router publication metadata')
    parser.add_argument('--report', type=Path, help='Save dated assessment JSON; contains no provider requests')
    parser.add_argument('--budget-start', help='UTC start recorded by the release owner; no inferred/reset deadline')
    parser.add_argument('--budget-phase', choices=('candidate', 'convergence'), default='convergence')
    parser.add_argument('--require-budget', action='store_true', help='Activated monitoring cannot run without the independently recorded start and expected SHA')
    parser.add_argument('--selection-file', type=Path, help='Actual fixed source selected by the scheduled/manual recovery workflow')
    args = parser.parse_args()
    if args.require_budget and (not args.budget_start or not args.expected_docs_ref):
        assessment = {'status': 'not_assessed', 'missing_inputs': ['recorded budget start and independently selected Docs SHA'],
                      'scope': 'activated monitor; no network or deadline inference'}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(assessment, indent=2) + '\n')
        print(json.dumps(assessment))
        return 3
    if (args.evidence_dir or args.expected_docs_ref) and not (args.acceptance or args.require_budget):
        parser.error('--evidence-dir and --expected-docs-ref require --acceptance')
    if args.acceptance and not args.expected_docs_ref:
        parser.error('--acceptance requires --expected-docs-ref from an independently selected publication')
    if args.expected_docs_ref and not re.fullmatch(r'[0-9a-f]{40}', args.expected_docs_ref):
        parser.error('--expected-docs-ref must be a full Git SHA')
    if args.budget_start:
        from contract_activation import deadline
        try:
            deadline(args.budget_start, args.budget_phase)
        except ValueError as exc:
            assessment = {'status': 'not_assessed', 'missing_inputs': ['valid independently recorded budget start'],
                          'scope': 'budget validation before any fetch', 'error': str(exc)}
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(assessment, indent=2) + '\n')
            print(json.dumps(assessment))
            return 3
    if args.selection_file:
        from contract_activation import select_revision
        selected = json.loads(args.selection_file.read_text())['selection']
        selection = select_revision(selected['event'], selected['docs_ref'], selected['openapi_sha256'],
                                    selected['docs_ref'], selected['openapi_sha256'])
        if selection['docs_ref'] != args.expected_docs_ref:
            raise ValueError('selected source differs from independently expected Docs SHA')
        raw = subprocess.check_output(['git', 'show', selection['docs_ref'] + ':openapi.yaml'], cwd=args.root)
        if hashlib.sha256(raw).hexdigest() != selection['openapi_sha256']:
            raise ValueError('selected source bytes do not match exact publication hash')
        spec = yaml.safe_load(raw)
    else:
        raw = (args.root / 'openapi.yaml').read_bytes()
        spec = yaml.safe_load(raw)
    source_hash = hashlib.sha256(raw).hexdigest()
    documents = spec.get('info', {}).get('x-aisa-document', {}).get('providers', {})
    targets = {
        'runtime': 'https://api.aisa.one/info/openapi.json',
        'website': 'https://aisa.one/.well-known/agent-card.json',
        'mcp': 'https://mcp.aisa.one/.well-known/mcp.json',
        'router': 'https://tools.aisa.one/.well-known/catalog.json',
    }
    if args.expected_docs_ref:
        targets['website_version'] = 'https://aisa.one/api/contracts/version'
    results, failures = {}, []
    for key, url in targets.items():
        try:
            filename = 'website-version' if key == 'website_version' else key
            results[key] = json.loads((args.evidence_dir / f'{filename}.json').read_text()) if args.evidence_dir else read_public(url)
        except Exception as exc:
            failures.append(f'{key}:unavailable:{type(exc).__name__}')
    assessment = assess(documents, **results, expected_docs_ref=args.expected_docs_ref,
                        expected_openapi_sha256=source_hash if args.expected_docs_ref else None,
                        failures=failures)
    # Strict acceptance neither reads nor writes prior monitor observations.
    previous = json.loads(args.state.read_text()) if not args.acceptance and args.state.exists() else {}
    observation = None
    if args.budget_start:
        from contract_activation import deadline
        assessment['timing'] = deadline(args.budget_start, args.budget_phase)
        if not args.acceptance:
            assessment['timing'], observation = monitor_timing(
                assessment, assessment['timing'], previous, args.expected_docs_ref, source_hash)
        if assessment['timing']['deadline_breached']:
            assessment['status'] = 'failed'
            assessment['mismatches'].append('timing:deadline_breached')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(assessment, indent=2, sort_keys=True) + '\n')
    if args.acceptance:
        print(json.dumps(assessment, indent=2, sort_keys=True))
        return 0 if assessment['status'] == 'passed' else 1
    # Scheduled monitoring observes the same convergence assessment as strict
    # acceptance, retaining only its existing two-consecutive-check escalation.
    failures = sorted(set(assessment['mismatches'] + assessment['missing_inputs']))
    state = update_state(failures, previous)
    if observation:
        state['convergence_observation'] = observation
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({'verified_providers': sum(bool(p.get('document_hash')) for p in documents.values()),
                      'legacy_providers': sum(not bool(p.get('document_hash')) for p in documents.values()),
                      'assessment_status': assessment['status'],
                      'mismatches': state['consecutive']}, indent=2))
    return 1 if assessment.get('timing', {}).get('deadline_breached') or any(count >= 2 for count in state['consecutive'].values()) else 0

if __name__ == '__main__':
    raise SystemExit(main())

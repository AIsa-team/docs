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


def compare(documents, runtime, website, router):
    errors = []
    index = {provider['id']: provider.get('facts_hash') for provider in (runtime or {}).get('providers', [])}
    web = (website or {}).get('x-aisa-document', {}).get('providers', {})
    router_hashes = (router or {}).get('provider_document_hashes', {})
    if not isinstance(router_hashes, dict):
        # Unpublished/legacy Router metadata can encode this map as null.
        # Keep the failure in the assessment and continue per-provider checks.
        errors.append('tool-router:provider_document_hashes_invalid')
        router_hashes = {}
    for provider, metadata in documents.items():
        expected = metadata.get('document_hash')
        if not expected:
            continue  # Legacy is explicitly not a verified runtime projection.
        for surface, available, actual in [('website', website, web.get(provider, {}).get('document_hash')),
                                ('tool-router', router, router_hashes.get(provider))]:
            if available is None:
                continue
            if actual != expected:
                errors.append(f'{provider}:{surface}:document_hash_mismatch')
        catalogs = metadata.get('catalogs') or {provider: {'x-aisa-document': {'facts_hash': metadata.get('facts_hash')}}}
        for catalog, info in catalogs.items():
            if runtime is None:
                continue
            facts = info.get('x-aisa-document', {}).get('facts_hash')
            if not facts or index.get(catalog) != facts:
                errors.append(f'{provider}:{catalog}:facts_hash_mismatch')
    return sorted(set(errors))


def read_public(url):
    with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=20) as response:
        return json.load(response)



def read_public_bytes(url):
    with urlopen(Request(url, headers={'Accept': 'application/yaml, application/json'}), timeout=60) as response:
        return response.read()


def website_metadata(raw, expected_sha256):
    """Bind the actual served aggregate before inspecting its provider metadata."""
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Website aggregate bytes differ from selected formal publication')
    spec = yaml.safe_load(raw)
    providers = spec.get('info', {}).get('x-aisa-document', {}).get('providers')
    if not isinstance(providers, dict):
        raise ValueError('Website formal aggregate provider metadata is missing')
    return {'x-aisa-document': {'providers': providers}}


def verified_empty_catalogs(root, ref, source_hash, runtime, documents, provider_reader=None):
    """Prove only omitted, disabled-only catalogs from the fixed formal graph.

    A missing provider is never waived by an empty paths map alone. Every
    coverage row must match an accepted disabled pending row in the hash-bound
    formal assessment. Other exclusions remain failures until explicitly modeled.
    """
    represented = set()
    for provider, metadata in documents.items():
        if metadata.get('document_hash'):
            represented.update(metadata.get('catalogs') or {provider: {}})
    absent = [p for p in runtime.get('providers', []) if p['id'] not in represented]
    if not absent or not ref:
        return {}
    def fixed(path):
        return subprocess.check_output(['git', 'show', ref + ':' + path], cwd=root)
    current = json.loads(fixed('docs/publication/current.json'))
    if current.get('status') != 'passed' or current.get('openapi') != {'path': 'openapi.yaml', 'sha256': source_hash} or current.get('files_sha256', {}).get('openapi.yaml') != source_hash:
        raise ValueError('Empty catalog proof differs from selected formal aggregate')
    def bound(path, expected):
        raw = fixed(path)
        if not expected or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Empty catalog proof artifact hash differs: ' + path)
        return json.loads(raw)
    coverage = bound('openapi/coverage.json', current['files_sha256'].get('openapi/coverage.json'))
    report_binding = current['formal_readiness']
    report = bound('docs/publication/formal-contract-readiness.json', report_binding.get('sha256'))
    if report_binding.get('path') != 'docs/publication/formal-contract-readiness.json' or report.get('status') != 'passed':
        raise ValueError('Empty catalog formal assessment is not passed')
    proofs = {}
    for provider in absent:
        name = provider['id']
        if not re.fullmatch(r'[a-z0-9_-]+', name):
            continue
        path = f'openapi/{name}.json'
        expected = current['files_sha256'].get(path)
        if not expected:
            continue
        spec = bound(path, expected)
        rows = coverage.get('providers', {}).get(name, [])
        assessment = report.get('providers', {}).get(name, {})
        metadata = spec.get('info', {}).get('x-aisa-document', {})
        if (spec.get('paths') != {} or not metadata.get('document_hash') or
                metadata.get('facts_hash') != provider.get('facts_hash') or
                assessment.get('status') != 'passed' or not rows or
                len(rows) != provider.get('operation_count')):
            continue
        accepted = assessment.get('existing_pending', [])
        if any(assessment.get(key) for key in ('errors', 'new_pending', 'missing_inputs')):
            continue
        # Compare every coverage field, including binding hashes and identity,
        # against the producer-accepted record; additional runtime_binding is OK.
        if len({row.get('operation_id') for row in rows}) != len(rows):
            continue
        if not all(row.get('catalog') == name and row.get('status') == 'pending' and
                   row.get('runtime_status') == 'disabled' and
                   any(all(item.get(key) == value for key, value in row.items()) and
                       item.get('runtime_binding', {}).get('status') == 'disabled'
                       for item in accepted) for row in rows):
            continue
        public_raw = (provider_reader(name) if provider_reader else
                      read_public_bytes(f'https://aisa.one/docs/openapi/{name}.json'))
        if hashlib.sha256(public_raw).hexdigest() != expected:
            raise ValueError('Public empty provider bytes differ from formal publication: ' + name)
        proofs[name] = {'reason': 'formal_disabled_only_no_public_operations',
                        'coverage_rows': len(rows), 'provider_sha256': expected,
                        'facts_hash': metadata['facts_hash'], 'document_hash': metadata['document_hash'], 'docs_ref': ref}
    return proofs


def update_state(errors, previous):
    counts = previous.get('consecutive', {})
    return {'checked_at': int(time.time()), 'consecutive': {error: counts.get(error, 0) + 1 for error in errors}}


def retain_assessment_history(state, previous, assessment, identity):
    """Keep the prior publication outcome when a new exact publication is selected."""
    history = list(previous.get('publication_history', []))
    old = previous.get('latest_publication_assessment')
    if previous and not old and 'publication_history' not in previous:
        history.append({'legacy_monitor_state': previous, 'status': 'historical_not_reclassified'})
    if old and old.get('identity') != identity:
        history.append(old)
    state['publication_history'] = history
    state['latest_publication_assessment'] = {'identity': identity, 'assessment': assessment}
    return state


def monitor_timing(assessment, current, previous, expected_ref, source_hash):
    """Retain first on-time completion only for this verified contract and clock.

    Every current public surface is still checked. This cache only avoids
    treating a completed release as forever overdue; strict acceptance ignores it.
    """
    from contract_activation import deadline
    if not expected_ref:
        return current, None
    identity = publication_identity(assessment, expected_ref, source_hash, current['budget_start'], current['phase'])
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


def publication_identity(assessment, expected_ref, source_hash, budget_start, phase):
    proof = assessment.get("formal_provenance")
    identity = {"openapi_sha256": source_hash, "budget_start": budget_start, "phase": phase}
    if proof and proof.get("status") == "passed":
        identity["contract_release"] = proof["contract_release"]
        identity["clock_docs_ref"] = proof["clock_docs_ref"]
    else:
        identity["docs_ref"] = expected_ref
    return identity


def assess(documents, runtime=None, website=None, router=None,
           expected_docs_ref=None, failures=(), website_version=None,
           expected_openapi_sha256=None, formal_provenance=None, empty_catalogs=None):
    """Strict, dated convergence evidence, separate from monitor escalation."""
    verified = {key: value for key, value in documents.items() if value.get('document_hash')}
    missing = list(failures)
    if not verified:
        missing.append('docs:no_runtime_composed_provider_metadata')
    surfaces = dict(runtime=runtime, website=website, router=router)
    missing.extend(f'{key}:publication_metadata_unavailable' for key, value in surfaces.items()
                   if not isinstance(value, dict))
    accepted_refs = {expected_docs_ref}
    if formal_provenance is not None:
        if formal_provenance.get('status') != 'passed' or formal_provenance.get('expected_docs_ref') != expected_docs_ref:
            raise ValueError('Invalid independently verified formal provenance')
        accepted_refs.update(formal_provenance['publications'])
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
    # Missing evidence on one surface must not conceal independently observable
    # drift on another. Unavailable surfaces still keep the assessment unpassed.
    errors = compare(documents, **{key: value if isinstance(value, dict) else None
                                  for key, value in surfaces.items()})
    if isinstance(runtime, dict):
        represented = set()
        for provider, metadata in verified.items():
            represented.update(metadata.get('catalogs') or {provider: {}})
        for provider in runtime.get('providers', []):
            if provider['id'] not in represented and provider['id'] not in (empty_catalogs or {}):
                errors.append(f"{provider['id']}:docs:catalog_missing")
        for provider in runtime.get('pending_providers', []):
            missing.append(f"runtime:{provider['id']}:projection_pending")
    if isinstance(router, dict):
        router_hashes = router.get('provider_document_hashes')
        for name, proof in (empty_catalogs or {}).items():
            if not isinstance(router_hashes, dict) or router_hashes.get(name) != proof.get('document_hash'):
                errors.append(f'{name}:tool-router:document_hash_mismatch')
        if expected_docs_ref:
            if router.get('docs_commit') not in accepted_refs:
                errors.append('tool-router:docs_revision_mismatch')
    if isinstance(website_version, dict):
        if expected_docs_ref or expected_openapi_sha256:
            if website_version.get('mode') != 'formal':
                errors.append('website:source_mode_not_formal')
            if expected_docs_ref and website_version.get('docsRevision') not in accepted_refs:
                errors.append('website:docs_revision_mismatch')
            if website_version.get('contentHash') != expected_openapi_sha256:
                errors.append('website:aggregate_content_hash_mismatch')
    return {'checked_at': int(time.time()),
            'status': 'not_assessed' if missing else ('failed' if errors else 'passed'),
            'scope': 'public_contract_convergence',
            'verified_providers': len(verified),
            'legacy_providers': len(documents) - len(verified),
            'verified_empty_catalogs': empty_catalogs or {},
            'expected_docs_ref': expected_docs_ref,
            'formal_provenance': formal_provenance,
            'expected_openapi_sha256': expected_openapi_sha256,
            'missing_inputs': sorted(set(missing)), 'mismatches': sorted(set(errors))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-surfaces', action='store_true', help='Also require complete JSON, llms content, visible bilingual page samples, MCP loaded source and all Router schemas')
    parser.add_argument('--all-doc-pages', action='store_true', help='With --all-surfaces, read every formal bilingual HTML page instead of sampling')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--state', type=Path, default=Path('.cache/contract-revisions/state.json'))
    parser.add_argument('--acceptance', action='store_true', help='Fail immediately on missing evidence or any mismatch; does not update monitor state')
    parser.add_argument('--evidence-dir', type=Path, help='Offline public evidence: runtime.json, website.yaml (raw aggregate), router.json')
    parser.add_argument('--expected-docs-ref', help='Immutable formal Docs SHA; older consumer refs require full same-contract provenance')
    parser.add_argument('--report', type=Path, help='Save dated assessment JSON; contains no provider requests')
    parser.add_argument('--budget-start', help='UTC start recorded by the release owner; no inferred/reset deadline')
    parser.add_argument('--budget-phase', choices=('candidate', 'convergence'), default='convergence')
    parser.add_argument('--require-budget', action='store_true', help='Activated monitoring cannot run without the independently recorded start and expected SHA')
    parser.add_argument('--selection-file', type=Path, help='Actual fixed source selected by the scheduled/manual recovery workflow')
    args = parser.parse_args()
    if args.all_doc_pages and not args.all_surfaces:
        parser.error('--all-doc-pages requires --all-surfaces')
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
        'website': 'https://aisa.one/openapi.yaml',
        'router': 'https://tools.aisa.one/.well-known/catalog.json',
    }
    if args.expected_docs_ref:
        targets['website_version'] = 'https://aisa.one/api/contracts/version'
    results, failures = {}, []
    for key, url in targets.items():
        try:
            filename = 'website-version' if key == 'website_version' else key
            if key == 'website':
                website_raw = ((args.evidence_dir / 'website.yaml').read_bytes() if args.evidence_dir
                               else read_public_bytes(url))
                results[key] = website_metadata(website_raw, source_hash)
            else:
                results[key] = json.loads((args.evidence_dir / f'{filename}.json').read_text()) if args.evidence_dir else read_public(url)
        except Exception as exc:
            failures.append(f'{key}:unavailable:{type(exc).__name__}')
    provenance = None
    surface_cache = {}
    if args.expected_docs_ref and args.budget_start and not args.evidence_dir and not failures:
        from publication_origin import verify_consumer_refs
        try:
            consumer_refs = [results["router"].get("docs_commit"), results["website_version"].get("docsRevision")]
            if args.all_surfaces:
                surface_cache['mcp-version'] = read_public_bytes('https://mcp.aisa.one/contract-version')
                mcp_refs = json.loads(surface_cache['mcp-version']).get('docsRefs')
                if not isinstance(mcp_refs, list) or len(mcp_refs) != 1:
                    raise ValueError('MCP does not identify one loaded source')
                consumer_refs.extend(mcp_refs)
            provenance = verify_consumer_refs(args.root, args.expected_docs_ref,
                consumer_refs, args.budget_start)
        except Exception as exc:
            failures.append(f"formal_provenance:unavailable:{type(exc).__name__}")
    empty_catalogs = {}
    if isinstance(results.get('runtime'), dict) and args.expected_docs_ref:
        try:
            empty_catalogs = verified_empty_catalogs(args.root, args.expected_docs_ref, source_hash,
                                                    results['runtime'], documents,
                provider_reader=(lambda name: (args.evidence_dir / f'{name}.json').read_bytes())
                if args.evidence_dir else None)
        except Exception as exc:
            failures.append(f'empty_catalog_proof:unavailable:{type(exc).__name__}')
    assessment = assess(documents, **results, formal_provenance=provenance, empty_catalogs=empty_catalogs, expected_docs_ref=args.expected_docs_ref,
                        expected_openapi_sha256=source_hash if args.expected_docs_ref else None,
                        failures=failures)
    if args.all_surfaces:
        from public_surface_checks import check_surfaces, fixed_request_blocks, fixed_payment_bytes
        accepted_refs = {args.expected_docs_ref} if args.expected_docs_ref else set()
        if provenance:
            accepted_refs.update(provenance.get('publications', {}))
        expected_requests = {}
        try:
            if not args.expected_docs_ref:
                raise ValueError('All-surface verification requires a fixed formal publication')
            expected_requests = fixed_request_blocks(args.root, args.expected_docs_ref)
        except Exception as exc:
            assessment['missing_inputs'].append('fixed_llms_requests:unavailable:' + type(exc).__name__)
        expected_payment = None
        try:
            if not args.expected_docs_ref:
                raise ValueError('Payment verification requires a fixed formal publication')
            expected_payment = fixed_payment_bytes(args.root, args.expected_docs_ref)
        except Exception as exc:
            assessment['missing_inputs'].append('fixed_payment_discovery:unavailable:' + type(exc).__name__)
        def surface_reader(name, url):
            if name in surface_cache:
                return surface_cache[name]
            if args.evidence_dir:
                extension = '.json' if name.endswith(('json', 'version')) else '.txt'
                return (args.evidence_dir / (name + extension)).read_bytes()
            return read_public_bytes(url)
        extra = check_surfaces(spec, source_hash, accepted_refs, read_bytes=surface_reader,
                               expected_requests=expected_requests, expected_payment=expected_payment)
        assessment['public_surfaces'] = extra
        assessment['missing_inputs'] = sorted(set(assessment['missing_inputs'] + extra['missing_inputs']))
        assessment['mismatches'] = sorted(set(assessment['mismatches'] + extra['mismatches']))
        from rendered_page_checks import fixed_pages, check_rendered_pages
        try:
            pages = fixed_pages(args.root, args.expected_docs_ref)
            def page_reader(name, url):
                if args.evidence_dir:
                    return (args.evidence_dir / (name + '.html')).read_bytes()
                with urlopen(Request(url, headers={'Accept': 'text/html'}), timeout=20) as response:
                    started, size, chunks = time.monotonic(), 0, []
                    while True:
                        if time.monotonic() - started > 30:
                            raise TimeoutError('Rendered page read exceeded time budget')
                        chunk = response.read(65536)
                        if not chunk:
                            return b''.join(chunks)
                        size += len(chunk)
                        if size > 16 * 1024 * 1024:
                            raise ValueError('Rendered page exceeds byte limit')
                        chunks.append(chunk)
            rendered = check_rendered_pages(pages, read_bytes=page_reader, full=args.all_doc_pages)
        except Exception as exc:
            rendered = {'status': 'not_assessed', 'missing_inputs': [
                'fixed_rendered_pages:unavailable:' + type(exc).__name__], 'mismatches': []}
        assessment['rendered_docs_pages'] = rendered
        assessment['missing_inputs'] = sorted(set(assessment['missing_inputs'] + rendered['missing_inputs']))
        assessment['mismatches'] = sorted(set(assessment['mismatches'] + rendered['mismatches']))
        from router_surface_checks import check_router_surface, METADATA, digest
        router_reads = 0
        def router_reader(method, url, payload=None):
            # Offline evidence is raw lookup output, never a pre-assessed pass.
            # Catalog snapshots bracket deterministically named schema batches.
            nonlocal router_reads
            if url == METADATA:
                router_reads += 1
                filename = 'router-schema-' + ('before' if router_reads == 1 else 'after') + '.json'
            else:
                filename = 'router-schema-batch-' + digest(payload['tools']) + '.json'
            from source_json import loads
            return loads((args.evidence_dir / filename).read_bytes())
        router_schema = check_router_surface(args.root, args.expected_docs_ref,
            read_json=router_reader if args.evidence_dir else None, accepted_refs=accepted_refs)
        assessment['router_schemas'] = router_schema
        assessment['missing_inputs'] = sorted(set(assessment['missing_inputs'] + router_schema['missing_inputs']))
        assessment['mismatches'] = sorted(set(assessment['mismatches'] + router_schema['mismatches']))
        assessment['status'] = ('not_assessed' if assessment['missing_inputs'] else
                                'failed' if assessment['mismatches'] else 'passed')
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
    retain_assessment_history(state, previous, assessment,
                              publication_identity(assessment, args.expected_docs_ref, source_hash, args.budget_start, args.budget_phase))
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

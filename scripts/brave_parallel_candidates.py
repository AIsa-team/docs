#!/usr/bin/env python3
"""Capture static Brave/Parallel references or build an unapproved offline packet.

No runtime/provider business endpoint, identity import, publication or registry
mutation is supported. Source selection uses an evidenced upstream path only.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from compose_openapi import METHODS, digest, effective_object, has_response_contract, referenced_components, response_object, upstream_path_item
from import_brave_reference import INDEX_URL, ORIGIN, convert_specs, decode_api_spec, import_reference, load_reference
from import_parallel_legacy_events import SOURCE_URL, extract
from source_json import loads

SOURCE_URLS = {name: 'https://docs.parallel.ai/' + name + '.json' for name in
               ('public-openapi', 'docs-latest-openapi', 'docs-legacy-openapi')}
FILE_URLS = {**{'parallel-' + key + '.json': value for key, value in SOURCE_URLS.items()},
             'brave-official.json': INDEX_URL, 'parallel-archived-events.json': SOURCE_URL}
PROVIDERS = {'parallel.ai', 'brave-search', 'brave-answer'}
EXPECTED_ORIGINS = {provider: 'https://api.parallel.ai' if provider == 'parallel.ai' else
                    'https://api.search.brave.com' for provider in PROVIDERS}
CURRENT_FIELDS = ('endpoint_id', 'provider_key', 'public_path', 'contract_method', 'upstream_path',
    'endpoint_status', 'provider_status', 'authority_equal_expected', 'profile_binding_metadata_matches',
    'target_matches_endpoint', 'target_has_query', 'compiled_contract_revision', 'profile_revision',
    'profile_key', 'profile_status', 'binding_sha256', 'profile_canonical_sha256',
    'profile_contract_sha256', 'target_sha256', 'upstream_origin_sha256', 'stored_target_path')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def static_url(url):
    if url in {INDEX_URL, SOURCE_URL, *SOURCE_URLS.values()}:
        return True
    prefix = ORIGIN + '/api-reference/'
    return (url.startswith(prefix) and url.endswith('/__data.json')
            and re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*/__data\.json', url[len(prefix):]) is not None)


class StaticRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not static_url(newurl):
            raise ValueError('static redirect destination outside allowlist')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def capture(packet):
    folder = packet / 'candidates'
    folder.mkdir(parents=True, exist_ok=True)
    receipts, brave_rows = [], {}
    opener = build_opener(StaticRedirectHandler())

    def fetch(url):
        if not static_url(url):
            raise ValueError('only allowlisted official static references may be fetched')
        with opener.open(Request(url, headers={'User-Agent': 'AIsa-static-contract-review'}), timeout=30) as response:
            if not static_url(response.url):
                raise ValueError('static source redirected outside allowlist')
            raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise ValueError('static source exceeds capture bound')
            receipts.append({'url': url, 'status': response.status,
                             'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                             'source_sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
            return raw

    for name, url in SOURCE_URLS.items():
        raw = fetch(url)
        load_reference(raw)
        # Preserve original official bytes for reproducible source hashing.
        (folder / ('parallel-' + name + '.json')).write_bytes(raw)
    raw = fetch(SOURCE_URL)
    (folder / 'parallel-archived-events-source.json').write_bytes(raw)
    write_json(folder / 'parallel-archived-events.json', extract(raw))

    def brave_fetch(url):
        raw = fetch(url)
        if url.endswith('/__data.json'):
            # Persist only the API schema graph. Page/session data is excluded.
            brave_rows[url.removesuffix('/__data.json')] = decode_api_spec(load_reference(raw))
        return raw

    document, metadata = import_reference(brave_fetch)
    write_json(folder / 'brave-official.json', document)
    write_json(packet / 'brave-structured-sources.json', brave_rows)
    write_json(packet / 'brave-source-provenance.json', metadata)
    write_json(packet / 'source-get-receipts.json', receipts)
    return receipts


def proposed_id(base, method, count, public_path):
    if not isinstance(base, str) or not base:
        return None
    if count == 1:
        return base
    candidate = method + '_' + base
    return candidate if len(candidate) <= 56 else candidate[:49] + '_' + hashlib.sha256(
        (method + ' ' + public_path).encode()).hexdigest()[:6]


def current_bindings(frozen, current):
    """Join sanitized metadata only; this is not a full ValidateBinding proof."""
    historical = {(r['provider_key'], r['public_path']): r for r in frozen}
    if len(historical) != len(frozen):
        raise ValueError('duplicate historical binding route')
    selected, endpoint_ids = {}, set()
    all_endpoint_ids = set()
    for raw in current['rows']:
        if not isinstance(raw, dict) or type(raw.get('endpoint_id')) is not int or raw['endpoint_id'] <= 0:
            raise ValueError('current endpoint id must be a positive integer')
        if raw['endpoint_id'] in all_endpoint_ids:
            raise ValueError('duplicate current endpoint in full input inventory')
        all_endpoint_ids.add(raw['endpoint_id'])
    for raw in current['rows']:
        if raw.get('provider_key') not in PROVIDERS:
            continue
        if any(key not in raw for key in CURRENT_FIELDS):
            raise ValueError('current binding metadata incomplete')
        if type(raw['endpoint_id']) is not int or raw['endpoint_id'] <= 0:
            raise ValueError('current endpoint id must be a positive integer')
        key = (raw['provider_key'], raw['public_path'])
        if key in selected or raw['endpoint_id'] in endpoint_ids:
            raise ValueError('duplicate current binding route or endpoint')
        if key not in historical:
            raise ValueError('current binding route absent from bounded inventory')
        endpoint_ids.add(raw['endpoint_id'])
        row = {name: copy.deepcopy(raw[name]) for name in CURRENT_FIELDS}
        row['frozen_proposed_identity'] = historical[key].get('frozen_proposed_identity')
        row['frozen_facts_file_sha256'] = historical[key].get('facts_file_sha256')
        row['frozen_mapping_equal_current'] = (
            historical[key]['upstream_path'] == row['upstream_path'] and
            historical[key]['contract_method'] == row['contract_method'])
        row['current_mapping_metadata_verified'] = (
            row['target_matches_endpoint'] is True and row['target_has_query'] is False and
            row['profile_binding_metadata_matches'] is True and
            type(row['profile_revision']) is int and type(row['compiled_contract_revision']) is int and
            row['profile_revision'] > 0 and row['compiled_contract_revision'] > 0 and
            row['endpoint_status'] == 'enabled' and row['provider_status'] == 'enabled' and
            row['profile_status'] == 'verified' and
            row['profile_revision'] == row['compiled_contract_revision'])
        row['authority_origin_verified'] = (row['authority_equal_expected'] is True and
            row['upstream_origin_sha256'] == hashlib.sha256(EXPECTED_ORIGINS[row['provider_key']].encode()).hexdigest())
        row['strict_profile_binding_validated'] = False
        selected[key] = row
    if selected.keys() != historical.keys():
        raise ValueError('current binding inventory is not the complete bounded route set')
    return [selected[key] for key in sorted(selected)]


def verified_source_methods(document, provider, target):
    """Validate each matched effective server before trusting path selection."""
    expected = 'https://api.search.brave.com/res' if provider.startswith('brave') else 'https://api.parallel.ai'
    for raw in document.get('paths', {}).values():
        if not isinstance(raw, dict):
            raise ValueError('invalid source path item')
        item = effective_object(raw, document) if '$ref' in raw else raw
        for method, operation in item.items():
            if method not in METHODS:
                continue
            if not isinstance(operation, dict):
                raise ValueError('invalid source operation')
            servers = operation.get('servers', item.get('servers', document.get('servers', [])))
            if not isinstance(servers, list) or any(not isinstance(server, dict) or
                                                  not isinstance(server.get('url'), str) for server in servers):
                raise ValueError('invalid source server declaration')
    matches = upstream_path_item(document, target)
    verified = set()
    for path, raw in document.get('paths', {}).items():
        item = effective_object(raw, document) if '$ref' in raw else raw
        for method, operation in item.items():
            if method not in matches or method not in METHODS:
                continue
            servers = operation.get('servers', item.get('servers', document.get('servers', [])))
            effective = {path}
            for server in servers:
                effective.add(urlsplit(server.get('url', '')).path.rstrip('/') + path)
            if target not in effective:
                continue
            if not servers or any(not isinstance(server, dict) or server.get('variables') or
                                  server.get('url', '').rstrip('/') != expected for server in servers):
                raise ValueError('matched source server origin or prefix differs from official authority')
            verified.add(method)
    if verified != matches.keys():
        raise ValueError('matched source server authority cannot be verified')
    return matches


def verify_capture(packet):
    """Corruption guard against recorded capture; not an independent approval."""
    receipts = load_reference((packet / 'source-get-receipts.json').read_bytes())
    recorded = {row['url']: row['source_sha256'] for row in receipts}
    if len(recorded) != len(receipts):
        raise ValueError('duplicate captured source URL')
    folder = packet / 'candidates'
    for name, url in SOURCE_URLS.items():
        raw = (folder / ('parallel-' + name + '.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != recorded.get(url):
            raise ValueError('Parallel captured source byte hash mismatch')
    raw = (folder / 'parallel-archived-events-source.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != recorded.get(SOURCE_URL):
        raise ValueError('Parallel archived source byte hash mismatch')
    if digest(extract(raw)) != digest(load_reference((folder / 'parallel-archived-events.json').read_bytes())):
        raise ValueError('Parallel archived converter output mismatch')
    rows = load_reference((packet / 'brave-structured-sources.json').read_bytes())
    metadata = load_reference((packet / 'brave-source-provenance.json').read_bytes())
    if digest(rows) != metadata.get('structured_source_hash'):
        raise ValueError('Brave structured source hash mismatch')
    page_hashes = {row['url']: row['content_hash'] for row in metadata.get('source_pages', [])}
    if page_hashes != {url + '/__data.json': digest(spec) for url, spec in rows.items()}:
        raise ValueError('Brave source page graph hash mismatch')
    if any(url + '/__data.json' not in recorded for url in rows):
        raise ValueError('Brave source page missing capture receipt')
    if digest(convert_specs(rows)) != digest(load_reference((folder / 'brave-official.json').read_bytes())):
        raise ValueError('Brave converter output mismatch')


def candidate_rows(bindings, sources):
    """Select exact evidenced paths; never infer ANY methods or route versions."""
    rows, namespace, identities = [], set(), set()
    for binding in bindings:
        if binding['provider_key'] not in PROVIDERS:
            raise ValueError('binding outside Brave/Parallel scope')
        public = binding['public_path']
        if not public.startswith('/apis/v1/' + ('parallel/' if binding['provider_key'] == 'parallel.ai' else 'brave/')):
            raise ValueError('public route outside provider scope')
        target = binding.get('upstream_path')
        choices = ['brave-official.json'] if binding['provider_key'].startswith('brave') else [
            'parallel-public-openapi.json', 'parallel-docs-legacy-openapi.json', 'parallel-archived-events.json']
        selected = None
        for name in choices:
            match = verified_source_methods(sources[name], binding['provider_key'], target)
            if match:
                selected = (name, sources[name], match)
                break
        result = copy.deepcopy(binding)
        result.update(source_approved=False, identity_approved=False, activatable=False,
                      current_mapping_metadata_verified=binding.get('current_mapping_metadata_verified', False),
                      strict_profile_binding_validated=False,
                      authority_origin_verified=binding.get('authority_origin_verified', False),
                      operations=[], gaps=[])
        if not selected:
            result['gaps'].append('exact_evidenced_upstream_path_absent_from_official_sources')
            rows.append(result)
            continue
        name, document, match = selected
        result['source_file'] = name
        result['source_url'] = FILE_URLS[name]
        result['source_content_hash'] = digest(document)
        result['source_lifecycle'] = ('archived' if name == 'parallel-archived-events.json' else
                                      'legacy_reference' if name == 'parallel-docs-legacy-openapi.json' else 'current_reference')
        if result['source_lifecycle'] == 'archived':
            result['gaps'].append('archived_contract_does_not_prove_current_provider_support')
        method = binding['contract_method']
        methods = sorted(match) if method == 'ANY' else [method.lower()] if method.lower() in match else []
        if not methods:
            result['gaps'].append('stored_method_absent_from_exact_official_operation')
        for method in methods:
            key = (public, method)
            if key in namespace:
                raise ValueError('duplicate public path/method candidate')
            namespace.add(key)
            operation = copy.deepcopy(match[method])
            try:
                components = referenced_components(operation, document)
                schema_gap = None
            except (ValueError, KeyError, TypeError):
                components, schema_gap = {}, 'unresolved_or_unsupported_official_reference'
            security = operation.get('security', document.get('security', []))
            schemes = {}
            for requirement in security:
                for key in requirement:
                    if key not in document.get('components', {}).get('securitySchemes', {}):
                        schema_gap = 'unresolved_official_authentication_scheme'
                    else:
                        schemes[key] = copy.deepcopy(document['components']['securitySchemes'][key])
            if schemes:
                components['securitySchemes'] = schemes
            successes = {k: v for k, v in operation.get('responses', {}).items()
                         if str(k).startswith('2')}
            if not successes:
                schema_gap = 'no_official_success_response'
            else:
                for status, raw in successes.items():
                    try:
                        response = response_object(raw, document)
                        if str(status) in {'204', '205'} and not response.get('content'):
                            continue
                        if not has_response_contract(response):
                            schema_gap = 'official_success_response_schema_incomplete'
                    except (ValueError, KeyError, TypeError):
                        schema_gap = 'unresolved_official_success_response'
            proposal = proposed_id(binding.get('frozen_proposed_identity'), method, len(methods), public)
            if proposal is not None:
                if proposal in identities:
                    raise ValueError('duplicate proposed public operation identity')
                identities.add(proposal)
            result['operations'].append({'method': method.upper(),
                'official_upstream_operation_id': operation.get('operationId'),
                'public_operation_id_proposed': proposal, 'identity_authority': 'unapproved_frozen_naming_candidate',
                'schema_hash': digest({'operation': operation, 'components': components}),
                'operation': operation, 'components': components, 'upstream_security': security,
                'success_response_statuses': sorted(successes), 'schema_gap': schema_gap})
        if not result['current_mapping_metadata_verified']:
            result['gaps'].append('current_runtime_target_and_revision_not_verified')
        if not result['authority_origin_verified']:
            result['gaps'].append('current_runtime_upstream_origin_not_verified')
        result['gaps'].extend(['independent_source_and_identity_approval_required',
                               'full_strict_profile_ValidateBinding_not_performed',
                               'public_gateway_auth_billing_and_async_ownership_require_runtime_evidence'])
        rows.append(result)
    return rows


def build(packet, bindings_file):
    verify_capture(packet)
    bindings = loads(bindings_file.read_bytes())
    sources = {p.name: load_reference(p.read_bytes()) for p in (packet / 'candidates').glob('*.json')}
    rows = candidate_rows(bindings['rows'], sources)
    files = {name: hashlib.sha256((packet / 'candidates' / name).read_bytes()).hexdigest()
             for name in sorted({row['source_file'] for row in rows if 'source_file' in row})}
    for row in rows:
        if 'source_file' in row:
            row['source_file_sha256'] = files[row['source_file']]
    write_json(packet / 'route-candidates-NOT-APPROVED.json', {
        'schema_version': 1, 'status': 'NOT_APPROVED', 'source_base_revision': '738d3e31b7dd649ce6169d5af17cb3f71d140b12',
        'binding_evidence_sha256': hashlib.sha256(bindings_file.read_bytes()).hexdigest(),
        'candidate_source_file_sha256': files,
        'converter_code_sha256': {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                                 for name in ['import_brave_reference.py', 'import_parallel_legacy_events.py',
                                              'brave_parallel_candidates.py', 'compose_openapi.py', 'source_json.py']},
        'business_requests_performed': 0, 'source_or_identity_approvals': 0,
        'runtime_writes_performed': 0, 'profile_compilations': 0, 'deployments': 0,
        'route_count': len(rows), 'official_method_candidate_count': sum(len(r['operations']) for r in rows),
        'rows': rows})
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--bindings', type=Path)
    parser.add_argument('--current-map', type=Path, help='Join a complete sanitized read-only map; no DB access')
    parser.add_argument('--capture-static', action='store_true', help='GET allowlisted docs only; persist a review packet')
    args = parser.parse_args()
    if args.capture_static:
        print(json.dumps({'static_sources_captured': len(capture(args.packet))}))
    if args.bindings:
        bindings_file = args.bindings
        if args.current_map:
            frozen = loads(args.bindings.read_bytes())
            current = loads(args.current_map.read_bytes())
            bindings_file = args.packet / 'current-binding-evidence.json'
            write_json(bindings_file, {'scope': 'Fresh sanitized mapping metadata; no full ValidateBinding proof',
                'observed_at_utc': current['observed_at_utc'], 'transaction': current['transaction'],
                'source_map_sha256': hashlib.sha256(args.current_map.read_bytes()).hexdigest(),
                'strict_profile_binding_validated': False, 'rows': current_bindings(frozen['rows'], current)})
        rows = build(args.packet, bindings_file)
        print(json.dumps({'routes': len(rows), 'method_candidates': sum(len(r['operations']) for r in rows),
                          'approved': False, 'activatable': False}))
    if not args.capture_static and not args.bindings:
        parser.error('specify --bindings (offline) or --capture-static (explicit static GET)')

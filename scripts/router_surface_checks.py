"""Read-only Router schema declarations versus one immutable formal Docs tree.

This checks published documentation, not executable binder/body equivalence or
provider execution. No second endpoint inventory: scope comes from bound specs.
It checks presence and fields of expected operations, not extra online operation
IDs: Router exposes bounded search and batch lookup, but no full public ID list.

Integration: call check_router_surface(root, fixed_formal_sha) after the existing
publication receipt checks. Merge missing_inputs/mismatches into the monitor's
assessment and retain observations/exclusions in its evidence report. Validate:
python -m unittest discover -s scripts/tests -p test_router_surface_checks.py
"""
import concurrent.futures
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import subprocess
import tarfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from compose_openapi import (METHODS, effective_object, effective_parameters,
                            map_contract_children, pointer_target)
from fetch_runtime_release import NoRedirect
from source_json import loads

ROUTER = 'https://tools.aisa.one'
METADATA = ROUTER + '/.well-known/catalog.json'
SCHEMAS = ROUTER + '/v1/tool-router/aisa-batch-get-schema'
FIELDS = ('description', 'summary', 'x-aisa-pricing', 'parameters', 'requestBody',
          'responses', 'security', 'servers', 'reference_targets')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def reference_targets(value, document):
    """Finite, context-aware closure, including auth and response Link targets."""
    targets, active = {}, set()

    def retain(ref):
        if ref in active:
            return
        active.add(ref)
        target = pointer_target(document, ref)
        targets[ref] = copy.deepcopy(target)
        visit(target, link=ref.startswith('#/components/links/'))

    def visit(node, link=False):
        if isinstance(node, list):
            for child in node:
                visit(child, link)
        elif isinstance(node, dict):
            if '$dynamicRef' in node or '$recursiveRef' in node:
                raise ValueError('Unsupported dynamic reference scope')
            if '$ref' in node:
                retain(node['$ref'])
            for ref in node.get('discriminator', {}).get('mapping', {}).values():
                retain(ref if ref.startswith('#/') else '#/components/schemas/' + ref.replace('~', '~0').replace('/', '~1'))
            if link:
                if 'operationRef' in node:
                    retain(node['operationRef'])
                if 'operationId' in node:
                    matches = [(p, m) for p, item in document.get('paths', {}).items()
                               for m, op in item.items() if m in METHODS and op.get('operationId') == node['operationId']]
                    if len(matches) != 1:
                        raise ValueError('Ambiguous Link operationId')
                    path, method = matches[0]
                    retain('#/paths/' + path.replace('~', '~0').replace('/', '~1') + '/' + method)
            else:
                for requirement in node.get('security', []):
                    for name in requirement:
                        retain('#/components/securitySchemes/' + name.replace('~', '~0').replace('/', '~1'))
            # map_contract_children preserves example/default/enum/extension
            # instances and property-name maps. Links need their own context.
            plain = {key: child for key, child in node.items() if key != 'links'
                     and not (link and key in ('parameters', 'requestBody'))}
            map_contract_children(plain, visit)
            for definition in node.get('links', {}).values():
                visit(definition, link=True)

    visit(value)
    return targets


def contract_fields(document, path, method):
    item = effective_object(document['paths'][path], document)
    operation = copy.deepcopy(item[method])
    operation['parameters'] = effective_parameters(item, operation, document)
    for field in ('servers', 'security'):
        operation[field] = operation.get(field, item.get(field, document.get(field, []))
                                         if field == 'servers' else document.get(field, []))
    values = {key: operation.get(key) for key in FIELDS if key != 'reference_targets'}
    values['reference_targets'] = reference_targets(values, document)
    return {'method': method.upper(), 'path': path, **values}


def in_scope(document):
    """Router's documented synchronous API namespace, not a provider allowlist."""
    # Router internal/catalog/compiler/compiler.go discoverInScopeOperations
    # intentionally reads root rawSpec.Servers, not operation-level overrides.
    servers = document.get('servers', [])
    return not servers or any(urlsplit(row.get('url', '')).netloc == 'api.aisa.one'
                              and (urlsplit(row['url']).path in ('', '/', '/apis/v1')
                                   or urlsplit(row['url']).path.startswith('/apis/v1/')) for row in servers)


def fixed_router_contracts(root, ref):
    if not re.fullmatch('[0-9a-f]{40}', ref):
        raise ValueError('Immutable formal Docs SHA required')
    pointer = loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
    if pointer.get('status') != 'passed':
        raise ValueError('Expected publication is not formal')
    hashes = pointer.get('files_sha256', {})
    paths = sorted(name for name in hashes if re.fullmatch(r'openapi/[A-Za-z0-9_.-]+\.json', name)
                   and name != 'openapi/openapi.json')
    if not paths:
        raise ValueError('No bound provider contracts')
    archive = subprocess.check_output(['git', 'archive', ref, '--', *paths], cwd=root)
    expected, excluded, provider_hashes = {}, [], {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as members:
        for member in members:
            if not member.isfile():
                continue
            raw = members.extractfile(member).read()
            if hashlib.sha256(raw).hexdigest() != hashes.get(member.name):
                raise ValueError('Provider file is not hash-bound')
            document = loads(raw)
            provider = member.name[len('openapi/'):-len('.json')]
            metadata = document.get('info', {}).get('x-aisa-document', {})
            if metadata.get('document_hash'):
                provider_hashes[provider] = metadata['document_hash']
            for path, raw_item in document.get('paths', {}).items():
                item = effective_object(raw_item, document)
                for method, operation in item.items():
                    if method not in METHODS:
                        continue
                    operation_id = operation.get('operationId')
                    if not isinstance(operation_id, str) or not operation_id:
                        raise ValueError('Formal operation has no identity')
                    reason = ('formal_operation_disabled' if operation.get('x-aisa-status') == 'disabled'
                              else 'outside_router_api_server_scope' if not in_scope(document) else None)
                    if reason:
                        excluded.append({'operation_id': operation_id, 'source_file': member.name,
                                         'method': method.upper(), 'path': path, 'reason': reason})
                        continue
                    if operation_id in expected:
                        raise ValueError('Duplicate formal Router operation identity')
                    values = contract_fields(document, path, method)
                    expected[operation_id] = {'fingerprints': {key: digest(value) for key, value in values.items()},
                        'source_file': member.name, 'source_hash': 'sha256:' + hashes[member.name],
                        'document_hash': metadata.get('document_hash'), 'method': method.upper(), 'path': path}
    if not expected:
        raise ValueError('Empty Router scope')
    return {'docs_ref': ref, 'operations': expected, 'excluded': excluded, 'provider_document_hashes': provider_hashes}


class PublicSchemaReader:
    def __init__(self, deadline):
        self.deadline = deadline

    def __call__(self, method, url, payload=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Router audit deadline exceeded')
        if (method, url) not in {('GET', METADATA), ('POST', SCHEMAS)}:
            raise ValueError('Only public catalog and read-only schema lookup are allowed')
        if method == 'GET':
            url += '?contract_audit=' + str(time.time_ns())
        request = Request(url, method=method, data=canonical(payload) if payload is not None else None,
                          headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=min(45, remaining)) as response:
            # A bounded batch may include large response-schema closures.
            raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('Router schema batch exceeded response bound')
        return loads(raw)


def check_router_surface(root, ref, *, read_json=None, expected=None, accepted_refs=None, workers=2, batch_size=20):
    """Return independent missing evidence and field drift; never execute tools.

    Only explicit formal disabled declarations are excluded. An unavailable
    legacy operation remains missing even when live Runtime lacks its route.
    Alternate accepted_refs must already have authenticated same-contract
    provenance from the monitor; they do not change the fixed expected fields.
    """
    if not 1 <= batch_size <= 20 or not 1 <= workers <= 4:
        raise ValueError('Invalid bounded Router audit concurrency')
    started = datetime.now(timezone.utc).isoformat()
    report = {'docs_ref': ref,
              'scope': 'expected operations presence and fields from hash-bound Router public documentation, including effective requests and full local ref closure; extra online operation IDs are not verified (no public full inventory); no executable binder or provider execution claim',
              'observed_at': started, 'missing_inputs': [], 'mismatches': [], 'observations': {}, 'exclusions': []}
    try:
        source = expected if expected is not None else fixed_router_contracts(root, ref)
        if source['docs_ref'] != ref:
            raise ValueError('Expected source identity differs')
    except Exception as exc:
        report['missing_inputs'].append('router-schema:fixed_formal_source:' + type(exc).__name__)
        return report
    read = read_json or PublicSchemaReader(time.monotonic() + 300)
    accepted_refs = set(accepted_refs or ()) | {ref}
    ids = sorted(source['operations'])
    report['exclusions'] = source['excluded']
    report['expected_operations'] = len(ids)
    report['verified_operations'] = 0
    report['unavailable_operations'] = []
    before = None
    try:
        before = read('GET', METADATA)
        report['observations']['metadata_before'] = before
        if before.get('docs_commit') not in accepted_refs or not before.get('build_id'):
            report['mismatches'].append('router-schema:fixed_source_or_build_mismatch')
        actual_hashes = before.get('provider_document_hashes', {})
        if set(actual_hashes) != set(source['provider_document_hashes']):
            report['mismatches'].append('router-schema:provider_membership_mismatch')
        for provider, expected_hash in source['provider_document_hashes'].items():
            if actual_hashes.get(provider) != expected_hash:
                report['mismatches'].append('router-schema:' + provider + ':document_hash_mismatch')
    except Exception as exc:
        report['missing_inputs'].append('router-schema:metadata_before:' + type(exc).__name__)
    if before is None or report['mismatches'] or report['missing_inputs']:
        return report

    def batch(selected):
        data = read('POST', SCHEMAS, {'tools': selected, 'include_documentation': True,
                    'include_arguments_schema': False, 'include_response_schema': False})
        rows = data.get('tools')
        if not isinstance(rows, dict) or set(rows) != set(selected):
            raise ValueError('Router batch membership differs')
        missing, mismatches, verified, unavailable = [], [], 0, []
        for operation_id in selected:
            row, expected_row = rows[operation_id], source['operations'][operation_id]
            label = 'router-schema:' + operation_id
            previous_mismatches = len(mismatches)
            if row.get('successful') is not True:
                code = row.get('error', {}).get('code')
                missing.append(label + ':unavailable')
                unavailable.append({'operation_id': operation_id, 'source_file': expected_row['source_file'],
                                    'method': expected_row['method'], 'path': expected_row['path'],
                                    'error_code': code if isinstance(code, str) else 'unknown',
                                    'disposition': 'requires_explicit_formal_disabled_or_reviewed_scope_evidence'})
                continue
            documentation = row.get('documentation', {})
            provenance = documentation.get('provenance', {})
            for field, value in [('docs_sha', before['docs_commit']), ('source_file', expected_row['source_file']), ('source_hash', expected_row['source_hash'])]:
                if provenance.get(field) != value:
                    mismatches.append(label + ':' + field + '_mismatch')
            if expected_row['document_hash'] and provenance.get('document_hash') != expected_row['document_hash']:
                mismatches.append(label + ':document_hash_mismatch')
            try:
                document = documentation['openapi']
                matches = [(path, method) for path, item in document['paths'].items()
                           for method, operation in item.items() if method in METHODS and operation.get('operationId') == operation_id]
                if len(matches) != 1:
                    raise ValueError('Primary operation identity is absent or ambiguous')
                actual = contract_fields(document, *matches[0])
                for field, expected_hash in expected_row['fingerprints'].items():
                    if digest(actual.get(field)) != expected_hash:
                        mismatches.append(label + ':' + field + '_mismatch')
                if len(mismatches) == previous_mismatches:
                    verified += 1
            except Exception as exc:
                missing.append(label + ':declaration:' + type(exc).__name__)
        return missing, mismatches, verified, unavailable

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(batch, ids[index:index + batch_size]): ids[index:index + batch_size]
                for index in range(0, len(ids), batch_size)}
        for future in concurrent.futures.as_completed(jobs):
            try:
                missing, mismatches, verified, unavailable = future.result()
                report['missing_inputs'].extend(missing)
                report['mismatches'].extend(mismatches)
                report['verified_operations'] += verified
                report['unavailable_operations'].extend(unavailable)
            except Exception as exc:
                report['missing_inputs'].extend('router-schema:' + operation_id + ':batch:' + type(exc).__name__ for operation_id in jobs[future])
    try:
        after = read('GET', METADATA)
        report['observations']['metadata_after'] = after
        if canonical(before) != canonical(after):
            report['mismatches'].append('router-schema:catalog_changed_during_audit')
    except Exception as exc:
        report['missing_inputs'].append('router-schema:metadata_after:' + type(exc).__name__)
    report['missing_inputs'] = sorted(set(report['missing_inputs']))
    report['mismatches'] = sorted(set(report['mismatches']))
    report['unavailable_operations'].sort(key=lambda row: row['operation_id'])
    return report

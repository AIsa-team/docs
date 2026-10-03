"""Discovery and public legacy-input indexing for the runtime contract puller."""
import copy
import json
from source_json import loads as source_json_loads
import re
from pathlib import Path
from urllib.parse import urlsplit
from compose_openapi import METHODS, digest, referenced_components, response_object

KEY = re.compile(r'[a-z0-9][a-z0-9_.-]*')


def catalog_ids(category):
    rows = category.get('apis') if isinstance(category, dict) else None
    if not isinstance(rows, list):
        raise ValueError('runtime category response requires apis list')
    result = []
    for row in rows:
        key = row.get('id') if isinstance(row, dict) else None
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError('runtime category contains invalid catalog id')
        result.append(key)
    if len(result) != len(set(result)):
        raise ValueError('runtime category contains duplicate catalog ids')
    return sorted(result)


def discover(registry, category):
    members = set()
    for key, entry in registry['providers'].items():
        if not KEY.fullmatch(key):
            raise ValueError(f'invalid provider key: {key}')
        group = (entry or {}).get('group', [key])
        if not isinstance(group, list) or not group or any(not isinstance(c, str) or not KEY.fullmatch(c) for c in group):
            raise ValueError(f'{key}: group must be a nonempty list of catalog ids')
        for catalog in group:
            if catalog in members:
                raise ValueError(f'catalog assigned to multiple outputs: {catalog}')
            members.add(catalog)
    for key in catalog_ids(category):
        if key not in members:
            registry['providers'][key] = {}
    return registry


def combine_facts(documents, provider):
    first = copy.deepcopy(next(iter(documents.values())))
    first['paths'] = {}
    catalogs = {}
    for catalog, document in sorted(documents.items()):
        if document.get('servers') != first.get('servers'):
            raise ValueError(f'{provider}: grouped catalogs must use the same public server')
        info = document.get('info', {})
        catalogs[catalog] = {k: copy.deepcopy(info[k]) for k in ('title', 'description', 'x-aisa-document', 'x-aisa-plans', 'x-aisa-capabilities') if k in info}
        for kind, entries in document.get('components', {}).items():
            target = first.setdefault('components', {}).setdefault(kind, {})
            for name, value in entries.items():
                if name in target and target[name] != value:
                    raise ValueError(f'{provider}: grouped component collision: {kind}/{name}')
                target[name] = copy.deepcopy(value)
        for path, item in document.get('paths', {}).items():
            target = first['paths'].setdefault(path, {})
            for method, value in item.items():
                if method in target:
                    raise ValueError(f'{provider}: grouped route collision: {method} {path}')
                target[method] = copy.deepcopy(value)
                if method in METHODS or method == 'x-aisa-any':
                    target[method]['x-aisa-catalog-id'] = catalog
                    target[method]['x-aisa-capabilities'] = {**info.get('x-aisa-capabilities', {}), **target[method].get('x-aisa-capabilities', {})}
    if len(documents) > 1:
        first['info']['title'] = provider
    first['info']['x-aisa-catalogs'] = catalogs
    if len(documents) > 1:
        first['info']['x-aisa-document']['facts_hash'] = digest({k: v.get('x-aisa-document', {}).get('facts_hash') for k, v in catalogs.items()})
    return first


def public_mirror_index(root: Path, overrides: dict | None = None):
    """Only explicit public-route mirrors may match a gateway URL directly."""
    index = {}
    documents = {path.name: source_json_loads(path.read_text()) for path in sorted((root / 'openapi/upstream').glob('*.json'))}
    documents.update(overrides or {})
    for filename, document in sorted(documents.items()):
        source = document.get('info', {}).get('x-aisa-source', {})
        if source.get('path_space') != 'public':
            continue
        if source.get('kind') != 'manual' or not all(source.get(k) for k in ('url', 'fetched_at', 'content_hash', 'converter')):
            raise ValueError(f'{filename}: public mirror requires complete manual provenance')
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        for route, item in document.get('paths', {}).items():
            for method, op in item.items():
                if method not in METHODS:
                    continue
                # Only request contract fields are consumed; copied response or
                # billing metadata cannot override runtime facts.
                request = {k: v for k, v in op.items() if k in {'operationId', 'summary', 'description', 'parameters', 'requestBody'}}
                request['parameters'] = item.get('parameters', []) + request.get('parameters', [])
                components = {}
                try:
                    components = referenced_components(request, document)
                except (ValueError, KeyError, TypeError) as exc:
                    request = {'x-aisa-mirror-error': str(exc)}
                # Public-route mirrors may also declare the gateway's success
                # payload. Keep its references separate: missing response
                # evidence must not invalidate a valid request declaration.
                responses = {}
                for status, raw in op.get('responses', {}).items():
                    if not re.fullmatch(r'2(?:[0-9]{2}|XX)', str(status)):
                        continue
                    try:
                        response = response_object(raw, document)
                        responses[str(status)] = {field: response[field] for field in ('description', 'content') if field in response}
                    except (ValueError, KeyError, TypeError):
                        # Preserve unresolved evidence for the response gap,
                        # without traversing unused protocol headers or links.
                        responses[str(status)] = raw
                response_operation = {'responses': responses}
                response_components = {}
                try:
                    response_components = referenced_components(response_operation, document)
                except (ValueError, KeyError, TypeError):
                    # The composer records the unsupported response reference.
                    pass
                candidate = {'operation': request, 'source': source, 'components': components,
                             'openapi': document.get('openapi', '3.1.0'),
                             'response_operation': response_operation, 'response_components': response_components}
                key = (prefix + route, method)
                if key in index and any(index[key].get(field) != candidate.get(field)
                                        for field in ('operation', 'components', 'openapi', 'response_operation', 'response_components')):
                    index[key] = {'operation': {'x-aisa-mirror-error': 'ambiguous published request contract'}, 'source': source}
                else:
                    index[key] = candidate
    return index


def published_documents(root: Path):
    return {p.stem: source_json_loads(p.read_text()) for p in sorted((root / 'openapi').glob('*.json')) if p.name not in {'openapi.json', 'pending.json', 'coverage.json', 'coverage-sources.json'}}


def previous_for_facts(facts, documents, provider):
    """Collect matching historic contracts even when split across old filenames."""
    from runtime_consolidate_openapi import merge_components
    from compose_openapi import resolve_fragment
    result = {'servers': [{'url': 'https://api.aisa.one'}], 'paths': {}, 'components': {}}
    fact_prefix = urlsplit((facts.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    routes = {fact_prefix + p for p in facts.get('paths', {})}
    for name, original in documents.items():
        document = copy.deepcopy(original)
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        document['paths'] = {prefix + p: item for p, item in document.get('paths', {}).items() if name == provider or prefix + p in routes}
        if not document['paths']:
            continue
        if document.get('openapi', '').startswith('3.0.'):
            # The merged publication has no single source dialect. Normalize
            # only reachable success payloads before losing this source's 3.0
            # semantics; unrelated components and response protocol stay intact.
            for item in document['paths'].values():
                for method, operation in item.items():
                    if method not in METHODS:
                        continue
                    for status, raw in operation.get('responses', {}).items():
                        if not re.fullmatch(r'2(?:[0-9]{2}|XX)', str(status)):
                            continue
                        response = copy.deepcopy(response_object(raw, document))
                        if not response.get('content'):
                            continue
                        converted = resolve_fragment({'content': response['content']}, document, document,
                                                     'previous_response_' + name + '.json', preserve_refs=True)
                        response['content'] = converted['content']
                        operation['responses'][status] = response
        merge_components(result, document, name + '.json')
        for path, item in document['paths'].items():
            target = result['paths'].setdefault(path, {})
            for method, op in item.items():
                if method in target and target[method] != op:
                    raise ValueError(f'conflicting published contracts: {method} {path}')
                target[method] = op
    return result


def coverage_rows(facts, document, pending, catalogs):
    from contract_readiness import binding_hash, reason_code
    failures = {(row['path'], row['method'].lower()): row['reason'] for row in pending}
    rows = []
    for path, item in sorted(facts.get('paths', {}).items()):
        for method, op in sorted(item.items()):
            if method not in METHODS and method != 'x-aisa-any':
                continue
            produced = document.get('paths', {}).get(path, {})
            methods = sorted(set(produced) & METHODS) if method == 'x-aisa-any' else [method]
            if not methods:
                methods = ['any']
            for actual in methods:
                emitted = produced.get(actual)
                reason = failures.get((path, actual), failures.get((path, 'any')))
                from compose_openapi import effective_public_operation
                effective = effective_public_operation(item, op, facts)
                rows.append({'catalog': op.get('x-aisa-catalog-id', catalogs[0]), 'path': path, 'method': actual.upper(),
                             'operation_id': emitted.get('operationId') if emitted else op.get('operationId'),
                             'status': 'composed' if emitted and not reason else 'pending',
                             'reason': reason or (None if emitted else 'operation_not_composed'),
                             'reason_code': reason_code(reason or 'operation_not_composed') if reason or not emitted else None,
                             'binding_hash': binding_hash(effective, facts),
                             'validation': op.get('x-aisa-validation'),
                             'runtime_status': op.get('x-aisa-status'),
                             'schema_source': emitted.get('x-aisa-source', {}).get('kind', 'runtime') if emitted else None})
    return rows

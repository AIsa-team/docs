"""Discovery and public legacy-input indexing for the runtime contract puller."""
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from compose_openapi import METHODS, digest, referenced_components

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
    documents = {path.name: json.loads(path.read_text()) for path in sorted((root / 'openapi/upstream').glob('*.json'))}
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
                candidate = {'operation': request, 'source': source, 'components': components}
                key = (prefix + route, method)
                if key in index and (index[key]['operation'] != request or index[key].get('components', {}) != components):
                    index[key] = {'operation': {'x-aisa-mirror-error': 'ambiguous published request contract'}, 'source': source}
                else:
                    index[key] = candidate
    return index


def published_documents(root: Path):
    return {p.stem: json.loads(p.read_text()) for p in sorted((root / 'openapi').glob('*.json')) if p.name not in {'openapi.json', 'pending.json', 'coverage.json', 'coverage-sources.json'}}


def previous_for_facts(facts, documents, provider):
    """Collect matching historic contracts even when split across old filenames."""
    from consolidate_openapi import merge_components
    result = {'servers': [{'url': 'https://api.aisa.one'}], 'paths': {}, 'components': {}}
    fact_prefix = urlsplit((facts.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    routes = {fact_prefix + p for p in facts.get('paths', {})}
    for name, original in documents.items():
        document = copy.deepcopy(original)
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        document['paths'] = {prefix + p: item for p, item in document.get('paths', {}).items() if name == provider or prefix + p in routes}
        if not document['paths']:
            continue
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
                effective = dict(op)
                if item.get('parameters'):
                    effective['parameters'] = item['parameters'] + op.get('parameters', [])
                rows.append({'catalog': op.get('x-aisa-catalog-id', catalogs[0]), 'path': path, 'method': actual.upper(),
                             'operation_id': emitted.get('operationId') if emitted else op.get('operationId'),
                             'status': 'composed' if emitted and not reason else 'pending',
                             'reason': reason or (None if emitted else 'operation_not_composed'),
                             'reason_code': reason_code(reason or 'operation_not_composed') if reason or not emitted else None,
                             'binding_hash': binding_hash(effective, facts),
                             'validation': op.get('x-aisa-validation'),
                             'schema_source': emitted.get('x-aisa-source', {}).get('kind', 'runtime') if emitted else None})
    return rows

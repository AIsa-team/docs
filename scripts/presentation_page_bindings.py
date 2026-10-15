"""Presentation references from a pinned Docs commit, never route/price authority."""
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit
import yaml

from contract_page_links import DOCS_PREFIX, operations, page_reference
from runtime_localize_openapi_zh import split_frontmatter

MEMBER = 'presentation/page-bindings.json'
SCOPE = 'historical_presentation_only_not_route_price_or_availability_authority'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def page_files(hashes):
    return {name: digest for name, digest in hashes.items()
            if name.startswith('api-reference/') and name.endswith('.mdx')}


def operation_index(documents):
    return {(f'openapi/{provider}.json', method, path): operation
            for provider, doc in documents.items() for path, method, operation in operations(doc)}


def export_bindings(docs_ref, hashes, documents, read, digest):
    """Read the actual original MDX bytes; record all examined page files."""
    index, pages = operation_index(documents), []
    for name, expected in sorted(page_files(hashes).items()):
        raw = read(name)
        require(digest(raw) == expected, 'Presentation MDX differs from formal binding')
        reference = page_reference(raw.decode('utf-8'))
        binding = None
        if reference:
            require(reference in index, 'Presentation page refers to an unknown native operation')
            spec, method, path = reference
            header, _ = split_frontmatter(raw.decode('utf-8'))
            declared = (yaml.safe_load(header) or {}).get('x-aisa-operation-id')
            require(not declared or declared == index[reference]['operationId'],
                    'Presentation frontmatter identity differs from native canonical ID')
            binding = dict(spec=spec, method=method, path=path,
                           operation_id=index[reference]['operationId'])
        pages.append(dict(path=name, sha256=expected, binding=binding))
    value = dict(schema_version=1, docs_ref=docs_ref, scope=SCOPE, pages=pages)
    validate_bindings(value, docs_ref, hashes, documents)
    return value


def validate_bindings(value, docs_ref, hashes, documents):
    require(isinstance(value, dict) and set(value) == {'schema_version', 'docs_ref', 'scope', 'pages'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['docs_ref'] == docs_ref and value['scope'] == SCOPE,
            'Invalid presentation binding envelope')
    pages = value['pages']
    require(isinstance(pages, list) and 0 < len(pages) <= 8192, 'Invalid presentation page count')
    expected, index, seen, bound = page_files(hashes), operation_index(documents), {}, set()
    identity_pages = {}
    for row in pages:
        require(isinstance(row, dict) and set(row) == {'path', 'sha256', 'binding'},
                'Invalid presentation page fields')
        name = row['path']
        require(isinstance(name, str) and len(name) <= 255 and
                re.fullmatch(r'api-reference/[A-Za-z0-9_./-]+\.mdx', name) and
                all(part not in ('', '.', '..') for part in name.split('/')) and name not in seen,
                'Invalid or duplicate presentation page path')
        require(name in expected and row['sha256'] == expected[name], 'Presentation page source hash differs')
        seen[name] = row['sha256']
        binding = row['binding']
        if binding is None:
            continue
        require(isinstance(binding, dict) and set(binding) == {'spec', 'method', 'path', 'operation_id'}
                and all(isinstance(item, str) for item in binding.values()),
                'Invalid presentation operation reference')
        key = (binding['spec'], binding['method'], binding['path'])
        require(key in index and index[key]['operationId'] == binding['operation_id'],
                'Presentation binding differs from native identity')
        bound.add(key)
        identity_pages.setdefault(binding['operation_id'], []).append(name)
    require(list(seen) == sorted(seen) and seen == expected, 'Presentation file inventory differs')
    # Completeness refers only to this historical bundle, never to future Runtime IDs.
    require(bound == set(index), 'Historical presentation bindings are incomplete')
    for operation in index.values():
        if operation.get('x-aisa-docs-url') is not None:
            primary = sorted(identity_pages[operation['operationId']])[-1]
            require(operation['x-aisa-docs-url'] == DOCS_PREFIX + str(PurePosixPath(primary).with_suffix('')),
                    'Historical native primary URL differs from presentation page selection')


def link_index(value, documents):
    ids, routes = {}, {}
    for row in value['pages']:
        binding = row['binding']
        if binding is None:
            continue
        page = str(PurePosixPath(row['path']).with_suffix(''))
        ids.setdefault(binding['operation_id'], set()).add(page)
        provider = PurePosixPath(binding['spec']).stem
        prefix = urlsplit((documents[provider].get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        routes[(prefix + binding['path'], binding['method'])] = page
    return ids, routes


def aggregate_links(value, documents):
    """Rebind old presentation by stable ID; new IDs retain shared native slugs.

    Aggregate picks the first sorted historical page, while native projection
    picks the last. No original method/path is used to create a new operation.
    """
    ids = {}
    for row in value['pages']:
        if row['binding'] is not None:
            ids.setdefault(row['binding']['operation_id'], []).append(row['path'])
    result = {}
    for provider, document in documents.items():
        for path, method, operation in operations(document):
            pages = ids.get(operation['operationId'])
            url = (DOCS_PREFIX + str(PurePosixPath(sorted(pages)[0]).with_suffix(''))
                   if pages else operation.get('x-aisa-docs-url'))
            require(isinstance(url, str) and url.startswith(DOCS_PREFIX + 'api-reference/'),
                    'Compiled operation has no verified or derived presentation URL')
            result[(provider + '.json', method, path)] = url
    return result

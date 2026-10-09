"""Small sales view derived exclusively from the already composed full graph.

No schema authority, fallback inputs, fetching, or approval lives here. The full
bundle remains the API contract; this view only avoids parsing its large schemas
in a constrained public page runtime.
"""
import copy
import hashlib
import json

SALES_CATALOG_PATH = 'docs/publication/sales-catalog.json'
METHODS = frozenset(('get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'))
OPERATION_FIELDS = ('operationId', 'summary', 'description', 'servers', 'x-aisa-provider',
                    'x-aisa-catalog-id', 'x-aisa-registry-provider', 'x-aisa-status',
                    'x-aisa-revision', 'x-aisa-pricing', 'x-aisa-runtime-operation')
PROVIDER_FIELDS = ('display_name', 'description', 'source', 'catalog_ids', 'registry_provider', 'document_hash')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def project_sales_catalog(document, openapi_sha256):
    info = document.get('info', {})
    small = {key: copy.deepcopy(document[key]) for key in ('openapi', 'servers') if key in document}
    small['info'] = {key: copy.deepcopy(info[key]) for key in ('title', 'version') if key in info}
    metadata = info.get('x-aisa-document', {})
    if 'providers' in metadata:
        providers = {}
        for name, value in metadata['providers'].items():
            providers[name] = {key: copy.deepcopy(value[key]) for key in PROVIDER_FIELDS if key in value}
            if 'catalogs' in value:
                providers[name]['catalogs'] = {key: {} for key in value['catalogs']}
        small['info']['x-aisa-document'] = {'providers': providers}
    small['paths'] = {}
    for path, item in document.get('paths', {}).items():
        projected = {key: copy.deepcopy(item[key]) for key in ('servers',) if key in item}
        for method, operation in item.items():
            if method in METHODS:
                projected[method] = {key: copy.deepcopy(operation[key]) for key in OPERATION_FIELDS if key in operation}
        small['paths'][path] = projected
    return {'schema_version': 1, 'openapi_sha256': openapi_sha256, 'document': small}


def sales_catalog_bytes(document, openapi_raw):
    return canonical(project_sales_catalog(document, hashlib.sha256(openapi_raw).hexdigest())) + b'\n'


def verify_sales_catalog(root, document, openapi_raw):
    expected = sales_catalog_bytes(document, openapi_raw)
    path = root / SALES_CATALOG_PATH
    if not path.is_file() or path.read_bytes() != expected:
        raise ValueError('Sales catalog does not equal the projection of the complete publication graph')
    return hashlib.sha256(expected).hexdigest()

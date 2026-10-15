"""Pure operation/page selection and the shared derived document hash."""
import re
from urllib.parse import urlsplit

from compose_openapi import METHODS, digest

DOCS_PREFIX = 'https://aisa.one/docs/'


def slug(value):
    return re.sub(r'[^a-zA-Z0-9_-]', '-', value)


def operations(document):
    for path, item in document.get('paths', {}).items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


def select_pages(provider, document, known_ids, known_routes):
    """Keep all historical pages, their ordering, and the existing fallback."""
    prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    return {operation['operationId']: sorted(known_ids.get(operation['operationId'], set())) or [
        known_routes.get((prefix + path, method),
                         f"api-reference/{provider}/{slug(operation['operationId'])}")]
        for path, method, operation in operations(document)}


def project_links(document, pages):
    """Mutate only derived links/hash, using the current composer hash as input.

    Call once on a freshly composed document. As in the page writer, the last
    sorted historical page is the primary URL when there are several pages.
    """
    for _, _, operation in operations(document):
        operation['x-aisa-docs-url'] = DOCS_PREFIX + pages[operation['operationId']][-1]
    meta = document['info']['x-aisa-document']
    meta['document_hash'] = digest({'composer_hash': meta['document_hash'], 'page_links': {
        operation['operationId']: operation.get('x-aisa-docs-url')
        for _, _, operation in operations(document)}})


def historical_link_index(documents):
    """Read only already published primary URLs from verified native schemas.

    This is sufficient for native contract projection. It is not a complete MDX
    page inventory and does not claim to recover every alternate historical URL.
    """
    ids, routes = {}, {}
    for document in documents.values():
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        for path, method, operation in operations(document):
            url = operation.get('x-aisa-docs-url')
            if url is None:
                continue
            if not isinstance(url, str) or not url.startswith(DOCS_PREFIX + 'api-reference/'):
                raise ValueError('Historical operation has an unsupported documentation URL')
            page = url.removeprefix(DOCS_PREFIX)
            if not re.fullmatch(r'[A-Za-z0-9_./-]+', page) or any(part in ('', '.', '..') for part in page.split('/')):
                raise ValueError('Historical documentation page escapes its namespace')
            identity = operation['operationId']
            if identity in ids and ids[identity] != {page}:
                raise ValueError('Historical canonical identity has conflicting primary URLs')
            ids[identity] = {page}
            route = (prefix + path, method)
            if route in routes and routes[route] != page:
                raise ValueError('Historical route has conflicting documentation URLs')
            routes[route] = page
    return ids, routes


def require_historical_primary_links(original_documents, composed_documents):
    """Bundle v1 cannot recover MDX-only URLs for a newly migrated legacy ID."""
    historical = {op['operationId']: op.get('x-aisa-docs-url')
                  for doc in original_documents.values() for _, _, op in operations(doc)}
    for document in composed_documents.values():
        for _, _, operation in operations(document):
            identity = operation['operationId']
            if identity in historical and historical[identity] is None:
                raise ValueError('Historical identity lacks a native primary URL; page inventory input required: ' + identity)

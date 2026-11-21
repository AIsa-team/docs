"""Validate actual bilingual runtime publication files without fetching or writing."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import sys
import yaml

from compose_openapi import METHODS
from deferred_definitions import POLICY_PATH, REBINDING_PATH
from sales_catalog_projection import SALES_CATALOG_PATH
from generate_payment_discovery import PAYMENT_FILES
from runtime_localize_openapi_zh import strip_translatable
from identity_compatibility import published_history, validate_document_identities, canonicalize_localized


# Public projections and production reference contracts joined the publication
# surface with the public projection change. Formal publications recorded before
# it hashed the surface without these paths, even where the files already existed.
PUBLIC_PROJECTION_PATTERNS = ('openapi-public/**/*.json', 'openapi-public/*.yaml', 'reference-contracts/**/*.json')


def publication_files(root, *, legacy=False):
    root = Path(root)
    files = {p for p in (root / 'openapi.yaml', root / 'llms.txt', root / 'docs.json', root / 'openapi/registry.yaml',
                        root / 'api-reference.mdx', root / 'zh/api-reference.mdx', root / POLICY_PATH, root / REBINDING_PATH, root / SALES_CATALOG_PATH) if p.is_file()}
    files.update(root / name for name in PAYMENT_FILES if (root / name).is_file())
    patterns = ('openapi/*.json', 'openapi/upstream/*.json', 'openapi/zh/*.json',
                'api-reference/**/*.mdx', 'zh/api-reference/**/*.mdx')
    for pattern in patterns + (() if legacy else PUBLIC_PROJECTION_PATTERNS):
        files.update(root.glob(pattern))
    return sorted(files)


def publication_hashes(root, *, legacy=False):
    """New publications always record the current surface; legacy=True only
    re-derives what an earlier formal publication recorded."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in publication_files(root, legacy=legacy)}


def navigation_pages(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'pages' and isinstance(value, list):
                for page in value:
                    if isinstance(page, str):
                        yield page
                    else:
                        yield from navigation_pages(page)
            elif isinstance(value, (dict, list)):
                yield from navigation_pages(value)
    elif isinstance(node, list):
        for value in node:
            yield from navigation_pages(value)


FRONTMATTER = re.compile(r'---\n(.*?)\n---[ \t]*(?:\n|$)', re.S)


def frontmatter(text):
    """YAML between the opening line and the next line that is exactly ---.

    Quoted descriptions may contain markdown tables (|---|), so a plain split
    on '---' is not a frontmatter boundary.
    """
    match = FRONTMATTER.match(text)
    return match[1] if match else None


def retired_archive(path):
    """A non-indexed human retirement page without an operation binding."""
    if not path.is_file():
        return False
    block = frontmatter(path.read_text())
    if block is None:
        return False
    header = yaml.safe_load(block) or {}
    return (header.get('x-aisa-human-retirement') is True and header.get('noindex') in (True, 'true')
            and 'openapi' not in header)


def disappeared_generated_pages(root, previous, native):
    """Plan removals only after the caller verifies the complete canonical graph.

    Both the old contract identity and generator-owned page body must agree.
    Authored prose, manual headers and editorial archives require human review.
    Identities still present anywhere (including disabled or moved) survive.
    """
    from readable_contract_notes import BEGIN, END, strip_generated_block
    live = {op['operationId'] for doc in native.values()
            for item in doc.get('paths', {}).values() for method, op in item.items() if method in METHODS}
    removed = set()
    for prefix in ('', 'zh/'):
        for path in (Path(root) / (prefix + 'api-reference')).rglob('*.mdx'):
            text = path.read_text()
            block = frontmatter(text)
            header = yaml.safe_load(block) if block is not None else None
            if not isinstance(header, dict) or set(header) - {'title', 'openapi', 'x-aisa-operation-id', 'noindex'}:
                continue
            reference = header.get('openapi')
            if not isinstance(reference, str) or not isinstance(header.get('x-aisa-operation-id'), str):
                continue
            match = re.fullmatch(r'(?:openapi(?:-public)?|reference-contracts)/(zh/)?([A-Za-z0-9_.-]+)\.json ([A-Z]+) (\S+)', reference)
            if not match or bool(match[1]) != bool(prefix) or match[2] not in native:
                continue  # A missing provider is not proof of a complete graph.
            document = previous.get(match[2], {})
            if not document.get('info', {}).get('x-aisa-document', {}).get('document_hash'):
                continue
            old = document.get('paths', {}).get(match[4], {}).get(match[3].lower(), {})
            identity = old.get('operationId')
            aliases = {row['operation_id'] for row in old.get('x-aisa-identity', {}).get('historical_aliases', [])}
            if not identity or identity in live or header['x-aisa-operation-id'] not in {identity, *aliases}:
                continue
            body = text[FRONTMATTER.match(text).end():]
            if BEGIN not in body or END not in body:
                continue
            body = strip_generated_block(body)
            body = re.sub(r'\{/\* aisa-contract-status:start \*/\}.*?\{/\* aisa-contract-status:end \*/\}', '', body, flags=re.S)
            if not body.strip():
                removed.add(path.relative_to(root).as_posix())
    return removed


def validate_surfaces(root, published_ref=None):
    root = Path(root)
    documents, all_documents = {}, {}
    for path in (root / 'openapi').glob('*.json'):
        if path.name == 'openapi.json':
            continue  # aggregate output, not an independent provider
        document = json.loads(path.read_text())
        all_documents[path.stem] = document
        if document.get('info', {}).get('x-aisa-document', {}).get('document_hash'):
            documents[path.stem] = document
    # The unchanged legacy workflow remains outside runtime activation.
    if not documents:
        return {'status': 'passed', 'scope': 'legacy publication; no runtime surface claim', 'providers': 0}
    # Public references must resolve to current projections of the same formal
    # graph. The formal graph remains the authority for bilingual identities.
    from public_projection import check as check_projection
    if (root / 'scripts/public_projection.json').is_file():
        problems = check_projection(root)
        if problems:
            raise ValueError('public projection differs from formal graph: ' + repr(problems[:5]))
    from validate_prod_reference_pages import validate_reference_pages
    validate_reference_pages(root)
    history = published_history(root, published_ref)
    validate_document_identities(all_documents, history)
    localized_documents = {}
    from readable_contract_notes import BEGIN, END, readable_block, PRICE_CARD_BEGIN, PRICE_CARD_END, price_card_block
    from runtime_localize_openapi_zh import translation
    catalog_path = root / 'translations/openapi-zh.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {'entries': {}}
    def translated_note(note):
        try:
            return translation(catalog, note)
        except KeyError:
            return note

    def localized_document(provider):
        # Scope the cache to this assessment. Repeated pages of a large
        # provider share one parse, while the next assessment rereads bytes.
        if provider not in localized_documents:
            path = root / 'openapi/zh' / (provider + '.json')
            if not path.is_file():
                raise ValueError('missing localized runtime schema: ' + provider)
            localized_documents[provider] = json.loads(path.read_text())
        return localized_documents[provider]

    identities = {operation.get('operationId') for document in documents.values()
                  for item in document.get('paths', {}).values() for method, operation in item.items()
                  if method in METHODS}
    if not (root / 'docs.json').is_file():
        raise ValueError('runtime publication has no navigation')
    docs = json.loads((root / 'docs.json').read_text())
    nav = {}
    for block in docs.get('navigation', {}).get('languages', []):
        language = block.get('language')
        if language not in ('en', 'zh'):
            continue
        tabs = [tab for tab in block.get('tabs', []) if tab.get('tab') in ('API Reference', 'API 参考')]
        if len(tabs) != 1 or language in nav:
            raise ValueError('runtime API navigation must have one tab per language')
        nav[language] = list(navigation_pages(tabs[0]))
        for page in nav[language]:
            if not re.fullmatch(r'(?:zh/)?api-reference(?:/[A-Za-z0-9_.-]+)*', page):
                raise ValueError('invalid API navigation target: ' + page)
            if not (root / (page + '.mdx')).is_file():
                raise ValueError('missing API navigation target: ' + page)
    if set(nav) != {'en', 'zh'}:
        raise ValueError('runtime publication requires EN and ZH API navigation')
    # Every Runtime identity keeps bilingual pages. Available operations must
    # appear in navigation; disabled ones remain non-indexed archive URLs.
    found = {'en': {}, 'zh': {}}
    for language, pattern in (('en', 'api-reference/**/*.mdx'), ('zh', 'zh/api-reference/**/*.mdx')):
        for path in root.glob(pattern):
            text = path.read_text()
            if not text.startswith('---\n'):
                continue
            block = frontmatter(text)
            if block is None:
                raise ValueError('invalid MDX frontmatter: ' + str(path))
            header = yaml.safe_load(block) or {}
            reference = header.get('openapi')
            if not isinstance(reference, str):
                if retired_archive(path):
                    continue  # Disabled archive/navigation closure is checked below.
                if header.get('x-aisa-operation-id') in identities:
                    raise ValueError('runtime page has no operation reference: ' + str(path))
                continue
            match = re.fullmatch(r'(?:openapi(?:-public)?|reference-contracts)/(zh/)?([A-Za-z0-9_.-]+)\.json ([A-Z]+) (\S+)', reference)
            if not match or match[2] not in all_documents:
                if header.get('x-aisa-operation-id') in identities:
                    raise ValueError('runtime page references an unknown document: ' + str(path))
                continue
            if bool(match[1]) != (language == 'zh'):
                raise ValueError('page references wrong language: ' + str(path))
            if reference.startswith('openapi-public/') and not (root / reference.split()[0]).is_file():
                raise ValueError('page references missing public projection: ' + str(path))
            provider, method, route = match[2], match[3].lower(), match[4]
            source_document = all_documents[provider]
            if language == 'zh':
                source_document = localized_document(provider)
            if reference.startswith('reference-contracts/') and header.get('x-aisa-operation-id') not in identities:
                continue  # Legacy reference pages have their own validated presentation.
            if reference.startswith('reference-contracts/'):
                # Existing production reference schemas may add reviewed response
                # descriptions, but cannot replace runtime requests or billing.
                from check_contract_candidate import effective_request
                reference_document = json.loads((root / reference.split()[0]).read_text())
                reference_operation = reference_document.get('paths', {}).get(route, {}).get(method)
                runtime_operation = source_document.get('paths', {}).get(route, {}).get(method)
                if not isinstance(reference_operation, dict) or not isinstance(runtime_operation, dict):
                    raise ValueError('missing reference operation: ' + str(path))
                if effective_request(reference_operation, reference_document) != effective_request(runtime_operation, source_document) or any(
                    reference_operation.get(key) != runtime_operation.get(key)
                    for key in ('operationId', 'x-aisa-status', 'x-aisa-pricing', 'x-aisa-capabilities')):
                    raise ValueError('reference schema changed runtime request or pricing: ' + str(path))
            operation = source_document.get('paths', {}).get(route, {}).get(method)
            if method not in METHODS or not isinstance(operation, dict):
                raise ValueError('page references missing operation: ' + str(path))
            identity = operation.get('operationId')
            if (provider in documents or 'x-aisa-operation-id' in header) and (not identity or header.get('x-aisa-operation-id') != identity):
                raise ValueError('page operation identity mismatch: ' + str(path))
            # A correct frontmatter binding cannot certify stale or edited
            # machine declarations in the body that llms-full will expose.
            canonical_source = all_documents[provider]
            canonical_operation = canonical_source['paths'][route][method]
            expected_block = readable_block(canonical_operation, language, translated_note,
                document=canonical_source, method=method, path=route,
                spec_path=f"openapi/{'zh/' if language == 'zh' else ''}{provider}.json")
            actual_blocks = re.findall(re.escape(BEGIN) + r".*?" + re.escape(END), text, re.S)
            if actual_blocks != [expected_block]:
                raise ValueError('page readable contract differs from provider: ' + str(path))
            expected_card = price_card_block(canonical_operation, language)
            actual_cards = re.findall(re.escape(PRICE_CARD_BEGIN) + r".*?" + re.escape(PRICE_CARD_END), text, re.S)
            if actual_cards != ([expected_card] if expected_card else []):
                raise ValueError('page price card differs from provider: ' + str(path))
            page = path.relative_to(root).with_suffix('').as_posix()
            if canonical_operation.get('x-aisa-status') == 'disabled':
                if page in nav[language]:
                    raise ValueError('disabled runtime page remains in navigation: ' + page)
                if header.get('noindex') not in (True, 'true'):
                    raise ValueError('disabled runtime page is indexable: ' + page)
            canonical = operation.get('x-aisa-identity', {}).get('canonical_operation_id', identity)
            found[language].setdefault((provider, route, method, canonical), set()).add(page)
    from retirement_pages import retirement_rows
    retired = retirement_rows(root)
    count = 0
    for provider, document in documents.items():
        localized = localized_document(provider)
        prefix = urlsplit((document.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
        if strip_translatable(document) != strip_translatable(canonicalize_localized(localized, history)):
            raise ValueError('localized runtime protocol changed: ' + provider)
        for route, item in document.get('paths', {}).items():
            for method, operation in item.items():
                if method not in METHODS:
                    continue
                key = (provider, route, method, operation.get('operationId'))
                count += 1
                if operation.get('x-aisa-status') == 'disabled':
                    english = found['en'].get(key, set())
                    chinese = found['zh'].get(key, set())
                    archive = retired.get((method.upper(), prefix + route))
                    if not english and not chinese and archive:
                        # An editorially retired route keeps its bilingual archive page
                        # instead of a contract page; it stays out of navigation.
                        for page in (archive, 'zh/' + archive):
                            if not retired_archive(root / (page + '.mdx')) or page in nav['zh' if page.startswith('zh/') else 'en']:
                                raise ValueError('retired runtime operation lacks a bilingual archive page: ' + repr(key))
                        continue
                    if not english or {'zh/' + page for page in english} != chinese:
                        raise ValueError('disabled runtime operation missing matching bilingual archive pages: ' + repr(key))
                    continue
                english = found['en'].get(key, set()) & set(nav['en'])
                chinese = found['zh'].get(key, set()) & set(nav['zh'])
                if not english or {'zh/' + page for page in english} != chinese:
                    raise ValueError('runtime operation missing matching bilingual navigation: ' + repr(key))
    # Existing legacy URLs remain public even after their pages move. Their
    # locale copies must not retain removed operations or obsolete prices.
    for name, source in all_documents.items():
        target = root / 'openapi/zh' / (name + '.json')
        if name not in documents and target.is_file():
            localized = json.loads(target.read_text())
            if strip_translatable(source) != strip_translatable(canonicalize_localized(localized, history)):
                raise ValueError('localized legacy protocol changed: ' + name)
    return {'status': 'passed', 'scope': 'actual EN/ZH schemas, page identities and navigation closure',
            'providers': len(documents), 'operations': count,
            'files': len(publication_files(root))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--legacy-write', action='store_true', help='Block the legacy sync writer whenever a runtime registry exists')
    args = parser.parse_args()
    if args.legacy_write:
        if (args.root / 'openapi/registry.yaml').exists():
            print('Runtime registry present: legacy sync cannot publish. Use pull-openapi with its strict formal assessment.', file=sys.stderr)
            raise SystemExit(3)
        print('Legacy publication has no runtime registry; original writer remains unchanged.')
        raise SystemExit(0)
    print(json.dumps(validate_surfaces(args.root), indent=2))

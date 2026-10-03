"""Validate actual bilingual runtime publication files without fetching or writing."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import yaml

from compose_openapi import METHODS
from runtime_localize_openapi_zh import strip_translatable


def publication_files(root):
    root = Path(root)
    files = {p for p in (root / 'openapi.yaml', root / 'docs.json', root / 'openapi/registry.yaml',
                        root / 'api-reference.mdx', root / 'zh/api-reference.mdx') if p.is_file()}
    for pattern in ('openapi/*.json', 'openapi/upstream/*.json', 'openapi/zh/*.json',
                    'api-reference/**/*.mdx', 'zh/api-reference/**/*.mdx'):
        files.update(root.glob(pattern))
    return sorted(files)


def publication_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in publication_files(root)}


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


def validate_surfaces(root):
    root = Path(root)
    documents = {}
    for path in (root / 'openapi').glob('*.json'):
        document = json.loads(path.read_text())
        if document.get('info', {}).get('x-aisa-document', {}).get('document_hash'):
            documents[path.stem] = document
    # The unchanged legacy workflow remains outside runtime activation.
    if not documents:
        return {'status': 'passed', 'scope': 'legacy publication; no runtime surface claim', 'providers': 0}
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
    # Manual overview pages may differ, but every runtime operation must be
    # represented by a matching page in both navigation trees.
    found = {'en': {}, 'zh': {}}
    for language, pattern in (('en', 'api-reference/**/*.mdx'), ('zh', 'zh/api-reference/**/*.mdx')):
        for path in root.glob(pattern):
            text = path.read_text()
            if not text.startswith('---\n'):
                continue
            parts = text.split('---', 2)
            if len(parts) != 3:
                raise ValueError('invalid MDX frontmatter: ' + str(path))
            header = yaml.safe_load(parts[1]) or {}
            reference = header.get('openapi')
            if not isinstance(reference, str):
                if header.get('x-aisa-operation-id') in identities:
                    raise ValueError('runtime page has no operation reference: ' + str(path))
                continue
            match = re.fullmatch(r'openapi/(zh/)?([A-Za-z0-9_.-]+)\.json ([A-Z]+) (\S+)', reference)
            if not match or match[2] not in documents:
                if header.get('x-aisa-operation-id') in identities:
                    raise ValueError('runtime page references an unknown document: ' + str(path))
                continue
            if bool(match[1]) != (language == 'zh'):
                raise ValueError('page references wrong language: ' + str(path))
            provider, method, route = match[2], match[3].lower(), match[4]
            operation = documents[provider].get('paths', {}).get(route, {}).get(method)
            if method not in METHODS or not isinstance(operation, dict):
                raise ValueError('page references missing operation: ' + str(path))
            identity = operation.get('operationId')
            if not identity or header.get('x-aisa-operation-id') != identity:
                raise ValueError('page operation identity mismatch: ' + str(path))
            page = path.relative_to(root).with_suffix('').as_posix()
            found[language].setdefault((provider, route, method, identity), set()).add(page)
    count = 0
    for provider, document in documents.items():
        localized_path = root / 'openapi/zh' / (provider + '.json')
        if not localized_path.is_file():
            raise ValueError('missing localized runtime schema: ' + provider)
        localized = json.loads(localized_path.read_text())
        if strip_translatable(document) != strip_translatable(localized):
            raise ValueError('localized runtime protocol changed: ' + provider)
        for route, item in document.get('paths', {}).items():
            for method, operation in item.items():
                if method not in METHODS:
                    continue
                key = (provider, route, method, operation.get('operationId'))
                count += 1
                english = found['en'].get(key, set()) & set(nav['en'])
                chinese = found['zh'].get(key, set()) & set(nav['zh'])
                if not english or {'zh/' + page for page in english} != chinese:
                    raise ValueError('runtime operation missing matching bilingual navigation: ' + repr(key))
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

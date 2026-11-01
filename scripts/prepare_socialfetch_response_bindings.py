"""Derive response-only public bindings from the official SocialFetch OpenAPI.

Runtime facts only select routes; each binding is accepted only when the
Runtime's own upstream path and origin digests equal the official route's.
Schemas come from the official document alone.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
from compose_openapi import METHODS, digest, referenced_components
from source_governance import initial_policy
from source_json import loads

VERSION = 'scripts/prepare_socialfetch_response_bindings.py@1'
SOURCE_FILE = 'openapi/upstream/socialfetch.json'
SOURCE_URL = 'https://www.socialfetch.dev/openapi.json'
ORIGIN = 'https://api.socialfetch.dev'
PUBLIC_PREFIX = '/apis/v1/socialfetch'


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def prepare(raw: bytes, facts: dict) -> dict[str, dict]:
    source = loads(raw)
    provenance = source['info']['x-aisa-source']
    if provenance['kind'] != 'provider_openapi' or provenance['url'] != SOURCE_URL:
        raise ValueError('official SocialFetch authority changed')
    if [server['url'] for server in source['servers']] != [ORIGIN]:
        raise ValueError('official SocialFetch server binding changed')
    source_sha256 = hashlib.sha256(raw).hexdigest()
    result = {}
    for public_path, item in sorted(facts['paths'].items()):
        for method, fact in item.items():
            if method not in METHODS or fact.get('x-aisa-response-passthrough') is not True:
                continue
            upstream_path = public_path.removeprefix(PUBLIC_PREFIX)
            original = source['paths'].get(upstream_path, {}).get(method)
            if original is None or not public_path.startswith(PUBLIC_PREFIX + '/'):
                continue
            if (fact.get('x-aisa-response-upstream-path-sha256'), fact.get('x-aisa-response-upstream-origin-sha256')) != (sha256(upstream_path), sha256(ORIGIN)):
                raise ValueError(f'{method.upper()} {public_path}: runtime upstream binding differs from the official route')
            responses = {status: copy.deepcopy(response) for status, response in original.get('responses', {}).items() if str(status).startswith('2')}
            if not responses:
                continue
            operation = {'responses': responses}
            path_parameters = [copy.deepcopy(p) for p in original.get('parameters', []) if p.get('in') == 'path']
            if path_parameters:
                operation['parameters'] = path_parameters
            document = {'openapi': source['openapi'],
                        'info': {'title': f'Official SocialFetch response for {method.upper()} {upstream_path}', 'version': source['info']['version']},
                        'servers': [{'url': 'https://api.aisa.one'}],
                        'paths': {public_path: {method: operation}},
                        'components': referenced_components(operation, source)}
            metadata = {'kind': 'manual', 'url': SOURCE_URL, 'converter': VERSION,
                        'fetched_at': provenance['fetched_at'], 'path_space': 'public', 'response_only': True,
                        'upstream_path_sha256': sha256(upstream_path), 'upstream_origin_sha256': sha256(ORIGIN),
                        'source_file': SOURCE_FILE, 'source_document_sha256': source_sha256,
                        'source_content_hash': provenance['content_hash'],
                        'refresh_policy': 'manual',
                        'refresh_reason': 'Regenerate from the refreshed official document; the route binding is rechecked against Runtime digests.',
                        'content_hash': digest({'official_source_sha256': source_sha256, 'upstream_origin': ORIGIN,
                                                'upstream_path': upstream_path, 'response_document': document})}
            document['info']['x-aisa-source'] = initial_policy(metadata)
            result['response-socialfetch-' + method + '-' + sha256(public_path)[:16] + '.json'] = document
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--facts', type=Path, required=True, help='Runtime facts document for socialfetch')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    documents = prepare(args.source.read_bytes(), json.loads(args.facts.read_text()))
    args.output.mkdir(parents=True, exist_ok=True)
    for stale in args.output.glob('response-socialfetch-*.json'):
        stale.unlink()
    for filename, document in documents.items():
        (args.output / filename).write_text(json.dumps(document, indent=2) + '\n')
    print(json.dumps({'bindings': len(documents)}))


if __name__ == '__main__':
    main()

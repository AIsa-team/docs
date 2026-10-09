"""Derive four reviewable response-only bindings from pinned official Akta schemas.

No Runtime facts are used as schema authority. Runtime target corrections and
independent manual-source review remain separate approval requirements.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
from compose_openapi import digest, referenced_components
from source_governance import initial_policy
from source_json import loads

VERSION = 'scripts/prepare_akta_response_bindings.py@1'
SOURCE_SHA256 = 'e8a0061971891051743a08793392e559128cb545c92ae9ad8ad0d88625831612'
SOURCE_COMMIT = 'f81b180650fdc2a877e1feb5327e94da4324b4ec'
SOURCE_FILE = 'openapi/upstream/akta-official.json'
ORIGIN = 'https://api.akta.pro'
PATHS = ('company/enrichment', 'company/search', 'industry/search', 'status/{request_id}')


def prepare(raw: bytes) -> dict[str, dict]:
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('pinned official Akta source bytes changed; independent review required')
    source = loads(raw)
    if source['servers'] != [{'url': ORIGIN + '/api', 'description': 'Production server'}]:
        raise ValueError('official Akta server binding changed')
    provenance = source['info']['x-aisa-source']
    if provenance['kind'] != 'provider_openapi' or provenance['url'] != 'https://docs.akta.pro/openapi.json':
        raise ValueError('official Akta authority changed')
    result = {}
    for suffix in PATHS:
        upstream_path = '/api/v1/' + suffix
        public_path = '/apis/v1/akta/' + suffix
        original = source['paths']['/v1/' + suffix]['get']
        operation = {'responses': copy.deepcopy(original['responses'])}
        # OpenAPI path templates require declarations in the source document.
        # response_only prevents them from contributing request authority.
        path_parameters = [copy.deepcopy(p) for p in original.get('parameters', []) if p.get('in') == 'path']
        if path_parameters:
            operation['parameters'] = path_parameters
        document = {'openapi': source['openapi'],
                    'info': {'title': 'Official Akta response for ' + suffix, 'version': source['info']['version']},
                    'servers': [{'url': 'https://api.aisa.one'}],
                    'paths': {public_path: {'get': operation}},
                    'components': referenced_components(operation, source)}
        metadata = {'kind': 'manual', 'url': provenance['url'], 'converter': VERSION,
                    'fetched_at': provenance['fetched_at'], 'path_space': 'public', 'response_only': True,
                    'upstream_path_sha256': hashlib.sha256(upstream_path.encode()).hexdigest(),
                    'upstream_origin_sha256': hashlib.sha256(ORIGIN.encode()).hexdigest(),
                    'source_revision': SOURCE_COMMIT, 'source_file': SOURCE_FILE,
                    'source_document_sha256': SOURCE_SHA256,
                    'source_content_hash': provenance['content_hash'],
                    'refresh_policy': 'manual',
                    'refresh_reason': 'Review the official response declarations and the explicit public route/origin/path binding together; never infer a trailing-slash alias.',
                    'content_hash': digest({'official_source_sha256': SOURCE_SHA256,
                                            'upstream_origin': ORIGIN, 'upstream_path': upstream_path,
                                            'response_document': document})}
        document['info']['x-aisa-source'] = initial_policy(metadata)
        filename = 'response-akta-get-' + hashlib.sha256(public_path.encode()).hexdigest()[:16] + '.json'
        result[filename] = document
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    documents = prepare(args.source.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, document in documents.items():
        target = args.output / filename
        if target.exists():
            raise ValueError('refusing to overwrite a response source')
        target.write_text(json.dumps(document, indent=2) + '\n')


if __name__ == '__main__':
    main()

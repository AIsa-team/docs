"""Bind one official order response to its reviewed Runtime transport hashes."""
import copy
import hashlib
import json

from compose_openapi import digest
from source_governance import initial_policy
from source_json import loads

SOURCE_FILE = 'openapi/upstream/duffel-flights-official.json'
SOURCE_SHA256 = 'f0fb7c96ad70801295afd8e4478ae54b2316ec4a0c57bf5795f2bae81652135e'
SOURCE_REVISION = 'b1f27437a89916e54712987581f9c353748456f7'
PUBLIC_PATH = '/apis/v1/duffel/flights/orders/{id}'
UPSTREAM_PATH = '/air/orders/{id}'
ORIGIN = 'https://api.duffel.com'
OFFICIAL_OBSERVED_AT = '2026-10-17T09:28:11.141395+00:00'
OFFICIAL_SHA256 = '1de7905eb073b81eee497c83c34c5820868e413833f82028edd1f3dc822dbd40'


def prepare(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Reviewed official Duffel source bytes changed')
    source = loads(raw)
    if source['servers'] != [{'url': ORIGIN}]:
        raise ValueError('Official Duffel origin changed')
    original = source['paths'][UPSTREAM_PATH]['get']
    operation = {'responses': copy.deepcopy(original['responses']),
                 'parameters': [copy.deepcopy(p) for p in original['parameters'] if p['in'] == 'path']}
    document = {'openapi': source['openapi'],
                'info': {'title': 'Official Duffel Get Order response', 'version': 'v2'},
                'servers': [{'url': 'https://api.aisa.one'}],
                'paths': {PUBLIC_PATH: {'get': operation}}}
    metadata = {
        'kind': 'manual', 'url': 'https://duffel.com/docs/api/v2/orders',
        'converter': 'scripts/prepare_duffel_order_response.py@1',
        'fetched_at': OFFICIAL_OBSERVED_AT, 'response_only': True, 'path_space': 'public',
        'upstream_path_sha256': hashlib.sha256(UPSTREAM_PATH.encode()).hexdigest(),
        'upstream_origin_sha256': hashlib.sha256(ORIGIN.encode()).hexdigest(),
        'source_revision': SOURCE_REVISION, 'source_file': SOURCE_FILE,
        'source_document_sha256': SOURCE_SHA256,
        'source_content_hash': source['info']['x-aisa-source']['content_hash'],
        'references': [{'url': 'https://duffel.com/docs/api/v2/orders', 'sha256': OFFICIAL_SHA256}],
        'refresh_policy': 'manual',
        'scope': 'Response authority only for the exact GET route and passthrough origin/path hashes. '
                 'No request fields, methods, pricing or execution permission are granted.',
        'content_hash': digest({'source_document_sha256': SOURCE_SHA256,
                                'response_document': document}),
    }
    document['info']['x-aisa-source'] = initial_policy(metadata)
    name = 'response-duffel-flights-get-' + hashlib.sha256(PUBLIC_PATH.encode()).hexdigest()[:16] + '.json'
    return {name: document}


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    documents = prepare(args.source.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    for name, document in documents.items():
        with (args.output / name).open('x') as handle:
            handle.write(json.dumps(document, ensure_ascii=False, indent=2) + '\n')

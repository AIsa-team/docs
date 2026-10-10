#!/usr/bin/env python3
"""Build the reviewed MPP pilot catalog; no network requests or payments."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(source, evidence, source_bytes):
    if hashlib.sha256(source_bytes).hexdigest() != evidence['source_sha256']:
        raise ValueError('Source changed; review schemas and refresh payment evidence first')
    doc = {
        'openapi': '3.1.0',
        'info': {
            'title': 'AIsa MPP Data APIs', 'version': '1.0.0',
            'description': 'Initial Polymarket data catalog. Prices are advisory; '
                           'the runtime 402 challenge is authoritative. Payment is '
                           'submitted through Authorization: Payment <credential>.',
        },
        'servers': [{'url': 'https://api.aisa.one'}],
        'x-service-info': {
            'categories': ['data', 'prediction-markets'],
            'docs': {'homepage': 'https://aisa.one',
                     'apiReference': 'https://aisa.one/docs/api-reference'},
        },
        'paths': {},
    }
    if not evidence['operations']:
        raise ValueError('No reviewed operations')
    for entry in evidence['operations']:
        path, method = entry['path'], entry['method']
        if method != 'get' or not path.startswith('/apis/v1/polymarket/'):
            raise ValueError('Pilot supports only reviewed Polymarket GET routes')
        original = source['paths'][path][method]
        if original.get('x-aisa-capabilities', {}).get('mpp') is not True:
            raise ValueError('Operation does not advertise MPP support')
        if original.get('x-aisa-pricing', {}).get('cost_contract') != 'fixed_success':
            raise ValueError('Pilot requires fixed pricing')
        offer = entry['offer']
        if (offer.get('method') != 'tempo' or offer.get('intent') != 'charge'
                or not re.fullmatch(r'[0-9]+', offer.get('amount', ''))
                or not re.fullmatch(r'0x[0-9a-fA-F]{40}', offer.get('currency', ''))
                or not offer.get('description') or entry.get('status') != 402
                or not entry.get('observed_at')):
            raise ValueError('Missing or invalid observed payment terms')
        op = copy.deepcopy(original)
        # Do not publish account pricing or inherited API-key authentication.
        op = {k: v for k, v in op.items() if not k.startswith('x-aisa-')
              and k not in ('security', 'servers')}
        item = source['paths'][path]
        if item.get('parameters'):
            op['parameters'] = copy.deepcopy(item['parameters']) + op.get('parameters', [])
        if not any('schema' in media
                   for status, response in op['responses'].items() if status.startswith('2')
                   for media in response.get('content', {}).values()):
            raise ValueError('Missing successful response schema')
        op['responses']['402'] = {
            'description': 'Payment required. Read WWW-Authenticate for current terms.',
            'headers': {'WWW-Authenticate': {
                'description': 'MPP payment challenge', 'schema': {'type': 'string'}}},
        }
        op['x-payment-info'] = {'offers': [copy.deepcopy(offer)]}
        if method in doc['paths'].get(path, {}):
            raise ValueError('Duplicate operation')
        doc['paths'].setdefault(path, {})[method] = op

    # Copy only reachable components and reject external/unresolved references.
    seen = set()

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if '$ref' in value:
                ref = value['$ref']
                if not ref.startswith('#/components/') or len(ref.split('/')) != 4:
                    raise ValueError('Unsupported reference: ' + ref)
                if ref not in seen:
                    seen.add(ref)
                    _, _, section, encoded = ref.split('/')
                    name = encoded.replace('~1', '/').replace('~0', '~')
                    component = copy.deepcopy(source['components'][section][name])
                    doc.setdefault('components', {}).setdefault(section, {})[name] = component
                    visit(component)
            for child in value.values():
                visit(child)

    visit(doc['paths'])
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'discovery/openapi.json')
    args = parser.parse_args()
    evidence = json.loads((ROOT / 'discovery/payment-evidence.json').read_text())
    source_bytes = (ROOT / evidence['source']).read_bytes()
    doc = build(json.loads(source_bytes), evidence, source_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + '\n')
    print(f'Generated {len(doc["paths"])} paths: {args.output}')


if __name__ == '__main__':
    main()

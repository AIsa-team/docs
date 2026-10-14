#!/usr/bin/env python3
"""Build the reviewed MPP pilot catalog; no network requests or payments."""
import argparse
import copy
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(source, evidence, source_bytes):
    if hashlib.sha256(source_bytes).hexdigest() != evidence['source_sha256']:
        raise ValueError('Source changed; review schemas and refresh payment evidence first')
    doc = {
        'openapi': '3.1.0',
        'info': {
            'title': 'AIsa MPP Data APIs', 'version': '1.0.0',
            'contact': {'url': 'https://aisa.one', 'email': 'developer@aisa.one'},
            'x-guidance': 'Use GET query parameters, not a JSON body. Holders requires '
                          'market condition IDs; live-volume requires an event id; '
                          'oi optionally accepts market condition IDs. Inspect the '
                          '402 WWW-Authenticate challenge before paying with Tempo MPP '
                          'and retry with Authorization: Payment <credential>.',
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
        # MPPScan requires price/protocols in addition to canonical MPP offers.
        # Use the reviewed USD price, not raw token units as a dollar amount.
        try:
            price = Decimal(str(original['x-aisa-pricing']['default_request_estimate_usd']))
        except (KeyError, InvalidOperation):
            raise ValueError('Missing reviewed fixed USD price') from None
        if not price.is_finite() or price < 0:
            raise ValueError('Invalid reviewed fixed USD price')
        op['x-payment-info'] = {
            'offers': [copy.deepcopy(offer)],
            'price': {'mode': 'fixed', 'currency': 'USD', 'amount': format(price, 'f')},
            'protocols': [{'mpp': {key: offer[key] for key in ('method', 'intent', 'currency')}}],
        }
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
    parser.add_argument('--allowlist', type=Path, help='Runtime packages/mppcatalog/allowlist.json')
    parser.add_argument('--evidence', type=Path, default=ROOT / 'discovery/payment-evidence.json')
    parser.add_argument('--runtime-plan', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.allowlist:
        from payment_catalog import build_catalog
        if not args.runtime_plan or not args.report:
            parser.error('--allowlist requires --runtime-plan and --report')
        blocked_path = args.allowlist.with_name('blocked.json')
        blocked = json.loads(blocked_path.read_bytes()) if blocked_path.exists() else []
        doc, report = build_catalog(ROOT, json.loads(args.allowlist.read_bytes()),
                                    json.loads(args.evidence.read_bytes()), args.runtime_plan.read_bytes(), blocked)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + '\n')
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n')
        print(json.dumps(report['providers'], indent=2))
        return
    evidence = json.loads(args.evidence.read_text())
    source_bytes = (ROOT / evidence['source']).read_bytes()
    doc = build(json.loads(source_bytes), evidence, source_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + '\n')
    print(f'Generated {len(doc["paths"])} paths: {args.output}')


if __name__ == '__main__':
    main()

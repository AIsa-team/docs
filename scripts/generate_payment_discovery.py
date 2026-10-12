#!/usr/bin/env python3
"""Build the reviewed MPP pilot catalog; no network requests or payments."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SEMANTIC_BINDING_ALGORITHM = 'sha256-json-except-composer-metadata-v1'
SEMANTIC_BINDING_ALGORITHM = 'sha256-selected-payment-contracts-v2'
PAYMENT_FILES = ('discovery/payment-evidence.json', 'discovery/openapi.json')


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('utf-8')


def source_semantic_sha256(source):
    """Bind all source content except two reviewed generator bookkeeping values.

    The exclusion is code-defined, never supplied by evidence. In particular,
    facts hashes, routes, schemas, prices, auth and capabilities remain bound.
    """
    semantic = copy.deepcopy(source)
    metadata = semantic.get('info', {}).get('x-aisa-document')
    if isinstance(metadata, dict):
        metadata.pop('composer_version', None)
        metadata.pop('document_hash', None)
    return hashlib.sha256(canonical_json(semantic)).hexdigest()


def referenced_components(source, value):
    """The complete local reference closure, never all provider components."""
    components, seen = {}, set()

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            if '$ref' in node:
                ref = node['$ref']
                if not isinstance(ref, str) or not ref.startswith('#/components/') or len(ref.split('/')) != 4:
                    raise ValueError('Unsupported reference: ' + str(ref))
                if ref not in seen:
                    seen.add(ref)
                    _, _, section, encoded = ref.split('/')
                    name = encoded.replace('~1', '/').replace('~0', '~')
                    try:
                        component = copy.deepcopy(source['components'][section][name])
                    except KeyError as exc:
                        raise ValueError('Unresolved reference: ' + ref) from exc
                    components.setdefault(section, {})[name] = component
                    visit(component)
            for child in node.values():
                visit(child)

    visit(value)
    return components


def selected_operations(source, evidence):
    entries, seen = [], set()
    if not isinstance(evidence.get('operations'), list) or not evidence['operations']:
        raise ValueError('No reviewed operations')
    for entry in evidence['operations']:
        path, method = entry['path'], entry['method']
        if method != 'get' or not path.startswith('/apis/v1/polymarket/'):
            raise ValueError('Pilot supports only reviewed Polymarket GET routes')
        if (path, method) in seen:
            raise ValueError('Duplicate operation')
        seen.add((path, method))
        try:
            item = source['paths'][path]
            operation = item[method]
        except KeyError as exc:
            raise ValueError('Reviewed operation missing: ' + method.upper() + ' ' + path) from exc
        entries.append((entry, item, operation))
    return entries


def method_supported(operation, method, *, legacy=False):
    capability = operation.get('x-aisa-capabilities', {})
    methods = capability.get('mpp_methods')
    # Only the explicit legacy evidence algorithm may read pre-method facts.
    if methods is None and legacy:
        return capability.get('mpp') is True
    return (capability.get('mpp') is True and isinstance(methods, list)
            and bool(methods) and all(isinstance(m, str) and m.upper() in
                ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE') for m in methods)
            and method.upper() in {m.upper() for m in methods})


def contract_projection(source, evidence):
    """Fixed dependencies of the reviewed operations, independent of compiler facts.

    Source bookkeeping and other operations are not payment review dependencies.
    Prices, binding, effective auth, request/response and reachable schemas are.
    Evidence cannot supply exclusion paths or choose projection fields.
    """
    projection = {'operations': {}}
    for entry, item, operation in selected_operations(source, evidence):
        path, method = entry['path'], entry['method']
        security = operation.get('security', source.get('security', []))
        contract = {key: copy.deepcopy(operation[key]) for key in
                    ('operationId', 'parameters', 'requestBody', 'responses', 'deprecated') if key in operation}
        contract['path_parameters'] = copy.deepcopy(item.get('parameters', []))
        contract['servers'] = copy.deepcopy(operation.get('servers', item.get('servers', source.get('servers', []))))
        contract['security'] = copy.deepcopy(security)
        # Schemes are referenced by name in security requirements, not by $ref.
        schemes = {}
        for requirement in security:
            for name in requirement:
                try:
                    schemes[name] = copy.deepcopy(source['components']['securitySchemes'][name])
                except KeyError as exc:
                    raise ValueError('Unresolved security scheme: ' + name) from exc
        contract['security_schemes'] = schemes
        for key in ('x-aisa-runtime-operation', 'x-aisa-upstream-path', 'x-aisa-status',
                    'x-aisa-pricing', 'x-aisa-revision', 'x-aisa-passthrough',
                    'x-aisa-query-policy', 'x-aisa-validation'):
            contract[key] = copy.deepcopy(operation.get(key))
        contract['mpp_method_enabled'] = method_supported(operation, method)
        contract['components'] = referenced_components(source, contract)
        projection['operations'][method.upper() + ' ' + path] = contract
    return projection


def projection_binding(source, evidence):
    projection = contract_projection(source, evidence)
    return {'algorithm': SEMANTIC_BINDING_ALGORITHM,
            'sha256': hashlib.sha256(canonical_json(projection)).hexdigest(),
            'projection': projection}


def changed_fields(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(set(before) | set(after)):
            path = prefix + '/' + key.replace('~', '~0').replace('/', '~1')
            result.extend([path] if key not in before or key not in after
                          else changed_fields(before[key], after[key], path))
        return result
    return [] if before == after else [prefix]


def verify_source_binding(source, evidence, source_bytes):
    if canonical_json(json.loads(source_bytes)) != canonical_json(source):
        raise ValueError('Source object does not match source bytes')
    binding = evidence.get('source_semantic_binding')
    if 'source_semantic_binding' not in evidence:
        matches = hashlib.sha256(source_bytes).hexdigest() == evidence['source_sha256']
    else:
        algorithm = binding.get('algorithm') if isinstance(binding, dict) else None
        keys = {'algorithm', 'sha256', 'projection'} if algorithm == SEMANTIC_BINDING_ALGORITHM else {'algorithm', 'sha256'}
        if (not isinstance(binding, dict) or set(binding) != keys
                or algorithm not in (SEMANTIC_BINDING_ALGORITHM, LEGACY_SEMANTIC_BINDING_ALGORITHM)
                or not isinstance(binding.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', binding['sha256'])):
            raise ValueError('Invalid reviewed source semantic binding')
        if algorithm == SEMANTIC_BINDING_ALGORITHM:
            if hashlib.sha256(canonical_json(binding['projection'])).hexdigest() != binding['sha256']:
                raise ValueError('Reviewed projection digest does not match')
            actual = contract_projection(source, evidence)
            differences = changed_fields(binding['projection'], actual)
            if differences:
                raise ValueError('Reviewed payment contract changed: ' + ', '.join(differences[:20]))
            matches = True
        else:
            matches = source_semantic_sha256(source) == binding['sha256']
    if not matches:
        raise ValueError('Source changed; review schemas and refresh payment evidence first')


def build(source, evidence, source_bytes):
    verify_source_binding(source, evidence, source_bytes)
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
        legacy = evidence.get('source_semantic_binding', {}).get('algorithm') != SEMANTIC_BINDING_ALGORITHM
        if not method_supported(original, method, legacy=legacy):
            raise ValueError('Operation does not advertise MPP support for ' + method.upper())
        if original.get('x-aisa-status') != 'enabled':
            raise ValueError('Payment operation is not enabled')
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

    components = referenced_components(source, doc['paths'])
    if components:
        doc['components'] = components
    return doc


def candidate(root):
    root = Path(root)
    evidence = json.loads((root / PAYMENT_FILES[0]).read_text())
    # A review input cannot make the candidate reader leave the provider tree.
    if evidence.get('source') != 'openapi/polymarket-data.json':
        raise ValueError('Unexpected payment source')
    raw = (root / evidence['source']).read_bytes()
    return build(json.loads(raw), evidence, raw)


def verify_payment_catalog(root):
    expected = candidate(root)
    actual = json.loads((Path(root) / PAYMENT_FILES[1]).read_text())
    if actual != expected:
        raise ValueError('Payment catalog does not match reviewed current source')
    return {'status': 'passed', 'operations': sum(len(item) for item in expected['paths'].values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Verify generated catalog without writing')
    args = parser.parse_args()
    if args.check:
        if args.output:
            parser.error('--check cannot be combined with --output')
        print(json.dumps(verify_payment_catalog(args.root), sort_keys=True))
        return
    doc = candidate(args.root)
    output = args.output or args.root / PAYMENT_FILES[1]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, indent=2, ensure_ascii=True) + '\n')
    print(f'Generated {len(doc["paths"])} paths: {output}')


if __name__ == '__main__':
    main()

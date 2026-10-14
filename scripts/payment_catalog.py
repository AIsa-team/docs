"""Multi-provider discovery publication from reviewed routes and observed quotes.

No endpoint is enabled and no payment is made by this module.
"""
import copy
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

# Reviewed settlement denomination, not a token-price oracle. New assets/chains
# require explicit review instead of assuming every ERC20 represents one USD.
USD_ASSETS = {(4217, '0x20c000000000000000000000b9537d11c60e8b50'): 6}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def key(row):
    return row['provider'], row['method'].upper(), row['path']


def local_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Source is outside docs root')
    return path


def build_catalog(root, allowlist, evidence, plan_raw, blocked=()):
    plan = json.loads(plan_raw)
    if evidence.get('version') != 2 or plan.get('version') != 1:
        raise ValueError('Expected reviewed v2 payment evidence and v1 runtime plan')
    if evidence.get('runtime_plan_sha256') != digest(plan_raw):
        raise ValueError('Runtime quote plan changed')
    if evidence.get('environment') != 'production' or evidence.get('server') != 'https://api.aisa.one':
        raise ValueError('Only production challenge evidence may be published')
    allowed = {key(op): op for op in allowlist}
    if len(allowed) != len(allowlist) or any(op['provider'] == 'tikhub' for op in allowlist):
        raise ValueError('Invalid reviewed allowlist')
    quotes = {key(row['operation']): row for row in plan['entries']}
    doc = {'openapi': '3.1.0', 'info': {
        'title': 'AIsa MPP Data APIs', 'version': '2.0.0',
        'contact': {'url': 'https://aisa.one', 'email': 'developer@aisa.one'},
        'description': 'Reviewed synchronous read-only APIs. Prices reflect the verified public PAYG quote; inspect the current 402 challenge before payment.',
        'x-guidance': 'GET uses query/path parameters. Read-only POST uses the documented requestBody. Request without credentials to inspect the 402 WWW-Authenticate challenge, then retry the same request and X-Request-ID with Authorization: Payment <credential>. Failed payment records do not imply an on-chain refund.'},
        'servers': [{'url': evidence['server']}], 'paths': {}}
    report = {'version': 2, 'runtime_plan_sha256': digest(plan_raw), 'allowlist_sha256': digest(json.dumps(allowlist, sort_keys=True).encode()),
              'providers': {}, 'included': [], 'excluded': [{'provider': r['provider'], 'method': r['method'], 'path': r['path'], 'reason': r['blocked_reason']} for r in blocked], 'known_warnings': ['MPPScan UI may warn about GET input schemas; query/path parameters remain authoritative and no synthetic JSON body is added.'], 'verification': 'Unauthenticated challenges only; paid execution remains a separate staging acceptance step.'}
    seen = set()
    operation_ids = set()
    for entry in evidence['operations']:
        identity = key(entry)
        if identity in seen:
            raise ValueError('Duplicate evidence operation')
        seen.add(identity)
        if identity not in allowed:
            raise ValueError('Evidence operation outside reviewed allowlist')
        if entry.get('error'):
            report['excluded'].append({'provider': identity[0], 'method': identity[1], 'path': identity[2], 'reason': entry['error']})
            continue
        quote = quotes.get(identity)
        if not quote or quote.get('blocked_reason'):
            raise ValueError('No eligible deterministic runtime quote')
        spec = allowed[identity]
        raw = local_file(root, spec['source']).read_bytes()
        if digest(raw) != entry['source_sha256']:
            raise ValueError('Source changed after challenge verification')
        source = json.loads(raw)
        provider, method, path = identity
        method = method.lower()
        if method not in ('get', 'post'):
            raise ValueError('Discovery supports reviewed read-only GET/POST only')
        item = source['paths'][path]
        original = item[method]
        caps = original.get('x-aisa-capabilities', {})
        if original.get('x-aisa-status') != 'enabled' or caps.get('mpp') is not True:
            raise ValueError('Runtime has not enabled MPP for this operation')
        if 'mpp_methods' in caps and method.upper() not in caps['mpp_methods']:
            raise ValueError('Runtime method is not enabled for MPP')
        document_target = original.get('x-aisa-upstream-path')
        if (quote['operation'].get('target') != spec['target'] or
                (document_target is not None and document_target != spec['target']) or
                (document_target is None and original.get('x-aisa-validation') != 'runtime')):
            raise ValueError('Reviewed upstream route changed or lacks runtime authority')
        revisions = original.get('x-aisa-revision')
        if not revisions or not all(quote.get(k) for k in ('profile_ref', 'customer_pricing_ref', 'plan_policy_version')) or revisions.get('profile_ref') != quote.get('profile_ref') or revisions.get('customer_pricing_ref') != quote.get('customer_pricing_ref') or revisions.get('plan_policy_version') != quote.get('plan_policy_version'):
            raise ValueError('Missing runtime source revisions')
        if original.get('x-aisa-pricing', {}).get('cost_contract') != 'fixed_success':
            raise ValueError('Runtime no longer advertises fixed cost')
        offer = entry['offer']
        decimals = USD_ASSETS.get((entry.get('chain_id'), offer.get('currency', '').lower()))
        amount = offer.get('amount', '')
        if (entry.get('status') != 402 or not entry.get('observed_at') or not entry.get('expires')
                or offer.get('method') != 'tempo' or offer.get('intent') != 'charge'
                or not offer.get('description') or not re.fullmatch(r'[0-9]+', amount)
                or decimals is None or entry.get('decimals') != decimals):
            raise ValueError('Invalid observed payment terms or unknown USD denomination')
        price = quote.get('price_micros_usd')
        base, multiplier = quote.get('base_micros_usd'), quote.get('payg_multiplier_ppm')
        if (not isinstance(price, int) or price <= 0 or not isinstance(base, int) or base <= 0
                or not isinstance(multiplier, int) or multiplier <= 0
                or price != (base * multiplier + 999999) // 1000000):
            raise ValueError('Invalid deterministic PAYG quote')
        if Decimal(amount) / 10**decimals != Decimal(price) / 1_000_000:
            raise ValueError('Live challenge amount differs from runtime PAYG quote')
        op = {k: copy.deepcopy(v) for k, v in original.items()
              if not k.startswith('x-aisa-') and k not in ('security', 'servers')}
        if method == 'post' and not op.get('requestBody'):
            raise ValueError('Read-only POST requires its real input schema')
        # Operation-level parameters override matching path-level parameters.
        def parameter_key(parameter):
            value, visited = parameter, set()
            while '$ref' in value:
                ref = value['$ref']
                if not ref.startswith('#/components/parameters/') or ref in visited:
                    raise ValueError('Invalid parameter reference')
                visited.add(ref)
                value = source
                for part in ref[2:].split('/'):
                    value = value[part.replace('~1', '/').replace('~0', '~')]
            return value['in'], value['name']
        params = {parameter_key(p): copy.deepcopy(p) for p in item.get('parameters', [])}
        params.update({parameter_key(p): p for p in op.get('parameters', [])})
        if params:
            op['parameters'] = list(params.values())
        namespace = provider.replace('-', '_') + '__'
        reachable = {}

        def rewrite(value):
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if not isinstance(value, dict):
                return value
            value = {k: rewrite(v) for k, v in value.items()}
            if '$ref' in value:
                value['$ref'] = reference(value['$ref'])
            if isinstance(value.get('discriminator'), dict):
                mapping = value['discriminator'].get('mapping', {})
                for name, ref in mapping.items():
                    mapping[name] = reference(ref)
            return value

        def reference(ref):
            if not isinstance(ref, str) or not ref.startswith('#/components/') or len(ref.split('/')) != 4:
                raise ValueError('Unsupported or external reference: ' + str(ref))
            _, _, section, encoded = ref.split('/')
            if section == 'securitySchemes':
                raise ValueError('Account authentication is not discovery input')
            name = encoded.replace('~1', '/').replace('~0', '~')
            target_name = namespace + name
            target = '#/components/' + section + '/' + target_name.replace('~', '~0').replace('/', '~1')
            if ref not in reachable:
                reachable[ref] = True
                component = rewrite(copy.deepcopy(source['components'][section][name]))
                dest = doc.setdefault('components', {}).setdefault(section, {})
                if target_name in dest and dest[target_name] != component:
                    raise ValueError('Component namespace collision')
                dest[target_name] = component
            return target

        op = rewrite(op)
        def resolve(value):
            refs = set()
            while '$ref' in value:
                ref = value['$ref']
                if ref in refs:
                    raise ValueError('Cyclic response reference')
                refs.add(ref)
                _, _, section, encoded = ref.split('/')
                value = doc['components'][section][encoded.replace('~1', '/').replace('~0', '~')]
            return value
        if not any('schema' in media for status, response in op.get('responses', {}).items()
                   if str(status).startswith('2') for media in resolve(response).get('content', {}).values()):
            raise ValueError('Missing successful response schema')
        if method == 'post' and not any('schema' in media for media in resolve(op['requestBody']).get('content', {}).values()):
            raise ValueError('Missing POST input schema')
        op['operationId'] = namespace + op.get('operationId', method + '_' + digest(path.encode())[:12])
        if op['operationId'] in operation_ids:
            raise ValueError('Duplicate operation identity')
        operation_ids.add(op['operationId'])
        op['responses']['402'] = {'description': 'Payment required. Inspect WWW-Authenticate for current terms.',
                                  'headers': {'WWW-Authenticate': {'schema': {'type': 'string'}}}}
        op['x-payment-info'] = {'offers': [copy.deepcopy(offer)],
                               'price': {'mode': 'fixed', 'currency': 'USD', 'amount': format(Decimal(price) / 1_000_000, 'f')},
                               'protocols': [{'mpp': {k: offer[k] for k in ('method', 'intent', 'currency')}}]}
        doc['paths'].setdefault(path, {})[method] = op
        report['included'].append({'provider': provider, 'method': method.upper(), 'path': path,
                                   'source': spec['source'], 'source_sha256': digest(raw), 'source_revision': revisions,
                                   'quote_source': {'profile_sha256': quote['profile_sha256'], 'pricing_sha256': quote['pricing_sha256'],
                                                    'base_micros_usd': base, 'payg_multiplier_ppm': multiplier, 'price_micros_usd': price},
                                   'observed_at': entry['observed_at'], 'chain_id': entry['chain_id'], 'decimals': decimals})
    for identity, spec in allowed.items():
        if identity not in seen:
            row = quotes.get(identity, {})
            report['excluded'].append({'provider': identity[0], 'method': identity[1], 'path': identity[2],
                                       'reason': row.get('blocked_reason') or 'missing_production_challenge_evidence'})
    for provider in sorted({k[0] for k in allowed} | {r['provider'] for r in blocked}):
        report['providers'][provider] = {'included': sum(r['provider'] == provider for r in report['included']),
                                         'excluded': sum(r['provider'] == provider for r in report['excluded'])}
    if not report['included']:
        raise ValueError('No verified operations; refusing empty publication')
    raw = (json.dumps(doc, indent=2, ensure_ascii=True) + '\n').encode()
    report['output_sha256'] = digest(raw)
    return doc, report

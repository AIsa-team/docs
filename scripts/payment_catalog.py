"""Multi-provider discovery publication from reviewed routes and observed quotes.

No endpoint is enabled and no payment is made by this module.
"""
import copy
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from compose_openapi import effective_object, map_contract_children, referenced_components

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


def build_catalog(root, allowlist, evidence, plan_raw=None, blocked=(), *, runtime_quotes=False):
    if runtime_quotes:
        if evidence.get('version') != 3 or evidence.get('quote_source') != 'runtime-unauthenticated-402':
            raise ValueError('Expected explicitly attributed Runtime 402 evidence')
        plan = {'entries': []}
    else:
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
    if len(quotes) != len(plan['entries']):
        raise ValueError('Duplicate runtime quote operation')
    doc = {'openapi': '3.1.0', 'info': {
        'title': 'AIsa MPP Data APIs', 'version': '2.0.0',
        'contact': {'url': 'https://aisa.one', 'email': 'developer@aisa.one'},
        'description': 'Reviewed synchronous read-only APIs. Prices reflect the verified public PAYG quote; inspect the current 402 challenge before payment.',
        'x-guidance': 'GET uses query/path parameters. Read-only POST uses the documented requestBody. Request without credentials to inspect the 402 WWW-Authenticate challenge, then retry the same request and X-Request-ID with Authorization: Payment <credential>. Failed payment records do not imply an on-chain refund.'},
        'servers': [{'url': evidence['server']}], 'paths': {}}
    report = {'version': 3 if runtime_quotes else 2, 'quote_source': 'runtime-unauthenticated-402' if runtime_quotes else 'verified-runtime-plan', 'allowlist_sha256': digest(json.dumps(allowlist, sort_keys=True).encode()),
              'providers': {}, 'included': [], 'excluded': [{'provider': r['provider'], 'method': r['method'], 'path': r['path'], 'reason': r['blocked_reason']} for r in blocked], 'known_warnings': ['MPPScan UI may warn about GET input schemas; query/path parameters remain authoritative and no synthetic JSON body is added.'], 'verification': 'Unauthenticated challenges only; paid execution remains a separate staging acceptance step.'}
    if not runtime_quotes:
        report['runtime_plan_sha256'] = digest(plan_raw)
    seen = set()
    operation_ids = set()
    sources, verified_bindings = {}, set()
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
        if not runtime_quotes and (not quote or quote.get('blocked_reason')):
            raise ValueError('No eligible deterministic runtime quote')
        spec = allowed[identity]
        if spec['source'] not in sources:
            raw = local_file(root, spec['source']).read_bytes()
            sources[spec['source']] = (raw, json.loads(raw))
        raw, source = sources[spec['source']]
        binding = evidence.get('source_contracts', {}).get(spec['source'])
        if binding is None:
            if digest(raw) != entry['source_sha256']:
                raise ValueError('Source changed after challenge verification')
        elif spec['source'] not in verified_bindings:
            verify_contract_binding(source, [op for op in allowlist if op['source'] == spec['source']], binding)
            verified_bindings.add(spec['source'])
        provider, method, path = identity
        method = method.lower()
        if method not in ('get', 'post'):
            raise ValueError('Discovery supports reviewed read-only GET/POST only')
        item = source['paths'][path]
        original = item[method]
        caps = original.get('x-aisa-capabilities', {})
        if original.get('x-aisa-status') != 'enabled' or caps.get('mpp') is not True:
            raise ValueError('Runtime has not enabled MPP for this operation')
        if not isinstance(caps.get('mpp_methods'), list) or method.upper() not in caps['mpp_methods']:
            raise ValueError('Runtime method is not enabled for MPP')
        document_target = original.get('x-aisa-upstream-path')
        bound_target = entry.get('runtime_binding', {}).get('target') if runtime_quotes else quote['operation'].get('target')
        if (bound_target != spec['target'] or
                (document_target is not None and document_target != spec['target']) or
                (document_target is None and original.get('x-aisa-validation') != 'runtime')):
            raise ValueError('Reviewed upstream route changed or lacks runtime authority')
        revisions = original.get('x-aisa-revision')
        quoted_revisions = entry.get('runtime_binding', {}).get('revision', {}) if runtime_quotes else quote
        if not revisions or not all(quoted_revisions.get(k) for k in ('profile_ref', 'customer_pricing_ref', 'plan_policy_version')) or any(revisions.get(k) != quoted_revisions.get(k) for k in ('profile_ref', 'customer_pricing_ref', 'plan_policy_version')):
            raise ValueError('Missing runtime source revisions')
        if runtime_quotes:
            bound = entry['runtime_binding']
            for name, field in (('pricing', 'x-aisa-pricing'), ('capabilities', 'x-aisa-capabilities'), ('status', 'x-aisa-status')):
                declared = original.get(field)
                if name == 'capabilities':
                    # Composer also documents ordinary token-auth quote and
                    # idempotency headers; Runtime owns these payment flags.
                    declared = {k: declared.get(k) for k in ('mpp', 'mpp_methods', 'x402') if k in bound[name]}
                if canonical_json(bound.get(name)) != canonical_json(declared):
                    raise ValueError('Current source differs from acquired Runtime payment binding')
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
        # Expiry is the historical challenge lifetime, not a claim that the
        # published static offer is still redeemable. Clients obtain a new 402.
        try:
            observed = datetime.fromisoformat(entry['observed_at'].replace('Z', '+00:00'))
            expires = datetime.fromisoformat(entry['expires'].replace('Z', '+00:00'))
            if observed.tzinfo is None or expires.tzinfo is None or expires <= observed:
                raise ValueError('Invalid observed challenge lifetime')
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid observed challenge lifetime') from exc
        if runtime_quotes:
            price = int(amount)
            if price <= 0 or decimals != 6:
                raise ValueError('Invalid Runtime fixed USD amount')
            quote_source = {'authority': 'runtime-unauthenticated-402', 'amount': amount,
                            'currency': offer['currency'], 'chain_id': entry['chain_id'], 'decimals': decimals}
        else:
            price = quote.get('price_micros_usd')
            base, multiplier = quote.get('base_micros_usd'), quote.get('payg_multiplier_ppm')
            if (type(price) is not int or price <= 0 or type(base) is not int or base <= 0
                    or type(multiplier) is not int or multiplier <= 0
                    or price != (base * multiplier + 999999) // 1000000):
                raise ValueError('Invalid deterministic PAYG quote')
            if Decimal(amount) / 10**decimals != Decimal(price) / 1_000_000:
                raise ValueError('Live challenge amount differs from runtime PAYG quote')
            quote_source = {'profile_sha256': quote['profile_sha256'], 'pricing_sha256': quote['pricing_sha256'],
                            'base_micros_usd': base, 'payg_multiplier_ppm': multiplier, 'price_micros_usd': price}
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
        # Match the deployed runtime catalogue identity and avoid collisions
        # between differently scoped component definitions of one provider.
        namespace = provider.replace('-', '_') + '_' + digest((method.upper() + path).encode())[:12] + '__'
        reachable = {}

        def rewrite(value):
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if not isinstance(value, dict):
                return value
            if '$dynamicRef' in value or '$recursiveRef' in value:
                raise ValueError('Unsupported dynamic payment reference')
            value = map_contract_children(value, rewrite)
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
                definition = copy.deepcopy(source['components'][section][name])
                component = (rewrite({'links': {'target': definition}})['links']['target']
                             if section == 'links' else rewrite(definition))
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
                                   'quote_source': quote_source,
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


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def contract_projection(source, operations):
    """Bind selected contracts and their full closure, not source refresh metadata.

    Instances and unknown extensions remain data; neither may introduce refs.
    Display-only fields do not authorize pricing, auth or schema changes.
    """
    selected = {}
    for spec in operations:
        method, path = spec['method'].lower(), spec['path']
        item = source['paths'][path]
        original = item[method]
        contract = {k: copy.deepcopy(v) for k, v in original.items() if k not in {
            'description', 'summary', 'tags', 'externalDocs', 'x-codeSamples',
            'x-aisa-source', 'x-aisa-response-source', 'x-aisa-docs-url', 'x-aisa-category'}}
        contract['path_parameters'] = copy.deepcopy(item.get('parameters', []))
        contract['servers'] = copy.deepcopy(original.get('servers', item.get('servers', source.get('servers', []))))
        contract['security'] = copy.deepcopy(original.get('security', source.get('security', [])))
        schemes = {}
        for requirement in contract['security']:
            for name in requirement:
                try:
                    schemes[name] = effective_object(source['components']['securitySchemes'][name], source)
                except KeyError as exc:
                    raise ValueError('Unresolved payment source security scheme') from exc
        # x-aisa fields and security scheme definitions are not request schemas.
        public = {k: v for k, v in contract.items() if not k.startswith('x-aisa-')}
        contract['components'] = referenced_components(public, source)
        contract['security_schemes'] = schemes
        selected[method.upper() + ' ' + path] = contract
    return selected


def contract_binding(source, operations):
    projection = contract_projection(source, operations)
    return {'algorithm': 'sha256-selected-multi-payment-contracts-v1',
            'sha256': digest(canonical_json(projection)), 'projection': projection}


def verify_contract_binding(source, operations, binding):
    if not isinstance(binding, dict) or set(binding) != {'algorithm', 'sha256', 'projection'}:
        raise ValueError('Invalid payment contract binding')
    actual = contract_binding(source, operations)
    if canonical_json(binding) != canonical_json(actual):
        raise ValueError('Reviewed payment contract changed; review and refresh evidence')


def build_publication(root, bundle):
    """Read the reviewed public subset without expanding production enablement."""
    if bundle.get('version') != 3 or bundle.get('kind') != 'reviewed-mpp-publication':
        raise ValueError('Unsupported payment publication bundle')
    allowed = bundle['allowlist']
    evidence = bundle['challenge_evidence']
    if not allowed or any(op['source'] != 'openapi/' + op['provider'] + '.json' for op in allowed):
        raise ValueError('Invalid payment provider source')
    if set(evidence.get('source_contracts', {})) != {op['source'] for op in allowed}:
        raise ValueError('Missing or unexpected reviewed payment source binding')
    identities = {key(op) for op in allowed}
    if identities != {key(row) for row in evidence['operations']} or any(row.get('error') for row in evidence['operations']):
        raise ValueError('Every published operation requires successful production challenge evidence')
    snapshot = evidence.get('runtime_snapshot', {})
    if (not re.fullmatch('[0-9a-f]{64}', str(snapshot.get('artifact_revision', '')))
            or not re.fullmatch('[0-9a-f]{40}', str(snapshot.get('compiler_revision', '')))
            or not re.fullmatch('[0-9a-f]{64}', str(snapshot.get('source_digest', '')))
            or type(snapshot.get('generation')) is not int or snapshot['generation'] < 0
            or evidence.get('fresh_before_and_after') is not True):
        raise ValueError('Missing stable fresh Runtime snapshot attribution')
    doc, report = build_catalog(root, allowed, evidence, runtime_quotes=True)
    if report['excluded'] or len(report['included']) != len(allowed):
        raise ValueError('Refusing to silently withdraw a published payment operation')
    return doc, report

#!/usr/bin/env python3
"""Prepare unapproved Financial/Polymarket/Parallel route decisions offline.

Exact alternative contracts are not evidence that the current target is equal.
No network, SQL execution, Profile compilation or publication is supported.
"""
import argparse
import ast
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.parse import urlsplit

import yaml

from compose_openapi import METHODS, digest, has_response_contract, referenced_components, response_object, upstream_path_item
from import_upstream import OfficialSourceLoader
from source_json import loads

ARCHIVE_SHA256 = '6a35a7ddd15b8f87dd476afeaa8c4e9e1c7164a95a963c9413ec9d863b5fc174'
SOURCE_FILES = {
    'financial': ('financial-authoritative-openapi.json', 'https://financialdatasets.ai/openapi.json', 'https://api.financialdatasets.ai'),
    'polymarket-clob': ('polymarket-clob-current.yaml', 'https://docs.polymarket.com/api-spec/clob-openapi.yaml', 'https://clob.polymarket.com'),
    'polymarket-data': ('polymarket-data-current.yaml', 'https://docs.polymarket.com/api-spec/data-openapi.yaml', 'https://data-api.polymarket.com'),
    'polymarket-gamma': ('polymarket-gamma-current.yaml', 'https://docs.polymarket.com/api-spec/gamma-openapi.yaml', 'https://gamma-api.polymarket.com'),
    'parallel.ai': ('parallel-public-openapi-current.json', 'https://docs.parallel.ai/public-openapi.json', 'https://api.parallel.ai'),
}
SDK_FILE = 'financial-mcp-server.py'
SDK_URL = 'https://raw.githubusercontent.com/financial-datasets/mcp-server/08e7a3dbb949d3d99bbd6d6f3a22e5f02973ec58/server.py'
SDK_SHA256 = 'eaa44f981737c3f29f774a61d027794e5f8c0e05772a15c58cac9fce3de977f5'
SDK_FUNCTIONS = ('get_crypto_prices', 'get_historical_crypto_prices', 'get_current_crypto_price')
# These are intentional migration alternatives, never equivalent-route aliases.
# Unsupported old contracts remain finite owner decisions rather than guesses.
TARGETS = (
    (1683, 'financial', '/company/facts/ticker', 'financial', '/company/facts', 'review_ticker_facts_migration'),
    (1684, 'financial', '/crypto/prices', None, None, 'legacy_crypto_support_decision'),
    (1685, 'financial', '/crypto/prices/snapshot', None, None, 'legacy_crypto_support_decision'),
    (1686, 'financial', '/earnings/press-releases', None, None, 'retain_with_provider_contract_or_retire'),
    (1694, 'financial', '/institutional-ownership', 'financial', '/institutional-holdings', 'review_institutional_response_change'),
    (1702, 'financial', '/financials/segmented-revenues', 'financial', '/financials/income-statements/segments', 'review_segment_response_change'),
    (2220, 'polymarket-clob', '/order/{orderID}', 'polymarket-clob', '/data/order/{orderID}', 'review_clob_target_and_signature_repair'),
    (2227, 'polymarket-clob', '/trades', 'polymarket-clob', '/data/trades', 'review_clob_target_and_signature_repair'),
    (2251, 'polymarket-data', '/public-search', 'polymarket-gamma', '/public-search', 'review_gamma_provider_ownership_migration'),
    (1801, 'parallel.ai', '/v1beta/tasks/runs/{run_id}/events', 'parallel.ai', '/v1/tasks/runs/{run_id}/events', 'retain_legacy_with_support_proof_or_migrate_to_existing_ga'),
)
CURRENT_FIELDS = ('endpoint_id', 'provider_key', 'public_path', 'endpoint_status', 'provider_status',
    'contract_method', 'upstream_path', 'stored_target_path', 'target_has_query', 'target_matches_endpoint',
    'authority_equal_expected', 'profile_binding_metadata_matches', 'profile_key', 'profile_revision',
    'compiled_contract_revision', 'profile_status', 'binding_sha256', 'profile_canonical_sha256',
    'profile_contract_sha256', 'target_sha256', 'upstream_origin_sha256', 'provider_config_sha256',
    'request_contract_sha256', 'body_shape', 'body_open', 'public_request_fields',
    'response_contract_present', 'target_query_request_wins', 'provider_metered_v2_optin',
    'full_binding_compiler_validation_performed', 'stored_profile_bytes_match_canonical_hash',
    'upstream_path_public_allowlisted', 'upstream_path_sha256', 'upstream_path_disclosure')


def source_bundle(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('exact official source fixture archive required')
    expected = {value[0] for value in SOURCE_FILES.values()} | {SDK_FILE}
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as handle:
        members = handle.getmembers()
        if len(members) != len(expected) or {item.name for item in members} != expected:
            raise ValueError('exact bounded source member inventory required')
        for item in members:
            if not item.isfile() or item.size > 8_000_000:
                raise ValueError('invalid official source member')
            files[item.name] = handle.extractfile(item).read()
    sources = {}
    for provider, (name, _, _) in SOURCE_FILES.items():
        value = yaml.load(files[name], Loader=OfficialSourceLoader) if name.endswith('.yaml') else loads(files[name])
        if not isinstance(value, dict) or not str(value.get('openapi', '')).startswith('3.'):
            raise ValueError('official source is not OpenAPI 3')
        sources[provider] = value
    return sources, files


def sdk_request_evidence(raw):
    """Read pinned vendor AST only; never execute/import code or load its env."""
    if hashlib.sha256(raw).hexdigest() != SDK_SHA256:
        raise ValueError('pinned official legacy SDK code bytes required')
    module = ast.parse(raw)
    constants = {node.targets[0].id: node.value.value for node in module.body
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                 and isinstance(node.value, ast.Constant)}
    if constants.get('FINANCIAL_DATASETS_API_BASE') != SOURCE_FILES['financial'][2]:
        raise ValueError('official SDK server changed')
    functions = {node.name: node for node in module.body if isinstance(node, ast.AsyncFunctionDef)}
    helper = functions['make_request']
    requests = [node for node in ast.walk(helper) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'client']
    if len(requests) != 1 or requests[0].func.attr != 'get' or not requests[0].args or not isinstance(requests[0].args[0], ast.Name) or requests[0].args[0].id != 'url':
        raise ValueError('official SDK request helper is not exact GET transport')
    result = []
    for name in SDK_FUNCTIONS:
        function = functions[name]
        arguments = function.args.args
        defaults = {arg.arg: ast.literal_eval(value) for arg, value in zip(arguments[-len(function.args.defaults):], function.args.defaults)}
        declared = {arg.arg: {'client_type': arg.annotation.id if isinstance(arg.annotation, ast.Name) else None,
                             'client_required': arg.arg not in defaults,
                             **({'client_default': defaults[arg.arg]} if arg.arg in defaults else {})} for arg in arguments}
        assignments = [node for node in function.body if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'url']
        if len(assignments) != 1 or not isinstance(assignments[0].value, ast.JoinedStr):
            raise ValueError('unsupported SDK request URL expression')
        parts = []
        for child in assignments[0].value.values:
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                parts.append(child.value)
            elif isinstance(child, ast.FormattedValue) and isinstance(child.value, ast.Name) and child.format_spec is None and child.conversion == -1:
                variable = child.value.id
                if variable == 'FINANCIAL_DATASETS_API_BASE':
                    parts.append(SOURCE_FILES['financial'][2])
                elif variable in declared:
                    parts.append('{' + variable + '}')
                else:
                    raise ValueError('unsupported SDK URL variable')
            else:
                raise ValueError('unsupported SDK URL interpolation')
        template = ''.join(parts)
        parsed = urlsplit(template)
        if parsed.scheme + '://' + parsed.netloc != SOURCE_FILES['financial'][2] or parsed.fragment:
            raise ValueError('SDK URL authority changed')
        query = []
        for pair in parsed.query.split('&'):
            key, value = pair.split('=', 1)
            variable = value.removeprefix('{').removesuffix('}')
            if value != '{' + variable + '}' or variable not in declared or not key.isidentifier():
                raise ValueError('unsupported SDK query template')
            query.append({'name': key, **declared[variable]})
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'make_request']
        if len(calls) != 1 or len(calls[0].args) != 1 or not isinstance(calls[0].args[0], ast.Name) or calls[0].args[0].id != 'url':
            raise ValueError('SDK does not invoke the verified request helper unchanged')
        result.append({'function': name, 'method': 'GET', 'literal_upstream_path': parsed.path,
            'query_arguments': query, 'source_url': SDK_URL, 'source_sha256': SDK_SHA256,
            'lifecycle': 'official_legacy_code_last_updated_2025_06_05',
            'provider_constraints_proven': False, 'complete_any_method_set_proven': False,
            'response_schema_proven': False, 'current_provider_support_proven': False})
    return result


def exact_alternative(sources, files, provider, path):
    document = sources[provider]
    matched = upstream_path_item(document, path)
    if not matched:
        raise ValueError('exact alternative absent from official source')
    expected_origin = SOURCE_FILES[provider][2]
    raw_item = document['paths'].get(path)
    if not isinstance(raw_item, dict) or '$ref' in raw_item:
        raise ValueError('alternative must be an exact direct Path Item')
    methods = sorted(set(raw_item) & METHODS)
    if set(methods) != set(matched):
        raise ValueError('alternative complete method inventory changed')
    operations = []
    for method in methods:
        operation = raw_item[method]
        servers = operation.get('servers', raw_item.get('servers', document.get('servers')))
        if not isinstance(servers, list) or not servers:
            raise ValueError('effective official production authority missing')
        origins = set()
        for server in servers:
            if not isinstance(server, dict) or not isinstance(server.get('url'), str) or server.get('variables'):
                raise ValueError('unsupported effective official server')
            uri = urlsplit(server['url'])
            if uri.username or uri.password or uri.query or uri.fragment or uri.path not in ('', '/'):
                raise ValueError('official target has unsupported authority or prefix')
            origins.add(uri.scheme + '://' + uri.netloc)
        allowed = {expected_origin}
        if provider == 'polymarket-clob':
            allowed.add('https://clob-staging.polymarket.com')
        if expected_origin not in origins or not origins <= allowed:
            raise ValueError('official alternative cannot use exact production authority')
        copied = copy.deepcopy(matched[method])
        components = referenced_components(copied, document)
        security = copied.get('security', document.get('security', []))
        for requirement in security:
            for name in requirement:
                scheme = document.get('components', {}).get('securitySchemes', {}).get(name)
                if scheme is None:
                    raise ValueError('official authentication scheme unresolved')
                components.setdefault('securitySchemes', {})[name] = copy.deepcopy(scheme)
        successes = {status: response for status, response in copied.get('responses', {}).items() if str(status).startswith('2')}
        complete = bool(successes) and all(str(status) in {'204', '205'} and not response_object(response, document).get('content')
            or has_response_contract(response_object(response, document)) for status, response in successes.items())
        operations.append({'method': method.upper(), 'official_upstream_operation_id': copied.get('operationId'),
            'operation': copied, 'components': components, 'upstream_security': copy.deepcopy(security),
            'schema_hash': digest({'operation': copied, 'components': components}),
            'complete_success_schema': complete})
    filename, url, _ = SOURCE_FILES[provider]
    return {'provider_key': provider, 'target_path': path, 'production_origin': expected_origin,
            'source_url': url, 'source_raw_sha256': hashlib.sha256(files[filename]).hexdigest(),
            'source_content_hash': digest(document), 'official_method_set': [method.upper() for method in methods],
            'operations': operations, 'current_target_equivalence_proven': False,
            'source_approved': False, 'identity_approved': False}


def current_index(mappings):
    indexed = {}
    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get('rows'), list):
            raise ValueError('current mapping requires explicit rows')
        if any(type(mapping.get(field)) is not int or mapping[field] != 0 for field in ('production_writes', 'profile_compilations', 'profile_rebindings')):
            raise ValueError('current evidence must have no writes or Profile mutations')
        for row in mapping['rows']:
            identity = row.get('endpoint_id') if isinstance(row, dict) else None
            if type(identity) is not int or identity <= 0 or identity in indexed:
                raise ValueError('globally unique positive current endpoint IDs required')
            indexed[identity] = {key: copy.deepcopy(row[key]) for key in CURRENT_FIELDS if key in row}
    return indexed


def prepare(mappings, sources, files):
    indexed = current_index(mappings)
    sdk = sdk_request_evidence(files[SDK_FILE])
    decisions = []
    for identity, provider, old, alternative_provider, alternative_path, code in TARGETS:
        current = indexed.get(identity)
        public_prefix = '/apis/v1/financial' if provider == 'financial' else '/apis/v1/parallel/v1beta/tasks/runs/{run_id}/events' if provider == 'parallel.ai' else '/apis/v1/polymarket'
        expected_public = public_prefix if provider == 'parallel.ai' else public_prefix + old
        if current and (current.get('provider_key') != provider or current.get('public_path') != expected_public or current.get('upstream_path') != old):
            raise ValueError('target/provider/public identity drift; refresh owner decision')
        row = {'endpoint_id': identity, 'provider_key': provider, 'public_path': expected_public,
            'current_upstream_path': old, 'decision_code': code, 'current_evidence': current,
            'current_routing_metadata_verified': False, 'strict_profile_binding_validated': False,
            'approved': False, 'apply_authorized': False, 'executable_mutation_ready': False,
            'owner_decisions': [], 'blocking_gates': ['Independent source and identity review required',
                'Complete current public wire facts and strict immutable Profile binding proof required'],
            'alternative_contract': None}
        if current:
            # New captures prove origin via its independently matched SHA256.
            # An older explicit authority result must still agree when present.
            valid = all(current.get(field) is True for field in ('target_matches_endpoint', 'profile_binding_metadata_matches'))
            valid = valid and ('authority_equal_expected' not in current or current['authority_equal_expected'] is True)
            valid = valid and current.get('target_has_query') is False and current.get('contract_method') == 'ANY'
            valid = valid and current.get('endpoint_status') == 'enabled' and current.get('provider_status') == 'enabled' and current.get('profile_status') == 'verified'
            # Profile revision and compiled contract revision are independent identities.
            valid = valid and all(type(current.get(field)) is int and current[field] > 0
                                  for field in ('profile_revision', 'compiled_contract_revision'))
            valid = valid and current.get('upstream_origin_sha256') == hashlib.sha256(SOURCE_FILES[provider][2].encode()).hexdigest()
            valid = valid and all(isinstance(current.get(key), str) and len(current[key]) == 64 and all(c in '0123456789abcdef' for c in current[key]) for key in ('binding_sha256', 'profile_canonical_sha256', 'profile_contract_sha256', 'target_sha256'))
            valid = valid and isinstance(current.get('profile_key'), str) and bool(current['profile_key'].strip())
            valid = valid and current.get('stored_target_path') == old
            valid = valid and current.get('target_sha256') == hashlib.sha256(old.encode()).hexdigest()
            valid = valid and ('upstream_path_sha256' not in current or
                                  current['upstream_path_sha256'] == hashlib.sha256(old.encode()).hexdigest())
            row['current_routing_metadata_verified'] = valid
        if not row['current_routing_metadata_verified']:
            row['blocking_gates'].append('Complete matching current routing metadata missing or invalid')
        if old in sources[provider]['paths']:
            raise ValueError('old path is now officially declared; reassess instead of proposing migration')
        if alternative_provider:
            row['alternative_contract'] = exact_alternative(sources, files, alternative_provider, alternative_path)
            row['owner_decisions'] = ['Approve intentional target/contract migration after complete current wire comparison',
                'Retain current route only with authoritative exact old-target support contract',
                'Retire current admission through separately approved reversible status change']
            row['blocking_gates'].append('Changing target or provider alone invalidates current immutable Profile; approved new bound Profile and atomic transition required')
            row['proposed_mutation_intent'] = {'public_path': expected_public,
                'forward_target_path': alternative_path, 'rollback_target_path': old,
                'forward_provider_key': alternative_provider, 'rollback_provider_key': provider,
                'old_guard_metadata': current,
                'guard_hash_semantics': {'binding_sha256': 'SHA256 of raw endpoint ConfigJSON bytes',
                    'profile_contract_sha256': 'SHA256 of raw immutable Profile ContractJSON bytes',
                    'target_sha256': 'SHA256 of raw endpoint TargetURI bytes',
                    'provider_config_sha256': 'SHA256 of raw provider ConfigJSON bytes',
                    'profile_canonical_sha256': 'stored canonical contract hash; not recomputed or compiler validated'},
                'new_profile_binding': None,
                'sql_execute_ready': False, 'requires_exact_sql_confirmation': True}
            if provider == 'polymarket-clob':
                row['blocking_gates'].append('Client L2 signature must cover the corrected GET /data path; no credential or signing rewrite performed')
            if identity in {1694, 1702, 2251, 1801}:
                row['blocking_gates'].append('Intentional provider/response/lifecycle compatibility change; equivalence is not established')
            if identity == 1801:
                row['existing_current_ga_endpoint_id'] = 1793
                row['blocking_gates'].append('Old beta route has archived evidence only; current SDK/docs expose GA; no business support probe performed')
        elif identity in {1684, 1685}:
            suffix = '/crypto/prices/' if identity == 1684 else '/crypto/prices/snapshot/'
            row['legacy_sdk_request_evidence'] = [proof for proof in sdk if proof['literal_upstream_path'] == suffix]
            row['literal_sdk_target_equal_current'] = False
            row['owner_decisions'] = ['Retain only after provider confirms exact current crypto path, methods and schemas',
                'Retire unsupported admission through separately approved reversible status change']
            row['blocking_gates'].extend(['Current authoritative OpenAPI excludes crypto; official old MCP code does not prove current support',
                'Trailing-slash alias and complete ANY method set are unproven; SDK defaults are not provider constraints',
                'No authoritative complete crypto response schema'])
        else:
            row['owner_decisions'] = ['Provide an authoritative current exact earnings press-release contract',
                'Retire current admission through separately approved reversible status change']
            row['blocking_gates'].append('No exact declaration in current authoritative spec or inspected official SDK; /earnings and /search are different products')
        decisions.append(row)
    return {'schema_version': 1, 'approval_status': 'UNAPPROVED', 'apply_authorized': False,
        'source_archive_sha256': ARCHIVE_SHA256, 'production_writes': 0, 'profile_compilations': 0,
        'business_api_calls': 0, 'scope': 'Ten finite route owner decisions and seven intentional alternative contracts; not current-target equivalence, publication or mutation approval.',
        'counts': {'route_decisions': len(decisions), 'current_metadata_verified': sum(row['current_routing_metadata_verified'] for row in decisions),
            'intentional_alternative_contracts': sum(row['alternative_contract'] is not None for row in decisions),
            'legacy_crypto_request_shape_evidence': 2, 'exact_current_earnings_press_contracts': 0,
            'approved_routes': 0, 'executable_mutations': 0}, 'decisions': decisions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-map', action='append', type=Path, required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sources, files = source_bundle(root / 'scripts/tests/fixtures/routing-debt-official-sources-20261008.tar.gz')
    report = prepare([loads(path.read_bytes()) for path in args.current_map], sources, files)
    report['current_map_sha256'] = [hashlib.sha256(path.read_bytes()).hexdigest() for path in args.current_map]
    if args.write:
        destination = root / 'docs/routing-debt-resolution-20261008'
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'route-decisions-NOT-APPROVED.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'approval_status': report['approval_status'], 'counts': report['counts'], 'report_written': args.write}))


if __name__ == '__main__':
    main()

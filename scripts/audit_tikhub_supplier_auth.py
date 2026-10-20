#!/usr/bin/env python3
"""Review TikHub auth from a pinned official SDK without replacing request sources."""
import argparse
import ast
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_supplier_auth import audit, check_security
from runtime_registry import combine_facts

SDK_REVISION = '1ede56bcc53f8c037744cbe2b70c93541b5cf840'
SPEC_SHA256 = '908b21213eeb9466c155971fce9ac4841bc57108d5f748406285f13573e71b9c'
CLIENT_SHA256 = '73c3722b674bc464b1bd1815c1d8ad854b4a92f56083ceb79a851c15b879a154'


def apply_supplement(base, transports, runtime_targets, spec_path, client_path):
    raw_spec, raw_client = spec_path.read_bytes(), client_path.read_bytes()
    if hashlib.sha256(raw_spec).hexdigest() != SPEC_SHA256 or hashlib.sha256(raw_client).hexdigest() != CLIENT_SHA256:
        raise ValueError('pinned official SDK bytes differ')
    # Inspect constants; never execute downloaded supplier code.
    origins = [node.value.value for node in ast.parse(raw_client).body
               if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
               and isinstance(node.value.value, str)
               and any(isinstance(target, ast.Name) and target.id == 'DEFAULT_BASE_URL' for target in node.targets)]
    if origins != ['https://api.tikhub.io']:
        raise ValueError('reviewed SDK origin differs')
    spec = json.loads(raw_spec)
    if spec.get('servers'):
        raise ValueError('SDK now declares servers; source review required')
    spec['servers'] = [{'url': origins[0]}]
    report = copy.deepcopy(base)
    selected, matched, missing = [], 0, 0
    for row in report['rows']:
        if row['provider'] != 'tikhub':
            continue
        if row['status'] != 'public_aisa_source_not_supplier_auth_authority':
            selected.append(row)
            continue
        path = row['path']
        if not path.startswith('/apis/v1/tikhub/'):
            raise ValueError('unexpected TikHub public path')
        supplier_path = path.replace('/apis/v1/tikhub', '/api/v1', 1)
        if runtime_targets.get((path, row['method'])) != supplier_path:
            raise ValueError('Runtime upstream target differs from reviewed supplier route')
        op = spec.get('paths', {}).get(supplier_path, {}).get(row['method'].lower())
        row['base_supplier_auth_status'] = row['status']
        if op is None:
            row['status'] = 'supplier_operation_unavailable_in_pinned_primary'
            missing += 1
        else:
            row.update(check_security(spec, op, transports.get(row['runtime_operation_id'])))
            matched += 1
        row['primary_auth_supplement'] = 'fixed_official_SDK_security_and_client_origin'
        selected.append(row)
    if not selected:
        raise ValueError('TikHub scope unavailable')
    counts = Counter(r['status'] for r in report['rows'])
    blocked = [r for r in report['rows'] if r['status'] == 'blocked_auth_transport']
    reviewed = {'transport_shape_compatible_key_validity_unverified', 'supplier_declares_unauthenticated_alternative'}
    report.update(status='blocked' if blocked else 'incomplete_not_business_validation' if set(counts) - reviewed else 'structural_checks_passed', counts=dict(counts), blocked_method_operations=len(blocked), blocked_runtime_parents=len({r['runtime_operation_id'] for r in blocked}))
    report['primary_supplement'] = {
        'supplier': 'tikhub', 'SDK_revision': SDK_REVISION,
        'spec_sha256': SPEC_SHA256, 'client_sha256': CLIENT_SHA256,
        'source_urls': ['https://raw.githubusercontent.com/TikHub/TikHub-API-Python-SDK/' + SDK_REVISION + '/' + path for path in ['spec/openapi.json', 'src/tikhub/_base_client.py']],
        'origin_basis': 'DEFAULT_BASE_URL constant from pinned official client; configured origin compared by hash',
        'Runtime_upstream_targets_verified': True,
        'method_operations': len(selected), 'primary_operations_matched': matched, 'primary_operations_missing': missing,
        'counts': dict(Counter(r['status'] for r in selected)),
        'request_schema_authority_replaced': False, 'credential_validity_or_provider_business_success': 'NOT_TESTED',
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'runtime-dir', 'metadata', 'credential-formats', 'primary-spec', 'primary-client', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    base = audit(args.root, args.runtime_dir, args.metadata, args.credential_formats)
    metadata, formats = json.loads(args.metadata.read_text()), json.loads(args.credential_formats.read_text())
    by_id = {r['provider_id']: r for r in formats['providers']}
    transports = {endpoint['operation_id']: {**provider, **by_id[provider['provider_id']], **endpoint, 'endpoints': None}
                  for provider in metadata['providers'] for endpoint in provider['endpoints']}
    facts = combine_facts({'tikhub': json.loads((args.runtime_dir / 'tikhub.json').read_text())}, 'tikhub')
    prefix = urlsplit(facts['servers'][0]['url']).path.rstrip('/')
    targets = {(prefix + path, method.upper()): op.get('x-aisa-upstream-path')
               for path, item in facts['paths'].items() for method, op in item.items()
               if method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}}
    result = apply_supplement(base, transports, targets, args.primary_spec, args.primary_client)
    result['effective_checker_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k in {'status', 'counts', 'blocked_method_operations', 'primary_supplement'}}))
    return 0 if result['status'] == 'structural_checks_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check supplier security groups against read-only transport metadata.

This is an independent acceptance gate, not a credential validator. A historical
AISA request mirror cannot establish supplier authentication. No credentials,
provider hosts or private configuration values belong in the metadata input.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from canonical_import import configured_inputs
from compose_openapi import (METHODS, apply_upstream_selector, effective_object,
                             effective_public_operation, resolve,
                             select_upstream_operations)
from runtime_registry import combine_facts, public_mirror_index, runtime_metadata_mirrors


def transport_field(location, name):
    return location, name.lower() if location == 'header' else name


def check_security(document, operation, transport):
    groups = operation.get('security', document.get('security'))
    if groups is None:
        return {'status': 'supplier_auth_not_declared'}
    if not isinstance(groups, list) or any(not isinstance(g, dict) for g in groups):
        raise ValueError('invalid supplier security requirement')
    if not groups or {} in groups:
        return {'status': 'supplier_declares_unauthenticated_alternative'}
    if transport is None:
        return {'status': 'transport_metadata_unverified'}
    available = {transport_field('header', n) for n in transport.get('fixed_header_names') or []}
    location = transport['auth_location'] or 'header'
    name = transport['auth_name'] or transport['auth_header'] or 'Authorization'
    if transport['credential_configured'] and location in {'header', 'query'}:
        available.add(transport_field(location, name))
    attempts = []
    for group in groups:
        expected, unsupported, formats = [], [], []
        for scheme, scopes in group.items():
            definition = resolve(document.get('components', {}).get('securitySchemes', {}).get(scheme, {}),
                                 document, preserve_recursive=True)
            kind = definition.get('type')
            if kind == 'apiKey':
                loc, field = definition.get('in'), definition.get('name')
                if not isinstance(field, str) or not field or loc not in {'header', 'query', 'cookie'}:
                    unsupported.append(scheme)
                    continue
                expected.append(transport_field(loc, field))
                if any(word in field.lower() for word in ('signature', 'timestamp', 'nonce')):
                    unsupported.append('dynamic_auth_generation_unverified:' + field)
            elif kind == 'http' and definition.get('scheme', '').lower() == 'bearer':
                expected.append(('header', 'authorization'))
                if not (location == 'header' and name.lower() == 'authorization'
                        and transport['credential_configured']
                        and (transport.get('credential_scheme') == 'bearer'
                             or transport.get('credential_format') == 'bearer_prefixed')):
                    formats.append('bearer_prefix_unverified')
                # bearerFormat is a documentation hint, not a schema constraint.
                # Inspecting the prefix proves no token validity or JWT signature.
            elif kind == 'http' and definition.get('scheme', '').lower() == 'basic':
                expected.append(('header', 'authorization'))
                if not (location == 'header' and name.lower() == 'authorization'
                        and transport['credential_configured']
                        and not transport.get('credential_scheme')
                        and transport.get('credential_format') == 'basic_prefixed'):
                    formats.append('basic_encoding_unverified')
            else:
                # A header name alone does not prove OAuth scopes, Basic's value
                # encoding, an OpenID flow or any unsupported signer.
                unsupported.append(scheme)
            if scopes:
                unsupported.append('security_scopes_unverified:' + scheme)
        missing = [dict(zip(('in', 'name'), field)) for field in expected if field not in available]
        attempts.append({'required_transport_fields': [dict(zip(('in', 'name'), f)) for f in expected],
                         'missing_transport_fields': missing, 'unsupported': unsupported,
                         'value_format_unverified': formats})
    servers = operation.get('servers', document.get('servers', []))
    origin_verified = any(hashlib.sha256(str(s.get('url', '')).rstrip('/').lower().encode()).hexdigest()
                          == transport['base_url_sha256'] for s in servers)
    if not origin_verified:
        status = 'auth_transport_origin_unverified'
    elif any(not a['missing_transport_fields'] and not a['unsupported']
             and not a['value_format_unverified'] for a in attempts):
        status = 'transport_shape_compatible_key_validity_unverified'
    elif all(a['missing_transport_fields'] for a in attempts):
        status = 'blocked_auth_transport'
    else:
        status = 'auth_scheme_or_value_unverified'
    return {'status': status, 'alternatives': attempts,
            'provider_id': transport['provider_id'], 'documented_server_binding_verified': origin_verified,
            'configured_auth_location': location, 'configured_auth_name': name,
            'configured_scheme': transport['credential_scheme'],
            'credential_configured': bool(transport['credential_configured'])}


def audit_provider(provider, facts, upstream, mirrors, bindings, transports):
    sources = upstream if isinstance(upstream, list) else ([upstream] if upstream else [])
    mirrors = runtime_metadata_mirrors(facts, upstream, mirrors)
    prefix = urlsplit((facts.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    rows = []
    for path, raw_item in sorted(facts['paths'].items()):
        item = effective_object(raw_item, facts)
        for method, raw in sorted(item.items()):
            if method not in METHODS and method != 'x-aisa-any':
                continue
            runtime = effective_public_operation(item, raw, facts)
            if runtime.get('x-aisa-status') != 'enabled':
                continue
            base = dict(provider=provider, path=prefix + path, runtime_operation_id=runtime['operationId'])
            if runtime.get('x-aisa-validation') == 'runtime':
                rows.append(dict(base, method=method.upper(), status='runtime_owned_auth_review_separate'))
                continue
            try:
                candidates = [d for d in sources if not d.get('info', {}).get('x-aisa-source', {}).get('response_only')]
                bound = bindings.get(prefix + path)
                if bound:
                    candidates = [d for d in candidates if d['info']['x-aisa-source']['url'] == bound]
                    if len(candidates) != 1:
                        raise ValueError('source binding must select exactly one source')
                selected = select_upstream_operations(candidates, runtime.get('x-aisa-upstream-path'),
                                                      runtime.get('x-aisa-upstream-selector'))
                if bound and not selected:
                    raise ValueError('bound source operation unavailable')
                methods = [method] if method != 'x-aisa-any' else sorted(
                    set(selected) & METHODS | {m for (p, m), v in mirrors.items()
                                              if p == prefix + path and not v.get('response_only')})
                if not methods:
                    raise ValueError('source operation unavailable')
                for actual in methods:
                    if actual in selected:
                        document, op = selected[actual]
                        op = apply_upstream_selector(op, runtime.get('x-aisa-upstream-selector'))
                        public_source = document.get('info', {}).get('x-aisa-source', {}).get('path_space') == 'public'
                        result = ({'status': 'public_aisa_source_not_supplier_auth_authority'} if public_source else
                                  check_security(document, op, transports.get(runtime['operationId'])))
                    else:
                        value = mirrors.get((prefix + path, actual), {})
                        if not value or value.get('response_only') or value.get('operation', {}).get('x-aisa-mirror-error'):
                            raise ValueError('source operation unavailable')
                        result = {'status': ('runtime_metadata_not_supplier_auth_authority'
                                  if value.get('source', {}).get('kind') == 'runtime_metadata'
                                  else 'public_aisa_source_not_supplier_auth_authority')}
                    rows.append(dict(base, method=actual.upper(), **result))
            except (ValueError, KeyError, TypeError) as exc:
                rows.append(dict(base, method='ANY' if method == 'x-aisa-any' else method.upper(),
                                 status='supplier_auth_source_unverified', reason=str(exc)))
    return rows


def audit(root, runtime_dir, metadata_path, formats_path=None):
    metadata = json.loads(metadata_path.read_text())
    if metadata['current_before'] != metadata['current_after']:
        raise ValueError('transport read crossed Runtime releases')
    current = json.loads((runtime_dir / 'current-after.json').read_text())
    if any(current[k] != v for k, v in metadata['current_after'].items()):
        raise ValueError('transport metadata and Runtime release differ')
    formats = {}
    if formats_path:
        inspection = json.loads(formats_path.read_text())
        if inspection['current_before'] != metadata['current_after'] or inspection['current_after'] != metadata['current_after']:
            raise ValueError('credential format inspection and Runtime release differ')
        for row in inspection['providers']:
            if row['provider_id'] in formats:
                raise ValueError('ambiguous credential format identity')
            formats[row['provider_id']] = row
        if set(formats) != {p['provider_id'] for p in metadata['providers']}:
            raise ValueError('credential format inspection provider set differs')
    transports = {}
    for provider in metadata['providers']:
        for endpoint in provider['endpoints']:
            identity = endpoint['operation_id']
            if identity in transports:
                raise ValueError('ambiguous Runtime transport identity')
            transports[identity] = {**provider, **formats.get(provider['provider_id'], {}), **endpoint, 'endpoints': None}
    registry = yaml.safe_load((root / 'openapi/registry.yaml').read_text())
    mirrors, rows, hashes = public_mirror_index(root), [], {}
    for provider, config in sorted(registry['providers'].items()):
        config = config or {}
        documents = {}
        for name in config.get('group', [provider]):
            path = runtime_dir / (name + '.json')
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            documents[name] = json.loads(path.read_text())
        upstream, bindings = configured_inputs(root, provider, config)
        rows.extend(audit_provider(provider, combine_facts(documents, provider), upstream, mirrors, bindings, transports))
    blocked = [r for r in rows if r['status'] == 'blocked_auth_transport']
    reviewed_statuses = {'transport_shape_compatible_key_validity_unverified',
                         'supplier_declares_unauthenticated_alternative'}
    incomplete = [r for r in rows if r['status'] not in reviewed_statuses and r['status'] != 'blocked_auth_transport']
    return {'status': 'blocked' if blocked else ('incomplete_not_business_validation' if incomplete else 'structural_checks_passed'),
            'scope': 'Supplier security declarations versus stored transport; no credential or business success claim',
            'current': metadata['current_after'], 'counts': dict(Counter(r['status'] for r in rows)),
            'blocked_method_operations': len(blocked),
            'blocked_runtime_parents': len({r['runtime_operation_id'] for r in blocked}),
            'metadata_sha256': hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            'credential_formats_sha256': hashlib.sha256(formats_path.read_bytes()).hexdigest() if formats_path else None,
            'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'runtime_files_sha256': hashes,
            'source_files_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in [root / 'openapi/registry.yaml', *sorted((root / 'openapi/upstream').glob('*.json'))]},
            'production_writes': 0, 'provider_calls': 0, 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'runtime-dir', 'metadata', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--credential-formats', type=Path)
    args = parser.parse_args()
    result = audit(args.root, args.runtime_dir, args.metadata, args.credential_formats)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in
                      {'rows', 'source_files_sha256', 'runtime_files_sha256'}}))
    return 0 if result['status'] == 'structural_checks_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

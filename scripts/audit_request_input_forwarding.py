#!/usr/bin/env python3
"""Audit source query inputs against Runtime forwarding, independently of consumers.

This offline check does not change composition or approve existing debt. A
consumer equality check cannot substitute for this result. Missing source
declarations are reported separately and never counted as verified inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from canonical_import import configured_inputs
from compose_openapi import (METHODS, apply_upstream_selector,
                             effective_object, effective_public_operation, resolve,
                             select_upstream_operations)
from runtime_registry import combine_facts, public_mirror_index, runtime_metadata_mirrors


def missing_query_inputs(runtime, source, document, auth_names=()):
    """Optional and required caller inputs both need an explicit forwarding path."""
    if runtime.get('x-aisa-query-policy', {}).get('request_wins') is True:
        return []
    declared = {p['name'] for p in runtime.get('parameters', []) if p.get('in') == 'query'}
    auth = {'authorization', 'x-api-key', 'api-key', *(name.lower() for name in auth_names)}
    return sorted({p['name'] for raw in source.get('parameters', [])
                   for p in [resolve(raw, document, preserve_recursive=True)]
                   if p.get('in') == 'query' and p['name'].lower() not in auth
                   and p['name'] not in declared})


def missing_header_inputs(runtime, source, document, auth_names=()):
    """Generic relay headers need an explicit caller-value forwarding contract.

    Typed request fields describe validation, not transport. Only the Runtime
    caller-header allowlist proves generic forwarding; Accept is the existing
    generic executor exception. Runtime-owned handlers are assessed separately.
    """
    declared = runtime.get('x-aisa-caller-headers', [])
    if not isinstance(declared, list) or not all(isinstance(name, str) for name in declared):
        raise ValueError('invalid Runtime caller-header forwarding declaration')
    forwarded = {'accept', *(name.lower() for name in declared)}
    consumed_auth = {'authorization', 'x-api-key', 'api-key', *(name.lower() for name in auth_names)}
    return sorted({p['name'] for raw in source.get('parameters', [])
                   for p in [resolve(raw, document, preserve_recursive=True)]
                   if p.get('in') == 'header' and p['name'].lower() not in forwarded | consumed_auth})


def audit_provider(provider, facts, upstream, mirrors, bindings, include_headers=False):
    sources = upstream if isinstance(upstream, list) else ([upstream] if upstream else [])
    mirrors = runtime_metadata_mirrors(facts, upstream, mirrors)
    prefix = urlsplit((facts.get('servers') or [{'url': ''}])[0]['url']).path.rstrip('/')
    auth = [scheme['name'] for doc in sources
            for scheme in doc.get('components', {}).get('securitySchemes', {}).values()
            if scheme.get('name')]
    rows = []
    for path, raw_item in sorted(facts['paths'].items()):
        item = effective_object(raw_item, facts)
        for method, raw in sorted(item.items()):
            if method not in METHODS and method != 'x-aisa-any':
                continue
            runtime = effective_public_operation(item, raw, facts)
            base = dict(provider=provider, path=prefix + path,
                        runtime_operation_id=runtime['operationId'],
                        runtime_status=runtime.get('x-aisa-status'))
            if runtime.get('x-aisa-validation') == 'runtime':
                rows.append(dict(base, method=method.upper(), status='runtime_owned'))
                continue
            try:
                candidates = [doc for doc in sources if not doc.get('info', {}).get('x-aisa-source', {}).get('response_only')]
                bound = bindings.get(prefix + path)
                if bound:
                    candidates = [doc for doc in candidates if doc['info']['x-aisa-source']['url'] == bound]
                    if len(candidates) != 1:
                        raise ValueError('source binding must select exactly one source')
                selected = select_upstream_operations(candidates, runtime.get('x-aisa-upstream-path'), runtime.get('x-aisa-upstream-selector'))
                if bound and not selected:
                    raise ValueError('bound source operation unavailable')
                methods = [method] if method != 'x-aisa-any' else sorted(
                    set(selected) & METHODS | {m for (p, m), value in mirrors.items()
                                              if p == prefix + path and not value.get('response_only')})
                if not methods:
                    raise ValueError('source operation unavailable')
                for actual in methods:
                    if actual in selected:
                        document, source = selected[actual]
                        source = apply_upstream_selector(source, runtime.get('x-aisa-upstream-selector'))
                    else:
                        value = mirrors.get((prefix + path, actual), {})
                        if not value or value.get('response_only') or value.get('operation', {}).get('x-aisa-mirror-error'):
                            raise ValueError('source operation unavailable')
                        document = {'openapi': value.get('openapi', '3.1.0'), 'components': value.get('components', {})}
                        source = value['operation']
                    missing = missing_query_inputs(runtime, source, document, auth)
                    headers = missing_header_inputs(runtime, source, document, auth) if include_headers else []
                    rows.append(dict(base, method=actual.upper(), status='blocked' if missing or headers else 'passed',
                                     missing_query_inputs=missing,
                                     **({'missing_header_inputs': headers} if include_headers else {})))
            except (ValueError, KeyError, TypeError) as exc:
                rows.append(dict(base, method='ANY' if method == 'x-aisa-any' else method.upper(),
                                 status='source_unverified', reason=str(exc)))
    return rows


def audit(root, runtime_dir, include_headers=False):
    registry = yaml.safe_load((root / 'openapi/registry.yaml').read_text())
    mirrors = public_mirror_index(root)
    rows, bindings = [], {}
    for provider, config in sorted(registry['providers'].items()):
        config = config or {}
        catalogs = config.get('group', [provider])
        documents = {}
        for name in catalogs:
            path = runtime_dir / (name + '.json')
            bindings[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            documents[name] = json.loads(path.read_bytes())
        upstream, source_bindings = configured_inputs(root, provider, config)
        rows.extend(audit_provider(provider, combine_facts(documents, provider), upstream, mirrors, source_bindings, include_headers))
    blocked = [r for r in rows if r['status'] == 'blocked']
    unverified = [r for r in rows if r['status'] == 'source_unverified']
    return {'status': 'blocked' if blocked or unverified else 'passed',
            'scope': 'Offline source-to-Runtime query forwarding' + (' and generic caller-header forwarding' if include_headers else '') + '; no provider execution or live freshness assertion',
            'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source_files_sha256': {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in [root / 'openapi/registry.yaml', *sorted((root / 'openapi/upstream').glob('*.json'))]},
            'runtime_files_sha256': bindings, 'operations': len(rows),
            'blocked_operations': len(blocked),
            'missing_query_occurrences': sum(len(r['missing_query_inputs']) for r in blocked),
            **({'missing_header_occurrences': sum(len(r.get('missing_header_inputs', [])) for r in blocked)} if include_headers else {}),
            'source_unverified_operations': len(unverified), 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-headers', action='store_true', help='Also require declared generic caller-header forwarding; Runtime-owned handlers remain separate')
    args = parser.parse_args()
    result = audit(args.root, args.runtime_dir, args.include_headers)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in {'rows', 'runtime_files_sha256', 'source_files_sha256'}}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

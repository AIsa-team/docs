"""Per-operation source/response debt evidence; no approval or execution policy."""
import copy
import re
from urllib.parse import urlsplit

try:
    from .compose_openapi import (METHODS, digest, has_response_contract, referenced_components,
                                 response_object, select_upstream_operations, upstream_path_item, map_contract_children, effective_public_operation)
    from .contract_readiness import _schema_contract, binding_hash, reason_code
except ImportError:
    from compose_openapi import (METHODS, digest, has_response_contract, referenced_components,
                                response_object, select_upstream_operations, upstream_path_item, map_contract_children, effective_public_operation)
    from contract_readiness import _schema_contract, binding_hash, reason_code


def declaration_evidence(operation, document, fields):
    """Only the selected declarations and reachable definitions, not whole source."""
    fragment = {key: operation[key] for key in fields if key in operation}
    value = {'declaration': _schema_contract(fragment), 'openapi': document.get('openapi')}
    try:
        value['components'] = _schema_contract(referenced_components(fragment, document))
    except (KeyError, ValueError, TypeError):
        # Keep the actual dangling declaration rather than grant a blank
        # fingerprint. Repairing/changing its local target invalidates debt.
        value['unresolved'] = True
        value['available_components'] = available_targets(fragment, document)
    return value


def available_targets(fragment, document):
    """Finite local graph, also recording missing targets for broken sources."""
    seen, targets = set(), {}
    def walk(node):
        if isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, dict):
            ref = node.get('$ref')
            if isinstance(ref, str) and ref not in seen:
                seen.add(ref)
                if ref.startswith('#/'):
                    value = document
                    try:
                        for part in ref[2:].split('/'):
                            value = value[part.replace('~1', '/').replace('~0', '~')]
                        targets[ref] = _schema_contract(value)
                        walk(value)
                    except (KeyError, TypeError):
                        targets[ref] = {'missing_target': True}
                else:
                    targets[ref] = {'external_target': True}
            map_contract_children(node, walk)
    walk(fragment)
    return targets


def source_binding_evidence(fact, facts, sources, mirrors, public_path, method, source_bindings=None, response=False):
    sources = sources if isinstance(sources, list) else ([sources] if sources else [])
    selected_url = (source_bindings or {}).get(public_path)
    selected_sources = [s for s in sources if not selected_url or s.get('info', {}).get('x-aisa-source', {}).get('url') == selected_url]
    value = {'runtime_binding': binding_hash(fact, facts), 'selected_url': selected_url,
             'upstream_path': fact.get('x-aisa-upstream-path'), 'selector': fact.get('x-aisa-upstream-selector')}
    ambiguous_candidates = []
    try:
        selected = select_upstream_operations(selected_sources, fact.get('x-aisa-upstream-path'), fact.get('x-aisa-upstream-selector'))
    except (ValueError, TypeError, KeyError) as exc:
        selected = {}
        value['selection_failure'] = reason_code(str(exc))
        # Ambiguity is debt too: record every candidate bound to this path,
        # rather than a whole-source hash or just the unchanged error string.
        for source in selected_sources:
            # Split path candidates when even one source contains conflicting
            # effective paths. Keep component resolution against the original.
            for path, item in source.get('paths', {}).items():
                scoped = {**source, 'paths': {path: item}}
                try:
                    candidates = upstream_path_item(scoped, fact.get('x-aisa-upstream-path'))
                except (ValueError, KeyError, TypeError):
                    if path == fact.get('x-aisa-upstream-path'):
                        candidates = {m: op for m, op in item.items() if m in METHODS and isinstance(op, dict)}
                    else:
                        candidates = {}
                ambiguous_candidates.extend((source, candidate, op) for candidate, op in candidates.items())
    methods = sorted(set(selected) | {m for p, m in mirrors if p == public_path}) if method.lower() == 'any' else [method.lower()]
    declarations = []
    def relevant(op, doc, public=False):
        if not response:
            return op, ('parameters', 'requestBody')
        if public:
            return op, ('responses',)
        # Composition imports supplier success payloads, never private errors.
        payloads = {}
        for status, raw in op.get('responses', {}).items():
            if not re.fullmatch(r'2(?:[0-9]{2}|XX)', str(status)):
                continue
            try:
                value = response_object(raw, doc)
                payloads[str(status)] = {key: value[key] for key in ('content', 'x-aisa-no-content') if key in value}
            except (ValueError, TypeError, KeyError):
                payloads[str(status)] = raw
        return {'responses': payloads}, ('responses',)
    if ambiguous_candidates:
        value['candidates'] = []
        for source, candidate, op in ambiguous_candidates:
            fragment, fields = relevant(op, source)
            metadata = source.get('info', {}).get('x-aisa-source', {})
            value['candidates'].append({'method': candidate, 'authority': metadata.get('url'),
                'kind': metadata.get('kind'), 'policy_revision': metadata.get('policy_revision'),
                **declaration_evidence(fragment, source, fields)})
        value['candidates'].sort(key=digest)
    for candidate in methods:
        if candidate in selected:
            source_doc, operation = selected[candidate]
            fragment, fields = relevant(operation, source_doc)
            source = source_doc.get('info', {}).get('x-aisa-source', {})
            declarations.append({'method': candidate, 'authority': source.get('url'),
                'kind': source.get('kind'), 'policy_revision': source.get('policy_revision'),
                **declaration_evidence(fragment, source_doc, fields)})
        elif (public_path, candidate) in mirrors:
            entry = mirrors[(public_path, candidate)]
            source = entry.get('source', {})
            fragment = {**entry.get('operation', {}), **entry.get('response_operation', {})}
            doc = {'openapi': entry.get('openapi'), 'components': {}}
            for name in ('components', 'response_components'):
                for section, definitions in entry.get(name, {}).items():
                    doc['components'].setdefault(section, {}).update(definitions)
            fragment, fields = relevant(fragment, doc, public=True)
            declarations.append({'method': candidate, 'authority': source.get('url'),
                'kind': source.get('kind'), 'policy_revision': source.get('policy_revision'),
                **declaration_evidence(fragment, doc, fields)})
    value['declarations'] = declarations
    return digest(value)


def enrich_coverage(rows, facts, upstream, mirrors, source_bindings=None):
    prefix = urlsplit((facts.get('servers') or [{'url': ''}])[0].get('url', '')).path.rstrip('/')
    for row in rows:
        item = facts['paths'].get(row['path'].removeprefix(prefix), {})
        fact = item.get(row['method'].lower(), item.get('x-aisa-any', {}))
        effective = effective_public_operation(item, fact, facts)
        row['source_binding_hash'] = source_binding_evidence(effective, facts, upstream, mirrors,
            row['path'], row['method'], source_bindings)
        row['response_source_binding_hash'] = source_binding_evidence(effective, facts, upstream, mirrors,
            row['path'], row['method'], source_bindings, response=True)
    return rows


def response_gap_rows(document, facts, coverage_rows):
    by_route = {(row['path'], row['method'].lower()): row for row in coverage_rows}
    prefix = urlsplit((document.get('servers') or [{'url': ''}])[0].get('url', '')).path.rstrip('/')
    fact_prefix = urlsplit((facts.get('servers') or [{'url': ''}])[0].get('url', '')).path.rstrip('/')
    gaps = []
    for path, item in document.get('paths', {}).items():
        for method, operation in item.items():
            if method not in METHODS or operation.get('x-aisa-contract-pending'):
                continue
            missing, unresolved = [], False
            for status, raw in operation.get('responses', {}).items():
                if not re.fullmatch(r'2(?:[0-9]{2}|XX)', str(status)):
                    continue
                try:
                    response = response_object(raw, document)
                    if str(status) in {'204', '205'} and not response.get('content'):
                        continue
                    if not has_response_contract(response):
                        missing.append(str(status))
                except (ValueError, TypeError, KeyError):
                    missing.append(str(status))
                    unresolved = True
            declared = operation.get('x-aisa-response-pending', {})
            if not missing and not declared:
                continue
            public = prefix + path
            coverage = by_route.get((public, method), by_route.get((public, 'any'), {}))
            fact_item = facts.get('paths', {}).get(public.removeprefix(fact_prefix), {})
            fact = fact_item.get(method, fact_item.get('x-aisa-any', {}))
            gaps.append({'operation_id': operation.get('operationId'), 'path': public, 'method': method.upper(),
                'statuses': sorted(missing or declared.get('statuses', [])),
                'reason_code': 'unresolved_response_reference' if unresolved else ('response_conversion_gap' if declared.get('reason') and not missing else 'missing_success_payload'),
                'binding_hash': coverage.get('binding_hash') or binding_hash(fact, facts),
                'source_binding_hash': coverage.get('source_binding_hash'),
                'response_source_binding_hash': coverage.get('response_source_binding_hash'),
                'response_binding_hash': digest(declaration_evidence(operation, document, ('responses',))),
                'runtime_status': operation.get('x-aisa-status')})
    return gaps


def gap_key(row):
    required = ('operation_id', 'path', 'method', 'reason_code', 'binding_hash', 'source_binding_hash', 'response_source_binding_hash', 'response_binding_hash')
    if any(not row.get(key) for key in required):
        return None
    return tuple(str(row[key]).upper() if key == 'method' else row[key] for key in required) + (tuple(sorted(row.get('statuses', []))), row.get('runtime_status'))


def assess_response_gaps(report, facts, documents, coverage, baseline):
    """Separate response debt from request completeness, exact identity comparison."""
    if coverage.get('schema_version') != 2:
        return  # Legacy unit inputs; staged publication always uses version 2.
    for provider, result in report['providers'].items():
        current = response_gap_rows(documents.get(provider, {}), facts.get(provider, {}), coverage['providers'].get(provider, []))
        declared = coverage.get('response_gaps', {}).get(provider)
        result.update(new_response_pending=[], existing_response_pending=[])
        if declared != current:
            result['errors'].append({'code': 'response_gap_accounting_mismatch', 'provider': provider})
        approved = {gap_key(row) for row in (baseline or {}).get('response_gaps', {}).get(provider, [])} - {None}
        for row in current:
            result['existing_response_pending' if gap_key(row) in approved else 'new_response_pending'].append(row)
        if result['errors'] or result['new_response_pending']:
            result['status'] = report['status'] = 'failed'
            if provider not in report['blocked_providers']:
                report['blocked_providers'].append(provider)

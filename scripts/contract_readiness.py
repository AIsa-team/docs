"""Pure publication assessment; never fetches, writes, or changes execution policy.

The caller supplies an independently reviewed baseline. A candidate's embedded
baseline/approval fields have no authority. Retained rows require explicit
publication_state='retained'; they do not prove fresh composition.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

METHODS = frozenset(('get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'))

# Reuse the composer's local-only reference and wire-default rules. These
# helpers perform no fetching and keep provider auth/merge policy out of here.
try:
    from .compose_openapi import merge_body, parameter_wire_default, referenced_components, resolve, effective_public_operation
except ImportError:  # CLI imports scripts directly on sys.path.
    from compose_openapi import merge_body, parameter_wire_default, referenced_components, resolve, effective_public_operation


def _schema_contract(value, link=False):
    """Ignore schema prose, without dropping properties named 'description'."""
    if isinstance(value, list):
        return [_schema_contract(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key in {'description', 'title', 'example', 'examples', '$comment', 'deprecated'}:
            continue
        if key == 'links' and isinstance(child, dict):
            result[key] = {name: _schema_contract(definition, link=True) for name, definition in child.items()}
        elif key in {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas', 'dependentRequired',
                   'schemas', 'responses', 'headers', 'requestBodies', 'securitySchemes', 'content', 'links',
                   'callbacks', 'webhooks', 'mapping'} and isinstance(child, dict):
            result[key] = {name: _schema_contract(schema) for name, schema in child.items()}
        elif key in {'const', 'default', 'enum', 'security'} or (link and key in {'parameters', 'requestBody'}):
            # Instance data is not a schema; its property names are literal.
            result[key] = child
        elif key == 'required' and isinstance(child, list) and all(isinstance(name, str) for name in child):
            result[key] = sorted(set(child))
        else:
            result[key] = _schema_contract(child)
    return result


def _parameter_contract(parameter, document):
    resolved = resolve(parameter, document, preserve_recursive=True)
    if not isinstance(resolved, dict) or not resolved.get('name') or resolved.get('in') not in {'query', 'path', 'header', 'cookie'}:
        raise ValueError('invalid runtime parameter declaration')
    resolved = parameter_wire_default(resolved)
    location = resolved['in']
    style = resolved.get('style', 'form' if location in {'query', 'cookie'} else 'simple')
    contract = {'required': resolved.get('required', False), 'style': style,
                'explode': resolved.get('explode', style == 'form'),
                'allowReserved': resolved.get('allowReserved', False),
                'allowEmptyValue': resolved.get('allowEmptyValue', False)}
    if 'schema' in resolved:
        contract['schema'] = _schema_contract(resolved['schema'])
    if 'content' in resolved:
        contract['content'] = {
            media_type: {'schema': _schema_contract(media.get('schema')),
                         **({'encoding': media['encoding']} if 'encoding' in media else {})}
            for media_type, media in resolved['content'].items()}
    if 'schema' not in contract and 'content' not in contract:
        raise ValueError('runtime parameter has no declared schema/content')
    return (location, resolved['name']), contract


def _runtime_parameter_errors(fact, facts_document, operation, document):
    errors = []
    try:
        # Path-level parameters precede operation-level overrides in _operations.
        required = dict(_parameter_contract(p, facts_document) for p in fact.get('parameters', []))
        actual = dict(_parameter_contract(p, document) for p in operation.get('parameters', []))
    except (ValueError, KeyError, TypeError) as exc:
        return [('unresolved_parameter_declaration', str(exc))]
    for key, contract in required.items():
        if key not in actual:
            errors.append(('missing_runtime_parameter', ':'.join(key)))
        elif contract != actual[key]:
            errors.append(('runtime_parameter_contract_mismatch', ':'.join(key)))
    return errors


def _body_contract(body):
    """Compare request semantics, excluding body/media prose and examples."""
    if not isinstance(body, dict) or not isinstance(body.get('content'), dict) or not body['content']:
        raise ValueError('request body has no declared content')
    content = {}
    for media_type, media in body['content'].items():
        if not isinstance(media, dict) or 'schema' not in media:
            raise ValueError('request body media has no declared schema')
        content[media_type] = {'schema': _schema_contract(media['schema'])}
        if 'encoding' in media:
            content[media_type]['encoding'] = media['encoding']
    return {'required': body.get('required', False), 'content': content}


def _runtime_body_errors(fact, facts_document, operation, document):
    runtime_body = fact.get('requestBody')
    if runtime_body is None:
        return []  # Provider-owned bodies have no runtime field declaration.
    if operation.get('requestBody') is None:
        return [('missing_runtime_request_body', None)]
    try:
        runtime = resolve(runtime_body, facts_document, preserve_recursive=True)
        actual = resolve(operation['requestBody'], document, preserve_recursive=True)
        actual_contract = _body_contract(actual)
        if fact.get('x-aisa-validation') == 'runtime':
            expected = _body_contract(runtime)
        else:
            # The composer defines which mixed fields runtime owns. Applying
            # that declaration again must preserve the actual candidate; extra
            # provider properties and their required fields remain permitted.
            expected = _body_contract(merge_body(actual, runtime))
        if actual_contract != expected:
            return [('runtime_body_contract_mismatch', None)]
    except (ValueError, KeyError, TypeError) as exc:
        return [('unresolved_body_declaration', str(exc))]
    return []


def reason_code(reason):
    """Classify known errors without incorporating variable paths/error suffixes.

    Unknown prose is not a stable classification and cannot grandfather debt.
    Unknown candidate codes cannot establish a verified classification.
    """
    text = str(reason or '').lower().strip()
    for needles, code in (
        (('upstream operation missing',), 'upstream_operation_missing'),
        (('upstream selector has no matching',), 'upstream_selector_no_match'),
        (('ambiguous',), 'ambiguous_source'),
        (('upstream binding changed',), 'upstream_binding_changed'),
        (('unsupported external', 'unsupported recursive', 'reference scope', 'reference has incompatible'), 'unsupported_reference'),
        (('identity_unmapped', 'identity is missing', 'operationid is missing'), 'identity_unmapped'),
        (('runtime_contract_unavailable', 'runtime facts unavailable', 'provider_document_unavailable', 'group_member_unavailable'), 'runtime_contract_unavailable'),
        (('operation_not_composed',), 'operation_not_composed'),
        (('missing source', 'source missing', 'mirror requires complete'), 'missing_source'),
        (('missing request', 'request schema missing'), 'missing_request_declaration'),
    ):
        if any(needle in text for needle in needles):
            return code
    return 'unclassified_contract_error'


def binding_hash(operation, document=None):
    """Fingerprint effective binding/request facts, excluding source/price churn."""
    if document is not None:
        operation = effective_public_operation({}, operation, document)
    keys = ('operationId', 'parameters', 'requestBody', 'security',
            'x-aisa-upstream-path', 'x-aisa-upstream-selector',
            'x-aisa-query-policy', 'x-aisa-validation', 'x-aisa-passthrough',
            'x-aisa-lifecycle', 'x-aisa-identity-source', 'x-aisa-endpoint-path')
    value = _schema_contract({key: operation[key] for key in keys if key in operation})
    if document is not None:
        request = {key: operation[key] for key in ('parameters', 'requestBody') if key in operation}
        components = referenced_components(request, document)
        if components:
            # Preserve the finite reachable graph: stable ref names alone do
            # not prove that runtime-owned types/constraints are unchanged.
            # Unreferenced schemas and source metadata do not affect binding.
            value['request_components'] = {
                section: {name: _schema_contract(definition) for name, definition in definitions.items()}
                for section, definitions in components.items()}
    revision = operation.get('x-aisa-revision', {})
    value['revision'] = {key: revision[key] for key in ('profile_ref', 'handler_contract_hash') if key in revision}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()


def _operations(document, any_method=False):
    servers = document.get('servers') or [{'url': ''}]
    prefix = urlsplit(servers[0].get('url', '')).path.rstrip('/')
    for path, item in document.get('paths', {}).items():
        public = prefix + path
        for method, operation in item.items():
            if method in METHODS or (any_method and method == 'x-aisa-any'):
                if isinstance(operation, dict):
                    # Parameter inheritance affects the effective request binding.
                    effective = effective_public_operation(item, operation, document)
                    yield (public, method), effective


def _valid_document(value):
    return isinstance(value, dict) and isinstance(value.get('paths'), dict)


def _error(code, provider=None, path=None, method=None, operation_id=None, **details):
    return {key: value for key, value in dict(code=code, provider=provider, path=path,
            method=method.upper() if method else None, operation_id=operation_id, **details).items() if value is not None}


def _pending_key(row):
    code = row.get('reason_code') or reason_code(row.get('reason'))
    # Missing old binding data cannot prove the candidate has not changed.
    if not row.get('binding_hash') or code == 'unclassified_contract_error':
        return None
    return (row.get('catalog'), row.get('operation_id'), row.get('path'),
            str(row.get('method', '')).upper(), row['binding_hash'], code,
            row.get('source_binding_hash'), row.get('runtime_status'))


def _runtime_accounting(index, facts, errors, missing, retained_providers, coverage):
    cov = index.get('coverage')
    if not isinstance(cov, dict):
        missing.append('runtime_index.coverage')
        return
    names = ('inventory_endpoint_count', 'selected_endpoint_count', 'projected_endpoint_count', 'pending_endpoint_count')
    if any(type(cov.get(name)) is not int or cov[name] < 0 for name in names):
        errors.append(_error('invalid_endpoint_counts'))
        return
    inventory, selected, projected, pending = (cov[name] for name in names)
    excluded = cov.get('excluded_endpoints')
    pending_rows = index.get('pending_endpoints')
    if not isinstance(excluded, list) or not isinstance(pending_rows, list):
        missing.append('runtime_endpoint_inventory')
        return
    pending_outcomes = {
        (row.get('catalog') or provider, row.get('path'))
        for provider, rows in coverage.get('providers', {}).items() if isinstance(rows, list)
        for row in rows if isinstance(row, dict) and row.get('status') == 'pending'
    }
    for row in pending_rows:
        pair = (row.get('provider'), row.get('path'))
        if pair not in pending_outcomes:
            errors.append(_error('pending_endpoint_coverage_missing', provider=pair[0], path=pair[1]))
    excluded_paths = {row.get('path') for row in excluded}
    pending_paths = {row.get('path') for row in pending_rows}
    if None in excluded_paths | pending_paths or len(excluded_paths) != len(excluded) or len(pending_paths) != len(pending_rows):
        errors.append(_error('duplicate_or_missing_endpoint_path'))
    if inventory != selected + len(excluded) or selected != projected + pending or pending != len(pending_rows):
        errors.append(_error('endpoint_accounting_mismatch'))
    if excluded_paths & pending_paths:
        errors.append(_error('endpoint_outcome_overlap'))
    fact_paths = set()
    derived_without_base = set()
    for provider, document in facts.items():
        if not _valid_document(document):
            continue
        ops = dict(_operations(document, True))
        bases = {path for (path, _), op in ops.items() if op.get('x-aisa-identity-source') != 'derived'}
        catalog_bases = {}
        for (path, _), op in ops.items():
            if op.get('x-aisa-identity-source') != 'derived':
                catalog_bases.setdefault(op.get('x-aisa-catalog-id', provider), set()).add(path)
        fact_paths.update(bases)
        for (path, _), op in ops.items():
            if op.get('x-aisa-endpoint-path'):
                fact_paths.add(op['x-aisa-endpoint-path'])
            elif op.get('x-aisa-identity-source') == 'derived':
                catalog = op.get('x-aisa-catalog-id', provider)
                if not any(path == base or path.startswith(base + '/') for base in catalog_bases.get(catalog, ())):
                    derived_without_base.add(catalog)
    explicit = cov.get('projected_endpoints')
    if isinstance(explicit, list):
        projected_paths = {row.get('path') for row in explicit}
        if None in projected_paths or len(projected_paths) != len(explicit) or len(projected_paths) != projected:
            errors.append(_error('projected_endpoint_inventory_mismatch'))
        if not fact_paths.issubset(projected_paths):
            errors.append(_error('fact_endpoint_not_in_inventory'))
        providers = index.get('providers')
        if isinstance(providers, list):
            actual_counts = {}
            for row in explicit:
                actual_counts[row.get('provider')] = actual_counts.get(row.get('provider'), 0) + 1
            expected_counts = {row.get('id'): row.get('endpoint_count') for row in providers}
            if len(expected_counts) != len(providers) or any(type(value) is not int or value < 0 for value in expected_counts.values()):
                errors.append(_error('invalid_projected_provider_counts'))
            if actual_counts != expected_counts:
                errors.append(_error('projected_provider_endpoint_counts_mismatch'))
        else:
            missing.append('projected_provider_counts')
        # For fully derived lifecycle families (e.g. Batch), the index's
        # DB-owned endpoint inventory is authoritative. Public paths cannot
        # reconstruct hidden database endpoint paths. Operations are checked
        # independently by the provider loop. The exception is local to the
        # operation's original catalog, including inside grouped output files.
        absent_retained = {row.get('path') for row in explicit if row.get('provider') in retained_providers}
        hidden_derived = {row.get('path') for row in explicit if row.get('provider') in derived_without_base}
        if fact_paths | absent_retained | hidden_derived != projected_paths:
            errors.append(_error('projected_endpoint_paths_mismatch'))
        if len(projected_paths | pending_paths) != selected:
            errors.append(_error('selected_endpoint_paths_mismatch'))
    else:
        missing.append('runtime_index.coverage.projected_endpoints')
        projected_paths = fact_paths
    if projected_paths & pending_paths or projected_paths & excluded_paths:
        errors.append(_error('endpoint_outcome_overlap'))


def check_readiness(facts_by_provider, documents_by_provider, coverage,
                    baseline_coverage=None, runtime_index=None, deferred_definitions=None):
    """Assess actual candidates. Provider failures do not imply global abort.

    status=failed means structural errors or new/changed pending items. Existing
    reviewed pending remains visible. Missing/retained inputs yield not_assessed;
    only global_errors require globally stopping publication. The caller supplies
    the independently reviewed baseline and optional code-pinned exact deferrals.
    """
    baseline_ok = isinstance(baseline_coverage, dict) and isinstance(baseline_coverage.get('providers'), dict)
    report = dict(schema_version=1, status='passed', global_errors=[], blocked_providers=[],
                  providers={}, baseline_assessed=baseline_ok, missing_inputs=[], legacy_route_overlaps=[])
    if deferred_definitions is not None:
        report['deferred_definitions'] = deferred_definitions.metadata
    if not isinstance(facts_by_provider, dict) or not isinstance(documents_by_provider, dict) or not isinstance(coverage, dict) or not isinstance(coverage.get('providers'), dict):
        report.update(status='not_assessed', missing_inputs=['facts/documents/coverage'])
        return report
    facts, documents = facts_by_provider, documents_by_provider
    rows_by_provider = coverage['providers']
    names = set(facts) | set(rows_by_provider)
    # Grouped provider facts may represent several runtime catalog ids.
    known_catalogs = set(names)
    for document in facts.values():
        if _valid_document(document):
            known_catalogs.update(document.get('info', {}).get('x-aisa-catalogs', {}))
            known_catalogs.update(op.get('x-aisa-catalog-id') for _, op in _operations(document, True) if op.get('x-aisa-catalog-id'))
    for rows in rows_by_provider.values():
        if isinstance(rows, list):
            known_catalogs.update(row.get('catalog') for row in rows if isinstance(row, dict) and row.get('catalog'))
    if isinstance(runtime_index, dict):
        for row in runtime_index.get('providers', []) + runtime_index.get('pending_providers', []):
            if row.get('id') and row['id'] not in known_catalogs:
                names.add(row['id'])
    names = sorted(names)
    if not names and runtime_index is None:
        report['missing_inputs'].append('provider_inputs')
    # Check the actual publication graph, including retained history.
    ids, routes = {}, {}
    for provider in sorted(documents):
        if not _valid_document(documents[provider]):
            continue
        for (path, method), op in _operations(documents[provider]):
            oid = op.get('operationId')
            where = (provider, path, method)
            if not isinstance(oid, str) or not oid.strip():
                report['global_errors'].append(_error('missing_operation_id', provider, path, method))
                oid = None
            if oid and oid in ids and ids[oid] != where:
                report['global_errors'].append(_error('duplicate_operation_id', provider, path, method, oid, previous=list(ids[oid])))
            if oid:
                ids[oid] = where
            previous_owners = routes.setdefault((path, method), [])
            for previous in previous_owners:
                overlap = _error('duplicate_public_route', provider, path, method, oid, previous=previous)
                if provider in names or previous in names:
                    report['global_errors'].append(overlap)
                else:
                    report['legacy_route_overlaps'].append(overlap)
            previous_owners.append(provider)
    retained_providers = set()
    index_pending_providers = {row.get('id') for row in (runtime_index or {}).get('pending_providers', [])} if isinstance(runtime_index, dict) else set()
    for provider in names:
        result = dict(status='passed', errors=[], new_pending=[], existing_pending=[], deferred_pending=[], missing_inputs=[])
        report['providers'][provider] = result
        document, fact_document = documents.get(provider), facts.get(provider)
        rows = rows_by_provider.get(provider)
        if not isinstance(rows, list):
            result['missing_inputs'].append('coverage')
            rows = []
        retained = bool(rows) and all(isinstance(row, dict) and row.get('publication_state') == 'retained' for row in rows)
        known_unavailable = retained or provider in index_pending_providers
        if known_unavailable:
            retained_providers.add(provider)
        if not _valid_document(fact_document):
            result['missing_inputs'].append('runtime_facts')
            fact_ops = {}
        else:
            fact_ops = dict(_operations(fact_document, True))
        if not _valid_document(document):
            result['missing_inputs'].append('candidate_document')
            doc_ops = {}
        else:
            doc_ops = dict(_operations(document))
        baseline_rows = baseline_coverage['providers'].get(provider, []) if baseline_ok else []
        baseline_ids = {(row.get('path'), str(row.get('method', '')).lower()): row.get('operation_id') for row in baseline_rows if row.get('status') == 'composed'}
        existing = {_pending_key(row) for row in baseline_rows if row.get('status') == 'pending'} - {None}
        covered = {}
        for original in rows:
            if not isinstance(original, dict) or not isinstance(original.get('path'), str) or str(original.get('method', '')).lower() not in METHODS | {'any'}:
                result['errors'].append(_error('invalid_coverage_row', provider))
                continue
            row = dict(original)
            path, method = row['path'], row['method'].lower()
            key = (path, method)
            if key in covered:
                result['errors'].append(_error('duplicate_coverage_row', provider, path, method))
            covered[key] = row
            fact = fact_ops.get(key, fact_ops.get((path, 'x-aisa-any')))
            op = doc_ops.get(key)
            retained = row.get('publication_state') == 'retained'
            if fact is None and not retained and _valid_document(fact_document):
                result['errors'].append(_error('coverage_without_fact', provider, path, method))
            if fact is not None:
                try:
                    computed_binding = binding_hash(fact, fact_document)
                except (ValueError, KeyError, TypeError) as exc:
                    result['errors'].append(_error('unresolved_binding_reference', provider, path, method, detail=str(exc)))
                    computed_binding = None
                if row.get('binding_hash') is not None and row['binding_hash'] != computed_binding:
                    result['errors'].append(_error('candidate_binding_hash_mismatch', provider, path, method))
                row['binding_hash'] = computed_binding
                if 'runtime_status' in row or 'x-aisa-status' in fact:
                    if 'runtime_status' in row and row['runtime_status'] != fact.get('x-aisa-status'):
                        result['errors'].append(_error('candidate_runtime_status_mismatch', provider, path, method))
                    row['runtime_status'] = fact.get('x-aisa-status')
            else:
                # Without current facts, a candidate-provided hash is not
                # evidence that an earlier reviewed binding is unchanged.
                row.pop('binding_hash', None)
            if row.get('status') == 'pending':
                computed_reason = reason_code(row.get('reason'))
                if row.get('reason_code') is not None and row['reason_code'] != computed_reason:
                    result['errors'].append(_error('candidate_reason_code_mismatch', provider, path, method))
                row['reason_code'] = computed_reason
                row['method'] = method.upper()
                target = 'existing_pending' if _pending_key(row) in existing else 'new_pending'
                if target == 'new_pending' and deferred_definitions is not None and deferred_definitions.matches(provider, 'request', _pending_key(row)):
                    target = 'deferred_pending'
                result[target].append(row)
                if not row.get('reason') and not original.get('reason_code'):
                    result['errors'].append(_error('pending_without_reason', provider, path, method))
                pending_ops = [value for (p, m), value in doc_ops.items() if p == path and (method == 'any' or m == method)]
                if any(not value.get('x-aisa-contract-pending') for value in pending_ops) and not retained:
                    result['errors'].append(_error('pending_published_as_complete', provider, path, method, row.get('operation_id')))
                if retained:
                    result['missing_inputs'].append('retained_document_not_fresh')
            elif row.get('status') == 'composed':
                if retained:
                    result['errors'].append(_error('retained_claims_fresh_composition', provider, path, method))
                if not op and _valid_document(document):
                    result['errors'].append(_error('composed_operation_missing', provider, path, method))
                elif op and (not op.get('operationId') or row.get('operation_id') != op['operationId']):
                    result['errors'].append(_error('composed_identity_mismatch', provider, path, method))
                elif op and fact is not None:
                    prior_id = baseline_ids.get(key)
                    if prior_id and op['operationId'] != prior_id:
                        result['errors'].append(_error('published_identity_changed', provider, path, method, op['operationId'], previous=prior_id))
                    flexible = (path, 'x-aisa-any') in fact_ops or fact.get('x-aisa-identity-source') == 'derived'
                    if not fact.get('operationId') or (not flexible and op['operationId'] != fact['operationId']):
                        result['errors'].append(_error('fact_identity_mismatch', provider, path, method, op['operationId']))
                    if op.get('x-aisa-contract-pending'):
                        result['errors'].append(_error('composed_operation_marked_pending', provider, path, method))
                    validation = fact.get('x-aisa-validation')
                    if validation != 'runtime' and not op.get('x-aisa-source', {}).get('kind'):
                        result['errors'].append(_error('missing_request_source', provider, path, method))
                    for code, parameter in _runtime_parameter_errors(fact, fact_document, op, document):
                        result['errors'].append(_error(code, provider, path, method, parameter=parameter))
                    for code, detail in _runtime_body_errors(fact, fact_document, op, document):
                        result['errors'].append(_error(code, provider, path, method, detail=detail))
                    body = op.get('requestBody')
                    if body is not None and not body.get('$ref') and (not body.get('content') or any('schema' not in media for media in body['content'].values())):
                        result['errors'].append(_error('missing_request_declaration', provider, path, method))
            else:
                result['errors'].append(_error('invalid_coverage_status', provider, path, method))
        for (path, method), fact in fact_ops.items():
            if method == 'x-aisa-any' and covered.get((path, 'any'), {}).get('status') == 'pending':
                expected = {(path, 'any')}
            elif method == 'x-aisa-any':
                expected = {(p, m) for p, m in doc_ops if p == path}
                expected |= {(p, m) for p, m in covered if p == path}
                expected = expected or {(path, 'any')}
            else:
                expected = {(path, method)}
            for key in sorted(expected):
                if key not in covered:
                    result['errors'].append(_error('missing_coverage', provider, *key, fact.get('operationId')))
        for (path, method), op in doc_ops.items():
            if _valid_document(fact_document) and (path, method) not in fact_ops and (path, 'x-aisa-any') not in fact_ops and not op.get('x-aisa-contract-pending'):
                if not any(row.get('publication_state') == 'retained' and row.get('path') == path and str(row.get('method', '')).lower() in (method, 'any') for row in rows if isinstance(row, dict)):
                    result['errors'].append(_error('published_operation_without_fact', provider, path, method, op.get('operationId')))
        result['missing_inputs'] = sorted(set(result['missing_inputs']))
        if result['errors'] or result['new_pending']:
            result['status'] = 'failed'
            report['blocked_providers'].append(provider)
        elif result['missing_inputs']:
            result['status'] = 'not_assessed'
        unassessed_inputs = [item for item in result['missing_inputs'] if item != 'retained_document_not_fresh']
        if unassessed_inputs and not known_unavailable:
            report['missing_inputs'].append(provider + ': ' + ', '.join(unassessed_inputs))
    if runtime_index is not None:
        if isinstance(runtime_index, dict):
            _runtime_accounting(runtime_index, facts, report['global_errors'], report['missing_inputs'], retained_providers, coverage)
        else:
            report['missing_inputs'].append('runtime_index')
    try:
        from .gap_evidence import assess_response_gaps
    except ImportError:
        from gap_evidence import assess_response_gaps
    assess_response_gaps(report, facts, documents, coverage, baseline_coverage, deferred_definitions)
    # Consumer evidence only: preserve native ANY/identity and exact current
    # public pricing/revision. Never derive method or schema authority from debt.
    for provider, result in report['providers'].items():
        fact_ops = dict(_operations(facts.get(provider, {}), True))
        for field in ('new_pending', 'existing_pending', 'deferred_pending',
                      'new_response_pending', 'existing_response_pending', 'deferred_response_pending'):
            for row in result.get(field, []):
                method, path = str(row.get('method', '')).lower(), row.get('path')
                native_method = method if (path, method) in fact_ops else 'x-aisa-any'
                fact = fact_ops.get((path, native_method))
                if fact is not None:
                    row['runtime_binding'] = copy.deepcopy({
                        'operation_id': fact.get('operationId'),
                        'provider': fact.get('x-aisa-catalog-id', provider),
                        'method': 'ANY' if native_method == 'x-aisa-any' else native_method.upper(),
                        'path': path, 'status': fact.get('x-aisa-status'),
                        'revision': fact.get('x-aisa-revision'), 'pricing': fact.get('x-aisa-pricing')})
    if report['global_errors'] or report['blocked_providers']:
        report['status'] = 'failed'
    elif report['missing_inputs']:
        report['status'] = 'not_assessed'
    return report

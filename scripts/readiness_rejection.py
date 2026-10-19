"""Bounded evidence of a completed readiness rejection, never a passed artifact.

Only declared diagnostic multisets are reordered. Every value is hashed; nested
metadata arrays retain their order. The digest is descriptive, not an oracle
authorizing an expected failure or any publication.
"""
from __future__ import annotations

import copy

from schema_input_bundle import HEX40, HEX64, canonical, require, sha

EXIT_READINESS_REJECTED = 78
MAX_PROOF_BYTES = 4096
NORMALIZATION = 'complete_readiness_multiset_v1'
SCOPE = 'aisa-internal-snapshot-readiness-rejection'
STATUSES = {'passed', 'failed', 'not_assessed'}
TOP_LISTS = ('global_errors', 'blocked_providers', 'missing_inputs', 'legacy_route_overlaps')
PENDING_LISTS = ('new_pending', 'existing_pending', 'deferred_pending',
                 'new_response_pending', 'existing_response_pending', 'deferred_response_pending',
                 'disabled_response_pending')
PROVIDER_LISTS = ('errors', 'missing_inputs', *PENDING_LISTS)
REASON_CODES = frozenset(('unforwarded_source_query', 'unforwarded_source_header',
    'upstream_operation_missing', 'upstream_selector_no_match', 'ambiguous_source',
    'upstream_binding_changed', 'unsupported_reference', 'identity_unmapped',
    'runtime_contract_unavailable', 'operation_not_composed', 'missing_source',
    'missing_request_declaration', 'unclassified_contract_error',
    'unresolved_response_reference', 'response_conversion_gap', 'missing_success_payload'))
ERROR_CODES = frozenset(('candidate_binding_hash_mismatch', 'candidate_reason_code_mismatch',
    'candidate_runtime_status_mismatch', 'composed_identity_mismatch',
    'composed_operation_marked_pending', 'composed_operation_missing', 'coverage_without_fact',
    'duplicate_coverage_row', 'duplicate_operation_id', 'duplicate_or_missing_endpoint_path',
    'duplicate_public_route', 'endpoint_accounting_mismatch', 'endpoint_outcome_overlap',
    'fact_endpoint_not_in_inventory', 'fact_identity_mismatch', 'invalid_coverage_row',
    'invalid_coverage_status', 'invalid_endpoint_counts', 'invalid_projected_provider_counts',
    'invalid_source_provenance', 'missing_coverage', 'missing_operation_id',
    'missing_path_parameter', 'missing_request_declaration', 'missing_request_source',
    'missing_runtime_parameter', 'missing_runtime_request_body', 'path_parameter_not_required',
    'path_parameter_without_placeholder', 'pending_endpoint_coverage_missing',
    'pending_published_as_complete', 'pending_without_reason', 'projected_endpoint_inventory_mismatch',
    'projected_endpoint_paths_mismatch', 'projected_provider_endpoint_counts_mismatch',
    'published_identity_changed', 'published_operation_without_fact', 'retained_claims_fresh_composition',
    'runtime_body_contract_mismatch', 'runtime_parameter_contract_mismatch',
    'selected_endpoint_paths_mismatch', 'unresolved_binding_reference', 'unresolved_body_declaration',
    'unresolved_parameter_declaration', 'unresolved_path_parameter_declaration',
    'response_gap_accounting_mismatch'))
PENDING_FIELDS = frozenset(('catalog', 'path', 'method', 'operation_id', 'status', 'reason',
    'reason_code', 'binding_hash', 'validation', 'runtime_status', 'schema_source',
    'source_binding_hash', 'response_source_binding_hash', 'publication_state', 'runtime_binding',
    'statuses', 'response_binding_hash', 'response_runtime_binding_hash'))
ERROR_FIELDS = frozenset(('code', 'provider', 'path', 'method', 'operation_id',
                          'previous', 'parameter', 'detail'))


class ReadinessRejected(ValueError):
    """Created only after stage returns a complete, structurally valid report."""

    def __init__(self, diagnostic):
        super().__init__('Offline native graph did not pass existing readiness gates')
        self.diagnostic = diagnostic


class SnapshotReadinessRejected(ValueError):
    """The private adapter has additionally bound its verified transport pins."""

    def __init__(self, proof):
        super().__init__('Internal snapshot readiness rejected')
        self.proof = proof


def _uint(value):
    return type(value) is int and 0 <= value < 1 << 32


def _json(value, depth=0, budget=None):
    """Reject non-JSON/nonfinite/unbounded shapes without printing their values."""
    if budget is None:
        budget = [1_000_000]
    budget[0] -= 1
    require(depth <= 64 and budget[0] >= 0, 'Readiness diagnostic exceeds bounds')
    if value is None or type(value) in (bool, int, str):
        require(type(value) is not str or len(value.encode()) <= 1 << 20,
                'Readiness diagnostic string exceeds bounds')
    elif type(value) is float:
        canonical(value)  # Reject NaN/infinity; preserve finite pricing metadata.
    elif type(value) is list:
        for child in value:
            _json(child, depth + 1, budget)
    elif type(value) is dict:
        require(all(type(key) is str for key in value), 'Invalid readiness diagnostic key')
        for child in value.values():
            _json(child, depth + 1, budget)
    else:
        raise ValueError('Invalid readiness diagnostic value')


def _strings(value):
    return type(value) is list and all(type(item) is str for item in value)


def _errors(rows):
    require(type(rows) is list, 'Invalid readiness error list')
    for row in rows:
        require(type(row) is dict and {'code'} <= set(row) <= ERROR_FIELDS and
                type(row['code']) is str and row['code'] in ERROR_CODES,
                'Unknown readiness error shape or code')
        for name in ('provider', 'path', 'method', 'operation_id', 'parameter'):
            require(name not in row or type(row[name]) is str, 'Invalid readiness error identity')
        require('detail' not in row or type(row['detail']) is str, 'Invalid readiness error detail')
        require('previous' not in row or type(row['previous']) is str or
                (_strings(row['previous']) and len(row['previous']) == 3),
                'Invalid readiness previous identity')


def _policy(value):
    required = {'policy_id', 'path', 'sha256', 'scope'}
    require(type(value) is dict and required <= set(value) <=
            required | {'rebinding', 'effective_scope'} and
            type(value['policy_id']) is str and value['policy_id'] and
            type(value['path']) is str and value['path'] and
            type(value['sha256']) is str and HEX64.fullmatch(value['sha256']),
            'Invalid readiness policy metadata')
    for field in ('scope', 'effective_scope'):
        if field in value:
            require(type(value[field]) is dict and set(value[field]) == {'request', 'response'} and
                    all(_uint(count) for count in value[field].values()),
                    'Invalid readiness policy scope')
    if 'rebinding' in value:
        row = value['rebinding']
        require(type(row) is dict and set(row) == {'path', 'sha256'} and
                type(row['path']) is str and row['path'] and
                type(row['sha256']) is str and HEX64.fullmatch(row['sha256']),
                'Invalid readiness policy rebinding')


def complete_diagnostic(report, summary):
    """Hash the entire closed report and every summary-only blocking reason."""
    required = {'schema_version', 'status', 'providers', 'baseline_assessed', *TOP_LISTS}
    require(type(report) is dict and required <= set(report) <= required | {'deferred_definitions'} and
            type(report['schema_version']) is int and report['schema_version'] == 1 and
            type(report['status']) is str and report['status'] in STATUSES and
            type(report['baseline_assessed']) is bool and type(report['providers']) is dict,
            'Incomplete readiness report')
    _json(report)
    _json(summary)
    if 'deferred_definitions' in report:
        _policy(report['deferred_definitions'])
    _errors(report['global_errors'])
    _errors(report['legacy_route_overlaps'])
    require(_strings(report['blocked_providers']) and _strings(report['missing_inputs']),
            'Invalid readiness closure')
    count = sum(len(report[name]) for name in TOP_LISTS if name != 'blocked_providers')
    normalized = copy.deepcopy(report)
    for name in TOP_LISTS:
        normalized[name].sort(key=canonical)
    for provider, row in report['providers'].items():
        require(type(provider) is str and provider and type(row) is dict and
                set(row) == {'status', *PROVIDER_LISTS} and
                type(row['status']) is str and row['status'] in STATUSES,
                'Incomplete provider readiness report')
        _errors(row['errors'])
        require(_strings(row['missing_inputs']), 'Invalid provider missing inputs')
        for name in PENDING_LISTS:
            require(type(row[name]) is list, 'Invalid readiness pending list')
            for pending in row[name]:
                require(type(pending) is dict and
                        {'path', 'method', 'operation_id', 'reason_code'} <= set(pending) <= PENDING_FIELDS and
                        type(pending['reason_code']) is str and pending['reason_code'] in REASON_CODES and
                        type(pending['path']) is str and pending['path'].startswith('/') and
                        type(pending['method']) is str and
                        pending['method'] in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE', 'ANY'} and
                        (pending['operation_id'] is None or type(pending['operation_id']) is str),
                        'Unknown readiness pending shape or reason')
                for field in PENDING_FIELDS - {'runtime_binding', 'statuses'}:
                    require(field not in pending or pending[field] is None or type(pending[field]) is str,
                            'Invalid pending diagnostic scalar')
                require('statuses' not in pending or _strings(pending['statuses']),
                        'Invalid pending response statuses')
                require('runtime_binding' not in pending or
                        (type(pending['runtime_binding']) is dict and
                         set(pending['runtime_binding']) <=
                         {'operation_id', 'provider', 'method', 'path', 'status', 'revision', 'pricing'}),
                        'Invalid pending Runtime binding')
                if 'runtime_binding' in pending:
                    binding = pending['runtime_binding']
                    for field in ('operation_id', 'provider', 'method', 'path', 'status'):
                        require(field not in binding or binding[field] is None or type(binding[field]) is str,
                                'Invalid pending Runtime identity')
                    for field in ('revision', 'pricing'):
                        require(field not in binding or binding[field] is None or type(binding[field]) is dict,
                                'Invalid pending Runtime metadata')
        for name in PROVIDER_LISTS:
            count += len(row[name])
            normalized['providers'][provider][name].sort(key=canonical)
    require(type(summary) is dict, 'Invalid composition summary')
    blocked = []
    for provider, row in summary.items():
        require(type(provider) is str and provider and type(row) is dict and
                {'changed', 'operations', 'pending'} <= set(row) <=
                {'changed', 'operations', 'pending', 'document_hash', 'blocked'} and
                type(row['changed']) is bool and _uint(row['operations']) and _uint(row['pending']),
                'Invalid composition summary shape')
        if 'document_hash' in row:
            require(type(row['document_hash']) is str, 'Invalid composition hash')
        if 'blocked' in row:
            require(type(row['blocked']) is str and row['blocked'], 'Invalid blocking summary')
            blocked.append({'provider': provider, 'blocked': row['blocked']})
    require(report['status'] != 'passed' or report['global_errors'] or report['missing_inputs'] or
            report['blocked_providers'] or blocked, 'Passed readiness cannot produce rejection')
    count += len(blocked)
    counts = {'provider_count': len(report['providers']),
              'blocked_provider_count': len(report['blocked_providers']),
              'diagnostic_entry_count': count}
    require(all(_uint(value) for value in counts.values()), 'Readiness count exceeds bounds')
    preimage = {'normalization': NORMALIZATION, 'report': normalized,
                'blocked_summary': sorted(blocked, key=canonical)}
    return {'diagnostic_sha256': sha(canonical(preimage)), **counts}


def snapshot_proof(diagnostic, bundle, runtime):
    """Use only pins independently checked by the private adapter's loaders."""
    proof = {'schema_version': 1, 'scope': SCOPE, 'status': 'readiness_rejected',
             'normalization': NORMALIZATION, 'bundle_manifest_sha256': bundle['manifest_sha256'],
             'docs_ref': bundle['docs_ref'], 'snapshot_sha256': runtime['snapshot_sha256'],
             'generation': runtime['generation'], 'source_digest': runtime['source_digest'],
             'compiler_revision': runtime['compiler_revision'], **diagnostic}
    for name in ('bundle_manifest_sha256', 'snapshot_sha256', 'source_digest', 'diagnostic_sha256'):
        require(type(proof[name]) is str and HEX64.fullmatch(proof[name]), 'Invalid rejection digest')
    for name in ('docs_ref', 'compiler_revision'):
        require(type(proof[name]) is str and HEX40.fullmatch(proof[name]), 'Invalid rejection revision')
    require(type(proof['generation']) is int and 0 <= proof['generation'] < 1 << 64 and
            len(canonical(proof)) <= MAX_PROOF_BYTES, 'Invalid rejection proof bounds')
    return proof

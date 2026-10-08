import copy
import unittest

from scripts.contract_readiness import binding_hash, check_readiness, reason_code


def fixture(path='/search', oid='get_search', method='get'):
    op = {'operationId': oid, 'x-aisa-validation': 'runtime', 'parameters': [], 'responses': {'200': {'description': 'OK'}}}
    doc = {'paths': {path: {method: op}}}
    row = {'path': path, 'method': method.upper(), 'operation_id': oid, 'status': 'composed'}
    return {'p': copy.deepcopy(doc)}, {'p': copy.deepcopy(doc)}, {'providers': {'p': [row]}}


def pending_fixture(path='/search', reason='upstream operation missing'):
    facts, documents, coverage = fixture(path)
    documents['p']['paths'] = {}
    op = facts['p']['paths'][path]['get']
    op['x-aisa-validation'] = 'mixed'
    op['x-aisa-upstream-path'] = '/v1/search'
    row = coverage['providers']['p'][0]
    row.update(status='pending', reason=reason, reason_code=reason_code(reason), binding_hash=binding_hash(op))
    return facts, documents, coverage


def index(paths, operations=None, pending=None, excluded=None):
    pending, excluded = pending or [], excluded or []
    return {'providers': [{'id': 'p', 'endpoint_count': len(paths), 'operation_count': operations or len(paths)}],
            'pending_endpoints': [{'provider': 'q', 'path': p} for p in pending],
            'coverage': {'inventory_endpoint_count': len(paths) + len(pending) + len(excluded),
                         'selected_endpoint_count': len(paths) + len(pending),
                         'projected_endpoint_count': len(paths), 'pending_endpoint_count': len(pending),
                         'projected_operation_count': operations or len(paths),
                         'projected_endpoints': [{'provider': 'p', 'path': p} for p in paths],
                         'excluded_endpoints': [{'provider': 'old', 'path': p} for p in excluded]}}


class ReadinessTests(unittest.TestCase):
    def errors(self, report):
        return {e['code'] for e in report['global_errors']} | {e['code'] for p in report['providers'].values() for e in p['errors']}

    def test_empty_declared_parameters_are_valid(self):
        args = fixture()
        before = copy.deepcopy(args)
        result = check_readiness(*args)
        self.assertEqual('passed', result['status'])
        self.assertEqual(before, args)

    def test_missing_inputs_not_assessed(self):
        for args in [(None, {}, {}), ({}, {}, {'providers': {}})]:
            self.assertEqual('not_assessed', check_readiness(*args)['status'])
        facts, docs, cov = fixture()
        self.assertEqual('not_assessed', check_readiness(facts, {}, cov)['status'])
        self.assertEqual('not_assessed', check_readiness({}, docs, cov)['status'])

    def test_missing_source_pending_without_baseline_fails(self):
        result = check_readiness(*pending_fixture())
        self.assertEqual('failed', result['status'])
        self.assertFalse(result['baseline_assessed'])
        self.assertEqual(['p'], result['blocked_providers'])
        self.assertEqual([], result['global_errors'])

    def test_reviewed_pending_does_not_block_other_provider(self):
        facts, docs, cov = pending_fixture()
        baseline = copy.deepcopy(cov)
        f, d, c = fixture('/other', 'other')
        facts['q'], docs['q'], cov['providers']['q'] = f['p'], d['p'], c['providers']['p']
        result = check_readiness(facts, docs, cov, baseline)
        self.assertEqual('passed', result['status'])
        self.assertEqual(1, len(result['providers']['p']['existing_pending']))
        self.assertEqual('passed', result['providers']['q']['status'])

    def test_equal_count_different_pending_set_fails(self):
        old = pending_fixture('/before')[2]
        result = check_readiness(*pending_fixture('/after'), old)
        self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(result['providers']['p']['new_pending']))

    def test_changed_binding_and_reason_are_new(self):
        for change in ('binding', 'reason'):
            with self.subTest(change=change):
                f, d, c = pending_fixture()
                base = copy.deepcopy(c)
                row = c['providers']['p'][0]
                if change == 'binding':
                    f['p']['paths']['/search']['get']['x-aisa-upstream-path'] = '/v2/search'
                    row['binding_hash'] = binding_hash(f['p']['paths']['/search']['get'])
                else:
                    row.update(reason='ambiguous official operation: details', reason_code='ambiguous_source')
                self.assertEqual('failed', check_readiness(f, d, c, base)['status'])

    def test_source_hash_and_error_suffix_do_not_change_pending(self):
        f, d, c = pending_fixture()
        base = copy.deepcopy(c)
        row = c['providers']['p'][0]
        row['reason'] += ': changed remote details 1234'
        row['source_hash'] = 'different'
        f['p']['info'] = {'x-aisa-source': {'content_hash': 'different'}}
        self.assertEqual('passed', check_readiness(f, d, c, base)['status'])

    def test_pending_referenced_runtime_contract_changes_are_new(self):
        for location in ('parameters', 'requestBody'):
            for change in ('type', 'required'):
                with self.subTest(location=location, change=change):
                    f, d, c = pending_fixture()
                    op = f['p']['paths']['/search']['get']
                    schema = {'type': 'object', 'required': ['q'], 'properties': {'q': {'type': 'string'}}}
                    f['p']['components'] = {'schemas': {'Input': schema}, 'parameters': {'Input': {
                        'name': 'input', 'in': 'query', 'schema': {'$ref': '#/components/schemas/Input'}}}}
                    if location == 'parameters':
                        op[location] = [{'$ref': '#/components/parameters/Input'}]
                    else:
                        op[location] = {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Input'}}}}
                    c['providers']['p'][0]['binding_hash'] = binding_hash(op, f['p'])
                    baseline = copy.deepcopy(c)
                    self.assertEqual('passed', check_readiness(f, d, c, baseline)['status'])
                    if change == 'type':
                        schema['properties']['q']['type'] = 'integer'
                    else:
                        schema['required'] = []
                    # A stale candidate-supplied fingerprint cannot conceal it.
                    result = check_readiness(f, d, c, baseline)
                    self.assertEqual('failed', result['status'])
                    self.assertEqual([], result['providers']['p']['existing_pending'])
                    self.assertEqual(1, len(result['providers']['p']['new_pending']))
                    self.assertIn('candidate_binding_hash_mismatch', self.errors(result))

    def test_reference_fingerprint_is_finite_and_ignores_unrelated_prose(self):
        f, d, c = pending_fixture()
        op = f['p']['paths']['/search']['get']
        op['requestBody'] = {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Node'}}}}
        node = {'type': 'object', 'properties': {'next': {'$ref': '#/components/schemas/Node'},
                                                'description': {'type': 'string'}}}
        f['p']['components'] = {'schemas': {'Node': node, 'Unused': {'type': 'string'}}}
        row = c['providers']['p'][0]
        row['binding_hash'] = binding_hash(op, f['p'])
        baseline = copy.deepcopy(c)
        node.update(description='Updated prose', examples=[{'description': 'sample'}])
        f['p']['components']['schemas']['Unused']['type'] = 'integer'
        f['p']['info'] = {'x-aisa-source': {'content_hash': 'changed'}}
        self.assertEqual('passed', check_readiness(f, d, c, baseline)['status'])
        node['properties']['description']['type'] = 'integer'
        self.assertNotEqual(row['binding_hash'], binding_hash(op, f['p']))

    def test_external_runtime_binding_reference_does_not_grandfather_pending(self):
        f, d, c = pending_fixture()
        f['p']['paths']['/search']['get']['requestBody'] = {'$ref': 'https://example.invalid/input.json'}
        result = check_readiness(f, d, c, copy.deepcopy(c))
        self.assertEqual('failed', result['status'])
        self.assertIn('unresolved_binding_reference', self.errors(result))
        self.assertEqual([], result['providers']['p']['existing_pending'])

    def test_unknown_reason_is_not_grandfathered(self):
        args = pending_fixture(reason='new unclassified failure at host 12')
        self.assertEqual('failed', check_readiness(*args, copy.deepcopy(args[2]))['status'])
        self.assertEqual(reason_code('unexpected host 12'), reason_code('unexpected host 45'))

    def test_old_baseline_missing_binding_cannot_prove_unchanged(self):
        f, d, c = pending_fixture()
        base = copy.deepcopy(c)
        del base['providers']['p'][0]['binding_hash']
        self.assertEqual('failed', check_readiness(f, d, c, base)['status'])

    def test_candidate_cannot_self_approve(self):
        f, d, c = pending_fixture()
        c['baseline_coverage'] = copy.deepcopy(c)
        c['reviewed'] = True
        self.assertEqual('failed', check_readiness(f, d, c)['status'])

    def test_duplicate_identity_and_public_route_are_global(self):
        for path, oid, code in [('/other', 'get_search', 'duplicate_operation_id'), ('/search', 'other_id', 'duplicate_public_route')]:
            f, d, c = fixture()
            f2, d2, c2 = fixture(path, oid)
            f['q'], d['q'], c['providers']['q'] = f2['p'], d2['p'], c2['providers']['p']
            self.assertIn(code, {e['code'] for e in check_readiness(f, d, c)['global_errors']})

    def test_missing_coverage(self):
        f, d, c = fixture()
        c['providers']['p'] = []
        self.assertIn('missing_coverage', self.errors(check_readiness(f, d, c)))

    def test_composed_missing_document_operation(self):
        f, d, c = fixture()
        d['p']['paths'] = {}
        self.assertIn('composed_operation_missing', self.errors(check_readiness(f, d, c)))

    def test_composed_identity_must_match_fact_and_coverage(self):
        f, d, c = fixture()
        d['p']['paths']['/search']['get']['operationId'] = 'renamed'
        self.assertIn('composed_identity_mismatch', self.errors(check_readiness(f, d, c)))
        c['providers']['p'][0]['operation_id'] = 'renamed'
        self.assertIn('fact_identity_mismatch', self.errors(check_readiness(f, d, c)))

    def test_any_expansion_keeps_distinct_published_ids(self):
        f, d, c = fixture(method='x-aisa-any', oid='base')
        op = d['p']['paths']['/search'].pop('x-aisa-any')
        d['p']['paths']['/search'] = {'get': dict(op, operationId='published_get'), 'post': dict(op, operationId='published_post')}
        c['providers']['p'] = [{'path': '/search', 'method': method.upper(), 'operation_id': 'published_' + method, 'status': 'composed'} for method in ('get', 'post')]
        result = check_readiness(f, d, c, runtime_index=index(['/search'], 2))
        self.assertEqual('passed', result['status'], result)
        c['providers']['p'].pop()
        self.assertIn('missing_coverage', self.errors(check_readiness(f, d, c)))

    def test_pending_cannot_appear_as_complete_document(self):
        f, d, c = pending_fixture()
        d['p'] = copy.deepcopy(f['p'])
        self.assertIn('pending_published_as_complete', self.errors(check_readiness(f, d, c)))
        d['p']['paths']['/search']['get']['x-aisa-contract-pending'] = 'source_missing'
        self.assertNotIn('pending_published_as_complete', self.errors(check_readiness(f, d, c)))

    def test_retained_document_is_not_fresh(self):
        f, d, c = pending_fixture()
        d['p'] = copy.deepcopy(f['p'])
        c['providers']['p'][0]['publication_state'] = 'retained'
        result = check_readiness(f, d, c, copy.deepcopy(c))
        self.assertEqual('passed', result['status'])
        self.assertEqual('not_assessed', result['providers']['p']['status'])
        self.assertEqual([], result['global_errors'])
        self.assertEqual([], result['providers']['p']['errors'])
        c['providers']['p'][0]['status'] = 'composed'
        self.assertIn('retained_claims_fresh_composition', self.errors(check_readiness(f, d, c)))

    def test_unconstrained_declared_schema_is_valid_but_example_is_not_schema(self):
        f, d, c = fixture(method='post')
        body = {'content': {'application/json': {'schema': {}}}}
        f['p']['paths']['/search']['post']['requestBody'] = copy.deepcopy(body)
        d['p']['paths']['/search']['post']['requestBody'] = body
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        body['content']['application/json'] = {'example': {}}
        self.assertIn('missing_request_declaration', self.errors(check_readiness(f, d, c)))

    def test_passthrough_requires_source_declaration(self):
        f, d, c = fixture()
        f['p']['paths']['/search']['get']['x-aisa-validation'] = 'mixed'
        self.assertIn('missing_request_source', self.errors(check_readiness(f, d, c)))
        d['p']['paths']['/search']['get']['x-aisa-source'] = {'kind': 'provider_openapi'}
        self.assertEqual('passed', check_readiness(f, d, c)['status'])

    def test_lifecycle_operations_are_not_endpoint_count(self):
        f, d, c = fixture('/jobs', 'submit', 'post')
        for path, method, oid in [('/jobs', 'get', 'list'), ('/jobs/{jobId}', 'get', 'detail'), ('/jobs/{jobId}/cancel', 'post', 'cancel')]:
            op = {'operationId': oid, 'x-aisa-validation': 'runtime', 'x-aisa-identity-source': 'derived'}
            for doc in (f['p'], d['p']):
                doc['paths'].setdefault(path, {})[method] = copy.deepcopy(op)
            c['providers']['p'].append({'path': path, 'method': method.upper(), 'operation_id': oid, 'status': 'composed'})
        self.assertEqual('passed', check_readiness(f, d, c, runtime_index=index(['/jobs'], 4))['status'])
        bad_index = index(['/jobs'], 4)
        bad_index['coverage']['projected_endpoint_count'] = 4
        self.assertIn('endpoint_accounting_mismatch', self.errors(check_readiness(f, d, c, runtime_index=bad_index)))

    def test_derived_batch_uses_explicit_db_endpoint_inventory(self):
        f, d, c = fixture('/batch/jobs', 'batch_submit', 'post')
        for doc in (f['p'], d['p']):
            doc['paths']['/batch/jobs']['post']['x-aisa-identity-source'] = 'derived'
        result = check_readiness(f, d, c, runtime_index=index(['/internal/batch/standard']))
        self.assertEqual('passed', result['status'], result)

    def test_derived_batch_cannot_hide_another_catalog_missing_endpoint(self):
        for grouped in (False, True):
            with self.subTest(grouped=grouped):
                f, d, c = fixture()
                batch_facts, batch_docs, batch_coverage = fixture('/batch/jobs', 'batch_submit', 'post')
                for doc in (batch_facts['p'], batch_docs['p']):
                    doc['paths']['/batch/jobs']['post'].update({
                        'x-aisa-identity-source': 'derived', 'x-aisa-catalog-id': 'batch'})
                batch_coverage['providers']['p'][0]['catalog'] = 'batch'
                if grouped:
                    f['p']['paths'].update(batch_facts['p']['paths'])
                    d['p']['paths'].update(batch_docs['p']['paths'])
                    c['providers']['p'].extend(batch_coverage['providers']['p'])
                else:
                    f['batch'], d['batch'] = batch_facts['p'], batch_docs['p']
                    c['providers']['batch'] = batch_coverage['providers']['p']
                value = index(['/search'])
                value['providers'].append({'id': 'batch', 'endpoint_count': 1, 'operation_count': 1})
                value['coverage']['projected_endpoints'].append({'provider': 'batch', 'path': '/internal/batch/standard'})
                for name in ('inventory_endpoint_count', 'selected_endpoint_count', 'projected_endpoint_count'):
                    value['coverage'][name] += 1
                result = check_readiness(f, d, c, runtime_index=value)
                self.assertEqual('passed', result['status'], result)
                # Counts remain internally consistent, but /missing has no
                # fact or coverage outcome in the normal catalog.
                value['providers'][0]['endpoint_count'] += 1
                value['coverage']['projected_endpoints'].append({'provider': 'p', 'path': '/missing'})
                for name in ('inventory_endpoint_count', 'selected_endpoint_count', 'projected_endpoint_count'):
                    value['coverage'][name] += 1
                result = check_readiness(f, d, c, runtime_index=value)
                self.assertEqual('failed', result['status'])
                self.assertIn('projected_endpoint_paths_mismatch', self.errors(result))

    def test_runtime_pending_and_excluded_account_separately(self):
        f, d, c = fixture()
        c['providers']['q'] = [{'catalog': 'q', 'path': '/unavailable', 'method': 'ANY', 'status': 'pending',
                                'reason': 'runtime_contract_unavailable', 'publication_state': 'retained'}]
        result = check_readiness(f, d, c, runtime_index=index(['/search'], pending=['/unavailable'], excluded=['/legacy']))
        self.assertEqual([], result['global_errors'], result)
        self.assertEqual([], result['missing_inputs'], result)
        bad = index(['/search'], pending=['/search'])
        self.assertIn('endpoint_outcome_overlap', self.errors(check_readiness(*fixture(), runtime_index=bad)))

    def test_old_runtime_index_missing_endpoint_evidence_not_assessed(self):
        value = index(['/search'])
        del value['coverage']['projected_endpoints']
        self.assertEqual('not_assessed', check_readiness(*fixture(), runtime_index=value)['status'])

    def test_runtime_provider_endpoint_counts_must_match(self):
        value = index(['/search'])
        value['providers'][0]['endpoint_count'] = 2
        self.assertIn('projected_provider_endpoint_counts_mismatch', self.errors(check_readiness(*fixture(), runtime_index=value)))

    def test_retained_any_pending_accounts_for_history_without_fresh_claim(self):
        f, d, c = fixture(method='x-aisa-any')
        op = d['p']['paths']['/search'].pop('x-aisa-any')
        d['p']['paths']['/search']['get'] = op
        row = c['providers']['p'][0]
        row.update(method='ANY', status='pending', reason='upstream operation missing', publication_state='retained', binding_hash=binding_hash(op))
        result = check_readiness(f, d, c, copy.deepcopy(c))
        self.assertEqual('passed', result['status'], result)
        self.assertEqual('not_assessed', result['providers']['p']['status'])

    def test_missing_runtime_body_or_parameter_is_not_complete(self):
        for key, value, code in [('requestBody', {'content': {'application/json': {'schema': {'type': 'object'}}}}, 'missing_runtime_request_body'),
                                  ('parameters', [{'name': 'q', 'in': 'query', 'schema': {'type': 'string'}}], 'missing_runtime_parameter')]:
            f, d, c = fixture()
            f['p']['paths']['/search']['get'][key] = value
            self.assertIn(code, self.errors(check_readiness(f, d, c)))

    def test_retained_unavailable_provider_does_not_make_global_input_missing(self):
        f, d, c = pending_fixture()
        c['providers']['p'][0]['publication_state'] = 'retained'
        result = check_readiness({}, d, c, copy.deepcopy(c))
        # Missing current facts cannot authenticate a candidate's old binding.
        self.assertEqual('failed', result['status'], result)
        self.assertEqual([], result['global_errors'])
        self.assertEqual([], result['missing_inputs'])
        self.assertEqual([], result['providers']['p']['existing_pending'])
        self.assertIn('runtime_facts', result['providers']['p']['missing_inputs'])

    def test_document_only_history_does_not_require_runtime_facts(self):
        f, d, c = fixture()
        d['historic'] = fixture('/history', 'history')[1]['p']
        result = check_readiness(f, d, c)
        self.assertEqual('passed', result['status'], result)
        self.assertNotIn('historic', result['providers'])
        d['historic']['paths']['/history']['get']['operationId'] = 'get_search'
        self.assertIn('duplicate_operation_id', self.errors(check_readiness(f, d, c)))

    def test_runtime_index_provider_cannot_be_omitted_from_inputs(self):
        value = index(['/search'])
        result = check_readiness({}, {}, {'providers': {}}, runtime_index=value)
        self.assertIn('p', result['providers'])
        self.assertNotEqual('passed', result['status'])

    def test_reviewed_published_identity_cannot_be_renamed_with_facts(self):
        f, d, c = fixture()
        baseline = copy.deepcopy(c)
        for document in (f['p'], d['p']):
            document['paths']['/search']['get']['operationId'] = 'renamed'
        c['providers']['p'][0]['operation_id'] = 'renamed'
        self.assertIn('published_identity_changed', self.errors(check_readiness(f, d, c, baseline)))

    def test_mixed_fresh_and_retained_operations_do_not_make_global_input_missing(self):
        f, d, c = pending_fixture()
        d['p'] = copy.deepcopy(f['p'])
        c['providers']['p'][0]['publication_state'] = 'retained'
        baseline = copy.deepcopy(c)
        fresh_f, fresh_d, fresh_c = fixture('/fresh', 'fresh')
        f['p']['paths'].update(fresh_f['p']['paths'])
        d['p']['paths'].update(fresh_d['p']['paths'])
        c['providers']['p'].extend(fresh_c['providers']['p'])
        result = check_readiness(f, d, c, baseline)
        self.assertEqual('passed', result['status'], result)
        self.assertEqual('not_assessed', result['providers']['p']['status'])
        self.assertEqual([], result['missing_inputs'])

    def test_candidate_cannot_replay_old_binding_hash(self):
        f, d, c = pending_fixture()
        baseline = copy.deepcopy(c)
        f['p']['paths']['/search']['get']['x-aisa-upstream-path'] = '/changed'
        result = check_readiness(f, d, c, baseline)
        self.assertIn('candidate_binding_hash_mismatch', self.errors(result))
        self.assertEqual([], result['providers']['p']['existing_pending'])
        self.assertEqual(1, len(result['providers']['p']['new_pending']))

    def test_candidate_cannot_replay_old_reason_code(self):
        for reason in ('ambiguous official operation', 'unrecognized new upstream failure'):
            f, d, c = pending_fixture()
            baseline = copy.deepcopy(c)
            c['providers']['p'][0]['reason'] = reason
            result = check_readiness(f, d, c, baseline)
            self.assertIn('candidate_reason_code_mismatch', self.errors(result))
            self.assertEqual([], result['providers']['p']['existing_pending'])
            self.assertEqual(1, len(result['providers']['p']['new_pending']))

    def test_current_inherited_parameters_participate_in_binding_hash(self):
        f, d, c = pending_fixture()
        baseline = copy.deepcopy(c)
        f['p']['paths']['/search']['parameters'] = [{'name': 'q', 'in': 'query', 'schema': {'type': 'string'}}]
        result = check_readiness(f, d, c, baseline)
        self.assertIn('candidate_binding_hash_mismatch', self.errors(result))
        self.assertEqual([], result['providers']['p']['existing_pending'])

    def test_runtime_parameter_required_cannot_be_weakened(self):
        f, d, c = fixture()
        parameter = {'name': 'q', 'in': 'query', 'required': True, 'schema': {'type': 'integer'}}
        f['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(parameter)]
        d['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(parameter)]
        d['p']['paths']['/search']['get']['parameters'][0]['required'] = False
        self.assertIn('runtime_parameter_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_runtime_parameter_type_cannot_be_changed(self):
        f, d, c = fixture()
        parameter = {'name': 'q', 'in': 'query', 'schema': {'type': 'integer'}}
        f['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(parameter)]
        d['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(parameter)]
        d['p']['paths']['/search']['get']['parameters'][0]['schema']['type'] = 'string'
        self.assertIn('runtime_parameter_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_parameter_serialization_and_implicit_defaults(self):
        f, d, c = fixture()
        parameter = {'name': 'q', 'in': 'query', 'schema': {'type': 'array', 'items': {'type': 'integer'}}}
        f['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(parameter)]
        d['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(parameter)]
        actual = d['p']['paths']['/search']['get']['parameters'][0]
        actual.update(required=False, style='form', explode=True, allowReserved=False)
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        for key, value in [('explode', False), ('style', 'spaceDelimited'), ('allowReserved', True)]:
            changed = copy.deepcopy(d)
            changed['p']['paths']['/search']['get']['parameters'][0][key] = value
            self.assertIn('runtime_parameter_contract_mismatch', self.errors(check_readiness(f, changed, c)))

    def test_path_inherited_local_parameter_and_schema_refs(self):
        f, d, c = fixture()
        parameter = {'name': 'q', 'in': 'query', 'required': True, 'schema': {'$ref': '#/components/schemas/Query'}}
        f['p']['components'] = {'parameters': {'Query': parameter}, 'schemas': {'Query': {'type': 'integer', 'minimum': 1}}}
        f['p']['paths']['/search']['parameters'] = [{'$ref': '#/components/parameters/Query'}]
        d['p']['paths']['/search']['get']['parameters'] = [{'name': 'q', 'in': 'query', 'required': True, 'schema': {'type': 'integer', 'minimum': 1}}]
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        d['p']['paths']['/search']['get']['parameters'][0]['schema']['minimum'] = 0
        self.assertIn('runtime_parameter_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_operation_parameter_overrides_path_parameter(self):
        f, d, c = fixture()
        inherited = {'name': 'q', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}
        override = {'name': 'q', 'in': 'query', 'schema': {'type': 'integer'}}
        f['p']['paths']['/search']['parameters'] = [inherited]
        f['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(override)]
        d['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(override)]
        self.assertEqual('passed', check_readiness(f, d, c)['status'])

    def test_mixed_provider_parameters_and_body_remain_allowed(self):
        f, d, c = fixture()
        f['p']['paths']['/search']['get']['x-aisa-validation'] = 'mixed'
        runtime_parameter = {'name': 'runtime', 'in': 'query', 'schema': {'type': 'string', 'default': False}}
        f['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(runtime_parameter)]
        op = d['p']['paths']['/search']['get']
        op['x-aisa-source'] = {'kind': 'provider_openapi'}
        op['parameters'] = [copy.deepcopy(runtime_parameter), {'name': 'provider', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}]
        op['parameters'][0]['schema']['default'] = 'false'
        op['requestBody'] = {'content': {'application/json': {'schema': {'type': 'object', 'properties': {'provider': {'type': 'string'}}}}}}
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        op['parameters'][0]['required'] = True
        self.assertIn('runtime_parameter_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_parameter_schema_annotations_do_not_hide_property_constraints(self):
        f, d, c = fixture()
        p = {'name': 'q', 'in': 'query', 'schema': {'type': 'object', 'properties': {'description': {'type': 'integer'}}}}
        f['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(p)]
        d['p']['paths']['/search']['get']['parameters'] = [copy.deepcopy(p)]
        actual = d['p']['paths']['/search']['get']['parameters'][0]
        actual['schema']['description'] = 'Editorial prose'
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        actual['schema']['properties']['description']['type'] = 'string'
        self.assertIn('runtime_parameter_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_runtime_body_type_and_required_must_match(self):
        for change in ('type', 'field_required', 'body_required'):
            with self.subTest(change=change):
                f, d, c = fixture()
                body = {'required': True, 'content': {'application/json': {'schema': {
                    'type': 'object', 'required': ['query'], 'properties': {'query': {'type': 'string'}}}}}}
                f['p']['paths']['/search']['get']['requestBody'] = copy.deepcopy(body)
                d['p']['paths']['/search']['get']['requestBody'] = body
                if change == 'body_required':
                    body['required'] = False
                elif change == 'field_required':
                    del body['content']['application/json']['schema']['required']
                else:
                    body['content']['application/json']['schema']['properties']['query']['type'] = 'integer'
                self.assertIn('runtime_body_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_runtime_body_local_refs_annotations_and_implicit_required(self):
        f, d, c = fixture()
        schema = {'type': 'object', 'required': ['b', 'a'], 'properties': {
            'a': {'type': 'string'}, 'b': {'type': 'integer'}}}
        f['p']['components'] = {'requestBodies': {'Input': {'content': {'application/json': {
            'schema': {'$ref': '#/components/schemas/Input'}}}}}, 'schemas': {'Input': schema}}
        f['p']['paths']['/search']['get']['requestBody'] = {'$ref': '#/components/requestBodies/Input'}
        actual = copy.deepcopy(schema)
        actual.update(required=['a', 'b'], description='Editorial prose', examples=[{'a': 'hello', 'b': 1}])
        d['p']['paths']['/search']['get']['requestBody'] = {'required': False, 'description': 'New prose',
            'content': {'application/json': {'schema': actual, 'example': {'a': 'hello', 'b': 1}}}}
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        actual['properties']['b']['type'] = 'string'
        self.assertIn('runtime_body_contract_mismatch', self.errors(check_readiness(f, d, c)))

    def test_mixed_body_preserves_runtime_fields_and_provider_additions(self):
        for validation in ('mixed', 'provider'):
            with self.subTest(validation=validation):
                f, d, c = fixture()
                runtime_schema = {'type': 'object', 'required': ['query'], 'properties': {
                    'query': {'type': 'string'}, 'options': {'type': 'object', 'properties': {'limit': {'type': 'integer'}}}}}
                f['p']['paths']['/search']['get'].update({'x-aisa-validation': validation,
                    'requestBody': {'required': True, 'content': {'application/json': {'schema': runtime_schema}}}})
                actual = copy.deepcopy(runtime_schema)
                actual['properties']['provider'] = {'type': 'boolean'}
                actual['required'].append('provider')
                actual['properties']['options']['properties']['provider_option'] = {'type': 'string'}
                op = d['p']['paths']['/search']['get']
                op.update({'x-aisa-source': {'kind': 'provider_openapi'}, 'requestBody': {
                    'required': True, 'content': {'application/json': {'schema': actual}}}})
                self.assertEqual('passed', check_readiness(f, d, c)['status'])
                for change in ('type', 'required', 'nested_type', 'body_required'):
                    changed = copy.deepcopy(d)
                    body = changed['p']['paths']['/search']['get']['requestBody']
                    schema = body['content']['application/json']['schema']
                    if change == 'type':
                        schema['properties']['query']['type'] = 'integer'
                    elif change == 'required':
                        schema['required'].remove('query')
                    elif change == 'nested_type':
                        schema['properties']['options']['properties']['limit']['type'] = 'string'
                    else:
                        body['required'] = False
                    self.assertIn('runtime_body_contract_mismatch', self.errors(check_readiness(f, changed, c)), change)

    def test_recursive_body_refs_are_finite_and_external_refs_fail_closed(self):
        f, d, c = fixture()
        schema = {'type': 'object', 'properties': {'value': {'type': 'string'}, 'next': {'$ref': '#/components/schemas/Node'}}}
        for document in (f['p'], d['p']):
            document['components'] = {'schemas': {'Node': copy.deepcopy(schema)}}
            document['paths']['/search']['get']['requestBody'] = {'content': {'application/json': {
                'schema': {'$ref': '#/components/schemas/Node'}}}}
        self.assertEqual('passed', check_readiness(f, d, c)['status'])
        d['p']['components']['schemas']['Node']['properties']['value']['type'] = 'integer'
        self.assertIn('runtime_body_contract_mismatch', self.errors(check_readiness(f, d, c)))
        d['p']['paths']['/search']['get']['requestBody'] = {'$ref': 'https://example.invalid/body.json'}
        self.assertIn('unresolved_body_declaration', self.errors(check_readiness(f, d, c)))

    def test_legacy_only_route_overlap_is_reported_not_global_failure(self):
        f, d, c = fixture()
        d['legacy_one'] = fixture('/legacy/shared', 'legacy_one')[1]['p']
        d['legacy_two'] = fixture('/legacy/shared', 'legacy_two')[1]['p']
        result = check_readiness(f, d, c)
        self.assertEqual('passed', result['status'], result)
        self.assertEqual(1, len(result['legacy_route_overlaps']))
        # Identities still have a global namespace, even for legacy-only docs.
        d['legacy_two']['paths']['/legacy/shared']['get']['operationId'] = 'legacy_one'
        self.assertIn('duplicate_operation_id', self.errors(check_readiness(f, d, c)))

    def test_managed_route_conflicting_with_any_legacy_owner_fails(self):
        f, d, c = fixture('/shared', 'managed')
        for name in ('a_legacy', 'z_legacy'):
            d[name] = fixture('/shared', name)[1]['p']
        result = check_readiness(f, d, c)
        self.assertEqual('failed', result['status'])
        self.assertEqual(2, len([e for e in result['global_errors'] if e['code'] == 'duplicate_public_route']))

    def test_runtime_pending_inventory_requires_each_coverage_path(self):
        f, d, c = fixture()
        c['providers']['q'] = [{'catalog': 'q', 'path': '/enabled_pending', 'method': 'ANY', 'status': 'pending',
                                'reason': 'runtime_contract_unavailable', 'publication_state': 'retained'}]
        value = index(['/search'], pending=['/enabled_pending', '/disabled_pending'])
        result = check_readiness(f, d, c, runtime_index=value)
        missing = [error for error in result['global_errors'] if error['code'] == 'pending_endpoint_coverage_missing']
        self.assertEqual([{'code': 'pending_endpoint_coverage_missing', 'provider': 'q', 'path': '/disabled_pending'}], missing)

    def test_grouped_pending_rows_use_original_catalog_ownership(self):
        f, d, c = fixture()
        c['providers']['grouped_output'] = [
            {'catalog': catalog, 'path': path, 'method': 'ANY', 'status': 'pending',
             'reason': 'runtime_contract_unavailable', 'publication_state': 'retained'}
            for catalog, path in [('q', '/enabled_pending'), ('other_catalog', '/disabled_pending')]]
        value = index(['/search'], pending=['/enabled_pending', '/disabled_pending'])
        value['pending_endpoints'][1]['provider'] = 'other_catalog'
        result = check_readiness(f, d, c, runtime_index=value)
        self.assertEqual([], result['global_errors'], result)
        self.assertEqual([], result['missing_inputs'], result)
        c['providers']['grouped_output'][1]['catalog'] = 'wrong_catalog'
        result = check_readiness(f, d, c, runtime_index=value)
        self.assertIn('pending_endpoint_coverage_missing', self.errors(result))

    def test_binding_hash_ignores_pricing_and_source_revision(self):
        op = {'operationId': 'a', 'x-aisa-upstream-path': '/v1', 'x-aisa-revision': {'profile_ref': 'same'}}
        before = binding_hash(op)
        op.update({'x-aisa-source': {'content_hash': 'new'}, 'x-aisa-pricing': {'normal': 5}})
        op['x-aisa-revision']['customer_pricing_ref'] = 'new'
        self.assertEqual(before, binding_hash(op))
        op['x-aisa-upstream-path'] = '/v2'
        self.assertNotEqual(before, binding_hash(op))


if __name__ == '__main__':
    unittest.main()

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deferred_definitions import (DeferredDefinitions, load_deferred_definitions, POLICY_PATH,
                                  POLICY_SHA256, validate_report_deferrals)
from contract_readiness import check_readiness, _pending_key, binding_hash
from gap_evidence import gap_key, response_gap_rows
from publication_surface import publication_hashes
from test_contract_readiness import pending_fixture

ROOT = Path(__file__).resolve().parents[2]


def policy_for(provider, kind, row):
    return DeferredDefinitions({'policy_id': 'synthetic unit fixture', 'scope': {kind: 1},
        'items': [{'provider': provider, 'kind': kind,
                   'gate_identity': (_pending_key if kind == 'request' else gap_key)(row)}]})


class DeferredDefinitionTests(unittest.TestCase):
    def test_exact_approved_bytes_and_all_identity_dimensions(self):
        policy = load_deferred_definitions(ROOT)
        raw = (ROOT / POLICY_PATH).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), POLICY_SHA256)
        items = json.loads(raw)['items']
        self.assertEqual(len(items), 60)
        self.assertEqual(sum(row['kind'] == 'request' for row in items), 10)
        for item in items:
            provider, kind, key = item['provider'], item['kind'], item['gate_identity']
            self.assertTrue(policy.matches(provider, kind, key))
            self.assertFalse(policy.matches(provider + '-other', kind, key))
            self.assertFalse(policy.matches(provider, 'response' if kind == 'request' else 'request', key))
            for i in range(len(key)):
                changed = copy.deepcopy(key)
                changed[i] = ['201'] if isinstance(changed[i], list) else 'changed'
                self.assertFalse(policy.matches(provider, kind, changed), (provider, kind, i))

    def test_missing_policy_never_grants_and_changed_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(load_deferred_definitions(root))
            p = root / POLICY_PATH; p.parent.mkdir(parents=True)
            raw = (ROOT / POLICY_PATH).read_bytes(); p.write_bytes(raw)
            self.assertEqual(publication_hashes(root)[POLICY_PATH], POLICY_SHA256)
            for changed in (raw + b' ', b'{}', raw.replace(b'"enabled"', b'"disabled"', 1)):
                p.write_bytes(changed)
                with self.assertRaises(ValueError):
                    load_deferred_definitions(root)

    def request_fixture(self):
        facts, docs, cov = pending_fixture()
        fact = facts['p']['paths']['/search']['get']
        fact.update({'x-aisa-status': 'enabled', 'x-aisa-revision': {'profile_ref': 'v1'},
                     'x-aisa-pricing': {'cost_contract': 'fixed_success', 'default_request_estimate_usd': 1}})
        row = cov['providers']['p'][0]
        row.update(runtime_status='enabled', source_binding_hash='source', binding_hash=binding_hash(fact))
        return facts, docs, cov, policy_for('p', 'request', row)

    def test_exact_request_deferral_preserves_pending_and_no_operation(self):
        f, d, c, policy = self.request_fixture(); before = copy.deepcopy((f, d, c))
        self.assertEqual(check_readiness(f, d, c)['status'], 'failed')
        report = check_readiness(f, d, c, deferred_definitions=policy)
        result = report['providers']['p']
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(result['deferred_pending']), 1)
        self.assertEqual(result['new_pending'], [])
        self.assertEqual(result['existing_pending'], [])
        self.assertEqual(before, (f, d, c))
        self.assertEqual(d['p']['paths'], {})
        binding = result['deferred_pending'][0]['runtime_binding']
        self.assertEqual(binding['revision'], {'profile_ref': 'v1'})
        self.assertEqual(binding['pricing'], f['p']['paths']['/search']['get']['x-aisa-pricing'])

    def test_request_source_binding_status_or_new_request_remains_blocked(self):
        for change in ('source', 'binding', 'status', 'false_status', 'new'):
            with self.subTest(change=change):
                f, d, c, policy = self.request_fixture()
                row = c['providers']['p'][0]
                fact = f['p']['paths']['/search']['get']
                if change == 'source': row['source_binding_hash'] = 'changed'
                if change == 'binding': fact['x-aisa-upstream-path'] = '/changed'
                if change == 'status': fact['x-aisa-status'] = row['runtime_status'] = 'disabled'
                if change == 'false_status': fact['x-aisa-status'] = 'disabled'
                if change == 'new':
                    f['q'] = copy.deepcopy(f['p']); d['q'] = copy.deepcopy(d['p']); c['providers']['q'] = copy.deepcopy(c['providers']['p'])
                report = check_readiness(f, d, c, deferred_definitions=policy)
                self.assertEqual(report['status'], 'failed')

    def test_original_baseline_stays_separate_and_errors_not_deferred(self):
        f, d, c, policy = self.request_fixture()
        result = check_readiness(f, d, c, copy.deepcopy(c), deferred_definitions=policy)['providers']['p']
        self.assertEqual(len(result['existing_pending']), 1)
        self.assertEqual(result['deferred_pending'], [])
        d['p']['paths'] = copy.deepcopy(f['p']['paths'])
        report = check_readiness(f, d, c, deferred_definitions=policy)
        self.assertEqual(report['status'], 'failed')
        self.assertIn('pending_published_as_complete', {e['code'] for e in report['providers']['p']['errors']})

    def test_response_deferral_keeps_exact_pending_schema_and_changes_block(self):
        fact = {'operationId': 'get_read', 'x-aisa-status': 'enabled', 'x-aisa-validation': 'runtime',
                'responses': {'200': {'description': 'Unknown response definition'}}}
        facts = {'p': {'paths': {'/read': {'get': fact}}}}; docs = copy.deepcopy(facts)
        row = {'path': '/read', 'method': 'GET', 'operation_id': 'get_read', 'status': 'composed',
               'source_binding_hash': 'source', 'response_source_binding_hash': 'response', 'binding_hash': binding_hash(fact)}
        cov = {'schema_version': 2, 'providers': {'p': [row]}}
        cov['response_gaps'] = {'p': response_gap_rows(docs['p'], facts['p'], [row])}
        policy = policy_for('p', 'response', cov['response_gaps']['p'][0]); before = copy.deepcopy(docs)
        report = check_readiness(facts, docs, cov, deferred_definitions=policy)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(len(report['providers']['p']['deferred_response_pending']), 1)
        self.assertEqual(docs, before)
        row['response_source_binding_hash'] = 'changed'
        cov['response_gaps']['p'] = response_gap_rows(docs['p'], facts['p'], [row])
        self.assertEqual(check_readiness(facts, docs, cov, deferred_definitions=policy)['status'], 'failed')

    def test_export_rejects_unbound_policy_or_unapproved_duplicate_deferral(self):
        policy = load_deferred_definitions(ROOT)
        report = {'deferred_definitions': policy.metadata,
                  'composed_candidate': {'deferred_definitions': policy.metadata}, 'providers': {}}
        validate_report_deferrals(ROOT, report)
        item = next(row for row in json.loads((ROOT / POLICY_PATH).read_text())['items'] if row['kind'] == 'request')
        fields = ('catalog', 'operation_id', 'path', 'method', 'binding_hash', 'reason_code', 'source_binding_hash', 'runtime_status')
        row = dict(zip(fields, item['gate_identity']))
        valid = copy.deepcopy(report)
        valid['providers'] = {item['provider']: {'deferred_pending': [row]}}
        validate_report_deferrals(ROOT, valid)
        duplicate = copy.deepcopy(valid)
        duplicate['providers'][item['provider']]['deferred_pending'].append(copy.deepcopy(row))
        with self.assertRaises(ValueError): validate_report_deferrals(ROOT, duplicate)
        tampered = copy.deepcopy(valid)
        tampered['providers'][item['provider']]['deferred_pending'][0]['source_binding_hash'] = 'changed'
        with self.assertRaises(ValueError): validate_report_deferrals(ROOT, tampered)
        for bad in ({}, {'deferred_definitions': policy.metadata, 'composed_candidate': {}},
                    {**report, 'providers': {'p': {'deferred_pending': [{'runtime_status': 'enabled'}]}}}):
            with self.assertRaises(ValueError): validate_report_deferrals(ROOT, bad)


if __name__ == '__main__': unittest.main()

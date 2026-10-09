"""Owning 204 declarations never infer payloads or replace request authority."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from source_governance import policy_errors
from prepare_agentmail_response_reference import OPERATIONS, extract, merge, prepare
ROOT = Path(__file__).resolve().parents[2]


def fixtures():
    after = json.loads((ROOT/'openapi/upstream/agentmail-official.json').read_text())
    before = copy.deepcopy(after)
    before['info']['x-aisa-source'] = copy.deepcopy(after['info']['x-aisa-source']['retained_request_source'])
    owning = {'openapi': '3.0.1', 'paths': {}}
    for method, path in OPERATIONS:
        responses = before['paths'][path][method]['responses']
        responses.pop('204')
        responses['200'] = {'description': 'Successful response'}
        owning['paths'].setdefault(path, {})[method] = {'responses': {'204': {'description': ''}}}
    return before, owning, after


class AgentMailResponseTests(unittest.TestCase):
    def test_exact_eleven_success_only_changes_preserve_all_other_graph(self):
        before, owning, after = fixtures()
        merged = merge(before, owning)
        after['info']['x-aisa-source'] = before['info']['x-aisa-source']
        self.assertEqual(merged, after)
        self.assertEqual(merged['components'], before['components'])
        self.assertEqual(merged.get('security'), before.get('security'))
        self.assertEqual(len(before['info']['x-aisa-source']['retained_operations']), 5)
        self.assertEqual(len(OPERATIONS), 11)

    def test_only_formal_exact_204_accepted_not_examples_or_other_success(self):
        _, owning, _ = fixtures()
        method, path = OPERATIONS[0]
        for responses in ({'200': {'description': 'Successful response'}},
                          {'204': {'description': '', 'content': {'application/json': {'schema': {}}}}},
                          {'204': {'description': ''}, '200': {'description': 'Success'}},
                          {'default': {'description': 'Success', 'examples': {'status': 204}}}):
            changed = copy.deepcopy(owning)
            changed['paths'][path][method]['responses'] = responses
            with self.assertRaises(ValueError): extract(changed)

    def test_missing_or_different_method_and_path_do_not_alias(self):
        _, owning, _ = fixtures()
        for path_change in [False, True]:
            changed = copy.deepcopy(owning)
            method, path = OPERATIONS[0]
            if path_change: changed['paths'][path+'/'] = changed['paths'].pop(path)
            else: changed['paths'][path]['get'] = changed['paths'][path].pop(method)
            with self.assertRaises(ValueError): extract(changed)

    def test_pinned_bytes_and_hosted_contract_drift_rejected(self):
        with self.assertRaises(ValueError): prepare(b'{}', b'{}', '2026-10-09T00:00:00Z')
        before, owning, _ = fixtures()
        method, path = OPERATIONS[0]
        before['paths'][path][method]['responses']['200']['content'] = {'application/json': {'schema': {'type': 'string'}}}
        with self.assertRaises(ValueError): merge(before, owning)

    def test_synthetic_actual_style_any_keeps_methods_request_identity_and_price(self):
        before, _, after = fixtures()
        facts = {'openapi':'3.1.0','info':{'x-aisa-document':{'facts_hash':'synthetic'}},'paths':{}}
        for _, path in OPERATIONS:
            public = path.replace('/v0', '/apis/v1/agentmail', 1)
            facts['paths'][public] = {'x-aisa-any': {'operationId': 'route_'+str(len(facts['paths'])), 'x-aisa-validation':'provider','x-aisa-passthrough':True,'x-aisa-upstream-path':path,'x-aisa-status':'enabled','x-aisa-pricing':{'price':1},'responses':{'200':{'description':'Successful response'}}}}
        old, old_pending = compose(facts, before)
        new, new_pending = compose(facts, after)
        self.assertEqual(old_pending, new_pending)
        self.assertEqual(old_pending, [])
        self.assertEqual(len(old['info']['x-aisa-document']['response_pending'])-len(new['info']['x-aisa-document']['response_pending']), 11)
        self.assertEqual(set(old['paths']), set(new['paths']))
        for path, item in old['paths'].items():
            self.assertEqual(set(item), set(new['paths'][path]))
            for method, operation in item.items():
                other = new['paths'][path][method]
                for key in ('operationId','requestBody','parameters','x-aisa-pricing','x-aisa-validation'):
                    self.assertEqual(operation.get(key), other.get(key), (path, method, key))

    def test_registry_pins_composite_and_normal_importer_uses_both_sources(self):
        import io
        import yaml
        from unittest.mock import patch
        import import_upstream
        import prepare_agentmail_response_reference as converter
        entry=yaml.safe_load((ROOT/'openapi/registry.yaml').read_text())['providers']['agentmail']['upstream']
        self.assertEqual(entry['url'],converter.URL)
        calls=[]
        def fetch(request, **kwargs):
            calls.append(request.full_url)
            return io.BytesIO(b'base' if request.full_url==converter.BASE_URL else b'owning')
        with patch.object(import_upstream,'urlopen',fetch), patch.object(converter,'prepare',return_value={'sentinel':True}) as prepare_mock:
            self.assertEqual(import_upstream.import_source('agentmail',converter.URL),{'sentinel':True})
        self.assertEqual(calls,[converter.BASE_URL,converter.URL])
        self.assertEqual(prepare_mock.call_args.args[:2],(b'base',b'owning'))

    def test_honest_composite_policy_and_conflict_no_approval_claim(self):
        _, _, after = fixtures()
        source=after['info']['x-aisa-source']
        self.assertEqual(policy_errors(source), [])
        self.assertEqual(len(source['source_pages']),2)
        self.assertEqual(source['refresh_policy'],'pinned')
        self.assertIn('200',source['hosted_status_conflict'])
        self.assertIn('204',source['hosted_status_conflict'])
        self.assertNotIn('reviewer',source)
        self.assertNotIn('review_ref',source)
        self.assertEqual(len(source['response_overrides']),11)


if __name__ == '__main__': unittest.main()

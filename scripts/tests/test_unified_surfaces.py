"""Independent expectations for JSON and readable request projections."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from readable_contract_notes import readable_block, update_readable_block


class UnifiedSurfacesTests(unittest.TestCase):
    def test_request_context_constraints_auth_recursion_and_numeric_values(self):
        operation = {'operationId': 'one', 'parameters': [
            {'name': 'target', 'in': 'query', 'required': True,
             'schema': {'type': 'string', 'enum': ['description', 'example']}},
            {'name': 'limit', 'in': 'query', 'schema': {'type': 'integer', 'default': 9007199254740993}}],
            'requestBody': {'required': True, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Node'}}}}}
        document = {'servers': [{'url': 'https://api.aisa.one'}], 'security': [{'Bearer': []}],
                    'info': {'x-aisa-document': {'facts_hash': 'f' * 64}},
                    'paths': {'/one': {'parameters': [{'name': 'limit', 'in': 'query', 'required': True}], 'post': operation}},
                    'components': {'securitySchemes': {'Bearer': {'type': 'http', 'scheme': 'bearer'}},
                                   'schemas': {'Node': {'type': 'object', 'required': ['description'], 'properties': {
                                       'description': {'type': 'number', 'default': 0.125, 'example': {'$ref': '#/not-a-schema'}},
                                       'example': {'$ref': '#/components/schemas/Node'}}}}}}
        before = copy.deepcopy(document)
        for language in ('en', 'zh'):
            block = readable_block(operation, language, document=document, method='post', path='/one', spec_path='openapi/p.json')
            request = json.loads(re.search(r'```json\n(.*?)\n```', block, re.S)[1])
            self.assertEqual(request['method'], 'POST')
            self.assertEqual(request['operationId'], 'one')
            self.assertEqual(request['parameters'], operation['parameters'][::-1])
            self.assertEqual(request['security'], [{'Bearer': []}])
            self.assertEqual(request['components'], document['components'])
            self.assertEqual(request['requestBody'], operation['requestBody'])
            self.assertIn('**target:** query; ' + ('required' if language == 'en' else '必填'), block)
            self.assertIn('f' * 64, block)
            self.assertIn('9007199254740993', block)
        self.assertEqual(document, before)

    def test_auth_reference_chain_is_complete_and_missing_scheme_fails(self):
        operation = {'operationId': 'secured'}
        document = {'paths': {'/one': {'get': operation}}, 'security': [{'Auth': []}],
                    'components': {'securitySchemes': {'Auth': {'$ref': '#/components/securitySchemes/Concrete'},
                    'Concrete': {'type': 'http', 'scheme': 'bearer'}}}}
        context = dict(document=document, method='get', path='/one', spec_path='openapi/p.json')
        request = json.loads(re.search(r'```json\n(.*?)\n```', readable_block(operation, **context), re.S)[1])
        self.assertEqual(request['components']['securitySchemes']['Auth'], {'type': 'http', 'scheme': 'bearer'})
        document['security'] = [{'Missing': []}]
        with self.assertRaisesRegex(ValueError, 'unresolved request security'):
            readable_block(operation, **context)

    def test_request_and_price_refresh_are_idempotent_and_keep_auth_override(self):
        operation = {'operationId': 'free', 'security': [], 'x-aisa-pricing': {'default_request_estimate_usd': 0}}
        document = {'paths': {'/free': {'get': operation}}, 'security': [{'Bearer': []}]}
        context = dict(document=document, method='get', path='/free', spec_path='openapi/free.json')
        rendered = update_readable_block('Human prose.\n', operation, **context)
        self.assertEqual(update_readable_block(rendered, operation, **context), rendered)
        self.assertIn('"security": []', rendered)
        operation['parameters'] = [{'name': 'date', 'in': 'query', 'required': True, 'schema': {'type': 'string', 'format': 'date'}}]
        changed = update_readable_block(rendered, operation, **context)
        self.assertIn('**date:** query; required', changed)
        self.assertEqual(changed.count('## Request contract'), 1)
        self.assertTrue(changed.startswith('Human prose.'))

    def test_historical_locale_url_refreshes_without_retaining_removed_operations(self):
        from test_runtime_contracts import PullTests
        from pull_openapi import stage
        fixture = PullTests(); fixture.setUp()
        try:
            source = {'openapi': '3.1.0', 'info': {'title': 'Historical'}, 'paths': {}}
            (fixture.root / 'openapi/legacy.json').write_text(json.dumps(source))
            target = fixture.root / 'openapi/zh/legacy.json'
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(dict(source, paths={'/removed': {'get': {'operationId': 'stale'}}})))
            changes, _ = stage(fixture.root, fixture.root / 'facts', 'unused')
            self.assertIn(target, changes)
            self.assertEqual(json.loads(changes[target])['paths'], {})
        finally:
            fixture.tearDown()

    def test_aggregate_json_matches_yaml_and_is_not_reimported(self):
        script = Path(__file__).resolve().parents[1] / 'runtime_consolidate_openapi.py'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'openapi').mkdir()
            (root / 'llms.txt').write_text('# Human-written index\n')
            source = {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'version': '1'},
                      'paths': {'/one': {'get': {'operationId': 'one', 'responses': {'200': {'description': 'ok'}},
                                               'parameters': [{'name': 'id', 'in': 'query', 'schema': {'type': 'integer', 'default': 9007199254740993}}]}}}}
            (root / 'openapi/p.json').write_text(json.dumps(source))
            command = [sys.executable, str(script), '--root', temp, '--output', str(root / 'openapi.yaml')]
            subprocess.run(command, check=True, capture_output=True)
            first = (root / 'openapi/openapi.json').read_bytes()
            self.assertEqual(json.loads(first), yaml.safe_load((root / 'openapi.yaml').read_text()))
            self.assertIn(b'9007199254740993', first)
            import hashlib
            index = (root / 'llms.txt').read_text()
            self.assertIn(hashlib.sha256((root / 'openapi.yaml').read_bytes()).hexdigest(), index)
            self.assertTrue(index.startswith('# Human-written index'))
            self.assertEqual(index.count('aisa-contract-source:start'), 1)
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual((root / 'openapi/openapi.json').read_bytes(), first)

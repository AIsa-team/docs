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
    def test_bound_llms_is_staged_with_every_generated_candidate(self):
        root = Path(__file__).resolve().parents[2]
        publish = yaml.safe_load((root / '.github/workflows/pull-openapi.yml').read_text())
        script = next(step['run'] for step in publish['jobs']['compose']['steps'] if step.get('id') == 'publish')
        staging = next(line.split() for line in script.splitlines() if line.strip().startswith('git add openapi '))
        self.assertIn('llms.txt', staging)
        refresh = yaml.safe_load((root / '.github/workflows/refresh-upstream.yml').read_text())
        candidate = next(step for step in refresh['jobs']['refresh']['steps'] if 'add-paths' in step.get('with', {}))
        self.assertIn('llms.txt', candidate['with']['add-paths'].splitlines())
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        trigger = workflow.get('on', workflow.get(True))
        for event in ('pull_request', 'push'):
            self.assertIn('llms.txt', trigger[event]['paths'])

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

    def test_availability_is_exact_bilingual_and_absence_is_not_enabled(self):
        for status in (None, "enabled", "disabled", "unknown"):
            operation = {"operationId": "historical", "x-aisa-pricing": {"unit_rate_usd": 0.02}}
            if status is not None:
                operation["x-aisa-status"] = status
            document = {"paths": {"/one": {"get": operation}}}
            before = copy.deepcopy(document)
            for language in ("en", "zh"):
                context = dict(document=document, method="get", path="/one", spec_path="openapi/p.json")
                block = readable_block(operation, language, **context)
                request = json.loads(re.search(r'```json\n(.*?)\n```', block, re.S)[1])
                self.assertEqual(request.get("x-aisa-status"), status)
                self.assertEqual("x-aisa-status" in request, status is not None)
                self.assertEqual(request["x-aisa-pricing"], operation["x-aisa-pricing"])
                warning = "This endpoint is disabled and cannot be called" if language == "en" else "此接口已停用，无法调用"
                self.assertEqual(warning in block, status == "disabled")
                rendered = update_readable_block("Manual historical prose.\n", operation, language, **context)
                self.assertTrue(rendered.startswith("Manual historical prose.\n"))
                self.assertEqual(update_readable_block(rendered, operation, language, **context), rendered)
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
        operation.update({'x-aisa-status': 'disabled', 'x-aisa-contract-state': 'retained_legacy'})
        block = readable_block(operation, **context)
        self.assertIn('Incomplete historical declaration (disabled)', block)
        self.assertIn('unresolved_security_scheme:Missing', block)
        request = json.loads(re.search(r'```json\n(.*?)\n```', block, re.S)[1])
        self.assertEqual(request['security'], [{'Missing': []}])
        self.assertNotIn('securitySchemes', request.get('components', {}))

    def test_request_and_price_refresh_are_idempotent_and_keep_auth_override(self):
        operation = {'operationId': 'free', 'security': [], 'x-aisa-pricing': {'default_request_estimate_usd': 0}}
        document = {'paths': {'/free': {'get': operation}}, 'security': [{'Bearer': []}]}
        context = dict(document=document, method='get', path='/free', spec_path='openapi/free.json')
        rendered = update_readable_block('Human prose.\n', operation, **context)
        self.assertEqual(update_readable_block(rendered, operation, **context), rendered)
        self.assertIn('"security": []', rendered)
        request = json.loads(re.search(r'```json\n(.*?)\n```', rendered, re.S)[1])
        self.assertEqual(request['x-aisa-pricing'], {'default_request_estimate_usd': 0})
        operation['x-aisa-pricing']['request_cost_drivers'] = {'kind': 'plan_units', 'formula': {'input': 'count', 'unit_scale': 10}}
        changed_price = update_readable_block(rendered, operation, **context)
        self.assertIn('"unit_scale": 10', changed_price)
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

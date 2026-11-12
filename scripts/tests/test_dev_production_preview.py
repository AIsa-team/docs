"""Production contracts previewed on dev without publishing production."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sync_dev_runtime as dev
from readable_contract_notes import readable_block
import test_dev_runtime
import test_fetch_runtime_release


class DevProductionPreviewTests(unittest.TestCase):
    def test_production_acquisition_uses_verified_immutable_release_bytes(self):
        revision, compiler, reader, _, payload, calls = test_fetch_runtime_release.PublicReleaseTests().fixture()
        files, source = dev.acquire_production(reader)
        self.assertEqual(files['example.json'], payload['providers/example.json'])
        self.assertEqual(files['index.json'], payload['index.json'])
        self.assertEqual(source['artifact_revision'], revision)
        self.assertEqual(source['compiler_revision'], compiler)
        self.assertNotIn('/info/openapi/example.json', calls)
        self.assertGreaterEqual(calls.count('/public/api-contract/current'), 3)
        revision, _, reader, _, _, _ = test_fetch_runtime_release.PublicReleaseTests().fixture()

        def corrupt(path):
            raw, headers = reader(path)
            return (raw + b' ', headers) if '/releases/' in path else (raw, headers)

        with self.assertRaisesRegex(ValueError, 'hash or ETag'):
            dev.acquire_production(corrupt)

    def test_production_preview_keeps_api_origin_but_links_to_dev_docs(self):
        _, _, reader = test_dev_runtime.DevRuntimeTests().fixture()
        files = dev.acquire(reader)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            (root / 'docs.json').write_text('{"navigation":{"languages":[]}}')
            outputs, report = dev.generate(root, files, source='production')
            self.assertEqual(report['environment'], 'dev')
            self.assertEqual(report['runtime_origin'], 'https://api.aisa.one')
            self.assertEqual(report['source_environment'], 'production')
            self.assertFalse(report['formal_publication'])
            page = outputs['api-reference/similarweb/published_identity.mdx'].decode()
            self.assertIn('https://api.aisa.one/apis/v1/similarweb/test', page)
            self.assertNotIn('https://dev-api.aisa.one', page)
            self.assertIn('refs/heads/dev/openapi/similarweb.json', page)
            self.assertNotIn('docs/publication/current.json', outputs)
            for name, raw in outputs.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            repeated, _ = dev.generate(root, files, source='production')
            self.assertEqual(outputs, repeated)

    def test_production_source_cannot_write_main_or_skip_a_source_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            (root / 'docs/dev-runtime.json').write_text(json.dumps({
                'environment': 'dev', 'runtime_origin': dev.DEV_ORIGIN,
                'formal_publication': False, 'status': 'generated', 'inputs_sha256': 'same'}))
            with patch.object(dev.subprocess, 'check_output', return_value='main'), \
                    patch.object(dev, 'acquire_production') as acquire, self.assertRaises(ValueError):
                dev.sync(root, source='production', write=True)
            acquire.assert_not_called()
            with patch.object(dev.subprocess, 'check_output', return_value='dev'), \
                    patch.object(dev.subprocess, 'run'), \
                    patch.object(dev, 'acquire_production', return_value=({'index.json': b'{}', 'category.json': b'{}'}, {})), \
                    patch.object(dev, 'inputs_sha256', return_value='same'), \
                    patch.object(dev, 'generate', return_value=({}, {'status': 'generated'})) as generate:
                dev.sync(root, source='production', if_changed=True)
            generate.assert_called_once()

    def test_source_switch_normalizes_retained_history_before_hashing(self):
        _, _, reader = test_dev_runtime.DevRuntimeTests().fixture()
        files = dev.acquire(reader)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            (root / 'docs.json').write_text('{"navigation":{"languages":[]}}')

            def write(outputs):
                for name, raw in outputs.items():
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)

            write(dev.generate(root, files)[0])
            spec = root / 'openapi/similarweb.json'
            document = json.loads(spec.read_text())
            old = copy.deepcopy(document['paths']['/apis/v1/similarweb/test']['post'])
            old.update(operationId='historic_identity', servers=[{'url': dev.DEV_ORIGIN}])
            for key in ('x-aisa-identity', 'x-aisa-runtime-operation'):
                old.pop(key, None)
            document['paths']['/apis/v1/similarweb/retired'] = {'post': old}
            spec.write_text(json.dumps(document))
            for source, origin in [('production', dev.PROD_ORIGIN), ('dev', dev.DEV_ORIGIN)]:
                with self.subTest(source=source):
                    before = spec.read_bytes()
                    outputs, _ = dev.generate(root, files, source=source)
                    self.assertEqual(spec.read_bytes(), before)
                    write(outputs)
                    repeated, _ = dev.generate(root, files, source=source)
                    self.assertEqual([name for name in outputs if outputs[name] != repeated.get(name)], [])
                    retained = json.loads(outputs['openapi/similarweb.json'])['paths']['/apis/v1/similarweb/retired']['post']
                    self.assertEqual(retained['servers'], [{'url': origin}])

    def test_disabled_legacy_labels_are_not_a_published_tariff(self):
        legacy = {'cost_tier': 'low', 'model': 'per_request'}
        for language, archive, unknown in (
                ('en', 'Historical archive: disabled, cannot be called, and no price is published.', 'Billing method unavailable.'),
                ('zh', '历史归档接口：已停用，不可调用，价格未发布。', '计费方式暂不可用。')):
            operation = {'x-aisa-status': 'disabled', 'x-aisa-pricing': copy.deepcopy(legacy)}
            before = copy.deepcopy(operation)
            self.assertIn(archive, readable_block(operation, language))
            self.assertNotIn(unknown, readable_block(operation, language))
            self.assertEqual(operation, before)
            operation['x-aisa-status'] = 'enabled'
            self.assertIn(unknown, readable_block(operation, language))
            operation.update({'x-aisa-status': 'disabled', 'x-aisa-pricing': {
                'kind': 'fixed_request', 'customer_micros_usd': 5000}})
            self.assertIn('$0.005', readable_block(operation, language))
            self.assertNotIn(archive, readable_block(operation, language))

    def test_production_presentation_clears_dev_notices_and_localizes_disabled_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            paths = {'/current': {'get': {'operationId': 'current', 'x-aisa-status': 'enabled'}},
                     '/old': {'get': {'operationId': 'old', 'x-aisa-status': 'disabled',
                                     'x-aisa-pricing': {'cost_tier': 'low', 'model': 'per_request'}}}}
            (root / 'openapi/example.json').write_text(json.dumps({'paths': paths}))
            (root / 'openapi/unverified.json').write_text(json.dumps({'paths': {
                '/legacy': {'get': {'operationId': 'legacy'}}}}))
            (root / 'docs.json').write_text('{"navigation":{"pages":[]}}')
            for language, prefix in [('en', ''), ('zh', 'zh/')]:
                for name in ('current', 'old'):
                    page = root / (prefix + 'api-reference/example/' + name + '.mdx')
                    page.parent.mkdir(parents=True, exist_ok=True)
                    page.write_text('---\nopenapi: "openapi/example.json GET /' + name + '"\n---\n'
                                    + dev.ARCHIVE_NOTE + dev.HISTORIC_NOTES[language])
                legacy = root / (prefix + 'api-reference/example/legacy.mdx')
                legacy.write_text('---\nopenapi: "openapi/unverified.json GET /legacy"\n---\n')
            dev.scope_presentation(root, {'info': {}, 'paths': {}}, {'example': {}}, source='production')
            for language, prefix in [('en', ''), ('zh', 'zh/')]:
                current = (root / (prefix + 'api-reference/example/current.mdx')).read_text()
                self.assertNotIn('<Warning>', current)
                old = (root / (prefix + 'api-reference/example/old.mdx')).read_text()
                self.assertNotIn('dev Runtime', old)
                self.assertIn(dev.DISABLED_NOTES[language], old)
                self.assertIn('历史归档接口' if language == 'zh' else 'Historical archive', old)
                legacy = (root / (prefix + 'api-reference/example/legacy.mdx')).read_text()
                self.assertIn(dev.PRODUCTION_NOTES[language], legacy)
                self.assertNotIn('历史归档接口' if language == 'zh' else 'Historical archive', legacy)

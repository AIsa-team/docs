import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose
from pull_openapi import stage
from runtime_registry import public_mirror_index
from test_runtime_contracts import facts, operation, mirror
import consolidate_openapi as consolidate


def contract(catalog, method='get', validation='runtime'):
    document = facts(validation, method)
    document['info']['title'] = catalog.title()
    document['info']['x-aisa-document']['facts_hash'] = 'sha256:' + catalog
    op = operation(document)
    op['operationId'] = catalog + '_test'
    document['paths'] = {'/apis/v1/' + catalog + '/test': {method: op}}
    return document


class FullRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'openapi').mkdir()
        (self.root / 'facts').mkdir()
        (self.root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
        (self.root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [{'language': lang, 'tabs': [{'tab': title, 'groups': []}]} for lang, title in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))

    def tearDown(self):
        self.temp.cleanup()

    def sources(self, documents):
        (self.root / 'facts/category.json').write_text(json.dumps({'apis': [{'id': key} for key in documents]}))
        for key, doc in documents.items():
            (self.root / f'facts/{key}.json').write_text(json.dumps(doc))

    def publish(self, changes):
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def pull(self):
        return stage(self.root, self.root / 'facts', 'unused')

    def test_new_catalog_and_new_endpoint_are_discovered_without_registry_edits(self):
        alpha = contract('alpha')
        self.sources({'alpha': alpha})
        self.publish(self.pull()[0])
        registry = yaml.safe_load((self.root / 'openapi/registry.yaml').read_text())
        self.assertEqual(set(registry['providers']), {'alpha'})
        self.assertEqual(self.pull()[0], {})
        extra = copy.deepcopy(operation(alpha))
        extra['operationId'] = 'alpha_new'
        alpha['paths']['/apis/v1/alpha/new'] = {'post': extra}
        alpha['info']['x-aisa-document']['facts_hash'] += '-changed'
        self.sources({'alpha': alpha, 'brand-new': contract('brand-new')})
        changes, summary = self.pull()
        self.assertEqual(summary['alpha']['operations'], 2)
        self.assertEqual(summary['brand-new']['operations'], 1)
        self.publish(changes)
        coverage = json.loads((self.root / 'openapi/coverage.json').read_text())
        self.assertEqual(sum(len(rows) for rows in coverage['providers'].values()), 3)
        self.assertTrue(all(row['status'] == 'composed' for rows in coverage['providers'].values() for row in rows))
        self.assertEqual(self.pull()[0], {})

    def test_passthrough_provider_requires_only_one_upstream_url(self):
        source = contract('alpha', method='post', validation='provider')
        self.sources({'alpha': source})
        (self.root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders:\n  alpha:\n    upstream: https://example.test/openapi.json\n')
        upstream = mirror()
        upstream['info']['x-aisa-source']['kind'] = 'provider_openapi'
        upstream['info']['x-aisa-source']['url'] = 'https://example.test/openapi.json'
        upstream['paths'] = {operation(source)['x-aisa-upstream-path']: next(iter(upstream['paths'].values()))}
        with patch('pull_openapi.import_source', return_value=upstream) as fetch:
            changes, summary = self.pull()
            self.assertEqual(summary['alpha']['pending'], 0)
            self.assertEqual(summary['alpha']['operations'], 1)
            fetch.assert_called_once_with('alpha', 'https://example.test/openapi.json')
            self.publish(changes)
        with patch('pull_openapi.import_source', side_effect=AssertionError('Existing mirror was fetched again')):
            self.assertEqual(self.pull()[0], {})

    def test_generation_time_does_not_churn_localized_pages_or_provider_spec(self):
        source = contract('alpha')
        self.sources({'alpha': source})
        self.publish(self.pull()[0])
        source['info']['x-aisa-document']['generated_at'] = '2030-01-01'
        self.sources({'alpha': source})
        changes, summary = self.pull()
        self.assertFalse(summary['alpha']['changed'])
        self.assertTrue(all('.cache' in path.parts for path in changes), list(changes))

    def test_group_preserves_catalog_membership_and_policy(self):
        (self.root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders:\n  weather:\n    group: [forecast, marine]\n')
        forecast, marine = contract('forecast'), contract('marine')
        forecast['info']['x-aisa-plans'] = {'payg': 1.2}
        marine['info']['x-aisa-plans'] = {'payg': 1.6}
        self.sources({'forecast': forecast, 'marine': marine})
        self.publish(self.pull()[0])
        registry = yaml.safe_load((self.root / 'openapi/registry.yaml').read_text())
        self.assertEqual(set(registry['providers']), {'weather'})
        document = json.loads((self.root / 'openapi/weather.json').read_text())
        self.assertEqual(document['paths']['/apis/v1/marine/test']['get']['x-aisa-catalog-id'], 'marine')
        self.assertEqual(document['info']['x-aisa-catalogs']['marine']['x-aisa-plans']['payg'], 1.6)
        with patch.object(consolidate, 'OPENAPI_DIR', str(self.root / 'openapi')):
            merged = consolidate.build_unified_spec()
        self.assertEqual(merged['info']['x-aisa-document']['providers']['weather']['catalog_ids'], ['forecast', 'marine'])
        self.assertEqual(merged['paths']['/apis/v1/marine/test']['get']['x-aisa-docs-url'], 'https://aisa.one/docs/api-reference/weather/marine_test')
        self.assertEqual(self.pull()[0], {})

    def test_manual_public_mirror_any_cutover_keeps_ids_response_and_old_page_urls(self):
        legacy = contract('alpha')
        legacy['info'].pop('x-aisa-document')
        legacy['servers'] = [{'url': 'https://api.aisa.one/apis/v1'}]
        first = operation(legacy)
        first['operationId'] = 'published_read'
        first['responses']['200']['content'] = {'application/json': {'schema': {'type': 'integer'}, 'example': 7}}
        second = copy.deepcopy(first)
        second['operationId'] = 'published_write'
        legacy['paths'] = {'/alpha/test': {'get': first, 'post': second}}
        (self.root / 'openapi/old-split.json').write_text(json.dumps(legacy))
        upstream = copy.deepcopy(legacy)
        upstream['info']['x-aisa-source'] = {'kind': 'manual', 'path_space': 'public', 'url': 'https://example.invalid/committed-source', 'content_hash': 'sha256:old', 'fetched_at': '2026-09-29', 'converter': 'fixture@1'}
        (self.root / 'openapi/upstream').mkdir()
        (self.root / 'openapi/upstream/old-split.json').write_text(json.dumps(upstream))
        for method in ['get', 'post']:
            page = self.root / f'api-reference/old-split/{method}_original-slug.mdx'
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(f'---\ntitle: "Original"\nopenapi: "openapi/old-split.json {method.upper()} /alpha/test"\n---\nKeep {method} prose.\n')
        runtime = contract('alpha', 'x-aisa-any', 'provider')
        operation(runtime)['operationId'] = 'published_write'  # Base identity must not overwrite GET.
        self.sources({'alpha': runtime})
        changes, summary = self.pull()
        self.assertEqual(summary['alpha']['operations'], 2)
        self.publish(changes)
        generated = json.loads((self.root / 'openapi/alpha.json').read_text())
        methods = generated['paths']['/apis/v1/alpha/test']
        self.assertEqual(methods['get']['operationId'], 'published_read')
        self.assertEqual(methods['post']['operationId'], 'published_write')
        self.assertEqual(methods['get']['responses']['200']['content'], first['responses']['200']['content'])
        self.assertEqual(methods['get']['x-aisa-source']['kind'], 'manual')
        self.assertEqual(methods['get']['x-aisa-docs-url'], 'https://aisa.one/docs/api-reference/old-split/get_original-slug')
        self.assertEqual(json.loads((self.root / 'openapi/old-split.json').read_text())['paths'], {})
        for method in ['get', 'post']:
            text = (self.root / f'api-reference/old-split/{method}_original-slug.mdx').read_text()
            self.assertIn(f'Keep {method} prose.', text)
            self.assertIn(f'openapi/alpha.json {method.upper()} /apis/v1/alpha/test', text)
        self.assertEqual(yaml.safe_load((self.root / 'openapi/registry.yaml').read_text())['providers']['alpha']['legacy_sources'], ['old-split'])
        self.assertEqual(self.pull()[0], {})

    def test_missing_mirror_keeps_old_docs_and_does_not_block_other_catalog(self):
        legacy = contract('alpha')
        (self.root / 'openapi/alpha.json').write_text(json.dumps(legacy))
        original = (self.root / 'openapi/alpha.json').read_text()
        self.sources({'alpha': contract('alpha', validation='provider'), 'beta': contract('beta')})
        changes, summary = self.pull()
        self.assertIn('blocked', summary['alpha'])
        self.assertEqual(summary['beta']['operations'], 1)
        self.publish(changes)
        self.assertEqual((self.root / 'openapi/alpha.json').read_text(), original)
        report = json.loads((self.root / 'openapi/coverage.json').read_text())
        self.assertEqual(report['providers']['alpha'][0]['reason'], 'upstream operation missing')

    def test_one_catalog_identity_collision_does_not_block_other_catalogs(self):
        broken = contract('alpha')
        operation(broken)['operationId'] = 'x' * 56 + '_first'
        extra = copy.deepcopy(operation(broken))
        extra['operationId'] = 'x' * 56 + '_second'
        broken['paths']['/apis/v1/alpha/other'] = {'get': extra}
        self.sources({'alpha': broken, 'beta': contract('beta')})
        changes, summary = self.pull()
        self.assertIn('operationId prefix collision', summary['alpha']['blocked'])
        self.assertEqual(summary['beta']['operations'], 1)
        self.publish(changes)
        rows = json.loads((self.root / 'openapi/coverage.json').read_text())['providers']['alpha']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('operationId prefix collision' in row['reason'] for row in rows))
        self.assertFalse((self.root / 'openapi/alpha.json').exists())

    def test_unavailable_catalog_reports_each_inventory_endpoint(self):
        self.sources({'missing': {}})
        directory = self.root / 'facts/inventory'
        directory.mkdir()
        (directory / 'missing.json').write_text(json.dumps({'api': {'endpoint_groups': [{'endpoints': [{'method': 'GET', 'path': '/apis/v1/missing/a'}, {'method': 'POST', 'path': '/apis/v1/missing/b'}]}]}}))
        changes, summary = self.pull()
        self.publish(changes)
        rows = json.loads((self.root / 'openapi/coverage.json').read_text())['providers']['missing']
        self.assertEqual(len(rows), 2)
        self.assertEqual(summary['missing']['pending'], 2)
        self.assertTrue(all(row['reason'] == 'runtime_contract_unavailable' for row in rows))
        self.assertFalse((self.root / 'openapi/missing.json').exists())

    def test_legacy_consumer_metadata_uses_registry_sources(self):
        (self.root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders:\n  twitter:\n    legacy_sources: [twitter-actions]\n')
        legacy = contract('twitter')
        legacy['info'].pop('x-aisa-document')
        (self.root / 'openapi/twitter-actions.json').write_text(json.dumps(legacy))
        page = self.root / 'api-reference/twitter/actual-old-page.mdx'
        page.parent.mkdir(parents=True)
        page.write_text('---\nopenapi: "openapi/twitter-actions.json GET /apis/v1/twitter/test"\n---\n')
        with patch.object(consolidate, 'OPENAPI_DIR', str(self.root / 'openapi')):
            document = consolidate.build_unified_spec()
        metadata = document['info']['x-aisa-document']['providers']['twitter-actions']
        self.assertEqual(metadata['catalog_ids'], ['twitter'])
        self.assertEqual(metadata['registry_provider'], 'twitter')
        op = document['paths']['/apis/v1/twitter/test']['get']
        self.assertEqual(op['x-aisa-catalog-id'], 'twitter')
        self.assertEqual(op['x-aisa-provider'], 'twitter-actions')
        self.assertEqual(op['x-aisa-docs-url'], 'https://aisa.one/docs/api-reference/twitter/actual-old-page')

    def test_unused_provider_response_recursion_does_not_hide_valid_request(self):
        upstream = mirror()
        upstream['components']['schemas']['RecursiveResponse'] = {'$ref': '#/components/schemas/RecursiveResponse'}
        upstream['paths']['/provider/test']['post']['responses'] = {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/RecursiveResponse'}}}}}
        document, pending = compose(facts('provider'), upstream)
        self.assertFalse(pending)
        self.assertIn('requestBody', operation(document))
        self.assertNotIn('content', operation(document)['responses']['200'])

    def test_recursive_request_components_survive_collisions_and_repeat_composition(self):
        upstream = mirror()
        upstream['components']['schemas']['Body'] = {'type': 'object', 'properties': {'children': {'type': 'array', 'items': {'$ref': '#/components/schemas/Body'}}}}
        runtime = facts('provider')
        runtime['components']['schemas'] = {'Body': {'type': 'string'}}
        other = copy.deepcopy(operation(runtime))
        other['operationId'] = 'second_tree'
        runtime['paths']['/apis/v1/similarweb/second'] = {'post': other}
        document, pending = compose(runtime, upstream)
        self.assertFalse(pending)
        self.assertEqual(document['components']['schemas']['Body'], {'type': 'string'})
        for item in document['paths'].values():
            schema = item['post']['requestBody']['content']['application/json']['schema']
            ref = schema['properties']['children']['items']['$ref']
            definition = document
            for part in ref[2:].split('/'):
                definition = definition[part]
            self.assertEqual(definition['properties']['children']['items']['$ref'], ref)
        repeated, pending = compose(runtime, upstream, previous=document)
        self.assertFalse(pending)
        self.assertEqual(repeated, document)

    def test_four_real_agentmail_recursive_requests_are_composable(self):
        root = Path(__file__).resolve().parents[2]
        mirrors = public_mirror_index(root)
        runtime = facts('provider')
        runtime['paths'] = {}
        paths = ['/apis/v1/agentmail/inboxes/{inbox_id}/messages/send',
                 *[f'/apis/v1/agentmail/inboxes/{{inbox_id}}/messages/{{message_id}}/{action}' for action in ['forward', 'reply', 'reply-all']]]
        for index, path in enumerate(paths):
            op = copy.deepcopy(operation(facts('provider')))
            op['operationId'] = f'agentmail_recursive_fixture_{index}'
            runtime['paths'][path] = {'post': op}
        document, pending = compose(runtime, public_mirrors=mirrors)
        self.assertEqual(pending, [])
        self.assertEqual(len(document['paths']), 4)
        self.assertTrue(document['components']['schemas'])
        def check_refs(node):
            if isinstance(node, list):
                for value in node:
                    check_refs(value)
            elif isinstance(node, dict):
                if '$ref' in node:
                    target = document
                    for token in node['$ref'][2:].split('/'):
                        target = target[token.replace('~1', '/').replace('~0', '~')]
                    self.assertIsInstance(target, dict)
                for value in node.values():
                    check_refs(value)
        check_refs(document)
        self.assertEqual(compose(runtime, previous=document, public_mirrors=mirrors)[0], document)

    def test_all_existing_mirrors_have_honest_public_manual_provenance(self):
        root = Path(__file__).resolve().parents[2]
        files = list((root / 'openapi/upstream').glob('*.json'))
        manual = 0
        for path in files:
            source = json.loads(path.read_text())['info']['x-aisa-source']
            if source['kind'] == 'provider_openapi':
                self.assertTrue(source['url'].startswith('https://'))
                self.assertNotIn('path_space', source)
                continue
            manual += 1
            self.assertEqual(source['kind'], 'manual')
            self.assertEqual(source['path_space'], 'public')
            self.assertIn('/blob/', source['url'])
        self.assertEqual(manual, 47)
        self.assertGreater(len(public_mirror_index(root)), 1000)


if __name__ == '__main__':
    unittest.main()

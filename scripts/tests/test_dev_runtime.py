import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_dev_runtime as dev
from test_runtime_contracts import facts


class DevRuntimeTests(unittest.TestCase):
    def fixture(self):
        document = facts()
        document['info']['x-aisa-document']['facts_hash'] = 'a' * 64
        index = {'providers': [{'id': 'similarweb', 'facts_hash': 'a' * 64,
                               'url': 'https://api.aisa.one/never-follow-this'}],
                 'pending_providers': [], 'pending_endpoints': []}
        values = {'/info/openapi.json': index, '/info/openapi/similarweb.json': document,
                  '/info/apis/category': {'apis': [{'id': 'similarweb'}]}}
        calls = []

        def reader(path):
            calls.append(path)
            return json.dumps(values[path], sort_keys=True).encode(), {}
        return values, calls, reader

    def test_complete_snapshot_brackets_every_provider_and_never_follows_urls(self):
        values, calls, reader = self.fixture()
        result = dev.acquire(reader)
        self.assertEqual(set(result), {'similarweb.json', 'index.json', 'category.json'})
        self.assertEqual(calls.count('/info/openapi/similarweb.json'), 2)
        self.assertEqual(calls.count('/info/openapi.json'), 2)
        self.assertEqual(calls.count('/info/apis/category'), 2)
        self.assertTrue(all(path.startswith('/info/') for path in calls))

    def test_missing_pending_duplicate_or_changed_provider_fails_closed(self):
        for mutation in ('hash', 'duplicate', 'pending', 'path'):
            values, _, reader = self.fixture()
            if mutation == 'hash':
                values['/info/openapi.json']['providers'][0]['facts_hash'] = 'b' * 64
            elif mutation == 'duplicate':
                values['/info/openapi.json']['providers'] *= 2
            elif mutation == 'pending':
                values['/info/openapi.json']['pending_endpoints'] = [{'id': 'pending'}]
            else:
                values['/info/openapi.json']['providers'][0]['id'] = '../escape'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                dev.acquire(reader)

    def test_provider_or_index_changes_reject_entire_snapshot(self):
        for target in ('/info/openapi.json', '/info/openapi/similarweb.json'):
            values, calls, reader = self.fixture()

            def changing(path):
                raw, headers = reader(path)
                if path == target and calls.count(path) == 2:
                    return raw + b' ', headers
                return raw, headers
            with self.subTest(target=target), self.assertRaises(ValueError):
                dev.acquire(changing)

    def test_wrong_branch_or_failed_acquisition_never_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / 'docs.json'; marker.write_text('last good docs')
            for branch in ('main', 'dev'):
                with patch.object(dev.subprocess, 'check_output', return_value=branch), \
                     patch.object(dev, 'acquire', side_effect=ValueError('unavailable')), \
                     patch.object(dev, 'generate') as generate, self.assertRaises(ValueError):
                    dev.sync(root, write=True, reader=object())
                generate.assert_not_called()
                self.assertEqual(marker.read_text(), 'last good docs')

    def test_generation_reuses_composer_and_produces_dev_pages_and_navigation(self):
        values, _, reader = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders:\n  historic:\n    upstream: https://provider.example/must-not-fetch.json\n')
            (root / 'openapi/pending.json').write_text('{"providers":{"obsolete-production-catalog":[{"reason":"historic"}]}}')
            config = {'navigation': {'languages': [
                {'language': language, 'tabs': [{'tab': tab, 'groups': []}]}
                for language, tab in [('en', 'API Reference'), ('zh', 'API 参考')]]}}
            (root / 'docs.json').write_text(json.dumps(config))
            outputs, report = dev.generate(root, dev.acquire(reader))
            self.assertIn('api-reference/similarweb/published_identity.mdx', outputs)
            self.assertIn('zh/api-reference/similarweb/published_identity.mdx', outputs)
            self.assertIn('api-reference/similarweb/published_identity', outputs['docs.json'].decode())
            self.assertNotIn('https://api.aisa.one', outputs['openapi/openapi.json'].decode())
            self.assertIn('raw.githubusercontent.com/AIsa-team/docs/refs/heads/dev/openapi/similarweb.json',
                          outputs['api-reference/similarweb/published_identity.mdx'].decode())
            self.assertFalse(report['formal_publication'])
            self.assertEqual(report['status'], 'generated')
            self.assertNotIn('obsolete-production-catalog', report['pending']['providers'])
            import yaml
            self.assertEqual(yaml.safe_load(outputs['openapi/registry.yaml'])['providers']['historic']['upstream'],
                             'https://provider.example/must-not-fetch.json')
            self.assertNotIn('docs/publication/current.json', outputs)
            self.assertFalse((root / 'openapi/similarweb.json').exists())

    def test_invalid_runtime_capability_is_reported_without_publishing_an_endpoint(self):
        values, _, reader = self.fixture()
        values['/info/openapi/similarweb.json']['paths']['/apis/v1/similarweb/test']['post']['x-aisa-capabilities'] = {'x402': 'invalid'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            (root / 'docs.json').write_text('{"navigation":{"languages":[]}}')
            outputs, report = dev.generate(root, dev.acquire(reader))
            self.assertEqual(report['status'], 'partial')
            self.assertEqual(report['blocked_providers'], ['similarweb'])
            self.assertIn('runtime payment capability must be boolean', report['providers']['similarweb']['blocked'])
            self.assertEqual(json.loads(outputs['openapi/openapi.json'])['paths'], {})
            self.assertNotIn('api-reference/similarweb/published_identity.mdx', outputs)

    def test_sync_workflow_has_dev_only_write_permission_and_no_production_dispatch(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/dev-docs.yml').read_text())
        job = workflow['jobs']['sync-runtime']
        self.assertIn("github.ref == 'refs/heads/dev'", job['if'])
        self.assertIn("github.event_name != 'pull_request'", job['if'])
        self.assertEqual(job['permissions'], {'contents': 'write'})
        serialized = yaml.safe_dump(job)
        self.assertNotIn('secrets.', serialized)
        self.assertNotIn('dispatch-contract', serialized)
        self.assertNotIn('HEAD:main', serialized)

    def test_historic_and_blocked_contracts_are_hidden_from_dev_navigation_and_aggregate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            operations = {'current': {}, 'historic': {}, 'blocked': {},
                          'disabled': {'x-aisa-status': 'disabled'}}
            pages = []
            for provider, fields in operations.items():
                document = {'paths': {'/endpoint': {'get': fields}}}
                (root / f'openapi/{provider}.json').write_text(json.dumps(document))
                for base in ('api-reference', 'zh/api-reference'):
                    page = root / base / provider / 'endpoint.mdx'
                    page.parent.mkdir(parents=True, exist_ok=True)
                    page.write_text(f'---\nopenapi: "openapi/{provider}.json GET /endpoint"\n---\nExample\n')
                    pages.append(page.relative_to(root).with_suffix('').as_posix())
            config = {'navigation': {'languages': [{'language': 'en', 'tabs': [
                {'tab': 'API', 'groups': [{'group': 'Endpoints', 'pages': pages}]}]}]}}
            (root / 'docs.json').write_text(json.dumps(config))
            aggregate = {'info': {}, 'paths': {f'/{key}': {'get': {**fields, 'x-aisa-provider': key}}
                                               for key, fields in operations.items()}}
            summary = {'current': {}, 'disabled': {}, 'blocked': {'blocked': 'invalid contract'}}
            count = dev.scope_presentation(root, aggregate, summary)
            self.assertEqual(count, 6)
            self.assertEqual(set(aggregate['paths']), {'/current'})
            nav = json.loads((root / 'docs.json').read_text())
            self.assertEqual(nav['navigation']['languages'][0]['tabs'][0]['groups'][0]['pages'],
                             ['api-reference/current/endpoint', 'zh/api-reference/current/endpoint'])
            page = root / 'api-reference/historic/endpoint.mdx'
            self.assertIn('noindex:', page.read_text())
            self.assertIn(dev.ARCHIVE_NOTE, page.read_text())
            # Repeated generation does not duplicate the archive notice.
            dev.scope_presentation(root, aggregate, summary)
            self.assertEqual(page.read_text().count(dev.ARCHIVE_NOTE), 1)


if __name__ == '__main__':
    unittest.main()

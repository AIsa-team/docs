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

    def test_change_detection_ignores_cache_time_but_tracks_contract_and_catalog_changes(self):
        values, _, reader = self.fixture()
        before = dev.acquire(reader)
        fingerprint = dev.inputs_sha256(before)
        values['/info/apis/category']['cached_at'] = 123
        self.assertEqual(dev.inputs_sha256(dev.acquire(reader)), fingerprint)
        self.assertEqual(dev.snapshot_hashes(dev.acquire(reader)), dev.snapshot_hashes(before))
        values['/info/apis/category']['apis'][0]['endpoint_count'] = 2
        self.assertNotEqual(dev.inputs_sha256(dev.acquire(reader)), fingerprint)
        for name in ('index.json', 'similarweb.json'):
            changed = dict(before)
            document = json.loads(changed[name])
            document['changed_public_contract'] = True
            changed[name] = json.dumps(document).encode()
            with self.subTest(file=name):
                self.assertNotEqual(dev.inputs_sha256(changed), fingerprint)

    def test_unchanged_runtime_skips_generation_and_keeps_committed_files(self):
        _, calls, reader = self.fixture()
        files = dev.acquire(reader)
        calls.clear()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            previous = {'environment': 'dev', 'runtime_origin': dev.DEV_ORIGIN,
                        'formal_publication': False, 'status': 'partial',
                        'inputs_sha256': dev.inputs_sha256(files)}
            marker = root / 'docs/dev-runtime.json'
            marker.write_text(json.dumps(previous))
            original = marker.read_bytes()
            with patch.object(dev.subprocess, 'check_output', return_value='dev'), \
                    patch.object(dev, 'generate') as generate:
                result = dev.sync(root, write=True, if_changed=True, reader=reader)
            generate.assert_not_called()
            self.assertEqual(result['status'], 'unchanged')
            self.assertEqual(result['generation_status'], 'partial')
            self.assertEqual(result['changed_files'], [])
            self.assertFalse(result['written'])
            self.assertEqual(marker.read_bytes(), original)
            # A fresh complete acquisition is mandatory even for a no-op run.
            self.assertEqual(calls.count('/info/openapi/similarweb.json'), 2)

    def test_changed_runtime_and_forced_generation_do_not_use_the_skip_path(self):
        _, _, reader = self.fixture()
        files = dev.acquire(reader)
        for mutation in ('changed', 'force', 'production', 'failed'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / 'docs').mkdir()
                previous = {'environment': 'dev', 'runtime_origin': dev.DEV_ORIGIN,
                            'formal_publication': False, 'status': 'generated',
                            'inputs_sha256': dev.inputs_sha256(files)}
                if mutation == 'changed': previous['inputs_sha256'] = 'old'
                if mutation == 'production': previous['runtime_origin'] = 'https://api.aisa.one'
                if mutation == 'failed': previous['status'] = 'failed'
                (root / 'docs/dev-runtime.json').write_text(json.dumps(previous))
                with patch.object(dev.subprocess, 'check_output', return_value='dev'), \
                        patch.object(dev.subprocess, 'run'), \
                        patch.object(dev, 'generate', return_value=({}, {'status': 'generated'})) as generate:
                    dev.sync(root, if_changed=mutation != 'force', reader=reader)
                generate.assert_called_once()

    def test_wrong_branch_or_failed_acquisition_never_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            marker = root / 'docs.json'; marker.write_text('last good docs')
            for branch in ('main', 'dev'):
                with patch.object(dev.subprocess, 'check_output', return_value=branch), \
                     patch.object(dev, 'acquire', side_effect=ValueError('unavailable')), \
                     patch.object(dev, 'generate') as generate, self.assertRaises(ValueError):
                    dev.sync(root, write=True, if_changed=True, reader=object())
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
            values['/info/apis/category']['cached_at'] = 123
            repeated, _ = dev.generate(root, dev.acquire(reader))
            self.assertEqual(outputs['docs/dev-runtime.json'], repeated['docs/dev-runtime.json'])

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

    def test_existing_reference_survives_generation_and_new_dev_pages_are_added(self):
        from check_nav_integrity import nav_pages
        _, _, reader = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
            document = facts()
            document['info']['title'] = 'Historic reference'
            item = document['paths'].pop('/apis/v1/similarweb/test')
            item['post']['operationId'] = 'historic_identity'
            # The shared Composer removes this old link; dev must restore it.
            item['post']['x-aisa-status'] = 'disabled'
            document['paths']['/apis/v1/historic/test'] = item
            (root / 'openapi/historic.json').write_text(json.dumps(document))
            (root / 'openapi/zh').mkdir()
            document['info']['x-aisa-language'] = 'zh'
            (root / 'openapi/zh/historic.json').write_text(json.dumps(document))
            config = {'navigation': {'languages': []}}
            for language, prefix, tab in [('en', '', 'API Reference'), ('zh', 'zh/', 'API 参考')]:
                page = root / f'{prefix}api-reference/historic/existing.mdx'
                page.parent.mkdir(parents=True, exist_ok=True)
                spec = 'openapi/zh/historic.json' if prefix else 'openapi/historic.json'
                page.write_text(f'---\nopenapi: "{spec} POST /apis/v1/historic/test"\n'
                                'noindex: "true" # aisa-contract-status\n---\n' + dev.ARCHIVE_NOTE + 'Existing example\n')
                config['navigation']['languages'].append({'language': language, 'tabs': [{
                    'tab': tab, 'groups': [{'group': 'Original category', 'pages': [{
                        'group': 'Original provider', 'pages': [f'{prefix}api-reference/historic/existing']}]}]}]})
            (root / 'docs.json').write_text(json.dumps(config))
            outputs, report = dev.generate(root, dev.acquire(reader))
            generated = json.loads(outputs['docs.json'])
            for prefix in ('', 'zh/'):
                historic = f'{prefix}api-reference/historic/existing'
                new = f'{prefix}api-reference/similarweb/published_identity'
                listed = nav_pages(generated['navigation'])
                self.assertEqual(listed.count(historic), 1)
                self.assertEqual(listed.count(new), 1)
                text = outputs[historic + '.mdx'].decode()
                self.assertIn('Existing example', text)
                self.assertNotIn(dev.ARCHIVE_NOTE, text)
                self.assertNotIn('noindex:', text)
            self.assertEqual(report['preserved_historic_pages'], 2)
            self.assertNotIn('/apis/v1/historic/test', json.dumps(json.loads(outputs['openapi/openapi.json'])['paths']))
            self.assertNotIn('historic', json.loads(outputs['openapi/openapi.json'])['info']['x-aisa-document'].get('providers', {}))
            # The next scheduled generation must retain the directory and notice.
            for name, raw in outputs.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            repeated, _ = dev.generate(root, dev.acquire(reader))
            self.assertEqual(outputs['docs.json'], repeated['docs.json'])
            for prefix in ('', 'zh/'):
                name = f'{prefix}api-reference/historic/existing.mdx'
                self.assertEqual(outputs[name], repeated[name])

    def test_dev_workflow_only_checks_and_cannot_publish_directly(self):
        import yaml
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/dev-docs.yml').read_text())
        self.assertEqual(set(workflow['jobs']), {'offline-contracts'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('git push', yaml.safe_dump(workflow))

    def test_preserved_reference_does_not_add_unverified_contracts_to_the_dev_aggregate(self):
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
            counts = dev.scope_presentation(root, aggregate, summary)
            self.assertEqual(counts, {'preserved_historic_pages': 6, 'hidden_historic_pages': 0})
            self.assertEqual(set(aggregate['paths']), {'/current'})
            nav = json.loads((root / 'docs.json').read_text())
            self.assertEqual(nav['navigation']['languages'][0]['tabs'][0]['groups'][0]['pages'],
                             pages)
            page = root / 'api-reference/historic/endpoint.mdx'
            self.assertNotIn('noindex:', page.read_text())
            self.assertIn(dev.HISTORIC_NOTES['en'], page.read_text())
            # Repeated generation does not duplicate the archive notice.
            dev.scope_presentation(root, aggregate, summary)
            self.assertEqual(page.read_text().count(dev.HISTORIC_NOTES['en']), 1)


if __name__ == '__main__':
    unittest.main()

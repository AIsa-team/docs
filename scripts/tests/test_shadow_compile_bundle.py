import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
from compose_openapi import digest
from contract_page_links import (historical_link_index, project_links, select_pages,
                                 require_historical_primary_links)
from fetch_runtime_release import acquire, save
from schema_input_bundle import canonical, sha
from shadow_compile_bundle import load_runtime
import test_fetch_runtime_release as runtime_tests
import test_runtime_contracts as contract_tests
from pull_openapi import stage


def document(identity='stable', path='/old', url=None):
    operation = {'operationId': identity, 'responses': {'200': {'description': 'Success'}}}
    if url is not None:
        operation['x-aisa-docs-url'] = url
    return {'info': {'x-aisa-document': {'document_hash': 'fresh-composer-hash'}},
            'servers': [{'url': 'https://api.aisa.one'}], 'paths': {path: {'get': operation}}}


class LinkProjectionTests(unittest.TestCase):
    def test_new_operation_uses_existing_slug_rule_and_recomputes_hash(self):
        doc = document('new.operation')
        selected = select_pages('provider', doc, {}, {})
        self.assertEqual(selected, {'new.operation': ['api-reference/provider/new-operation']})
        project_links(doc, selected)
        url = 'https://aisa.one/docs/api-reference/provider/new-operation'
        self.assertEqual(doc['paths']['/old']['get']['x-aisa-docs-url'], url)
        self.assertEqual(doc['info']['x-aisa-document']['document_hash'],
            digest({'composer_hash': 'fresh-composer-hash', 'page_links': {'new.operation': url}}))

    def test_all_historical_page_names_and_last_primary_are_preserved(self):
        doc = document()
        selected = select_pages('provider', doc,
            {'stable': {'api-reference/old/z', 'api-reference/old/a'}}, {})
        self.assertEqual(selected['stable'], ['api-reference/old/a', 'api-reference/old/z'])
        project_links(doc, selected)
        self.assertEqual(doc['paths']['/old']['get']['x-aisa-docs-url'],
                         'https://aisa.one/docs/api-reference/old/z')

    def test_path_and_provider_moves_keep_canonical_primary_url(self):
        old = document(url='https://aisa.one/docs/api-reference/old-provider/old-page')
        index = historical_link_index({'old-provider': old})
        new = document(path='/new')
        selected = select_pages('new-provider', new, *index)
        self.assertEqual(selected['stable'], ['api-reference/old-provider/old-page'])
        project_links(new, selected)
        self.assertEqual(new['paths']['/new']['get']['x-aisa-docs-url'], old['paths']['/old']['get']['x-aisa-docs-url'])
        self.assertEqual(old['info']['x-aisa-document']['document_hash'], 'fresh-composer-hash')

    def test_identity_match_precedes_route_fallback(self):
        selected = select_pages('provider', document(), {'stable': {'api-reference/stable'}},
                                {('/old', 'get'): 'api-reference/route'})
        self.assertEqual(selected['stable'], ['api-reference/stable'])
        selected = select_pages('provider', document('new'), {}, {('/old', 'get'): 'api-reference/route'})
        self.assertEqual(selected['new'], ['api-reference/route'])

    def test_alias_metadata_does_not_create_another_route_or_url_identity(self):
        doc = document(url='https://aisa.one/docs/api-reference/provider/canonical')
        doc['paths']['/old']['get']['x-aisa-identity'] = {
            'canonical_operation_id': 'stable', 'historical_aliases': [{'operation_id': 'legacy_zh'}]}
        ids, routes = historical_link_index({'provider': doc})
        self.assertEqual(set(ids), {'stable'})
        self.assertEqual(set(select_pages('provider', doc, ids, routes)), {'stable'})
        self.assertEqual(list(doc['paths']), ['/old'])

    def test_invalid_or_conflicting_historical_urls_rejected(self):
        for url in ['https://evil.test/api-reference/x', 'https://aisa.one/docs/api-reference/../x',
                    'https://aisa.one/docs/api-reference/x?query']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                historical_link_index({'provider': document(url=url)})
        with self.assertRaisesRegex(ValueError, 'conflicting primary'):
            historical_link_index({'a': document(url='https://aisa.one/docs/api-reference/a'),
                                   'b': document(url='https://aisa.one/docs/api-reference/b')})

    def test_unlinked_legacy_migration_requires_page_inventory(self):
        old = {'legacy': document()}
        with self.assertRaisesRegex(ValueError, 'page inventory input required'):
            require_historical_primary_links(old, {'new-provider': document(path='/moved')})
        require_historical_primary_links(old, {'new-provider': document('genuinely_new')})
        require_historical_primary_links(old, {})  # Uncomposed legacy bytes stay unchanged.


class OfflineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'facts'
        self.revision, self.compiler, reader, *_ = runtime_tests.PublicReleaseTests().fixture()
        save(self.root, acquire(self.revision, self.compiler, reader))
        self.receipt_sha = sha((self.root / 'acquisition-receipt.json').read_bytes())

    def load(self):
        return load_runtime(self.root, artifact_revision=self.revision,
            compiler_revision=self.compiler, receipt_sha256=self.receipt_sha)

    def test_original_snapshot_without_network_or_new_receipt(self):
        original = (self.root / 'acquisition-receipt.json').read_bytes()
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            facts, result = self.load()
        self.assertEqual(facts['example.json'], (self.root / 'providers/example.json').read_bytes())
        self.assertEqual(result['freshness'], 'historical_acquisition_only_not_current_freshness')
        self.assertEqual((self.root / 'acquisition-receipt.json').read_bytes(), original)

    def test_flat_unverified_duplicate_is_never_a_compiler_input(self):
        (self.root / 'example.json').write_bytes(b'{"untrusted":true}')
        facts, _ = self.load()
        self.assertNotIn(b'untrusted', facts['example.json'])

    def test_raw_file_tamper_fails_original_manifest(self):
        with (self.root / 'providers/example.json').open('ab') as handle:
            handle.write(b' ')
        with self.assertRaisesRegex(ValueError, 'immutable manifest'):
            self.load()

    def test_changed_unversioned_category_fails_original_receipt(self):
        (self.root / 'category.json').write_bytes(b'{"apis":[]}')
        with self.assertRaisesRegex(ValueError, 'category differs'):
            self.load()

    def test_wrong_external_receipt_pin_rejected(self):
        self.receipt_sha = '0' * 64
        with self.assertRaisesRegex(ValueError, 'caller pin'):
            self.load()

    def test_limits_remain_enforced_offline(self):
        with patch('shadow_compile_bundle.MAX_TOTAL', 1), self.assertRaisesRegex(ValueError, 'byte limit'):
            self.load()

    def test_current_changed_after_acquisition_rejected(self):
        value = json.loads((self.root / 'current-after.json').read_bytes())
        value['generation'] += 1
        value['published_generation'] += 1
        (self.root / 'current-after.json').write_bytes(canonical(value))
        with self.assertRaisesRegex(ValueError, 'not stable'):
            self.load()


class StageInjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = contract_tests.PullTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root

    def test_same_previous_hash_cannot_mask_independent_output(self):
        self.fixture.write(stage(self.root, self.root / 'facts', 'unused')[0])
        path = self.root / 'openapi/similarweb.json'
        old = json.loads(path.read_bytes())
        old['paths']['/apis/v1/similarweb/test']['post']['summary'] = 'Tampered old output with unchanged hash'
        path.write_bytes(canonical(old))
        links = historical_link_index({'similarweb': old})
        with patch('pull_openapi.published_history', side_effect=AssertionError('Git forbidden')):
            changes, summary = stage(self.root, self.root / 'facts', 'unused', with_pages=False,
                identity_history=None, page_link_index=links, reuse_unchanged_documents=False)
        actual = json.loads(changes[path])
        self.assertFalse(summary['similarweb']['changed'])  # The hash really is unchanged.
        self.assertEqual(actual['paths']['/apis/v1/similarweb/test']['post']['summary'], 'Runtime title')
        self.assertEqual(actual['info']['x-aisa-document']['document_hash'], old['info']['x-aisa-document']['document_hash'])

    def test_production_page_writer_preserves_all_historical_pages(self):
        for suffix in ['z', 'a']:
            path = self.root / ('api-reference/old/' + suffix + '.mdx')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('---\ntitle: old\nopenapi: "openapi/similarweb.json POST /apis/v1/similarweb/test"\n'
                            'x-aisa-operation-id: published_identity\n---\nKeep ' + suffix + '\n')
        changes, _ = stage(self.root, self.root / 'facts', 'unused')
        actual = json.loads(changes[self.root / 'openapi/similarweb.json'])
        self.assertEqual(actual['paths']['/apis/v1/similarweb/test']['post']['x-aisa-docs-url'],
                         'https://aisa.one/docs/api-reference/old/z')
        for suffix in ['a', 'z']:
            for prefix in ['', 'zh/']:
                self.assertIn(self.root / (prefix + 'api-reference/old/' + suffix + '.mdx'), changes)
            self.assertIn('Keep ' + suffix, changes[self.root / ('api-reference/old/' + suffix + '.mdx')])


if __name__ == '__main__':
    unittest.main()

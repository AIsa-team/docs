import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contract_page_links import project_links, select_pages
from presentation_page_bindings import (aggregate_links, export_bindings, link_index,
                                        validate_bindings)
from schema_input_bundle import canonical, sha
import runtime_consolidate_openapi as consolidate


def document(identity='stable', path='/old'):
    return {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'x-aisa-document': {'document_hash': 'fresh'}},
            'servers': [{'url': 'https://api.aisa.one/apis/v1'}],
            'paths': {path: {'get': {'operationId': identity, 'responses': {'200': {'description': 'OK'}}}}}}


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.ref = 'a' * 40
        self.docs = {'old': document()}
        self.raw = {f'api-reference/old/{name}.mdx':
            b'---\nopenapi: "openapi/old.json GET /old"\n---\nManual prose.\n' for name in ['a', 'z']}
        self.raw['api-reference/overview.mdx'] = b'---\ntitle: Overview\n---\n'
        self.hashes = {name: sha(raw) for name, raw in self.raw.items()}
        self.value = export_bindings(self.ref, self.hashes, self.docs, self.raw.__getitem__, sha)

    def validate(self, value):
        validate_bindings(value, self.ref, self.hashes, self.docs)

    def test_actual_mdx_bytes_and_complete_bound_and_unbound_files(self):
        self.assertEqual(len(self.value['pages']), 3)
        self.assertIsNone(self.value['pages'][-1]['binding'])
        self.validate(self.value)
        with self.assertRaisesRegex(ValueError, 'MDX differs'):
            export_bindings(self.ref, self.hashes, self.docs, lambda _: b'changed', sha)

    def test_export_rejects_conflicting_explicit_frontmatter_identity(self):
        raw = {name: content.replace(b'---\nManual', b'x-aisa-operation-id: wrong\n---\nManual')
               for name, content in self.raw.items()}
        hashes = {name: sha(content) for name, content in raw.items()}
        with self.assertRaisesRegex(ValueError, 'frontmatter identity'):
            export_bindings(self.ref, hashes, self.docs, raw.__getitem__, sha)

    def test_existing_native_primary_must_match_last_historical_page(self):
        operation = self.docs['old']['paths']['/old']['get']
        operation['x-aisa-docs-url'] = 'https://aisa.one/docs/api-reference/old/z'
        self.validate(self.value)
        operation['x-aisa-docs-url'] = 'https://aisa.one/docs/api-reference/old/a'
        with self.assertRaisesRegex(ValueError, 'primary URL'):
            self.validate(self.value)

    def test_multi_page_native_last_aggregate_first_and_provider_path_move(self):
        moved = document(path='/new')
        selection = select_pages('new', moved, *link_index(self.value, self.docs))
        self.assertEqual(selection['stable'], ['api-reference/old/a', 'api-reference/old/z'])
        project_links(moved, selection)
        self.assertTrue(moved['paths']['/new']['get']['x-aisa-docs-url'].endswith('/old/z'))
        self.assertEqual(aggregate_links(self.value, {'new': moved}),
                         {('new.json', 'get', '/new'): 'https://aisa.one/docs/api-reference/old/a'})

    def test_new_runtime_id_uses_shared_slug_without_historical_inventory_requirement(self):
        new = document('genuinely.new', '/new')
        project_links(new, select_pages('new', new, *link_index(self.value, self.docs)))
        self.assertEqual(aggregate_links(self.value, {'new': new}),
                         {('new.json', 'get', '/new'): 'https://aisa.one/docs/api-reference/new/genuinely-new'})

    def test_wrong_identity_method_path_hash_duplicate_and_missing_rejected(self):
        mutations = [lambda v: v['pages'][0]['binding'].update(operation_id='wrong'),
                     lambda v: v['pages'][0]['binding'].update(method='post'),
                     lambda v: v['pages'][0]['binding'].update(path='/wrong'),
                     lambda v: v['pages'][0].update(sha256='0' * 64),
                     lambda v: v['pages'].append(copy.deepcopy(v['pages'][0])),
                     lambda v: v['pages'].pop(),
                     lambda v: v['pages'][0].update(path='api-reference/../escape.mdx'),
                     lambda v: v['pages'][0]['binding'].update(price=0),
                     lambda v: [row.update(binding=None) for row in v['pages']]]
        for mutate in mutations:
            value = copy.deepcopy(self.value)
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.validate(value)

    def test_explicit_aggregator_root_and_map_never_scan_pages_or_change_global_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'openapi').mkdir()
            (root / 'openapi/old.json').write_bytes(canonical(self.docs['old']))
            previous_root = consolidate.OPENAPI_DIR
            with patch.object(consolidate, 'endpoint_page_links', side_effect=AssertionError('MDX scan forbidden')):
                aggregate = consolidate.build_unified_spec(root=root,
                    page_links=aggregate_links(self.value, self.docs))
            self.assertEqual(consolidate.OPENAPI_DIR, previous_root)
            self.assertTrue(aggregate['paths']['/old']['get']['x-aisa-docs-url'].endswith('/old/a'))


if __name__ == '__main__':
    unittest.main()

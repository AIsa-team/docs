import copy
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publication_surface import validate_surfaces, publication_hashes
from pull_openapi import generate_pages


class PublicationSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'openapi').mkdir()
        (self.root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
            {'language': lang, 'tabs': [{'tab': title, 'groups': []}]}
            for lang, title in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
        document = {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'x-aisa-document': {'document_hash': 'h'}},
            'paths': {'/one': {'get': {'operationId': 'one', 'responses': {'200': {'description': 'Success',
                'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                    'description': {'const': 'literal description'}, 'literal': {'default': {'description': 'literal'}}}}}}}}}}}}
        changes = {}
        generate_pages(self.root, 'fixture', document, changes)
        changes[self.root / 'openapi/fixture.json'] = json.dumps(document)
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def change_json(self, path, mutate):
        file = self.root / path
        data = json.loads(file.read_text())
        mutate(data)
        file.write_text(json.dumps(data))

    def test_actual_generated_pages_and_language_graph_pass_and_bind_all_bytes(self):
        for relative in ('api-reference.mdx', 'zh/api-reference.mdx'):
            overview = self.root / relative
            overview.parent.mkdir(parents=True, exist_ok=True)
            overview.write_text('---\ntitle: API overview\n---\nOverview prose.\n')
        self.assertEqual(validate_surfaces(self.root)['operations'], 1)
        hashes = publication_hashes(self.root)
        self.assertTrue({'docs.json', 'openapi/fixture.json', 'openapi/zh/fixture.json',
            'api-reference/fixture/one.mdx', 'zh/api-reference/fixture/one.mdx',
            'api-reference.mdx', 'zh/api-reference.mdx'} <= hashes.keys())
        overview = self.root / 'zh/api-reference.mdx'
        overview.write_text(overview.read_text() + 'Translated overview prose.\n')
        self.assertNotEqual(hashes['zh/api-reference.mdx'], publication_hashes(self.root)['zh/api-reference.mdx'])
        page = self.root / 'zh/api-reference/fixture/one.mdx'
        page.write_text(page.read_text() + 'Different prose\n')
        self.assertNotEqual(hashes[page.relative_to(self.root).as_posix()], publication_hashes(self.root)[page.relative_to(self.root).as_posix()])

    def test_legacy_bound_pages_render_without_runtime_ids_or_invented_prices(self):
        from pull_openapi import refresh_legacy_page_blocks
        from runtime_registry import published_documents
        source = {'openapi': '3.1.0', 'info': {'title': 'Account'},
                  'servers': [{'url': 'https://api.aisa.one/v1'}],
                  'paths': {'/usage': {'get': {'operationId': 'accountUsage',
                  'parameters': [{'name': 'scope', 'in': 'query', 'schema': {'type': 'string', 'enum': ['key', 'account']}}],
                  'responses': {'200': {'description': 'Usage'}}}}}}
        (self.root / 'openapi/account.json').write_text(json.dumps(source))
        originals = {}
        for language in ('en', 'zh'):
            prefix = 'zh/' if language == 'zh' else ''
            page = self.root / (prefix + 'api-reference/account-usage.mdx')
            originals[page] = '---\ntitle: Usage\nopenapi: "openapi/' + prefix + 'account.json GET /usage"\n---\nManual example stays.\n'
            page.write_text(originals[page])
        navigation = (self.root / 'docs.json').read_text()
        changes = {}
        refresh_legacy_page_blocks(self.root, published_documents(self.root), changes, {'entries': {}})
        for page, text in originals.items():
            self.assertTrue(changes[page].startswith(text))
            self.assertIn('"operationId": "accountUsage"', changes[page])
            self.assertNotIn('x-aisa-pricing', changes[page])
            self.assertNotIn('x-aisa-operation-id:', changes[page])
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        self.assertEqual((self.root / 'docs.json').read_text(), navigation)
        validate_surfaces(self.root)
        page = self.root / 'api-reference/account-usage.mdx'
        page.write_text(page.read_text().replace('"method": "GET"', '"method": "POST"'))
        with self.assertRaisesRegex(ValueError, 'readable contract differs'):
            validate_surfaces(self.root)

    def test_missing_or_tampered_readable_request_cannot_pass_formal_surface_check(self):
        from readable_contract_notes import strip_generated_block
        for prefix in ('', 'zh/'):
            page = self.root / (prefix + 'api-reference/fixture/one.mdx')
            original = page.read_text()
            for changed in (original.replace('"method": "GET"', '"method": "POST"'),
                            original.replace('"parameters": []', '"parameters": [{"name":"hidden","in":"query","required":true}]'),
                            strip_generated_block(original)):
                page.write_text(changed)
                with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, 'readable contract differs'):
                    validate_surfaces(self.root)
                page.write_text(original)

    def test_disabled_status_refresh_and_tampering_are_formally_checked(self):
        document = json.loads((self.root / 'openapi/fixture.json').read_text())
        document['paths']['/one']['get']['x-aisa-status'] = 'disabled'
        changes = {}
        generate_pages(self.root, 'fixture', document, changes)
        changes[self.root / 'openapi/fixture.json'] = json.dumps(document)
        for path, text in changes.items():
            path.write_text(text)
        validate_surfaces(self.root)
        for prefix in ('', 'zh/'):
            page = self.root / (prefix + 'api-reference/fixture/one.mdx')
            original = page.read_text()
            for replacement in ('"x-aisa-status": "enabled"', '"unpublished-status": "disabled"'):
                page.write_text(original.replace('"x-aisa-status": "disabled"', replacement))
                with self.assertRaisesRegex(ValueError, 'readable contract differs'):
                    validate_surfaces(self.root)
                page.write_text(original)

    def test_translated_prose_is_allowed_but_literal_schema_data_is_not(self):
        self.change_json('openapi/zh/fixture.json', lambda d: d['paths']['/one']['get']['responses']['200'].update(description='成功'))
        validate_surfaces(self.root)
        self.change_json('openapi/zh/fixture.json', lambda d: d['paths']['/one']['get']['responses']['200']['content']['application/json']['schema']['properties']['literal']['default'].update(description='changed'))
        with self.assertRaisesRegex(ValueError, 'protocol changed'):
            validate_surfaces(self.root)

    def test_multiple_pages_share_one_localized_read_and_protocol_check(self):
        document = json.loads((self.root / 'openapi/fixture.json').read_text())
        document['paths']['/two'] = copy.deepcopy(document['paths']['/one'])
        document['paths']['/two']['get']['operationId'] = 'two'
        changes = {}
        generate_pages(self.root, 'fixture', document, changes)
        changes[self.root / 'openapi/fixture.json'] = json.dumps(document)
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        localized = self.root / 'openapi/zh/fixture.json'
        original_read = Path.read_text
        reads = []

        def count_read(path, *args, **kwargs):
            if path == localized:
                reads.append(path)
            return original_read(path, *args, **kwargs)

        before = publication_hashes(self.root)
        with patch.object(Path, 'read_text', count_read):
            self.assertEqual(validate_surfaces(self.root)['operations'], 2)
        # Both page identity checks and final wire parity share the same bytes.
        self.assertEqual(reads, [localized])
        self.assertEqual(publication_hashes(self.root), before)

    def test_localized_cache_does_not_hide_wire_tampering_between_assessments(self):
        localized = self.root / 'openapi/zh/fixture.json'
        original_read = Path.read_text
        reads = []

        def count_read(path, *args, **kwargs):
            if path == localized:
                reads.append(path)
            return original_read(path, *args, **kwargs)

        with patch.object(Path, 'read_text', count_read):
            validate_surfaces(self.root)
            document = json.loads(original_read(localized))
            schema = document['paths']['/one']['get']['responses']['200']['content']['application/json']['schema']
            schema['properties']['literal']['default']['description'] = 'changed'
            localized.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'protocol changed'):
                validate_surfaces(self.root)
        self.assertEqual(reads, [localized, localized])

    def test_missing_language_schema_page_or_navigation_cannot_pass(self):
        for relative in ('openapi/zh/fixture.json', 'api-reference/fixture/one.mdx', 'zh/api-reference/fixture/one.mdx'):
            file = self.root / relative
            original = file.read_bytes()
            file.unlink()
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                validate_surfaces(self.root)
            file.write_bytes(original)
        self.change_json('docs.json', lambda d: d['navigation']['languages'][1]['tabs'][0].update(groups=[]))
        with self.assertRaisesRegex(ValueError, 'bilingual navigation'):
            validate_surfaces(self.root)

    def test_wrong_operation_identity_or_language_reference_cannot_pass(self):
        file = self.root / 'zh/api-reference/fixture/one.mdx'
        original = file.read_text()
        for text in (original.replace('x-aisa-operation-id: "one"', 'x-aisa-operation-id: "other"'),
                     original.replace('openapi/zh/fixture.json', 'openapi/zh/unknown.json'),
                     original.replace('openapi/zh/fixture.json', 'openapi/fixture.json'),
                     original.replace('GET /one', 'POST /one')):
            file.write_text(text)
            with self.assertRaises(ValueError):
                validate_surfaces(self.root)
        file.write_text(original)

    def test_legacy_without_runtime_metadata_makes_no_surface_claim(self):
        (self.root / 'openapi/fixture.json').write_text('{"paths": {}}')
        self.assertEqual(validate_surfaces(self.root)['providers'], 0)

    def test_legacy_writer_blocks_runtime_registry_before_any_output_mutation(self):
        script = Path(__file__).resolve().parents[1] / 'publication_surface.py'
        def guard():
            return subprocess.run([sys.executable, str(script), '--root', str(self.root), '--legacy-write'], capture_output=True)
        self.assertEqual(guard().returncode, 0)
        (self.root / 'openapi/registry.yaml').write_text('providers: {}\n')
        before = publication_hashes(self.root)
        result = guard()
        self.assertEqual(result.returncode, 3)
        self.assertIn(b'pull-openapi', result.stderr)
        self.assertEqual(before, publication_hashes(self.root))
        workflow = (script.parents[1] / '.github/workflows/sync-openapi.yml').read_text()
        self.assertLess(workflow.index('publication_surface.py --legacy-write'), workflow.index('Copy spec to docs repo root'))
        self.assertLess(workflow.index('publication_surface.py --legacy-write'), workflow.index('Commit and push'))

    def test_published_identity_reuses_all_old_alias_urls_after_path_migration(self):
        root = self.root
        en = root / 'api-reference/fixture/old-one.mdx'; zh = root / 'zh/api-reference/fixture/old-one.mdx'
        for path, localized in ((en, False), (zh, True)):
            path.write_text('---\nopenapi: "openapi/' + ('zh/' if localized else '') + 'fixture.json GET /old-one"\nx-aisa-operation-id: "one"\n---\nPreserve old prose.\n')
        document = json.loads((root / 'openapi/fixture.json').read_text())
        document['paths']['/migrated-one'] = document['paths'].pop('/one')
        changes = {}; generate_pages(root, 'fixture', document, changes)
        changes[root / 'openapi/fixture.json'] = json.dumps(document)
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        self.assertIn('GET /migrated-one', en.read_text())
        self.assertIn('Preserve old prose.', en.read_text())
        self.assertIn('Preserve old prose.', zh.read_text())
        self.assertEqual(validate_surfaces(root)['operations'], 1)


if __name__ == '__main__':
    unittest.main()

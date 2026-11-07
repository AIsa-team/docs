"""Page-scan reuse must preserve exact output and provider-local fallbacks."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pull_openapi
import validate_runtime_api_reference_slugs as slugs


class PageIdentityCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'openapi').mkdir()
        (self.root / 'api-reference/custom').mkdir(parents=True)
        (self.root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
            {'language': lang, 'tabs': [{'tab': title, 'groups': []}]}
            for lang, title in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
        self.references = []
        for name, identity in [('stable', 'stable-id'), ('legacy', None)]:
            front = 'title: Original ' + name + '\nopenapi: "openapi/old.json GET /' + name + '"'
            if identity: front += '\nx-aisa-operation-id: "' + identity + '"'
            (self.root / ('api-reference/custom/' + name + '.mdx')).write_text(
                '---\n' + front + '\n---\nOriginal prose survives.\n')
            self.references.append(('openapi/old.json', '/prefix', '/' + name, 'get', 'api-reference/custom/' + name))
        self.previous = self.document('Previous', '/legacy', 'provider-specific-id')
        self.previous['servers'] = [{'url': 'https://api.aisa.one/prefix'}]
        original = self.document('Previous', '/legacy', 'source-fallback-id')
        original['servers'] = self.previous['servers']
        (self.root / 'openapi/old.json').write_text(json.dumps(original))

    def document(self, title, route, identity):
        return {'openapi': '3.1.0', 'info': {'title': title, 'x-aisa-document': {'document_hash': 'h'}},
                'paths': {route: {'get': {'operationId': identity, 'responses': {'200': {'description': 'OK'}}}}}}

    def render(self, cache):
        changes = {}; selected = []; header_parses = []
        real_load = yaml.safe_load
        real_select = pull_openapi.select_pages
        def count(text):
            if isinstance(text, str) and text.startswith('title: Original'):
                header_parses.append(text)
            return real_load(text)
        def observe(provider, document, known_ids, known):
            selected.append((provider, copy.deepcopy(known_ids)))
            return real_select(provider, document, known_ids, known)
        with patch.object(yaml, 'safe_load', side_effect=count), patch.object(pull_openapi, 'select_pages', side_effect=observe):
            pull_openapi.generate_pages(self.root, 'old', self.document('Old', '/moved', 'provider-specific-id'),
                changes, copy.deepcopy(self.previous), page_references=self.references, page_identity_cache=cache)
            pull_openapi.generate_pages(self.root, 'new', self.document('New', '/new', 'stable-id'),
                changes, {}, page_references=self.references, page_identity_cache=cache)
        return changes, selected, header_parses

    def test_shared_header_scan_is_byte_identical_and_parsed_once(self):
        original, original_ids, original_parses = self.render(None)
        cached, cached_ids, cached_parses = self.render({})
        self.assertEqual(cached, original)
        self.assertEqual(cached_ids, original_ids)
        self.assertEqual(len(original_parses), 4)
        self.assertEqual(len(cached_parses), 2)
        self.assertIn('Original prose survives.', cached[self.root / 'api-reference/custom/legacy.mdx'])

    def test_missing_explicit_identity_does_not_cache_provider_fallback(self):
        cache = {}; _, selected, _ = self.render(cache)
        self.assertIsNone(cache['api-reference/custom/legacy'])
        self.assertIn('provider-specific-id', selected[0][1])
        self.assertNotIn('provider-specific-id', selected[1][1])
        self.assertIn('source-fallback-id', selected[1][1])

    def test_separate_stage_cache_reads_changed_page_identity(self):
        first = {}; self.render(first)
        page = self.root / 'api-reference/custom/stable.mdx'
        page.write_text(page.read_text().replace('stable-id', 'new-stable-id'))
        second = {}; _, selected, parses = self.render(second)
        self.assertEqual(first['api-reference/custom/stable'], 'stable-id')
        self.assertEqual(second['api-reference/custom/stable'], 'new-stable-id')
        self.assertEqual(len(parses), 2)
        self.assertIn('new-stable-id', selected[0][1])

    def test_slug_validator_parses_shared_schema_once_but_checks_each_page(self):
        document = self.document('Shared', '/one', 'one')
        document['paths']['/two'] = {'get': {'operationId': 'two', 'responses': {'200': {'description': 'OK'}}}}
        path = self.root / 'openapi/shared.json'
        path.write_text(json.dumps(document))
        for route, identity in [('/one', 'one'), ('/two', 'wrong')]:
            (self.root / ('api-reference/custom/' + route[1:] + '.mdx')).write_text(
                '---\nopenapi: "openapi/shared.json GET ' + route + '"\nx-aisa-operation-id: "' + identity + '"\n---\n')
        reads = []
        original = Path.read_text
        def counted(file, *args, **kwargs):
            if file == path: reads.append(file)
            return original(file, *args, **kwargs)
        with patch.object(Path, 'read_text', counted):
            errors = slugs.validate(self.root, True)
        self.assertEqual(len(reads), 1)
        self.assertTrue(any('two.mdx' in error and 'identity differs' in error for error in errors))
        document['paths']['/two']['get']['operationId'] = 'wrong'
        path.write_text(json.dumps(document))
        self.assertFalse(any('two.mdx' in error for error in slugs.validate(self.root, True)))


if __name__ == '__main__':
    unittest.main()

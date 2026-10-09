import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_upstream import import_source
from compose_openapi import digest
from pull_openapi import stage
from test_runtime_contracts import facts, operation
from wrapper_cloudsway_reference import REFERENCE_URL as SMART_URL
from wrapper_twitter_reference import REFERENCE_URL as TWITTER_URL

FIXTURES = Path(__file__).parent / 'fixtures'


class ReviewedSourceImportTests(unittest.TestCase):
    def test_fred_official_filename_refresh_uses_canonical_provider(self):
        from import_fred_reference import INDEX
        from refresh_upstream import refresh
        from source_governance import initial_policy
        document = {'openapi': '3.1.0', 'info': {'title': 'FRED', 'version': '1'}, 'paths': {}}
        document['info']['x-aisa-source'] = initial_policy({
            'kind': 'provider_openapi', 'url': INDEX,
            'content_hash': digest(document), 'fetched_at': '2026-10-09T00:00:00+00:00'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            (root/'openapi/upstream/fred-official.json').write_text(json.dumps(document))
            with patch('import_upstream.import_fred_reference', return_value=copy.deepcopy(document)) as convert:
                changes, report = refresh(root)
            convert.assert_called_once_with('fred', INDEX)
            self.assertEqual(changes, {})
            self.assertEqual(report['failed'], {})
            self.assertEqual(report['checked']['fred-official']['status'], 'source_unchanged')
            self.assertEqual(len(report['receipts']), 1)

    def test_wrapper_dispatch_and_canonical_hashes(self):
        cases = [
            ('search', SMART_URL, ['wrapper_cloudsway_smart.html'], 'manual'),
            ('aisa-twitter', TWITTER_URL, ['wrapper_twitter_routes.py.txt', 'wrapper_twitter_schemas.py.txt'], 'provider_openapi'),
        ]
        for provider, url, names, kind in cases:
            with self.subTest(provider=provider):
                with patch('import_upstream.urlopen', side_effect=[io.BytesIO((FIXTURES/name).read_bytes()) for name in names]):
                    result = import_source(provider, url)
                source = result['info'].pop('x-aisa-source')
                self.assertEqual(source['kind'], kind)
                self.assertEqual(source['content_hash'], digest(result))
                self.assertTrue(source['fetched_at'])

    def test_newly_fetched_public_mirror_composes_in_same_pull(self):
        with patch('import_upstream.urlopen', return_value=io.BytesIO((FIXTURES/'wrapper_cloudsway_smart.html').read_bytes())):
            mirror = import_source('search', SMART_URL)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi').mkdir()
            (root/'facts').mkdir()
            (root/'openapi/registry.yaml').write_text(yaml.safe_dump({'auto_register': True, 'providers': {'search': {'upstream': {'url': SMART_URL, 'file': 'smart.json'}}}}))
            runtime = facts('provider', 'x-aisa-any')
            op = copy.deepcopy(operation(runtime))
            # A synthetic stable binding tests indexing without disclosing a real account path.
            import hashlib
            op['x-aisa-upstream-path'] = '/search/test-account/smart'
            op['x-aisa-query-policy'] = {'request_wins': True}
            mirror['info']['x-aisa-source']['upstream_path_sha256'] = hashlib.sha256(op['x-aisa-upstream-path'].encode()).hexdigest()
            runtime['paths'] = {'/apis/v1/search/smart': {'x-aisa-any': op}}
            (root/'facts/category.json').write_text(json.dumps({'apis': [{'id': 'search'}]}))
            (root/'facts/search.json').write_text(json.dumps(runtime))
            (root/'docs.json').write_text(json.dumps({'navigation': {'languages': []}}))
            with patch('pull_openapi.import_source', return_value=mirror):
                changes, summary = stage(root, root/'facts', 'unused', False)
            self.assertEqual(summary['search']['pending'], 0)
            self.assertEqual(summary['search']['operations'], 1)
            for path, content in changes.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            with patch('pull_openapi.import_source', side_effect=AssertionError('locked public source refetched')):
                changes, summary = stage(root, root/'facts', 'unused', False)
            self.assertEqual(summary['search']['pending'], 0)
            self.assertEqual(changes, {})

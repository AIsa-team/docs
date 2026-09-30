import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from refresh_upstream import preserve_removed, refresh

class RefreshTests(unittest.TestCase):
    def test_deleted_upstream_operation_retains_its_renamed_components(self):
        old = {'paths': {'/old': {'get': {'operationId': 'old', 'responses': {'200': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Body'}}}}}}}}, 'components': {'schemas': {'Body': {'type': 'string'}}}}
        new = {'info': {'x-aisa-source': {'kind': 'provider_openapi'}}, 'paths': {'/new': {'get': {'operationId': 'new'}}}, 'components': {'schemas': {'Body': {'type': 'integer'}}}}
        result, removed = preserve_removed(old, new, 'provider.json')
        self.assertEqual(removed, ['GET /old'])
        self.assertEqual(result['components']['schemas']['Body']['type'], 'integer')
        ref = result['paths']['/old']['get']['responses']['200']['content']['application/json']['schema']['$ref'].split('/')[-1]
        self.assertEqual(result['components']['schemas'][ref]['type'], 'string')
        self.assertNotIn('/old', new['paths'])

    def test_private_pin_does_not_block_public_or_mapped_source_refresh(self):
        import json
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'openapi/upstream').mkdir(parents=True)
            for name, kind, policy in [('private', 'provider_openapi', 'pinned'), ('public', 'provider_openapi', None), ('mapped', 'manual', 'automatic')]:
                source = {'kind': kind, 'url': 'https://example.test/' + name, 'content_hash': 'old'}
                if policy: source['refresh_policy'] = policy
                (root/'openapi/upstream'/(name+'.json')).write_text(json.dumps({'info': {'x-aisa-source': source}, 'paths': {}}))
            def acquire(name, url):
                self.assertNotEqual(name, 'private')
                return {'info': {'x-aisa-source': {'kind': 'provider_openapi' if name == 'public' else 'manual', 'content_hash': 'new'}}, 'paths': {}}
            fetch = Mock(side_effect=acquire)
            changes, report = refresh(root, fetch)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(changes), 2)
            self.assertEqual(report['failed'], {})
            self.assertIn('private', report['pinned'])
            self.assertEqual(set(report['updated']), {'public', 'mapped'})

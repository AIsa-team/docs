import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from refresh_upstream import preserve_removed

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

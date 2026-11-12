import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_tool_prose import inventory

class ToolProseInventoryTests(unittest.TestCase):
    def test_aggregate_excluded_and_price_only_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            document = {'paths': {'/sample': {'parameters': [], 'get': {
                'operationId': 'sample', 'summary': 'sample_tool',
                'description': '<!-- aisa-pricing:start -->Paid<!-- aisa-pricing:end -->',
            }}}}
            raw = json.dumps(document)
            for name in ('sample', 'openapi'):
                (root / 'openapi' / (name + '.json')).write_text(raw)
            rows = inventory(root)
            self.assertEqual(1, len(rows))
            self.assertIn('missing_nonpricing_description', rows[0]['quality_flags'])
            self.assertEqual('unresolved', rows[0]['summary_owner_family'])
            self.assertEqual('', rows[0]['summary_candidate'])
            self.assertEqual(raw, (root / 'openapi/sample.json').read_text())

    def test_purpose_is_draft_and_runtime_description_owner_is_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            document = {'paths': {'/sample': {'get': {
                'operationId': 'sample', 'summary': 'fetch_profile',
                'description': 'Example (web).\n\n### Purpose:\n- Get profile by UID\n### Return:\n- Profile',
                'x-aisa-runtime-operation': {'operation_id': 'runtime-id'},
            }}}}
            (root / 'openapi/sample.json').write_text(json.dumps(document))
            row = inventory(root)[0]
            self.assertEqual('Example (web): Get profile by UID', row['summary_candidate'])
            self.assertEqual('candidate_needs_review', row['review_status'])
            self.assertIn('raw facts required', row['description_owner_family'])
            self.assertFalse(row['changed'])

if __name__ == '__main__':
    unittest.main()

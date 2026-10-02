from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_contract_candidate import main
from source_governance import acquisition_receipt, initial_policy, receipt_key


class FormalReceiptTests(unittest.TestCase):
    def run_check(self, source_receipt=True, tamper=False, unresolved=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upstream = root / 'openapi/upstream'; upstream.mkdir(parents=True)
            source = initial_policy({'kind': 'provider_openapi', 'url': 'https://official.invalid/spec', 'content_hash': 'sha256:fixture'})
            (upstream / 'p.json').write_text(json.dumps({'info': {'x-aisa-source': source}}))
            if source_receipt:
                cache = root / '.cache'; cache.mkdir()
                (cache / 'source-reviews.json').write_text(json.dumps({'receipts': {
                    receipt_key(source): acquisition_receipt(source, datetime.now(timezone.utc))}}))
            raw = b'openapi: 3.1.0\npaths: {}\n'
            expected = {'openapi': '3.1.0', 'paths': {}}
            if unresolved:
                expected['components'] = {'schemas': {'Input': {'$ref': '#/components/schemas/Missing'}}}
                raw = json.dumps(expected).encode()
            (root / 'openapi.yaml').write_bytes(raw if not tamper else raw + b'info: {title: altered}\n')
            report_path = root / 'report.json'
            with patch('check_contract_candidate.assess_candidate', return_value={
                'status': 'passed', 'global_errors': [], 'missing_inputs': [],
                'evaluation': 'actual_publication_graph_and_offline_composed_candidate'}), \
                 patch('runtime_consolidate_openapi.build_unified_spec', return_value=expected), \
                 patch('runtime_consolidate_openapi.inject_x402_annotations'), patch('runtime_consolidate_openapi.remove_v2_path_mirrors'), \
                 patch.object(sys, 'argv', ['check', '--root', str(root), '--report', str(report_path)]), patch('builtins.print'):
                result = main()
            return result, json.loads(report_path.read_text()), hashlib.sha256(raw).hexdigest()

    def test_formal_report_binds_verified_aggregate_and_source_evidence(self):
        status, report, sha = self.run_check()
        self.assertEqual(status, 0)
        self.assertEqual(report['publication_artifact']['openapi_sha256'], sha)
        self.assertEqual(report['publication_artifact']['source_hashes'], {'p.json': 'sha256:fixture'})
        self.assertIn('openapi/upstream/p.json', report['publication_artifact']['files_sha256'])

    def test_missing_source_receipt_is_nonzero_not_assessed(self):
        status, report, _ = self.run_check(source_receipt=False)
        self.assertEqual((status, report['status']), (3, 'not_assessed'))

    def test_stale_aggregate_cannot_get_passed_receipt(self):
        status, report, _ = self.run_check(tamper=True)
        self.assertEqual((status, report['status']), (1, 'failed'))
        self.assertIn({'code': 'aggregate_recomposition_mismatch'}, report['global_errors'])

    def test_even_equal_fresh_aggregate_rejects_unresolved_declaration(self):
        status, report, _ = self.run_check(unresolved=True)
        self.assertEqual((status, report['status']), (1, 'failed'))
        self.assertEqual('aggregate_unresolved_reference', report['global_errors'][0]['code'])


if __name__ == '__main__':
    unittest.main()

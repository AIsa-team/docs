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
from payment_fixture import install_payment_fixture
from source_governance import acquisition_receipt, initial_policy, receipt_key
from sales_catalog_projection import SALES_CATALOG_PATH, sales_catalog_bytes


class FormalReceiptTests(unittest.TestCase):
    def run_check(self, source_receipt=True, tamper=False, unresolved=False, surfaces=False, surface_mutation=None, sales_mutation=None, payment_mutation=None, json_mutation=None, llms_mutation=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install_payment_fixture(root)
            if payment_mutation:
                payment_mutation(root)
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
            (root / 'openapi/openapi.json').write_text(json.dumps(expected))
            if json_mutation:
                json_mutation(root / 'openapi/openapi.json')
            from runtime_consolidate_openapi import discovery_index_block
            index_path = root / 'llms.txt'
            index_path.write_text(discovery_index_block(raw))
            if llms_mutation:
                llms_mutation(index_path)
            sales = root / SALES_CATALOG_PATH
            sales.parent.mkdir(parents=True)
            sales.write_bytes(sales_catalog_bytes(expected, raw))
            if sales_mutation:
                sales_mutation(sales)
            if surfaces:
                from pull_openapi import generate_pages
                document = {'openapi': '3.1.0', 'info': {'title': 'Fixture', 'x-aisa-document': {'document_hash': 'h'}},
                            'paths': {'/one': {'get': {'operationId': 'one', 'responses': {'204': {'description': 'Empty'}}}}}}
                (root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
                    {'language': lang, 'tabs': [{'tab': title, 'groups': []}]}
                    for lang, title in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))
                changes = {}; generate_pages(root, 'p', document, changes)
                changes[root / 'openapi/p.json'] = json.dumps(document)
                for path, content in changes.items():
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
                if surface_mutation:
                    surface_mutation(root)
            report_path = root / 'report.json'
            with patch('check_contract_candidate.assess_candidate', return_value={
                'status': 'passed', 'global_errors': [], 'missing_inputs': [],
                'evaluation': 'actual_publication_graph_and_offline_composed_candidate'}), \
                 patch('runtime_consolidate_openapi.build_unified_spec', return_value=expected), \
                 patch('runtime_consolidate_openapi.inject_x402_annotations'), patch('runtime_consolidate_openapi.remove_v2_path_mirrors'), \
                 patch.object(sys, 'argv', ['check', '--root', str(root), '--report', str(report_path)]), patch('builtins.print'):
                result = main()
            return result, json.loads(report_path.read_text()), hashlib.sha256(raw).hexdigest()

    def test_missing_or_stale_llms_index_cannot_receive_formal_receipt(self):
        for mutate in (lambda p: p.unlink(), lambda p: p.write_text('stale index')):
            with self.subTest(mutate=mutate):
                status, report, _ = self.run_check(llms_mutation=mutate)
                self.assertEqual(status, 1)
                self.assertIn({'code': 'llms_index_provenance_mismatch'}, report['global_errors'])

    def test_missing_or_stale_json_cannot_receive_formal_receipt(self):
        for mutate in (lambda p: p.unlink(), lambda p: p.write_text('{"paths":{"/plants":{}}}')):
            with self.subTest(mutate=mutate):
                status, report, _ = self.run_check(json_mutation=mutate)
                self.assertEqual(status, 1)
                self.assertIn({'code': 'aggregate_json_recomposition_mismatch'}, report['global_errors'])

    def test_formal_report_binds_verified_aggregate_and_source_evidence(self):
        status, report, sha = self.run_check()
        self.assertEqual(status, 0)
        self.assertEqual(report['publication_artifact']['openapi_sha256'], sha)
        self.assertEqual(report['publication_artifact']['source_hashes'], {'p.json': 'sha256:fixture'})
        self.assertIn('openapi/upstream/p.json', report['publication_artifact']['files_sha256'])

    def test_payment_evidence_output_and_source_are_one_formal_candidate(self):
        for mutation in (lambda r: (r / 'discovery/openapi.json').unlink(),
                         lambda r: (r / 'discovery/openapi.json').write_text('{}'),
                         lambda r: (r / 'discovery/payment-evidence.json').unlink(),
                         lambda r: (r / 'openapi/polymarket-data.json').write_text('{}')):
            with self.subTest(mutation=mutation):
                status, report, _ = self.run_check(payment_mutation=mutation)
                self.assertEqual((status, report['status']), (1, 'failed'))
                self.assertIn('payment_discovery_mismatch', {e['code'] for e in report['global_errors']})
        status, report, _ = self.run_check()
        self.assertEqual(status, 0)
        self.assertEqual(report['payment_discovery'], {'status': 'passed', 'operations': 3})
        self.assertTrue({'discovery/openapi.json', 'discovery/payment-evidence.json'} <=
                        report['publication_artifact']['files_sha256'].keys())

    def test_missing_or_changed_sales_projection_blocks_formal_receipt(self):
        for mutation in (lambda p: p.unlink(), lambda p: p.write_text('{}')):
            status, report, _ = self.run_check(sales_mutation=mutation)
            self.assertEqual((status, report['status']), (1, 'failed'))
            self.assertIn('sales_catalog_projection_mismatch', {e['code'] for e in report['global_errors']})

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

    def test_formal_receipt_binds_actual_language_schema_pages_and_navigation(self):
        status, report, _ = self.run_check(surfaces=True)
        self.assertEqual(status, 0)
        self.assertEqual(report['publication_surfaces']['operations'], 1)
        self.assertTrue({'openapi.yaml', 'docs.json', 'openapi/zh/p.json', 'api-reference/p/one.mdx',
                         'zh/api-reference/p/one.mdx'} <= report['publication_artifact']['files_sha256'].keys())

    def test_actual_language_navigation_or_identity_tampering_blocks_formal_receipt(self):
        for mutation in (lambda root: (root / 'openapi/zh/p.json').unlink(),
                         lambda root: (root / 'zh/api-reference/p/one.mdx').write_text('---\nopenapi: "openapi/zh/p.json GET /one"\nx-aisa-operation-id: "wrong"\n---\n'),
                         lambda root: (root / 'docs.json').write_text('{"navigation":{}}')):
            status, report, _ = self.run_check(surfaces=True, surface_mutation=mutation)
            self.assertEqual((status, report['status']), (1, 'failed'))
            self.assertEqual(report['global_errors'][0]['code'], 'publication_surface_mismatch')


if __name__ == '__main__':
    unittest.main()

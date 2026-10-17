import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit_tikhub_supplier_auth as checker


class TikHubSupplierAuthTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.spec = Path(self.folder.name) / 'spec.json'
        self.client = Path(self.folder.name) / 'client.py'
        self.document = {'openapi': '3.1.0', 'paths': {'/api/v1/example': {'get': {'security': [{'HTTPBearer': []}]}}}, 'components': {'securitySchemes': {'HTTPBearer': {'type': 'http', 'scheme': 'bearer'}}}}
        self.client.write_text('DEFAULT_BASE_URL = "https://api.tikhub.io"\n')
        self.base = {'rows': [{'provider': 'tikhub', 'path': '/apis/v1/tikhub/example', 'method': 'GET', 'runtime_operation_id': 'example', 'status': 'public_aisa_source_not_supplier_auth_authority'}, {'provider': 'other', 'path': '/other', 'method': 'GET', 'runtime_operation_id': 'other', 'status': 'supplier_auth_not_declared'}]}
        self.transport = {'example': {'provider_id': 108, 'auth_location': 'header', 'auth_name': 'Authorization', 'auth_header': 'Authorization', 'credential_configured': True, 'credential_scheme': '', 'credential_format': 'bearer_prefixed', 'base_url_sha256': hashlib.sha256(b'https://api.tikhub.io').hexdigest()}}
        self.targets = {('/apis/v1/tikhub/example', 'GET'): '/api/v1/example'}

    def run_review(self):
        self.spec.write_text(json.dumps(self.document))
        with patch.object(checker, 'SPEC_SHA256', hashlib.sha256(self.spec.read_bytes()).hexdigest()), patch.object(checker, 'CLIENT_SHA256', hashlib.sha256(self.client.read_bytes()).hexdigest()):
            return checker.apply_supplement(self.base, self.transport, self.targets, self.spec, self.client)

    def test_exact_primary_security_origin_and_format_are_required(self):
        result = self.run_review()
        self.assertEqual(result['rows'][0]['status'], 'transport_shape_compatible_key_validity_unverified')
        self.assertEqual(result['rows'][1], self.base['rows'][1])
        self.assertEqual(result['primary_supplement']['credential_validity_or_provider_business_success'], 'NOT_TESTED')
        self.assertFalse(result['primary_supplement']['request_schema_authority_replaced'])

    def test_modified_supplier_bytes_are_rejected(self):
        self.spec.write_text(json.dumps(self.document))
        with self.assertRaisesRegex(ValueError, 'pinned official SDK bytes differ'):
            checker.apply_supplement(self.base, self.transport, self.targets, self.spec, self.client)

    def test_unverified_binding_is_not_overridden_by_the_public_path(self):
        self.base['rows'][0]['status'] = 'supplier_auth_source_unverified'
        self.assertEqual(self.run_review()['rows'][0], self.base['rows'][0])

    def test_actual_Runtime_target_must_match_the_reviewed_supplier_method(self):
        self.targets[('/apis/v1/tikhub/example', 'GET')] = '/api/v1/other'
        with self.assertRaisesRegex(ValueError, 'Runtime upstream target differs'):
            self.run_review()

    def test_missing_route_and_undeclared_security_are_never_waived(self):
        self.document['paths'] = {}
        self.assertEqual(self.run_review()['rows'][0]['status'], 'supplier_operation_unavailable_in_pinned_primary')
        self.document['paths'] = {'/api/v1/example': {'get': {}}}
        self.assertEqual(self.run_review()['rows'][0]['status'], 'supplier_auth_not_declared')

    def test_header_origin_and_prefix_errors_remain_visible(self):
        for field, value, status in [('auth_name', 'wrong-name', 'blocked_auth_transport'), ('base_url_sha256', 'different-origin', 'auth_transport_origin_unverified'), ('credential_format', 'nonempty_other', 'auth_scheme_or_value_unverified')]:
            with self.subTest(field=field), patch.dict(self.transport['example'], {field: value}):
                self.assertEqual(self.run_review()['rows'][0]['status'], status)


if __name__ == '__main__':
    unittest.main()

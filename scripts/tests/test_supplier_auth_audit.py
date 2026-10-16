import copy
import hashlib
import unittest

from audit_supplier_auth import audit_provider, check_security
from test_runtime_contracts import facts, mirror, operation


def transport(**changes):
    value = dict(provider_id=1, auth_location='header', auth_name='x-api-key', auth_header='',
                 credential_configured=True, credential_scheme='', fixed_header_names=[],
                 base_url_sha256=hashlib.sha256(b'https://secret-provider.example').hexdigest())
    value.update(changes)
    return value


def source():
    doc = mirror()
    doc['components']['securitySchemes'] = {
        'Key': {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'},
        'Address': {'type': 'apiKey', 'in': 'header', 'name': 'POLY_ADDRESS'},
        'Signature': {'type': 'apiKey', 'in': 'header', 'name': 'POLY_SIGNATURE'},
        'Bearer': {'type': 'http', 'scheme': 'bearer'},
    }
    return doc


class SupplierAuthAuditTests(unittest.TestCase):
    def test_security_groups_are_or_and_fields_within_group_are_and(self):
        doc = source()
        op = {'security': [{'Key': [], 'Address': []}]}
        self.assertEqual(check_security(doc, op, transport())['status'], 'blocked_auth_transport')
        op['security'].append({'Key': []})
        self.assertEqual(check_security(doc, op, transport())['status'],
                         'transport_shape_compatible_key_validity_unverified')

    def test_operation_override_and_anonymous_alternative(self):
        for security in ([], [{}], [{'Key': []}, {}]):
            self.assertEqual(check_security(source(), {'security': security}, None)['status'],
                             'supplier_declares_unauthenticated_alternative')
        doc = source()
        self.assertEqual(check_security(doc, {}, transport())['status'],
                         'transport_shape_compatible_key_validity_unverified')
        doc.pop('security')
        self.assertEqual(check_security(doc, {}, transport())['status'], 'supplier_auth_not_declared')

    def test_header_case_insensitivity_does_not_apply_to_query(self):
        doc = source()
        op = {'security': [{'Key': []}]}
        self.assertEqual(check_security(doc, op, transport(auth_name='X-Api-Key'))['status'],
                         'transport_shape_compatible_key_validity_unverified')
        doc['components']['securitySchemes']['Key'].update({'in': 'query', 'name': 'apiKey'})
        result = check_security(doc, op, transport(auth_location='query', auth_name='apikey'))
        self.assertEqual(result['status'], 'blocked_auth_transport')
        self.assertEqual(result['alternatives'][0]['missing_transport_fields'], [{'in': 'query', 'name': 'apiKey'}])

    def test_origin_binding_is_required_before_calling_a_gap_confirmed(self):
        result = check_security(source(), {'security': [{'Key': []}]}, transport(auth_name='Authorization', base_url_sha256='unknown'))
        self.assertEqual(result['status'], 'auth_transport_origin_unverified')
        self.assertFalse(result['documented_server_binding_verified'])

    def test_static_signature_header_is_not_proof_of_a_signer(self):
        result = check_security(source(), {'security': [{'Key': [], 'Signature': []}]},
                                transport(fixed_header_names=['POLY_SIGNATURE']))
        self.assertEqual(result['status'], 'auth_scheme_or_value_unverified')
        self.assertIn('dynamic_auth_generation_unverified:POLY_SIGNATURE', result['alternatives'][0]['unsupported'])

    def test_bearer_prefix_token_format_and_unsupported_flows_are_explicit(self):
        doc = source()
        op = {'security': [{'Bearer': []}]}
        bare = transport(auth_name='Authorization')
        self.assertEqual(check_security(doc, op, bare)['status'], 'auth_scheme_or_value_unverified')
        bare['credential_scheme'] = 'bearer'
        self.assertEqual(check_security(doc, op, bare)['status'], 'transport_shape_compatible_key_validity_unverified')
        doc['components']['securitySchemes']['Bearer']['bearerFormat'] = 'JWT'
        self.assertEqual(check_security(doc, op, bare)['status'], 'transport_shape_compatible_key_validity_unverified')
        bare['credential_scheme'] = ''
        bare['credential_format'] = 'bearer_prefixed'
        self.assertEqual(check_security(doc, op, bare)['status'], 'transport_shape_compatible_key_validity_unverified')
        for definition in ({'type': 'http', 'scheme': 'basic'}, {'type': 'oauth2', 'flows': {}}, {}):
            doc['components']['securitySchemes']['Bearer'] = definition
            self.assertEqual(check_security(doc, op, bare)['status'], 'auth_scheme_or_value_unverified')

    def test_observed_basic_encoding_is_compatible_only_without_bearer_rewrite(self):
        doc = source()
        doc['components']['securitySchemes']['Basic'] = {'type': 'http', 'scheme': 'basic'}
        op = {'security': [{'Basic': []}]}
        config = transport(auth_name='Authorization', credential_format='basic_prefixed')
        self.assertEqual(check_security(doc, op, config)['status'], 'transport_shape_compatible_key_validity_unverified')
        config['credential_scheme'] = 'bearer'
        self.assertEqual(check_security(doc, op, config)['status'], 'auth_scheme_or_value_unverified')

    def test_refs_missing_credentials_and_cookie_not_supported_by_generic_transport(self):
        doc = source()
        doc['components']['securitySchemes']['Alias'] = {'$ref': '#/components/securitySchemes/Key'}
        self.assertEqual(check_security(doc, {'security': [{'Alias': []}]}, transport())['status'],
                         'transport_shape_compatible_key_validity_unverified')
        self.assertEqual(check_security(doc, {}, transport(credential_configured=False))['status'], 'blocked_auth_transport')
        doc['components']['securitySchemes']['Key']['in'] = 'cookie'
        self.assertEqual(check_security(doc, {}, transport())['status'], 'blocked_auth_transport')

    def test_any_public_mirrors_are_counted_without_inventing_supplier_authority(self):
        runtime = facts('mixed', 'x-aisa-any')
        mirrors = {('/apis/v1/similarweb/test', m): {'operation': {}, 'source': {'kind': 'manual'}} for m in ('get', 'post')}
        rows = audit_provider('example', runtime, None, mirrors, {}, {})
        self.assertEqual([(r['method'], r['status']) for r in rows],
                         [(m, 'public_aisa_source_not_supplier_auth_authority') for m in ('GET', 'POST')])

    def test_bound_source_cannot_fall_back_to_a_historical_mirror(self):
        runtime, doc = facts('mixed'), source()
        doc['paths'] = {}
        path = '/apis/v1/similarweb/test'
        rows = audit_provider('example', runtime, doc, {(path, 'post'): {'operation': {}}},
                              {path: doc['info']['x-aisa-source']['url']}, {})
        self.assertEqual(rows[0]['status'], 'supplier_auth_source_unverified')

    def test_runtime_owned_disabled_and_public_source_have_separate_accounting(self):
        runtime, doc = facts('runtime'), source()
        self.assertEqual(audit_provider('example', runtime, doc, {}, {}, {})[0]['status'], 'runtime_owned_auth_review_separate')
        operation(runtime)['x-aisa-status'] = 'disabled'
        self.assertEqual(audit_provider('example', runtime, doc, {}, {}, {}), [])
        runtime = facts('mixed')
        doc['info']['x-aisa-source']['path_space'] = 'public'
        before = copy.deepcopy(doc)
        self.assertEqual(audit_provider('example', runtime, doc, {}, {}, {})[0]['status'], 'public_aisa_source_not_supplier_auth_authority')
        self.assertEqual(doc, before)


if __name__ == '__main__':
    unittest.main()

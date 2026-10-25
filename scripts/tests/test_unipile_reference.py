import copy
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import compose, digest, upstream_path_item
from import_unipile_reference import V1_URL, JOB_SLOTS_URL, JOB_SLOTS_PATH, convert_reference
from import_upstream import import_source
from source_governance import policy_errors


class UnipileReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = Path(__file__).parent / 'fixtures/unipile-official-20261025.tar.gz'
        with tarfile.open(archive) as source:
            cls.v1 = source.extractfile('v1.json').read()
            cls.slots = source.extractfile('job-slots.md').read()

    def imported(self, raw, url):
        with patch('import_upstream.urlopen', return_value=io.BytesIO(raw)):
            return import_source('unipile', url)

    def test_v1_parameter_rename_preserves_all_other_official_bytes(self):
        document, metadata = convert_reference(self.v1, V1_URL)
        restored = copy.deepcopy(document)
        item = restored['paths'].pop('/api/v1/users/{user_id}/posts')
        for container in (item, item.get('get', {})):
            for parameter in container.get('parameters', []):
                if parameter.get('in') == 'path' and parameter.get('name') == 'user_id':
                    parameter['name'] = 'identifier'
        restored['paths']['/api/v1/users/{identifier}/posts'] = item
        self.assertEqual(restored, json.loads(self.v1))
        self.assertEqual(metadata['upstream_content_hash'], digest(restored))

    def test_official_job_slot_fragment_preserves_typed_request_and_response(self):
        document = self.imported(self.slots, JOB_SLOTS_URL)
        operation = document['paths'][JOB_SLOTS_PATH]['get']
        self.assertEqual(operation['parameters'][0]['schema']['pattern'], '^acc_(.*)$')
        schema = operation['responses']['200']['content']['application/json']['schema']
        self.assertEqual(set(schema['required']), {'object', 'total', 'used', 'available'})
        self.assertEqual(schema['properties']['available']['type'], 'number')
        self.assertEqual(policy_errors(document['info']['x-aisa-source']), [])

    def test_official_sources_resolve_actual_v1_and_v2_operation_paths(self):
        v1 = self.imported(self.v1, V1_URL)
        for path, method in [('/api/v1/chats', 'post'), ('/api/v1/chats/{chat_id}/messages', 'post'),
                             ('/api/v1/linkedin/company/{identifier}', 'get'),
                             ('/api/v1/users/{user_id}/posts', 'get'),
                             ('/api/v1/users/invite', 'post'),
                             ('/api/v1/users/invite/sent/{invitation_id}', 'delete'),
                             ('/api/v1/posts', 'post'), ('/api/v1/posts/reaction', 'post'),
                             ('/api/v1/posts/{post_id}/comments', 'post')]:
            with self.subTest(path=path):
                self.assertIn(method, upstream_path_item(v1, path))
        self.assertIn('get', upstream_path_item(self.imported(self.slots, JOB_SLOTS_URL), JOB_SLOTS_PATH))

    def test_original_missing_source_regression_and_job_slots_composition(self):
        path = '/apis/v1/unipile/linkedin/recruiter/job-slots-credits/{account_id}'
        facts = {'openapi': '3.1.0', 'servers': [{'url': 'https://api.aisa.one'}],
                 'info': {'title': 'Unipile', 'version': '1', 'x-aisa-document': {'facts_hash': 'sha256:fixture'}},
                 'paths': {path: {'get': {'operationId': 'get_unipile_linkedin_job_slots_credits',
                    'x-aisa-status': 'enabled', 'x-aisa-validation': 'provider',
                    'x-aisa-upstream-path': JOB_SLOTS_PATH, 'parameters': [],
                    'responses': {'200': {'description': 'Success'}}}}}}
        _, missing = compose(facts)
        self.assertEqual(missing[0]['reason'], 'upstream operation missing')
        document, pending = compose(facts, self.imported(self.slots, JOB_SLOTS_URL))
        self.assertEqual(pending, [])
        operation = document['paths'][path]['get']
        self.assertEqual(operation['operationId'], 'get_unipile_linkedin_job_slots_credits')
        self.assertTrue(any(row['name'] == 'account_id' and row['required']
                            for row in operation['parameters']))

    def test_ambiguous_markdown_and_changed_operation_fail_closed(self):
        for raw in (self.slots + self.slots,
                    self.slots.replace(b'getRecruiterJobSlotsCredits', b'otherOperation'),
                    self.slots.replace(JOB_SLOTS_PATH.encode(), b'/other')):
            with self.subTest(raw_length=len(raw)), self.assertRaises(ValueError):
                convert_reference(raw, JOB_SLOTS_URL)

    def test_source_hash_excludes_only_acquisition_annotation(self):
        for raw, url in ((self.v1, V1_URL), (self.slots, JOB_SLOTS_URL)):
            document = self.imported(raw, url)
            source = document['info'].pop('x-aisa-source')
            self.assertEqual(source['content_hash'], digest(document))
            self.assertEqual(source['url'], url)
            self.assertEqual(policy_errors(source), [])

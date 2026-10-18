"""Synthetic transport controls; never reads an operator credential."""
import base64
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import probe_existing_read_app as probe


LOCK = b'''{
  "schema_version": 2,
  "compiler_inputs": {
    "protocol_version": "aisa-runtime-canonical-v1",
    "bundle_manifest_sha256": "18fa13c04d38a0fa5b308869b396e645ee2676c8eb16bbda1e9601eab7cfddae",
    "docs_ref": "8b29bded034c7da45c95d0c9a4b60fd4cc666ae9",
    "composer_revision": "85e42087074577eecb83d881340e0cc13b655483",
    "source_manifest_sha256": "7f80c7572fc9f543342bd21047d2e51062e2f88446c35d4b14121e678d0e747b"
  },
  "bundle_supply": {
    "kind": "reviewed_git",
    "repository": "AIsa-team/docs"
  }
}
'''


def fixture():
    values = [
        {'id': probe.SERVICES_RUN, 'head_sha': probe.SERVICES_HEAD,
            'path': '.github/workflows/api-contract-e2e.yml',
            'repository': {'full_name': 'AIsa-team/AIsaServices', 'private': True},
            'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success'},
        {'type': 'file', 'path': probe.LOCK_PATH, 'encoding': 'base64',
            'sha': probe.LOCK_BLOB_SHA1, 'content': base64.b64encode(LOCK).decode(), 'size': len(LOCK)},
        {'id': probe.DOCS_RUN, 'head_sha': probe.DOCS_HEAD,
            'path': '.github/workflows/test-runtime-contracts.yml',
            'repository': {'full_name': 'AIsa-team/docs'}, 'conclusion': 'failure'},
    ]
    client = mock.Mock()
    client.json.side_effect = values
    return values, client


class ExistingReadAppProbeTests(unittest.TestCase):
    def test_three_fixed_objects_verify_credential_read_only_not_successful_Docs_qualification(self):
        _, client = fixture()
        result = probe.probe(client, probe.APP_SLUG, probe.APP_ID)
        self.assertEqual([c.args[0] for c in client.json.call_args_list], list(probe.PATHS))
        self.assertEqual(result['fixed_API_GETs'], 3)
        for key in ['token_exported', 'source_qualification', 'formal', 'deploy']:
            self.assertIs(result[key], False)
        self.assertEqual(result['writes'], 0)

    def test_wrong_public_App_identity_rejects_before_any_API(self):
        for slug, app in [('other', probe.APP_ID), (probe.APP_SLUG, '4961125'),
                (None, probe.APP_ID), (probe.APP_SLUG, 4961124)]:
            _, client = fixture()
            with self.subTest(slug=slug, app=app), self.assertRaises(ValueError):
                probe.probe(client, slug, app)
            client.json.assert_not_called()

    def test_fixed_run_head_repo_private_status_and_lock_content_pins(self):
        for mode in ['Services-ID', 'Services-head', 'Services-repo', 'public', 'failed',
                'lock-sha', 'lock-base64', 'lock-content', 'lock-size', 'Docs-ID', 'Docs-head']:
            values, client = fixture()
            if mode == 'Services-ID': values[0]['id'] = True
            elif mode == 'Services-head': values[0]['head_sha'] = probe.DOCS_HEAD
            elif mode == 'Services-repo': values[0]['repository']['full_name'] = 'other/repo'
            elif mode == 'public': values[0]['repository']['private'] = False
            elif mode == 'failed': values[0]['conclusion'] = 'failure'
            elif mode == 'lock-sha': values[1]['sha'] = '0' * 40
            elif mode == 'lock-base64': values[1]['content'] = 'not-base64!'
            elif mode == 'lock-content': values[1]['content'] = base64.b64encode(b'changed').decode()
            elif mode == 'lock-size': values[1]['size'] = True
            elif mode == 'Docs-ID': values[2]['id'] += 1
            else: values[2]['head_sha'] = probe.SERVICES_HEAD
            with self.subTest(mode=mode), self.assertRaises((ValueError, TypeError)):
                probe.probe(client, probe.APP_SLUG, probe.APP_ID)

    def test_token_only_fixed_API_GET_no_proxy_or_redirect(self):
        client = probe.FixedAPI('synthetic_' + 't' * 32)
        response = mock.MagicMock()
        response.code = 200
        response.headers = {'Content-Length': '2'}
        response.read1.side_effect = [b'{}', b'']
        response.__enter__.return_value = response
        client._opener.open = mock.Mock(return_value=response)
        self.assertEqual(client.json(probe.PATHS[0]), {})
        request = client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, probe.API + probe.PATHS[0])
        self.assertEqual(request.get_method(), 'GET')
        for path in ['https://evil.invalid', '/repos/other/repo', probe.PATHS[0] + '/logs']:
            with self.assertRaises(ValueError): client.json(path)
        client._opener.open.assert_called_once()
        self.assertIsNone(probe.NoRedirect().redirect_request(None, None, 302, '', {},
            'https://storage.invalid/secret-location'))

    def test_response_call_time_and_duplicate_JSON_limits(self):
        for mode in ['calls', 'deadline', 'length', 'actual-bytes', 'duplicate']:
            client = probe.FixedAPI('synthetic_' + 't' * 32)
            response = mock.MagicMock()
            response.code = 200
            response.headers = {}
            response.read1.side_effect = [b'{}', b'']
            response.__enter__.return_value = response
            client._opener.open = mock.Mock(return_value=response)
            if mode == 'calls': client._calls = 3
            elif mode == 'deadline': client._deadline = time.monotonic() - 1
            elif mode == 'length': response.headers = {'Content-Length': str(probe.LIMIT + 1)}
            elif mode == 'actual-bytes':
                response.read1.side_effect = None
                response.read1.return_value = b'x' * 65536
            else: response.read1.side_effect = [b'{"id":1,"id":2}', b'']
            with self.subTest(mode=mode), self.assertRaises(ValueError): client.json(probe.PATHS[0])

    def test_failure_and_success_stdout_do_not_include_token_or_raw_errors(self):
        environment = {'READ_APP_SLUG': probe.APP_SLUG, 'READ_APP_ID': probe.APP_ID,
            'GH_TOKEN': 'synthetic-secret-not-for-log'}
        for success in [False, True]:
            _, client = fixture()
            if not success: client.json.side_effect = RuntimeError('private-token-or-URL-value')
            with mock.patch.dict(probe.os.environ, environment, clear=True), \
                    mock.patch.object(probe.sys, 'argv', ['probe']), \
                    mock.patch.object(probe, 'FixedAPI', return_value=client), \
                    contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(probe.main(), 0 if success else 1)
            public = out.getvalue() + err.getvalue()
            self.assertNotIn(environment['GH_TOKEN'], public)
            self.assertNotIn('private-token-or-URL-value', public)
            if not success:
                self.assertEqual(out.getvalue(), '')
                self.assertEqual(err.getvalue(),
                    'Existing Docs Read App probe rejected; private diagnostics withheld\n')

    def test_workflow_manual_exact_feature_branch_and_two_readonly_repo_scope(self):
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2] /
            '.github/workflows/test-runtime-contracts.yml').read_text())
        event = workflow.get('on', workflow.get(True))
        self.assertIs(event['workflow_dispatch']['inputs']['read_app_probe']['default'], False)
        job = workflow['jobs']['probe-existing-read-app']
        self.assertEqual(job['if'], "github.event_name == 'workflow_dispatch' && inputs.read_app_probe == true && github.ref == 'refs/heads/codex/existing-read-app-docs-probe-20261018'")
        step = next(s for s in job['steps'] if s.get('id') == 'probe_read')
        self.assertEqual(step['with'], {'app-id': '${{ vars.AISA_CI_READ_APP_ID }}',
            'private-key': '${{ secrets.AISA_CI_READ_APP_PRIVATE_KEY }}', 'owner': 'AIsa-team',
            'repositories': 'AIsaServices\ndocs\n', 'permission-actions': 'read',
            'permission-contents': 'read'})
        self.assertNotIn('environment', job)
        self.assertFalse(any('upload-artifact' in s.get('uses', '') for s in job['steps']))


if __name__ == '__main__':
    unittest.main()

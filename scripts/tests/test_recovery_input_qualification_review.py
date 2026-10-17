"""Independent adversarial review of exact recovery evidence consumption."""
import copy
from contextlib import ExitStack
from datetime import timedelta
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import read_recovery_input_qualification as reader
import test_recovery_input_qualification as fixtures


class RecoveryQualificationIndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryQualificationTests()
        self.fixture.setUp()
        self.now = self.fixture.now
        self.binding = copy.deepcopy(self.fixture.binding)
        self.report = copy.deepcopy(self.fixture.report)
        self.event = copy.deepcopy(self.fixture.event)

    def assess_fixture(self, output, finished, *, formal_error=None, governance=None):
        paths = ['docs/schema-inputs/context.json', 'openapi/upstream/official.json']
        self.report['changed_paths'] = sorted(paths)
        formal_ref = '7' * 40
        contents = {
            reader.INPUT_CONTEXT_MEMBER: json.dumps({'historical_formal_ref': formal_ref}).encode(),
            'evidence/source-receipts.json': b'{"schema_version":1,"receipts":{}}',
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(reader, 'git_changed_paths', return_value=paths))
            stack.enter_context(patch.object(reader, 'verify_producer', return_value=(
                self.report, self.fixture.old_inputs, {})))
            ancestry = stack.enter_context(patch.object(reader.subprocess, 'run'))
            stack.enter_context(patch.object(reader, 'export_reviewed_bundle',
                return_value=self.report['input_bundle']))
            stack.enter_context(patch.object(reader, 'load_bundle',
                return_value=SimpleNamespace(contents=contents)))
            historical = stack.enter_context(patch.object(reader, 'inspect_publication',
                return_value={'expected_docs_ref': formal_ref}, side_effect=formal_error))
            policy = stack.enter_context(patch.object(reader, 'source_report', return_value=(
                governance or {'status': 'passed', 'policy_errors': {}, 'sources': {}})))
            result = reader.assess(Path('/public/review-fixture'), output, self.binding,
                self.event, None, self.now, clock=lambda: finished)
            historical.assert_called_once_with(Path('/public/review-fixture'), formal_ref, historical=True)
            ancestry.assert_called_once()
            self.assertEqual(policy.call_args.kwargs['checked_at'], finished)
            return result

    def test_full_assessment_cannot_write_passed_receipt_after_any_deadline(self):
        for mode in ('operator-binding-expiry', 'original-request-expiry', 'proof-age-limit'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                self.setUp()
                if mode == 'operator-binding-expiry':
                    self.binding['expires_at'] = (self.now + timedelta(minutes=1)).isoformat()
                    finished = self.now + timedelta(minutes=2)
                elif mode == 'original-request-expiry':
                    self.report['request']['expires_at'] = (self.now + timedelta(minutes=1)).isoformat()
                    finished = self.now + timedelta(minutes=2)
                else:
                    finished = self.now + timedelta(minutes=15)
                output = Path(folder) / 'assessment'
                with self.assertRaises(ValueError):
                    self.assess_fixture(output, finished)
                self.assertFalse((output / 'receipt.json').exists())

    def test_fresh_assessment_retains_independent_historical_formal_producer_and_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'assessment'
            result = self.assess_fixture(output, self.now + timedelta(seconds=1))
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['scope'], reader.SCOPE)
            self.assertEqual(result['checked_at'], (self.now + timedelta(seconds=1)).isoformat())
            self.assertEqual(result['historical_formal_provenance']['expected_docs_ref'], '7' * 40)
            self.assertEqual(result['freshness_scope'],
                'authenticated_source_at_qualification_only_not_CI_time_current_or_formal_freshness')
            self.assertTrue((output / 'receipt.json').is_file())

    def test_historical_formal_failure_cannot_be_replaced_by_new_qualification(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'assessment'
            with self.assertRaisesRegex(ValueError, 'sole-publisher'):
                self.assess_fixture(output, self.now, formal_error=ValueError('sole-publisher rejected'))
            self.assertFalse((output / 'receipt.json').exists())

    def test_current_source_policy_failure_after_download_cannot_issue_passed_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'assessment'
            with self.assertRaises(ValueError):
                self.assess_fixture(output, self.now, governance={
                    'status': 'failed', 'policy_errors': {'official': ['expired']}})
            self.assertFalse((output / 'receipt.json').exists())

    def test_foreign_run_duplicate_or_skipped_job_and_wrong_exporter_lock_are_rejected(self):
        for mode in ('foreign-repository', 'duplicate-job', 'skipped-job', 'lock-encoding',
                     'exporter-lock-differs-from-source'):
            with self.subTest(mode=mode):
                responses, read = self.fixture.producer_fixture()
                if mode == 'foreign-repository':
                    responses['actions/runs/42']['repository']['full_name'] = 'untrusted/repository'
                elif mode == 'duplicate-job':
                    jobs = responses['actions/runs/42/attempts/2/jobs']['jobs']
                    jobs.append(copy.deepcopy(jobs[-1]))
                elif mode == 'skipped-job':
                    responses['actions/runs/42/attempts/2/jobs']['jobs'][-1]['conclusion'] = 'skipped'
                else:
                    lock = responses['contents/packages/apicontract/composer-inputs.lock.json?ref=' + '2' * 40]
                    if mode == 'lock-encoding':
                        lock['encoding'] = 'plain'
                    else:
                        import base64
                        lock['content'] = base64.b64encode(json.dumps({
                            'compiler_inputs': self.fixture.inputs}).encode()).decode()
                with self.assertRaises(ValueError):
                    report, old_inputs, _ = reader.verify_producer(self.fixture.binding, read)
                    reader.verify_report(self.fixture.binding, report, old_inputs, self.now)

    def test_rehashed_archive_with_unsafe_or_incomplete_members_is_rejected(self):
        for mode in ('traversal', 'symlink', 'duplicate', 'missing'):
            with self.subTest(mode=mode):
                responses, read = self.fixture.producer_fixture()
                with zipfile.ZipFile(io.BytesIO(responses['actions/artifacts/17/zip'])) as original:
                    entries = [(name, original.read(name)) for name in original.namelist()]
                changed = io.BytesIO()
                with warnings.catch_warnings(), zipfile.ZipFile(changed, 'w') as packet:
                    warnings.simplefilter('ignore', UserWarning)
                    for index, (name, raw) in enumerate(entries):
                        if index == 0 and mode == 'missing':
                            continue
                        if index == 0 and mode == 'traversal':
                            name = '../' + name
                        info = zipfile.ZipInfo(name)
                        if index == 0 and mode == 'symlink':
                            info.create_system = 3
                            info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        packet.writestr(info, raw)
                        if index == 0 and mode == 'duplicate':
                            packet.writestr(name, raw)
                raw = changed.getvalue()
                self.fixture.binding['archive_sha256'] = reader.sha(raw)
                responses['actions/artifacts/17']['size_in_bytes'] = len(raw)
                responses['actions/artifacts/17/zip'] = raw
                with self.assertRaises(ValueError):
                    reader.verify_producer(self.fixture.binding, read)

    def test_authenticated_download_redirect_never_sends_app_token_to_other_origin(self):
        redirect = reader.Redirect()
        request = urllib.request.Request('https://api.github.com/repos/example/artifact',
            headers={'Authorization': 'Bearer synthetic-review-token'})
        headers = {}
        moved = redirect.redirect_request(request, None, 302, 'Found', headers,
            'https://archive.example.invalid/artifact.zip')
        self.assertIsNone(moved.get_header('Authorization'))
        same = redirect.redirect_request(request, None, 302, 'Found', headers,
            'https://api.github.com/another-artifact')
        self.assertEqual(same.get_header('Authorization'), 'Bearer synthetic-review-token')
        with self.assertRaises(ValueError):
            redirect.redirect_request(request, None, 302, 'Found', headers,
                'http://archive.example.invalid/artifact.zip')


if __name__ == '__main__':
    unittest.main()

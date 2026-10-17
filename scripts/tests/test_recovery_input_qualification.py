import base64
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from read_recovery_input_qualification import (binding_value, verify_producer, verify_report,
    SCOPE, REPOSITORY, WORKFLOW, sha)


class RecoveryQualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 17, 14, 30, tzinfo=timezone.utc)
        self.inputs = {'protocol_version': 'aisa-runtime-canonical-v1', 'docs_ref': 'a' * 40,
            'composer_revision': 'c' * 40, 'bundle_manifest_sha256': 'd' * 64, 'source_manifest_sha256': 'e' * 64}
        self.old_inputs = {**self.inputs, 'docs_ref': 'f' * 40}
        self.binding = {'schema_version': 1, 'scope': SCOPE, 'head_revision': 'a' * 40,
            'base_revision': 'b' * 40, 'candidate_compiler_inputs': self.inputs, 'source_api_revision': '1' * 40,
            'source_export_revision': '2' * 40, 'qualifier_revision': '3' * 40, 'run_id': '42',
            'run_attempt': 2, 'artifact_id': '17', 'archive_sha256': '4' * 64,
            'issued_at': self.now.isoformat(), 'expires_at': (self.now + timedelta(minutes=30)).isoformat()}
        self.event = {'pull_request': {'number': 219, 'head': {'sha': 'a' * 40, 'repo': {'full_name': 'AIsa-team/docs'}},
            'base': {'sha': 'b' * 40, 'ref': 'main', 'repo': {'full_name': 'AIsa-team/docs'}}}}
        request = {key: self.binding[key] for key in ('scope', 'head_revision', 'base_revision',
            'candidate_compiler_inputs', 'source_api_revision', 'source_export_revision')}
        request.update(docs_pr=219, issued_at=(self.now - timedelta(minutes=10)).isoformat(),
            expires_at=(self.now + timedelta(minutes=20)).isoformat())
        self.report = {'schema_version': 1, 'status': 'passed', 'scope': SCOPE,
            'workflow_revision': self.binding['qualifier_revision'], 'run_id': '42', 'run_attempt': 2,
            'source_unchanged_across_qualification': True, 'production_database_writes': 0, 'provider_calls': 0,
            'formal_publication_or_promotion': False, 'request': request,
            'started_at': (self.now - timedelta(minutes=8)).isoformat(),
            'completed_at': (self.now - timedelta(minutes=1)).isoformat(),
            'source': {'compiler_revision': '1' * 40, 'compiler_inputs': self.old_inputs,
                'generation': 917, 'source_digest': '5' * 64},
            'source_governance': {'status': 'passed', 'policy_errors': {}, 'sources': {'official': {'freshness': 'fresh'}}},
            'input_bundle': {'docs_ref': 'a' * 40, 'manifest_sha256': 'd' * 64},
            'composition': {'scope': 'existing_composer_offline_shadow_only_not_formal_publication',
                            'summary': {'status': 'passed'}}}

    def test_explicit_binding_never_selects_unrelated_pr_or_formal_scope(self):
        self.assertEqual(binding_value(json.dumps(self.binding), self.event, self.now), self.binding)
        self.assertIsNone(binding_value('', self.event, self.now))
        self.assertIsNone(binding_value(json.dumps(self.binding), {}, self.now))
        event = copy.deepcopy(self.event); event['pull_request']['head']['sha'] = '6' * 40
        self.assertIsNone(binding_value(json.dumps(self.binding), event, self.now))
        for mode in ('scope', 'unknown', 'base', 'expired', 'long', 'duplicate', 'fork'):
            with self.subTest(mode=mode):
                value, event = copy.deepcopy(self.binding), copy.deepcopy(self.event)
                if mode == 'scope': value['scope'] = 'formal_current'
                if mode == 'unknown': value['allow_stale'] = True
                if mode == 'base': value['base_revision'] = '6' * 40
                if mode == 'expired': value['expires_at'] = self.now.isoformat()
                if mode == 'long': value['expires_at'] = (self.now + timedelta(hours=2)).isoformat()
                if mode == 'fork': event['pull_request']['head']['repo']['full_name'] = 'untrusted/fork'
                raw = json.dumps(value)
                if mode == 'duplicate': raw = raw.replace('"run_attempt": 2', '"run_attempt": 2, "run_attempt": 2')
                with self.assertRaises(ValueError): binding_value(raw, event, self.now)

    def test_qualified_source_is_independent_of_candidate_inputs_and_has_no_formal_authority(self):
        verify_report(self.binding, self.report, self.old_inputs, self.now)
        for mode in ('scope', 'run', 'attempt', 'source-api', 'source-inputs', 'changed-cohort',
                     'expired', 'finished-after-expiry', 'overdue', 'policy', 'governance', 'formal', 'bundle', 'composition'):
            with self.subTest(mode=mode):
                value = copy.deepcopy(self.report)
                if mode == 'scope': value['scope'] = 'formal_current'
                if mode == 'run': value['run_id'] = '43'
                if mode == 'attempt': value['run_attempt'] = 3
                if mode == 'source-api': value['source']['compiler_revision'] = '6' * 40
                if mode == 'source-inputs': value['source']['compiler_inputs'] = self.inputs
                if mode == 'changed-cohort': value['source_unchanged_across_qualification'] = False
                if mode == 'expired': value['request']['expires_at'] = self.now.isoformat()
                if mode == 'finished-after-expiry':
                    value['request']['expires_at'] = (self.now - timedelta(minutes=2)).isoformat()
                if mode == 'overdue': value['completed_at'] = (self.now - timedelta(minutes=16)).isoformat()
                if mode == 'policy': value['source_governance']['policy_errors'] = {'official': ['missing_owner']}
                if mode == 'governance': value['source_governance']['sources']['official']['freshness'] = 'overdue'
                if mode == 'formal': value['formal_publication_or_promotion'] = True
                if mode == 'bundle': value['input_bundle']['manifest_sha256'] = '6' * 64
                if mode == 'composition': value['composition']['summary']['status'] = 'failed'
                with self.assertRaises(ValueError): verify_report(self.binding, value, self.old_inputs, self.now)

    def producer_fixture(self):
        expected = {'qualification.json'} | {phase + '/' + name for phase in ('source-before', 'source-after')
            for name in {'observations.json'} | {node + '/' + part for node in ('api-a', 'api-b')
                for part in ('source.json', 'snapshot.json', 'receipt.json')}}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as packet:
            for name in expected:
                packet.writestr(name, json.dumps(self.report) if name == 'qualification.json' else '{}')
        raw = archive.getvalue(); self.binding['archive_sha256'] = sha(raw)
        run = {'id': 42, 'run_attempt': 2, 'head_sha': self.binding['qualifier_revision'], 'path': WORKFLOW,
            'event': 'workflow_dispatch', 'repository': {'full_name': REPOSITORY}, 'status': 'completed', 'conclusion': 'success'}
        jobs = {'jobs': [{'name': name, 'conclusion': 'success'} for name in
            ('contracts', 'Durable contract publication on MySQL', 'source-input-recovery-qualification')]}
        artifact = {'id': 17, 'expired': False, 'name': 'source-input-qualification-42-2', 'size_in_bytes': len(raw),
            'workflow_run': {'id': 42, 'head_sha': self.binding['qualifier_revision']}}
        lock = {'encoding': 'base64', 'content': base64.b64encode(json.dumps({'compiler_inputs': self.old_inputs}).encode()).decode()}
        responses = {'actions/runs/42': run, 'actions/runs/42/attempts/2/jobs': jobs, 'actions/artifacts/17': artifact,
            'actions/artifacts/17/zip': raw, 'contents/packages/apicontract/composer-inputs.lock.json?ref=' + '2' * 40: lock}
        def read(path, limit=None):
            value = responses[path]
            return value if isinstance(value, bytes) else json.dumps(value).encode()
        return responses, read

    def test_trusted_workflow_run_jobs_artifact_and_original_source_lock_all_independently_match(self):
        responses, read = self.producer_fixture()
        report, old_inputs, run = verify_producer(self.binding, read)
        self.assertEqual(report, self.report); self.assertEqual(old_inputs, self.old_inputs)
        for mode in ('workflow', 'revision', 'event', 'run-attempt', 'failed-job', 'expired-artifact', 'foreign-artifact', 'archive'):
            with self.subTest(mode=mode):
                responses, read = self.producer_fixture()
                if mode == 'workflow': responses['actions/runs/42']['path'] = '.github/workflows/untrusted.yml'
                if mode == 'revision': responses['actions/runs/42']['head_sha'] = '6' * 40
                if mode == 'event': responses['actions/runs/42']['event'] = 'pull_request'
                if mode == 'run-attempt': responses['actions/runs/42']['run_attempt'] = 3
                if mode == 'failed-job': responses['actions/runs/42/attempts/2/jobs']['jobs'][2]['conclusion'] = 'failure'
                if mode == 'expired-artifact': responses['actions/artifacts/17']['expired'] = True
                if mode == 'foreign-artifact': responses['actions/artifacts/17']['workflow_run']['id'] = 43
                if mode == 'archive': responses['actions/artifacts/17/zip'] += b'tampered'
                with self.assertRaises(ValueError): verify_producer(self.binding, read)


if __name__ == '__main__':
    unittest.main()

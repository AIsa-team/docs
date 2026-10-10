import copy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import publication_origin as origin
from check_contract_revisions import retain_assessment_history, monitor_timing
from contract_activation import deadline
import test_contract_publication as fixtures


class OriginTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        for name in ('api-reference', 'zh/api-reference'):
            directory=self.root/name; directory.mkdir(parents=True); (directory/'.keep').write_text('')
        (self.root/'docs.json').write_text('{}')
        self.fixture.report['publication_artifact']['files_sha256'] = origin.publication_hashes(self.root)
        self.now = self.fixture.now.replace(microsecond=0) + timedelta(seconds=2)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        self.fixture.report['publication_artifact']['published_ref'] = self.base
        self.install()
        self.git('add', '.')
        self.receipt = origin.record(self.root, '123', 1, self.now)
        self.git('add', origin.ORIGIN)
        self.git('commit', '-qm', 'formal publication')
        self.ref = self.git('rev-parse', 'HEAD')
        self.run = {'id': 123, 'run_attempt': 1, 'repository': {'full_name': origin.REPOSITORY},
                    'path': origin.WORKFLOW, 'head_branch': 'main', 'head_sha': self.base,
                    'event': 'workflow_dispatch'}
        self.jobs = [{'name': 'compose', 'conclusion': 'success', 'steps': [
            {'name': origin.STEP, 'conclusion': 'success',
             'started_at': (self.now-timedelta(seconds=1)).isoformat(),
             'completed_at': (self.now+timedelta(seconds=1)).isoformat()}]}]
        self.end = self.now + timedelta(seconds=2)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True).strip()

    def install(self):
        for name, raw in self.fixture.prepared().items():
            (self.root / 'docs/publication' / name).write_bytes(raw)
        self.artifact = (self.root / 'docs/publication/formal-contract-readiness.json').read_bytes()

    def test_same_c_metadata_selection_preserves_first_genuine_clock(self):
        original = {'expected_docs_ref': self.ref, 'contract_release': self.receipt['contract_release'],
                    'budget_start': self.receipt['budget_start'], 'producer_origin': self.receipt}
        later = dict(original, expected_docs_ref='b' * 40, budget_start=(self.now + timedelta(hours=1)).isoformat())
        with patch.object(origin.subprocess, 'check_output', return_value='b' * 40), \
             patch.object(origin, 'first_contract_ref', return_value=self.ref), \
             patch.object(origin, 'inspect_publication', side_effect=[later, original]) as inspect:
            selected = origin.select(self.root)
        self.assertEqual(selected['expected_docs_ref'], 'b' * 40)
        self.assertEqual(selected['clock_docs_ref'], self.ref)
        self.assertEqual(selected['budget_start'], original['budget_start'])
        inspect.assert_called_with(self.root, self.ref, historical=True)

    def test_real_history_stops_at_distinct_contract_and_rejects_shallow_clock(self):
        self.assertEqual(origin.first_contract_ref(self.root, self.receipt['contract_release']), self.ref)
        with patch.object(origin.subprocess, 'check_output', return_value='true'):
            with self.assertRaisesRegex(ValueError, 'Complete publication history'):
                origin.first_contract_ref(self.root, self.receipt['contract_release'])

    def test_consumer_same_c_requires_active_policy_ancestry_and_original_clock(self):
        selected = {'expected_docs_ref': self.ref, 'contract_release': 'c' * 64,
                    'budget_start': self.receipt['budget_start'], 'clock_docs_ref': self.ref,
                    'authorization_fingerprint': {'alpha': {'policy_revision': 'approved'}},
                    'authorization_expires_at': '2099-01-01T00:00:00Z'}
        candidate = dict(selected, expected_docs_ref=self.base)
        with patch.object(origin, 'remote_formal_ref', return_value=self.ref), \
             patch.object(origin, 'select', return_value=selected), \
             patch.object(origin, 'inspect_publication', return_value=candidate):
            proof = origin.verify_consumer_refs(self.root, self.ref, [self.base], selected['budget_start'])
            self.assertEqual(proof['status'], 'passed')
            for changed in [dict(candidate, contract_release='d' * 64),
                            dict(candidate, authorization_fingerprint={'alpha': {'policy_revision': 'revoked'}})]:
                with patch.object(origin, 'inspect_publication', return_value=changed):
                    with self.assertRaisesRegex(ValueError, 'Consumer contract or active'):
                        origin.verify_consumer_refs(self.root, self.ref, [self.base], selected['budget_start'])
            with self.assertRaisesRegex(ValueError, 'Genuine contract clock'):
                origin.verify_consumer_refs(self.root, self.ref, [self.base], '2099-01-01T00:00:00Z')
            with self.assertRaises(ValueError):
                origin.verify_consumer_refs(self.root, self.ref, ['not-a-ref'], selected['budget_start'])

    def test_real_metadata_commits_do_not_restart_clock_but_changed_c_does(self):
        self.fixture.report['publication_artifact']['published_ref'] = self.ref
        self.fixture.report['source_governance']['checked_at'] = self.now.isoformat()
        for row in self.fixture.report['source_governance']['sources'].values():
            row['checked_at'] = self.now.isoformat()
        self.fixture.now = self.now
        self.install(); self.git('add', '.')
        metadata = origin.record(self.root, '456', 1, self.now + timedelta(seconds=5))
        self.git('add', origin.ORIGIN); self.git('commit', '-qm', 'metadata refresh')
        metadata_ref = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(metadata_ref, self.ref)
        self.assertEqual(origin.first_contract_ref(self.root, metadata['contract_release']), self.ref)
        pointer_path = self.root / 'docs/publication/current.json'
        pointer = json.loads(pointer_path.read_bytes())
        pointer['contract_release'] = 'd' * 64
        pointer_path.write_text(json.dumps(pointer))
        self.git('add', '.')
        origin.record(self.root, '789', 1, self.now + timedelta(seconds=10))
        self.git('add', origin.ORIGIN); self.git('commit', '-qm', 'different contract')
        self.assertEqual(origin.first_contract_ref(self.root, 'd' * 64), self.git('rev-parse', 'HEAD'))
        # This synthetic graph must still be rejected by the real full verifier;
        # the history walk selects a clock, it does not authorize publication.
        with self.assertRaises(ValueError):
            origin.verify_graph(self.root, json.loads((self.root / origin.ORIGIN).read_bytes()), self.artifact, self.end)

    def test_fixed_original_expected_ref_accepts_only_fully_verified_current_same_c(self):
        selected = {'expected_docs_ref': self.ref, 'contract_release': 'c' * 64,
                    'budget_start': self.receipt['budget_start'], 'clock_docs_ref': self.base,
                    'authorization_fingerprint': {}, 'authorization_expires_at': '2099-01-01T00:00:00Z'}
        original = dict(selected, expected_docs_ref=self.base)
        with patch.object(origin, 'remote_formal_ref', return_value=self.ref), \
             patch.object(origin, 'select', return_value=selected), \
             patch.object(origin, 'inspect_publication', return_value=original) as inspect:
            proof = origin.verify_consumer_refs(self.root, self.base, [self.ref], selected['budget_start'])
            self.assertEqual(proof['expected_docs_ref'], self.base)
            self.assertEqual(proof['latest_docs_ref'], self.ref)
            self.assertEqual(proof['clock_docs_ref'], self.base)
            inspect.assert_called_once_with(self.root, self.base)
            with patch.object(origin, 'inspect_publication', return_value=dict(original, contract_release='d' * 64)):
                with self.assertRaisesRegex(ValueError, 'Consumer contract or active'):
                    origin.verify_consumer_refs(self.root, self.base, [self.ref], selected['budget_start'])
            with patch.object(origin, 'inspect_publication', side_effect=ValueError('Code-only ref')):
                with self.assertRaisesRegex(ValueError, 'Code-only ref'):
                    origin.verify_consumer_refs(self.root, self.base, [self.ref], selected['budget_start'])

    def test_formal_advance_and_expiry_during_assessment_fail_closed(self):
        selected = {'expected_docs_ref': self.ref, 'contract_release': 'c' * 64,
                    'budget_start': self.receipt['budget_start'], 'clock_docs_ref': self.ref,
                    'authorization_fingerprint': {}, 'authorization_expires_at': '2099-01-01T00:00:00Z'}
        with patch.object(origin, 'select', return_value=selected), \
             patch.object(origin, 'remote_formal_ref', side_effect=[self.ref, 'b' * 40]):
            with self.assertRaisesRegex(ValueError, 'changed during assessment'):
                origin.verify_consumer_refs(self.root, self.ref, [self.ref], selected['budget_start'])
        selected['authorization_expires_at'] = '2000-01-01T00:00:00Z'
        with patch.object(origin, 'select', return_value=selected), \
             patch.object(origin, 'remote_formal_ref', return_value=self.ref):
            with self.assertRaisesRegex(ValueError, 'expired during assessment'):
                origin.verify_consumer_refs(self.root, self.ref, [self.ref], selected['budget_start'])

    def test_consumer_failed_full_inspection_is_not_equivalence(self):
        selected = {'expected_docs_ref': self.ref, 'contract_release': 'c' * 64,
                    'budget_start': self.receipt['budget_start']}
        with patch.object(origin, 'remote_formal_ref', return_value=self.ref), \
             patch.object(origin, 'select', return_value=selected), \
             patch.object(origin, 'inspect_publication', side_effect=ValueError('Authenticated graph failed')):
            with self.assertRaisesRegex(ValueError, 'Authenticated graph failed'):
                origin.verify_consumer_refs(self.root, self.ref, [self.base], selected['budget_start'])

    def test_formal_origin_and_full_graph_pass(self):
        origin.verify_producer(self.receipt, self.run, self.jobs, self.base, self.end)
        current = origin.verify_graph(self.root, self.receipt, self.artifact, self.end)
        self.assertEqual(current['contract_release'], self.receipt['contract_release'])
        self.assertNotIn(origin.ORIGIN, current['files_sha256'])

    def test_no_change_retry_does_not_rewrite_budget_or_commit(self):
        raw = (self.root / origin.ORIGIN).read_bytes()
        self.assertIsNone(origin.record(self.root, '456', 2, self.now + timedelta(hours=1)))
        self.assertEqual(raw, (self.root / origin.ORIGIN).read_bytes())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_same_c_new_metadata_is_distinct_publication_with_original_step_clock(self):
        old = self.receipt
        self.fixture.report['publication_artifact']['published_ref'] = self.ref
        self.fixture.report['source_governance']['checked_at'] = self.now.isoformat()
        for row in self.fixture.report['source_governance']['sources'].values():
            row['checked_at'] = self.now.isoformat()
        # Metadata renewal is tested with real exported bytes from the same graph.
        self.fixture.now = self.now
        self.install(); self.git('add', '.')
        new = origin.record(self.root, '456', 1, self.now + timedelta(seconds=5))
        self.assertEqual(old['contract_release'], new['contract_release'])
        self.assertNotEqual(old['current_sha256'], new['current_sha256'])
        self.assertNotEqual(old['budget_start'], new['budget_start'])
        self.assertEqual(new['assessed_base'], self.ref)

    def test_retained_receipt_and_non_graph_observation_do_not_publish_or_reset_t0(self):
        import os
        import shlex
        import yaml
        from export_contract_publication import export
        self.fixture.report['publication_artifact']['published_ref'] = self.ref
        report = self.root/'assessment.json'
        report.write_text(json.dumps(self.fixture.report))
        pointer = (self.root/'docs/publication/current.json').read_bytes()
        export(self.root, self.fixture.facts, report, now=self.end)
        self.assertEqual((self.root/'docs/publication/current.json').read_bytes(), pointer)
        retained = json.loads((self.root/'docs/publication/formal-contract-readiness.json').read_bytes())
        self.assertEqual(retained['publication_artifact']['published_ref'], self.base)
        extra = self.root/'openapi/coverage/observation.json'; extra.parent.mkdir()
        extra.write_text('{"observed":"new"}')
        workflow = yaml.safe_load((Path(__file__).resolve().parents[2]/'.github/workflows/pull-openapi.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['compose']['steps'] if s.get('id')=='publish')
        script = script.replace('python scripts/', shlex.quote(sys.executable)+' scripts/')
        before=(self.root/origin.ORIGIN).read_bytes()
        result=subprocess.run(['bash','-e','-c',script],cwd=self.root, capture_output=True,text=True,
                              env={**os.environ,'GITHUB_STEP_SUMMARY':str(self.root/'summary'),
                                   'GITHUB_OUTPUT':str(self.root/'output')})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.git('rev-parse','HEAD'),self.ref)
        self.assertEqual((self.root/origin.ORIGIN).read_bytes(),before)
        self.assertFalse((self.root/'output').exists())

    def test_changed_content_creates_distinct_c_and_publication(self):
        path = self.root/'api-reference/new.mdx'; path.parent.mkdir(exist_ok=True)
        path.write_text('New reviewed content')
        self.fixture.report['publication_artifact']['published_ref'] = self.ref
        self.fixture.report['publication_artifact']['files_sha256'] = origin.publication_hashes(self.root)
        self.install(); self.git('add', '.')
        new = origin.record(self.root, '456', 1, self.now+timedelta(seconds=5))
        self.assertNotEqual(new['contract_release'], self.receipt['contract_release'])
        self.assertEqual(new['assessed_base'], self.ref)

    def test_run_branch_attempt_origin_or_parent_tampering_rejected(self):
        for field, value in [('id', 999), ('run_attempt', 2), ('path', 'evil.yml'),
                             ('head_branch', 'fork'), ('head_sha', 'b'*40),
                             ('repository', {'full_name': 'attacker/docs'}), ('event', 'pull_request')]:
            run = dict(self.run, **{field:value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                origin.verify_producer(self.receipt, run, self.jobs, self.base, self.end)
        for receipt in [dict(self.receipt, repository='evil/docs'), dict(self.receipt, assessed_base='b'*40),
                        dict(self.receipt, budget_start=(self.end+timedelta(days=1)).isoformat())]:
            with self.assertRaises(ValueError):
                origin.verify_producer(receipt, self.run, self.jobs, self.base, self.end)

    def test_successful_other_job_or_missing_publish_step_is_not_proof(self):
        for jobs in [[], [{'name':'notify-consumers','conclusion':'success'}],
                     [dict(self.jobs[0], conclusion='failure')], [dict(self.jobs[0], steps=[])]]:
            with self.assertRaises(ValueError):
                origin.verify_producer(self.receipt, self.run, jobs, self.base, self.end)
        jobs = copy.deepcopy(self.jobs); jobs[0]['steps'][0]['started_at'] = self.end.isoformat()
        with self.assertRaises(ValueError):
            origin.verify_producer(self.receipt, self.run, jobs, self.base, self.end)

    def test_graph_artifact_or_current_drift_and_source_expiry_rejected(self):
        with self.assertRaises(ValueError):
            origin.verify_graph(self.root, self.receipt, b'{}', self.end)
        with self.assertRaises(ValueError):
            origin.verify_graph(self.root, self.receipt, self.artifact, self.end + timedelta(days=3))
        path = self.root/'openapi.yaml'; path.write_text(path.read_text()+'# unassessed\n')
        with self.assertRaises(ValueError):
            origin.verify_graph(self.root, self.receipt, self.artifact, self.end)

    def test_later_nonformal_main_commit_selects_last_formal_commit(self):
        (self.root/'code.txt').write_text('unrelated main progress')
        self.git('add', 'code.txt'); self.git('commit', '-qm', 'code change')
        real_run = subprocess.run
        def command(args, **kwargs):
            if args[:3] == ['gh', 'run', 'download']:
                destination = Path(args[args.index('--dir')+1]); destination.mkdir()
                (destination/'formal-contract-readiness.json').write_bytes(self.artifact)
                return subprocess.CompletedProcess(args, 0)
            return real_run(args, **kwargs)
        with patch.object(origin, 'gh_json', side_effect=[self.run, {'jobs':self.jobs}]), \
             patch.object(origin.subprocess, 'run', side_effect=command), \
             patch.object(origin, 'datetime') as clock:
            clock.now.return_value = self.end
            clock.fromisoformat.side_effect = __import__('datetime').datetime.fromisoformat
            selected = origin.select(self.root, self.root/'selection.json')
        self.assertEqual(selected['expected_docs_ref'], self.ref)
        self.assertEqual(selected['budget_start'], self.receipt['budget_start'])

    def test_legacy_failure_cache_is_retained_without_reclassifying_success(self):
        legacy = {'checked_at': 1, 'consecutive': {'router:mismatch': 4}}
        state = retain_assessment_history({}, legacy, {'status':'passed'}, {'docs_ref':'a'*40})
        self.assertEqual(state['publication_history'][0]['legacy_monitor_state'], legacy)
        self.assertEqual(state['publication_history'][0]['status'], 'historical_not_reclassified')

    def test_new_publication_retains_prior_failure_and_same_sha_never_resets_budget(self):
        old_identity = {'docs_ref':'a'*40,'budget_start':self.now.isoformat()}
        old = {'identity':old_identity,'assessment':{'status':'failed','timing':{'deadline_breached':True}}}
        previous = {'latest_publication_assessment':old}
        state = retain_assessment_history({}, previous, {'status':'passed'}, {'docs_ref':'b'*40,'budget_start':self.end.isoformat()})
        self.assertEqual(state['publication_history'], [old])
        again = retain_assessment_history({}, state, {'status':'passed'}, state['latest_publication_assessment']['identity'])
        self.assertEqual(again['publication_history'], [old])
        # No success cache can extend an already expired unchanged identity.
        timing = deadline(self.now.isoformat(), 'convergence', self.now+timedelta(hours=5))
        got, observed = monitor_timing({'status':'passed','checked_at':int((self.now+timedelta(hours=5)).timestamp())}, timing, {}, 'a'*40, 'c'*64)
        self.assertTrue(got['deadline_breached']); self.assertIsNone(observed)

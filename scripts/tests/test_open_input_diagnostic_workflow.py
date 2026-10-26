"""Exercise the required-job selector against real immutable Git and event data.

No test token leaves this process. Selected assessment itself is implemented and
separately tested in the fixed Services reader, not a source PR Python script.
"""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/test-runtime-contracts.yml'
SCOPE = 'reviewed_open_input_diagnostic_compatibility_only_not_strict_readiness_or_publication'
READER = 'a' * 40  # Test-only independently reviewed code identity; never a workflow ref.


def encode(value): return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()
def steps(): return yaml.safe_load(WORKFLOW.read_text())['jobs']['artifact-contracts']['steps']
def select_step(): return next(s for s in steps() if s.get('id') == 'open_input_diagnostic')
def python_body(run): return run.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]


class Response:
    status = 200
    def __init__(self, value): self.raw = encode(value)
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.raw[:limit]


class OpenInputWorkflowTests(unittest.TestCase):
    def fixture(self, directory):
        root = directory / 'docs'; root.mkdir()
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
        git('init', '-q'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
        (root / 'scripts').mkdir()
        for name in ('contract_change_scope.py', 'source_governance.py'):
            (root / 'scripts' / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
        git('add', '.'); git('commit', '-qm', 'trusted compiler and base')
        base = git('rev-parse', 'HEAD')
        (root / 'docs/schema-inputs').mkdir(parents=True)
        (root / 'docs/schema-inputs/context.json').write_text('{}\n')
        (root / 'openapi/upstream').mkdir(parents=True)
        (root / 'openapi/upstream/test.json').write_text('{}\n')
        git('add', '.'); git('commit', '-qm', 'source only')
        head = git('rev-parse', 'HEAD')
        now = datetime.now(timezone.utc)
        pins = dict(protocol_version='aisa-runtime-canonical-v1', composer_revision=base,
            source_manifest_sha256='b'*64, docs_ref=head, bundle_manifest_sha256='c'*64)
        req = dict(schema_version=3, scope=SCOPE, mode='open_reviewed_input_diagnostic_qualification', docs_pr=219,
            base_revision=base, head_revision=head, main_revision=base, candidate_compiler_inputs=pins,
            qualifier_revision='d'*40, workflow_sha256='e'*64, source_api_revision='f'*40,
            source_export_revision='1'*40, source_export_lock_sha256='2'*64,
            source_binary_identity_canonical_sha256='3'*64, ssh_target_sha256='4'*64, known_hosts_sha256='5'*64,
            original_source=dict(schema_version='1', generation=928, source_digest='6'*64,
                compiler_revision='f'*40, compiler_inputs=dict(pins, docs_ref='7'*40)),
            original_snapshot_sha256='8'*64, materialized_snapshot_sha256='9'*64, historical_formal_ref='0'*40,
            source_context_sha256='1'*64, source_receipts_sha256='2'*64,
            changed_paths_sha256=sha(encode(['docs/schema-inputs/context.json','openapi/upstream/test.json'])),
            diagnostic_expectation=dict(normalization='complete_readiness_multiset_v1', diagnostic_sha256='3'*64,
                provider_count=46, blocked_provider_count=9, diagnostic_entry_count=247),
            issued_at=(now-timedelta(seconds=10)).isoformat(), expires_at=(now+timedelta(minutes=10)).isoformat())
        binding=dict(schema_version=3,scope=SCOPE,request_sha256=sha(encode(req)),reader_revision=READER,
            run_id=100,run_attempt=1,artifact_id=200,archive_sha256='4'*64,issued_at=req['issued_at'],expires_at=req['expires_at'])
        pr=dict(number=219,state='open',merged=False,
            head=dict(sha=head,repo=dict(full_name='AIsa-team/docs')),
            base=dict(sha=base,ref='main',repo=dict(full_name='AIsa-team/docs')))
        event=dict(number=219,repository=dict(full_name='AIsa-team/docs'),pull_request=pr)
        return root,req,binding,event,git

    def envelope(self, req, binding):
        binding=copy.deepcopy(binding); binding['request_sha256']=sha(encode(req))
        return dict(schema_version=1,scope='reviewed_open_input_diagnostic_operator_selection_v1',reader_revision=READER,
            request_raw=encode(req).decode(),request_sha256=sha(encode(req)),binding_raw=encode(binding).decode(),binding_sha256=sha(encode(binding)))

    def execute(self, directory, root, event, envelope, *, old='', main=None, actual_pr=None, reader=READER, event_name='pull_request'):
        event_path=directory/'event.json'; event_path.write_bytes(encode(event))
        output=directory/'output'; output.write_text('')
        runner=directory/'runner'; runner.mkdir(exist_ok=True)
        env=dict(GITHUB_OUTPUT=str(output),RUNNER_TEMP=str(runner),GITHUB_EVENT_PATH=str(event_path),
            GITHUB_EVENT_NAME=event_name,GITHUB_REPOSITORY='AIsa-team/docs',GITHUB_SHA='5'*40,
            REVIEWED_OPEN_INPUT_READER_REVISION=reader,METADATA_TOKEN='test-only-not-a-real-token',
            OPERATOR_OPEN_INPUT_DIAGNOSTIC_BINDING=encode(envelope).decode() if envelope is not None else '',
            OPERATOR_INPUT_RECOVERY_BINDING=old)
        calls=[]
        class Opener:
            def open(self, request, timeout):
                calls.append(request.full_url)
                if request.full_url.endswith('/branches/main'):
                    return Response({'commit': {'sha': main or event['pull_request']['base']['sha']}})
                if request.full_url.endswith('/pulls/219'):
                    return Response(actual_pr if actual_pr is not None else event['pull_request'])
                raise AssertionError('Unexpected network path')
        previous=Path.cwd(); stderr=io.StringIO(); exitcode=0
        try:
            os.chdir(root)
            with patch.dict(os.environ,env,clear=True),patch('urllib.request.build_opener',return_value=Opener()),contextlib.redirect_stderr(stderr):
                try: exec(compile(python_body(select_step()['run']),'<workflow selector>','exec'),{'__name__':'__main__'})
                except SystemExit as error: exitcode=error.code
        finally: os.chdir(previous)
        return exitcode,output.read_text(),calls,stderr.getvalue(),runner

    def test_real_source_git_event_live_metadata_and_exact_raw_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp); root,req,binding,event,git=self.fixture(directory)
            envelope=self.envelope(req,binding)
            result=self.execute(directory,root,event,envelope)
            self.assertEqual(result[:2],(0,'selected=true\nrequest_sha256='+envelope['request_sha256']+'\nbinding_sha256='+envelope['binding_sha256']+'\nbase_revision='+req['base_revision']+'\n'))
            self.assertEqual(len(result[2]),2)
            staged=result[4]/'open-input-reader-input'
            self.assertEqual((staged/'request.json').read_bytes(),envelope['request_raw'].encode())
            self.assertEqual((staged/'binding.json').read_bytes(),envelope['binding_raw'].encode())
            self.assertEqual(staged.stat().st_mode & 0o777,0o700)
            self.assertEqual((staged/'request.json').stat().st_mode & 0o777,0o600)
            self.assertNotIn('test-only',result[1]+result[3])

    def test_default_off_and_nonmatching_R_do_not_mint_or_query_metadata(self):
        for case in ('absent','push','other_R'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp); root,req,binding,event,_=self.fixture(directory)
                if case=='other_R': req['head_revision']='a'*40
                result=self.execute(directory,root,event,None if case=='absent' else self.envelope(req,binding),event_name='push' if case=='push' else 'pull_request')
                self.assertEqual(result[:3],(0,'selected=false\n',[])); self.assertFalse((result[4]/'open-input-reader-input').exists())

    def test_selected_closed_pins_types_expiry_and_conflict_fail_before_metadata(self):
        cases=('hash','reader','zero_reader','schema','extra','unknown_request','merge_field','old_schema','bad_pin','bool_id','expired','bool_generation','count_float','protocol','missing_context','conflict')
        for case in cases:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp); root,req,binding,event,_=self.fixture(directory)
                if case=='unknown_request': req['unexpected']=True
                if case=='merge_field': req['merge_revision']=req['head_revision']
                if case=='old_schema': req['schema_version']=2
                if case=='bad_pin': req['workflow_sha256']='g'*64
                if case=='bool_id': binding['run_id']=True
                if case=='expired': req['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
                if case=='bool_generation': req['original_source']['generation']=True
                if case=='count_float': req['diagnostic_expectation']['provider_count']=46.0
                if case=='protocol': req['candidate_compiler_inputs']['protocol_version']='1'
                if case=='missing_context':
                    req['changed_paths_sha256']=sha(encode(['openapi/upstream/test.json']))
                envelope=self.envelope(req,binding)
                if case=='hash': envelope['request_sha256']='0'*64
                if case=='reader': envelope['reader_revision']='b'*40
                if case=='schema': envelope['schema_version']=True
                if case=='extra': envelope['unknown']=True
                old=encode(dict(head_revision=req['head_revision'],base_revision=req['base_revision'])).decode() if case=='conflict' else ''
                result=self.execute(directory,root,event,envelope,old=old,reader='0'*40 if case=='zero_reader' else READER)
                self.assertEqual(result[:3],(1,'',[])); self.assertEqual(result[3],'Open input selection rejected\n')
                self.assertFalse((result[4]/'open-input-reader-input').exists())

    def test_event_main_PR_and_compiler_changes_cannot_select(self):
        for case in ('fork','closed','merged','wrong_B','advance_main','actual_merged','compiler_change','policy_drift'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                directory=Path(temp); root,req,binding,event,git=self.fixture(directory)
                actual=None; main=None
                if case=='fork': event['pull_request']['head']['repo']['full_name']='Other/docs'
                if case=='closed': event['pull_request']['state']='closed'
                if case=='merged': event['pull_request']['merged']=True
                if case=='wrong_B': event['pull_request']['base']['sha']='a'*40
                if case=='advance_main': main='b'*40
                if case=='actual_merged': actual=copy.deepcopy(event['pull_request']);actual['merged']=True
                if case in ('compiler_change','policy_drift'):
                    name='contract_change_scope.py' if case=='compiler_change' else 'source_governance.py'
                    (root/'scripts'/name).write_text('# changed\n');git('add','.');git('commit','-qm','unreviewed code')
                    if case=='compiler_change':
                        req['head_revision']=git('rev-parse','HEAD');req['candidate_compiler_inputs']['docs_ref']=req['head_revision'];event['pull_request']['head']['sha']=req['head_revision']
                        req['changed_paths_sha256']=sha(encode(['docs/schema-inputs/context.json','openapi/upstream/test.json','scripts/contract_change_scope.py']))
                    else:
                        req['base_revision']=req['main_revision']=git('rev-parse','HEAD');event['pull_request']['base']['sha']=req['base_revision']
                result=self.execute(directory,root,event,self.envelope(req,binding),main=main,actual_pr=actual)
                self.assertEqual(result[0],1);self.assertEqual(result[3],'Open input selection rejected\n')
                self.assertFalse((result[4]/'open-input-reader-input').exists())

    def test_stale_other_PR_binding_is_inert_but_slow_selection_cannot_extend_lease(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);root,req,binding,event,_=self.fixture(directory)
            result=self.execute(directory,root,event,self.envelope(req,binding),old=encode(dict(head_revision='b'*40,base_revision=req['base_revision'])).decode())
            self.assertEqual(result[0],0);self.assertIn('selected=true',result[1])
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);root,req,binding,event,_=self.fixture(directory)
            real=datetime
            class CrossDeadline(real):
                calls=0
                @classmethod
                def now(cls,tz=None):
                    cls.calls+=1
                    return real.now(tz)+(timedelta(hours=2) if cls.calls>1 else timedelta())
            with patch('datetime.datetime',CrossDeadline):
                result=self.execute(directory,root,event,self.envelope(req,binding))
            self.assertEqual(result[0],1);self.assertEqual(len(result[2]),2)
            self.assertFalse((result[4]/'open-input-reader-input').exists())

    def test_duplicate_keys_and_no_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);root,req,binding,event,_=self.fixture(directory)
            envelope=self.envelope(req,binding);envelope['request_raw']=envelope['request_raw'].replace('"docs_pr":219','"docs_pr":219,"docs_pr":219');envelope['request_sha256']=sha(envelope['request_raw'].encode())
            result=self.execute(directory,root,event,envelope);self.assertEqual(result[0],1);self.assertEqual(result[2],[])
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);root,req,binding,event,_=self.fixture(directory)
            sentinel=directory/'runner/open-input-reader-input';sentinel.mkdir(parents=True);(sentinel/'keep').write_text('owned elsewhere')
            result=self.execute(directory,root,event,self.envelope(req,binding));self.assertEqual(result[0],1);self.assertEqual((sentinel/'keep').read_text(),'owned elsewhere')

    def test_fixed_reader_siblings_step_local_token_and_existing_gates(self):
        rows=steps();byname={s.get('name'):s for s in rows}
        token=byname['Generate existing scoped qualifier-evidence read token']
        self.assertEqual(token['if'],"steps.input_recovery.outputs.selected == 'true' || steps.open_input_diagnostic.outputs.selected == 'true'")
        self.assertEqual(token['with']['repositories'],'AIsaServices\ndocs\n')
        self.assertEqual(token['with']['permission-actions'],'read');self.assertEqual(token['with']['permission-contents'],'read')
        services=byname['Checkout independently fixed Services open-input reader']
        self.assertEqual(services['with']['repository'],'AIsa-team/AIsaServices')
        self.assertEqual(services['with']['ref'],select_step()['env']['REVIEWED_OPEN_INPUT_READER_REVISION'])
        self.assertRegex(services['with']['ref'],r'^[0-9a-f]{40}$')
        self.assertFalse(services['with']['persist-credentials'])
        docs=byname['Checkout immutable clean Docs base for open-input reader']
        self.assertFalse(docs['with']['persist-credentials']);self.assertNotIn('/',docs['with']['path']);self.assertNotIn('/',services['with']['path']);self.assertNotEqual(docs['with']['path'],services['with']['path'])
        for row in rows:
            if 'GH_TOKEN' in row.get('env',{}):
                if row['name']=='Check actual candidate readiness':
                    # Authenticate the public historical publisher, using only
                    # the workflow's own read token, never the private reader App.
                    self.assertEqual(row['env']['GH_TOKEN'],'${{ github.token }}')
                else:
                    self.assertIn(row['name'],('Check exact authenticated source-only input qualification',
                        'Check exact authenticated open-input diagnostic qualification',
                        'Check explicit reviewed source-only input without claiming formal output'))
            if row.get('uses','').startswith('actions/upload-artifact'):
                self.assertNotIn('reader-input',row['with']['path']);self.assertNotIn('github.event_path',row['with']['path'])
        self.assertEqual(byname['Check actual candidate readiness']['if'],"needs.changes.outputs.input_candidate != 'true'")
        self.assertIn('--current',byname['Acquire one complete fresh immutable Runtime release']['run'])
        self.assertEqual(yaml.safe_load(WORKFLOW.read_text())['jobs']['contracts']['needs'],['changes','code-contracts','artifact-contracts'])
        self.assertNotIn('continue-on-error',WORKFLOW.read_text())

    def test_nonselected_parsed_workflow_preserves_every_original_job_and_step(self):
        workflow=yaml.safe_load(WORKFLOW.read_text())
        rows=workflow['jobs']['artifact-contracts']['steps']
        added=('Select exact open-input diagnostic consumer','Checkout immutable clean Docs base for open-input reader',
            'Checkout independently fixed Services open-input reader','Use pinned reader dependency interpreter',
            'Use exact Services Go toolchain for original snapshot verification','Install independently pinned reader dependencies',
            'Check exact authenticated open-input diagnostic qualification','Retain input-only diagnostic consumer receipt',
            'Renew due automatic source observations','Retain automatic source renewal observations',
            'Cache actual source renewal observations')
        original=[]
        for row in rows:
            if row.get('name') in added: continue
            row=copy.deepcopy(row)
            if row.get('name')=='Check actual candidate readiness':
                # The narrow canonical presentation branch is intentional.
                # Its nonselected branch must retain the exact original gate.
                self.assertEqual(sha(row['run'].encode()),'5bbabad1fd8dc18f4e62ba9dbb0643c7e48d824da6baf87f3dcfdbf96dfaec26')
                self.assertEqual(row['env'].pop('GH_TOKEN'),'${{ github.token }}')
                fallback=row['run'].split('\nelse\n',1)[1].rsplit('\nfi',1)[0]
                row['run']='\n'.join(line[2:] for line in fallback.splitlines())+'\n'
            if 'if' in row:
                row['if']=row['if'].replace(" && steps.open_input_diagnostic.outputs.selected != 'true'",'').replace(" || steps.open_input_diagnostic.outputs.selected == 'true'",'')
                if row['if']=="steps.open_input_diagnostic.outputs.selected != 'true'": del row['if']
            original.append(row)
        workflow['jobs']['artifact-contracts']['steps']=original
        def normalize(value):
            if type(value) is dict:return {str(k):normalize(v) for k,v in value.items()}
            if type(value) is list:return [normalize(v) for v in value]
            return value
        # Independent immutable a79 pre-change workflow, including every old run block,
        # permission, trigger, required aggregate, formal and passed input branch.
        self.assertEqual(sha(json.dumps(normalize(workflow),sort_keys=True,separators=(',',':')).encode()),'8f2a3055805905f71ca31124fe52e3e7d5b955c1cf71efdb3e6b4dabdb00b6d6')

    def test_all_run_blocks_are_shell_and_python_syntax_valid(self):
        for job in yaml.safe_load(WORKFLOW.read_text())['jobs'].values():
            for row in job['steps']:
                if 'run' not in row: continue
                subprocess.run(['bash','-n'],input=row['run'],text=True,check=True)
                if "<<'PY'\n" in row['run']: compile(python_body(row['run']),'<workflow>','exec')


if __name__=='__main__':unittest.main()

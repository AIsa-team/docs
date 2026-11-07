import base64
import copy
import datetime as dt
import gzip
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import read_eks_source_input as reader
from schema_input_bundle import canonical, sha
from readiness_rejection import SnapshotReadinessRejected


def binding():
    now = dt.datetime.now(dt.timezone.utc)
    return {'schema_version': 1, 'scope': reader.SCOPE, 'docs_pr': 299,
        'base_revision': 'a'*40, 'head_revision': 'b'*40, 'trusted_code_revision': 'a'*40,
        'changed_paths_sha256': '1'*64, 'bundle_manifest_sha256': '2'*64,
        'infra_source': 'c'*40, 'workflow_sha256': sha(b'producer'),
        'run_id': 123, 'run_attempt': 1, 'jobs': [{'name':'tests','id':1},{'name':'collect','id':2}],
        'artifact_id': 456, 'artifact_zip_sha256': '4'*64, 'artifact_gzip_sha256': '5'*64,
        'snapshot_pins': {'snapshot_sha256':'6'*64, 'generation':13336,
            'source_digest':'7'*64, 'compiler_revision':'d'*40},
        'diagnostic_expectation': {'normalization':reader.NORMALIZATION,'diagnostic_sha256':'8'*64,
            'provider_count':549,'blocked_provider_count':459,'diagnostic_entry_count':3296},
        'issued_at': (now-dt.timedelta(minutes=1)).isoformat(),
        'expires_at': (now+dt.timedelta(minutes=30)).isoformat()}


def proof(value):
    return {'schema_version':1,'scope':'aisa-internal-snapshot-readiness-rejection',
        'status':'readiness_rejected','bundle_manifest_sha256':value['bundle_manifest_sha256'],
        'docs_ref':value['head_revision'],**value['snapshot_pins'],**value['diagnostic_expectation']}


def archive(value, mutate=None, extra=None, mode=None):
    packed = gzip.compress(canonical(value['snapshot_pins']))
    value['artifact_gzip_sha256'] = sha(packed)
    dispatch = {'infra_source':value['infra_source'],'identity':'123-1','operation':'export-integration-catalog',
                'build_id':'build','source_version':'s3version'}
    build = {'id':'build','buildStatus':'SUCCEEDED','sourceVersion':'s3version'}
    observation = {**dispatch,'status':'collected','kind':'publication','executor':'codebuild',
        'SQL_mutations':0,'Kubernetes_mutations':0,'provider_credentials_exported':0,
        'sources':{'prod':value['snapshot_pins']['compiler_revision']},
        'generation':value['snapshot_pins']['generation'],'source_digest':value['snapshot_pins']['source_digest'],
        'artifact':{'name':'publication-snapshot.json.gz','bytes':len(packed),'sha256':sha(packed)}}
    if mutate: mutate(dispatch,build,observation)
    files = {'dispatch.json':canonical(dispatch),'build.json':canonical(build),
             'observation.json':canonical(observation),'publication-snapshot.json.gz':packed}
    result = io.BytesIO()
    with zipfile.ZipFile(result,'w') as target:
        for name,raw in files.items():
            info=zipfile.ZipInfo(name)
            if mode: info.external_attr=mode<<16
            target.writestr(info,raw)
        if extra: target.writestr(extra,b'ignored')
    raw=result.getvalue();value['artifact_zip_sha256']=sha(raw)
    return raw


class BindingTests(unittest.TestCase):
    def test_exact_binding(self):
        reader.validate_binding(binding())

    def test_expired_future_long_or_non_utc_lease(self):
        for field,text in [('expires_at','2000-01-01T00:00:00Z'),('issued_at','2099-01-01T00:00:00Z'),
                           ('issued_at','2000-01-01T00:00:00Z'),('issued_at','2026-01-01T00:00:00')]:
            value=binding();value[field]=text
            with self.subTest(field=field,text=text),self.assertRaises(ValueError): reader.validate_binding(value)

    def test_bool_ids_unknown_fields_and_different_q_rejected(self):
        for key,value in [('docs_pr',True),('trusted_code_revision','f'*40),('unexpected',False)]:
            candidate=binding();candidate[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):reader.validate_binding(candidate)

    def test_other_pr_binding_is_inert(self):
        self.assertIsNone(reader.selected_binding(canonical(binding()).decode(),{'pull_request':{'head':{'sha':'e'*40}}}))

    def test_matching_bad_binding_cannot_fallback(self):
        value=binding();value['scope']='publication'
        with self.assertRaises(ValueError):reader.selected_binding(canonical(value).decode(),{'pull_request':{'head':{'sha':'b'*40}}})

    def test_closed_source_diff_rejects_code_and_policy(self):
        source=['openapi/upstream/source.json','docs/schema-inputs/context.json']
        self.assertTrue(reader.source_only(source))
        for extra in ['scripts/tests/test_skip.py','scripts/compose_openapi.py','.github/workflows/test-runtime-contracts.yml',
                      'openapi/policies/deferred-enabled-20261010.json','docs/deferred-age-response-rebinding-20261012.json']:
            with self.subTest(extra=extra):self.assertFalse(reader.source_only(source+[extra]))


class CaptureTests(unittest.TestCase):
    def test_exact_capture(self):
        value=binding();raw=archive(value)
        self.assertEqual(reader.unpack_capture(raw,value),canonical(value['snapshot_pins']))

    def test_digest_and_extra_and_symlink(self):
        value=binding();raw=archive(value);value['artifact_zip_sha256']='f'*64
        with self.assertRaises(ValueError):reader.unpack_capture(raw,value)
        for extra in ['../script.py','script.py','dispatch.json']:
            value=binding();raw=archive(value,extra=extra)
            with self.subTest(extra=extra),self.assertRaises(ValueError):reader.unpack_capture(raw,value)
        value=binding();raw=archive(value,mode=stat.S_IFLNK|0o777)
        with self.assertRaises(ValueError):reader.unpack_capture(raw,value)

    def test_capture_identity_mutation_and_credentials(self):
        for key,replacement in [('SQL_mutations',1),('Kubernetes_mutations',1),('provider_credentials_exported',1),
                                ('identity','123-2'),('kind','catalog'),('source_digest','a'*64)]:
            value=binding();raw=archive(value,mutate=lambda d,b,o:o.update({key:replacement}))
            with self.subTest(key=key),self.assertRaises(ValueError):reader.unpack_capture(raw,value)

    def test_decompression_ceiling(self):
        value=binding();raw=archive(value)
        with patch.object(reader,'MAX_RAW',1),self.assertRaises(ValueError):reader.unpack_capture(raw,value)


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.binding=binding();b=self.binding;root='/repos/'+reader.INFRA
        self.data={root+'/branches/main':{'protected':True,'commit':{'sha':b['infra_source']}},
            root+'/contents/'+reader.WORKFLOW+'?ref='+b['infra_source']:
                {'type':'file','encoding':'base64','content':base64.b64encode(b'producer').decode()},
            root+'/actions/runs/123':{'id':123,'run_attempt':1,'head_sha':b['infra_source'],'head_branch':'main',
                'event':'workflow_dispatch','path':reader.WORKFLOW,'status':'completed','conclusion':'success',
                'repository':{'full_name':reader.INFRA},'created_at':'original','updated_at':'original'},
            root+'/actions/runs/123/attempts/1/jobs?per_page=100':{'total_count':2,'jobs':[
                {**j,'status':'completed','conclusion':'success','run_id':123,'head_sha':b['infra_source'],'run_attempt':1}
                for j in b['jobs']]},
            root+'/actions/artifacts/456':{'id':456,'expired':False,'name':'integration-catalog-export-123',
                'digest':'sha256:'+b['artifact_zip_sha256'],'workflow_run':{'id':123,'head_sha':b['infra_source']},
                'created_at':'original'}}
        self.api=Mock();self.api.json.side_effect=lambda path:copy.deepcopy(self.data[path])

    def test_authenticate_exact_success(self):
        self.assertEqual(reader.authenticate_producer(self.api,self.binding)['artifact_created_at'],'original')

    def test_wrong_attempt_job_branch_workflow_or_digest(self):
        mutations=[('/branches/main',lambda x:x.update(protected=False)),
            ('/actions/runs/123',lambda x:x.update(run_attempt=2)),
            ('/actions/runs/123',lambda x:x.update(head_branch='feature')),
            ('/actions/runs/123/attempts/1/jobs?per_page=100',lambda x:x['jobs'][0].update(conclusion='skipped')),
            ('/actions/artifacts/456',lambda x:x.update(digest='sha256:'+'f'*64)),
            ('/contents/'+reader.WORKFLOW+'?ref='+self.binding['infra_source'],lambda x:x.update(content=base64.b64encode(b'evil').decode()))]
        for suffix,mutate in mutations:
            with self.subTest(suffix=suffix):
                self.setUp();mutate(self.data['/repos/'+reader.INFRA+suffix])
                with self.assertRaises(ValueError):reader.authenticate_producer(self.api,self.binding)


class StrictVerdictTests(unittest.TestCase):
    def test_complete_rejection_is_exact_not_counts_only(self):
        value=binding();actual=proof(value);reader.check_rejection(actual,value)
        for key,changed in [('diagnostic_sha256','f'*64),('provider_count',550),('docs_ref','f'*40),
                            ('status','passed'),('snapshot_sha256','f'*64),('extra','unknown')]:
            altered={**actual,key:changed}
            with self.subTest(key=key),self.assertRaises(ValueError):reader.check_rejection(altered,value)

    def call_run(self,temporary,error):
        value=binding();output=Path(temporary)/'receipt'
        with patch.object(reader,'authenticate_docs',return_value=['source']) as docs,\
             patch.object(reader,'authenticate_producer',return_value={'original':'capture'}) as producer,\
             patch.object(reader,'unpack_capture',return_value=b'{}'),\
             patch.object(reader,'git',side_effect=[('d'*40).encode(),b'']),\
             patch.object(reader.subprocess,'run'),patch.object(reader,'load_snapshot'),\
             patch.object(reader,'assess_source',return_value={'status':'passed'}),\
             patch.object(reader,'check_governance',return_value={'status':'passed'}),\
             patch.object(Path,'read_bytes',return_value=canonical({'receipts':{}})),\
             patch.object(reader,'compile_snapshot',side_effect=error):
            result=reader.run(value,api=Mock(),repo=Path(temporary),trusted_root=Path(temporary),
                              services=Path(temporary),output=output)
            self.assertEqual(docs.call_count,2);self.assertEqual(producer.call_count,2)
            return result,output

    def test_only_typed_expected_rejection_yields_narrow_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            result,out=self.call_run(directory,SnapshotReadinessRejected(proof(binding())))
            self.assertEqual(result['status'],'source_input_diagnostic_compatible')
            self.assertFalse(result['formal_publication']);self.assertEqual(result['output_artifact_count'],0)
            self.assertEqual([x.name for x in out.iterdir()],['receipt.json'])

    def test_generic_error_success_and_unexpected_typed_rejection_never_qualify(self):
        for error in [None,ValueError('ordinary failure'),SnapshotReadinessRejected({**proof(binding()),'provider_count':550})]:
            with tempfile.TemporaryDirectory() as directory,self.subTest(error=error):
                with self.assertRaises(ValueError):self.call_run(directory,error)
                self.assertFalse((Path(directory)/'receipt').exists())

    def test_ordinary_workflow_remains_strict(self):
        text=(Path(__file__).resolve().parents[2]/'.github/workflows/test-runtime-contracts.yml').read_text()
        self.assertIn('timeout-minutes: 10',text)
        self.assertIn('python scripts/fetch_runtime_release.py --current',text)
        self.assertIn('python scripts/check_reviewed_schema_inputs.py',text)
        self.assertNotIn('continue-on-error:',text)
        self.assertIn("path: docs-eks-input-anchor",text)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}",text)


if __name__=='__main__':unittest.main()

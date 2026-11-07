import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sync_prod_runtime_docs as prod
from test_runtime_contracts import facts


class ProductionReferenceTests(unittest.TestCase):
    def fixture(self,root,validation='runtime'):
        (root/'openapi').mkdir()
        (root/'openapi/registry.yaml').write_text('auto_register: true\nproviders: {}\n')
        config={'name':'AIsa','markdown':{'instructions':'Keep production guidance'},'navigation':{'languages':[
            {'language':language,'tabs':[{'tab':tab,'groups':[]}]}for language,tab in [('en','API Reference'),('zh','API 参考')]]}}
        (root/'docs.json').write_text(json.dumps(config))
        f=facts(validation);f['info']['x-aisa-document']['facts_hash']='a'*64
        return {k:json.dumps(v).encode()for k,v in {'similarweb.json':f,'index.json':{'providers':[{'id':'similarweb','facts_hash':'a'*64}],'pending_providers':[],'pending_endpoints':[]},'category.json':{'apis':[{'id':'similarweb'}]}}.items()}

    def test_real_composer_preserves_production_metadata_and_isolates_formal_exports(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);files=self.fixture(root)
            (root/'openapi.yaml').write_text('immutable formal bytes')
            (root/'docs/publication').mkdir(parents=True)
            (root/'docs/publication/current.json').write_text('{"unchanged":true}')
            before={str(p.relative_to(root)):p.read_bytes()for p in root.rglob('*')if p.is_file()}
            outputs,report=prod.generate(root,files)
            self.assertEqual(report['environment'],'prod');self.assertFalse(report['formal_publication'])
            self.assertEqual(report['status'],'generated')
            self.assertIn('reference-contracts/similarweb.json',outputs)
            self.assertIn('reference-contracts/zh/similarweb.json',outputs)
            for prefix in ('','zh/'):
                key=prefix+'api-reference/similarweb/published_identity.mdx'
                self.assertIn('reference-contracts/'+('zh/'if prefix else '')+'similarweb.json',outputs[key].decode())
                self.assertNotIn('dev-api.aisa.one',outputs[key].decode())
            self.assertFalse(any(k.startswith('openapi/')or k=='openapi.yaml'or k.startswith('docs/publication/')for k in outputs))
            for name,raw in before.items():self.assertEqual((root/name).read_bytes(),raw)
            for name,raw in outputs.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            self.assertEqual(prod.validate_reference_pages(root),2)
            self.assertEqual(json.loads(outputs['docs.json'])['markdown']['instructions'],'Keep production guidance')

    def test_prior_reference_history_is_restored_only_in_private_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);files=self.fixture(root)
            outputs,_=prod.generate(root,files)
            for name,raw in outputs.items():
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            original=(root/'reference-contracts/similarweb.json').read_bytes()
            repeated,report=prod.generate(root,files)
            self.assertIn('api-reference/similarweb/published_identity.mdx',repeated)
            self.assertEqual((root/'reference-contracts/similarweb.json').read_bytes(),original)
            self.assertFalse((root/'openapi/similarweb.json').exists())
            self.assertEqual(report['status'],'generated')
            self.assertIn('reference-contracts/similarweb.json',repeated['api-reference/similarweb/published_identity.mdx'].decode())

    def test_missing_source_remains_partial_without_inventing_an_operation(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);files=self.fixture(root,'provider')
            outputs,report=prod.generate(root,files)
            self.assertEqual(report['status'],'partial')
            self.assertIn('upstream operation missing',json.dumps(report['pending']))
            self.assertNotIn('api-reference/similarweb/published_identity.mdx',outputs)
            self.assertFalse(report['formal_publication'])

    def test_reference_validation_checks_both_languages_and_aliases(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td)
            for prefix in ('','zh/'):
                p=root/(prefix+'api-reference/example/a.mdx');p.parent.mkdir(parents=True)
                p.write_text('---\nopenapi: "reference-contracts/'+prefix+'example.json GET /a"\nx-aisa-operation-id: "known"\n---\n')
                schema=root/('reference-contracts/'+prefix+'example.json');schema.parent.mkdir(parents=True)
                schema.write_text(json.dumps({'paths':{'/a':{'get':{'operationId':'known'}}}}))
            self.assertEqual(prod.validate_reference_pages(root),2)
            schema.write_text(json.dumps({'paths':{'/a':{'get':{'operationId':'wrong'}}}}))
            with self.assertRaises(ValueError):prod.validate_reference_pages(root)

    def test_malformed_reference_is_rejected_instead_of_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);page=root/'zh/api-reference/example/bad.mdx';page.parent.mkdir(parents=True)
            page.write_text('---\nopenapi: "reference-contracts/zh/demo.json"\n---\n')
            with self.assertRaisesRegex(ValueError,'Malformed'):prod.validate_reference_pages(root)

    def test_failed_snapshot_validation_never_generates_or_writes(self):
        with tempfile.TemporaryDirectory()as td:
            root=Path(td);marker=root/'docs.json';marker.write_text('last good')
            with patch.object(prod,'load_snapshot',side_effect=ValueError('mismatch')),patch.object(prod,'generate')as generate,self.assertRaises(ValueError):
                prod.sync(root,snapshot_dir=root,snapshot_sha256='a'*64,generation=1,source_digest='b'*64,compiler_revision='c'*40,write=True)
            generate.assert_not_called();self.assertEqual(marker.read_text(),'last good')

    def test_acquisition_observation_is_bound_to_exact_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'observation.json'
            pins={'snapshot_sha256':'a'*64,'generation':13336,'source_digest':'b'*64,'compiler_revision':'c'*40}
            record={**pins,'kind':'verified_private_runtime_export','environment':'prod',
                    'formal_publication':False,'run_id':123,'run_attempt':1}
            path.write_text(json.dumps(record))
            self.assertEqual(prod.read_acquisition_receipt(path,**pins),record)
            with self.assertRaisesRegex(ValueError,'generation'):
                prod.read_acquisition_receipt(path,**{**pins,'generation':13337})
            record['formal_publication']=True;path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'formal_publication'):
                prod.read_acquisition_receipt(path,**pins)

    def test_rewrites_local_spec_links_without_changing_formal_public_urls(self):
        text='openapi: "openapi/zh/demo.json GET /x"\nhttps://aisa.one/docs/openapi/demo.json\nhttps://api.aisa.one/apis/v1/demo\nhttps://aisa.one/openapi.yaml\nhttps://aisa.one/docs/openapi/openapi.json\n[aggregate](openapi/openapi.json)\n'
        out=prod.reference_text(text)
        self.assertIn('reference-contracts/zh/demo.json',out)
        self.assertIn('https://aisa.one/docs/reference-contracts/demo.json',out)
        self.assertIn('https://aisa.one/openapi.yaml',out)
        self.assertIn('https://aisa.one/docs/openapi/openapi.json',out)
        self.assertIn('[aggregate](openapi/openapi.json)',out)
        self.assertIn('https://api.aisa.one/apis/v1/demo',out)

if __name__=='__main__':unittest.main()

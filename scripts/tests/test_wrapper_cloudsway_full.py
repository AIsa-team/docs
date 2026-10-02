import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wrapper_cloudsway_full_reference as full
from compose_openapi import digest

FIXTURE = Path(__file__).parent / 'fixtures/wrapper_cloudsway_full.html'


def fixture_hash():
    parser = full.CodeBlocks()
    parser.feed(FIXTURE.read_text())
    document = json.loads(parser.blocks[0])
    return hashlib.sha256(json.dumps(document,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class CloudswayFullReferenceTests(unittest.TestCase):
    def test_preserves_embedded_wire_fields_without_smart_synthesis(self):
        with patch.object(full,'EMBEDDED_SHA256',fixture_hash()):
            document,source = full.convert_reference(FIXTURE.read_bytes())
        op = document['paths'][full.PUBLIC_PATH]['get']
        params = {p['name']:p for p in op['parameters']}
        self.assertEqual(set(params), {'q','count','freshness','offset','mkt','cc','safeSearch','setLang','textDecorations','contentType'})
        self.assertEqual([p['name'] for p in op['parameters'] if p['required']], ['q'])
        self.assertNotIn('default', params['count']['schema'])
        self.assertNotIn('maximum', params['count']['schema'])
        self.assertNotIn('minLength', params['q']['schema'])
        self.assertEqual(params['offset']['schema'], {'type':'integer','format':'int16','default':0})
        self.assertEqual(params['contentType']['schema']['enum'], ['HTML','MARKDOWN'])
        self.assertNotIn('enableContent',params)
        self.assertNotIn('requestBody',op)
        self.assertNotIn('operationId',op)
        self.assertEqual(source['upstream_operation_id'],'fullTextSearch')
        self.assertEqual(source['lifecycle'],'historical')
        self.assertEqual(source['article_date'],'2025-11-20')
        self.assertEqual(source['kind'],'manual')
        self.assertNotIn('ACCOUNT_REDACTED',json.dumps(document))

    def test_changed_or_ambiguous_embedded_contract_fails_closed(self):
        raw=FIXTURE.read_bytes()
        with patch.object(full,'EMBEDDED_SHA256',fixture_hash()):
            for changed in [raw.replace(b'&quot;count&quot;',b'&quot;max_results&quot;'),raw+raw,b'<p>Documentation home</p>']:
                with self.assertRaises(ValueError):full.convert_reference(changed)

    def test_mirror_is_valid_openapi_and_hash_does_not_include_provenance(self):
        from openapi_spec_validator import validate
        from catalog_fixture import catalog_root
        root = catalog_root()
        doc=json.loads((root/'openapi/upstream/wrapper-cloudsway-full.json').read_text())
        validate(doc)
        source=doc['info'].pop('x-aisa-source')
        self.assertEqual(source['content_hash'],digest(doc))
        self.assertEqual(source['embedded_openapi_sha256'],'sha256:'+full.EMBEDDED_SHA256)


if __name__=='__main__':unittest.main()

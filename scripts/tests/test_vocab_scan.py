import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vocab_scan  # noqa: E402

# Synthetic stand-ins: never a real supplier list in the public repository.
TERMS = ['acmefeeds', 'zeta-gateway.dev', 'serpapi', 'ab']


class VocabScanTests(unittest.TestCase):
    def setUp(self):
        self.rules = vocab_scan.load_rules(terms=TERMS, public_names=['tiktok'])

    def test_supplier_terms_report_index_not_word(self):
        hits = vocab_scan.scan_json({'description': 'Media is an AcmeFeeds-hosted asset.'}, self.rules, 'openapi/x.json')
        self.assertEqual(hits, [{'location': 'openapi/x.json#/description', 'class': 'supplier', 'term_index': 1}])
        self.assertNotIn('acmefeeds', json.dumps(hits).lower())

    def test_public_brands_catalog_ids_and_short_terms_are_excluded(self):
        self.assertEqual(self.rules.term_count, 4)
        self.assertEqual(len(self.rules.terms), 2)  # serpapi is a public brand; 'ab' is too short
        self.assertEqual(vocab_scan.scan_text('Search with SerpApi on TikTok', self.rules), [])

    def test_word_boundaries(self):
        self.assertEqual(vocab_scan.scan_text('macmefeedsx', self.rules), [])
        self.assertEqual(vocab_scan.scan_text('see https://api.zeta-gateway.dev/v1', self.rules), [('supplier', 2)])

    def test_internal_notes_and_hash_text(self):
        for text, rule in [('THIS IS THE PRICE DIAL for the shared key', 'IN01'),
                           ('Cost VERIFIED 2026-09-08', 'IN02'),
                           ('email=nobody-quick-20260908%40example.org', 'IN10'),
                           ('the shared tier absorbs it', 'IN09'),
                           ('upstream_path_sha256: ' + 'a' * 64, 'HF01')]:
            with self.subTest(rule=rule):
                self.assertIn(rule, [r for _, r in vocab_scan.scan_text(text, self.rules)])

    def test_generated_pricing_block_is_not_an_internal_note(self):
        text = '<!-- aisa-pricing:start -->\n$0.014 per request\n<!-- aisa-pricing:end -->'
        self.assertEqual(vocab_scan.scan_text(text, self.rules), [])
        self.assertEqual(vocab_scan.scan_text('$0.014 per request', self.rules), [('internal_note', 'IN11')])

    def test_business_values_and_provenance_are_not_prose(self):
        document = {'paths': {'/x': {'get': {
            'parameters': [{'name': 'q', 'example': 'acmefeeds', 'schema': {'enum': ['acmefeeds'], 'default': 'acmefeeds'}}],
            'x-aisa-source': {'url': 'https://acmefeeds.example/openapi.json'},
            'x-aisa-response-source': {'source': {'converter': 'reviewed-acmefeeds@1'}},
            'x-codeSamples': [{'label': 'Reference example', 'source': 'curl https://api.aisa.one/x?q=1'}],
            'x-aisa-notes': ['Use acmefeeds wisely']}}}}
        hits = vocab_scan.scan_json(document, self.rules, 'f.json')
        self.assertEqual([h['location'] for h in hits], ['f.json#/paths/~1x/get/x-aisa-notes/0'])

    def test_mdx_fenced_json_and_prose(self):
        text = ('---\ntitle: "x"\nopenapi: "openapi/acmefeeds.json GET /x"\n---\n\nPlain prose about acmefeeds.\n\n'
                '````json\n{"parameters": [{"name": "q", "description": "PRICE DIAL", "example": "acmefeeds"}]}\n````\n')
        hits = vocab_scan.scan_mdx(text, self.rules, 'api-reference/x.mdx')
        self.assertEqual(sorted(h['location'] for h in hits),
                         ['api-reference/x.mdx:6', 'api-reference/x.mdx:9#/parameters/0/description'])

    def test_digest_is_order_and_case_insensitive(self):
        self.assertEqual(vocab_scan.vocab_digest(['B', 'a']), vocab_scan.vocab_digest(['a', 'b ']))
        self.assertTrue(vocab_scan.vocab_digest([]).startswith('sha256:'))

    def test_terms_come_from_the_secret_environment_only(self):
        self.assertEqual(vocab_scan.load_terms({}), [])
        self.assertEqual(vocab_scan.load_terms({'SUPPLIER_VOCAB_JSON': '{"terms": ["x1y"]}'}), ['x1y'])
        with self.assertRaises(ValueError):
            vocab_scan.load_terms({'SUPPLIER_VOCAB_JSON': '"x1y"'})

    def test_cli_never_prints_the_matched_word(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi').mkdir()
            (root / 'llms.txt').write_text('An AcmeFeeds-hosted asset\n')
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.dict('os.environ', {'SUPPLIER_VOCAB_JSON': json.dumps(TERMS)}), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = vocab_scan.main(['--root', str(root), '--report', str(root / 'r.json')])
            self.assertEqual(status, 1)
            for text in (out.getvalue(), err.getvalue(), (root / 'r.json').read_text()):
                self.assertNotIn('acmefeeds', text.lower())
            self.assertIn('llms.txt:1: supplier 1', err.getvalue())


if __name__ == '__main__':
    unittest.main()

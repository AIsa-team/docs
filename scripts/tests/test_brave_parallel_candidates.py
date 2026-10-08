import copy
import json
import hashlib
from pathlib import Path
import sys
import tempfile
from urllib.request import Request
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brave_parallel_candidates import candidate_rows, current_bindings, static_url, StaticRedirectHandler, verify_capture, SOURCE_URL, CURRENT_FIELDS, SOURCE_URLS, EXPECTED_ORIGINS
from import_brave_reference import convert_specs
from import_parallel_legacy_events import extract
from test_brave_reference import spec
from catalog_fixture import catalog_root
from compose_openapi import digest



class BraveParallelCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = catalog_root()
        cls.bindings = []
        for provider in ['parallel.ai', 'brave-search', 'brave-answer']:
            document = json.loads((root / 'facts' / (provider + '.json')).read_text())
            for path, item in document['paths'].items():
                for method, operation in item.items():
                    if method not in ['x-aisa-any', 'post', 'get']:
                        continue
                    cls.bindings.append({'provider_key': provider, 'public_path': path,
                        'contract_method': 'ANY' if method == 'x-aisa-any' else method.upper(),
                        'upstream_path': operation['x-aisa-upstream-path'],
                        'frozen_proposed_identity': operation['operationId']})
        cls.sources = {name: json.loads((root / 'openapi/upstream' / original).read_text()) for name, original in [
            ('brave-official.json', 'brave-official.json'),
            ('parallel-public-openapi.json', 'parallel.ai.json'),
            ('parallel-archived-events.json', 'parallel-legacy-events.json')]}
        cls.sources['parallel-docs-legacy-openapi.json'] = {'paths': {}}

    def test_all_33_exact_historical_paths_have_real_schemas_and_unapproved_identity_candidates(self):
        rows = candidate_rows(self.bindings, self.sources)
        self.assertEqual(len(rows), 33)
        self.assertEqual(sum(len(r['operations']) for r in rows), 37)
        for row in rows:
            self.assertFalse(row['activatable'])
            self.assertFalse(row['source_approved'])
            self.assertFalse(row['identity_approved'])
            self.assertFalse(row['current_mapping_metadata_verified'])
            for operation in row['operations']:
                self.assertIsNone(operation['schema_gap'], row['public_path'])
                self.assertTrue(operation['public_operation_id_proposed'])
                self.assertTrue(operation['success_response_statuses'])
        legacy = [r for r in rows if r['source_lifecycle'] == 'archived']
        self.assertEqual([r['upstream_path'] for r in legacy], ['/v1beta/tasks/runs/{run_id}/events'])
        self.assertIn('archived_contract_does_not_prove_current_provider_support', legacy[0]['gaps'])
        self.assertIn('text/event-stream', legacy[0]['operations'][0]['operation']['responses']['200']['content'])

    def test_no_path_version_or_method_inference(self):
        missing = copy.deepcopy(self.bindings[0])
        missing['upstream_path'] = '/a/nonexistent/version'
        row = candidate_rows([missing], self.sources)[0]
        self.assertEqual(row['operations'], [])
        self.assertEqual(row['gaps'], ['exact_evidenced_upstream_path_absent_from_official_sources'])
        wrong_method = copy.deepcopy(self.bindings[0])
        wrong_method['contract_method'] = 'DELETE'
        row = candidate_rows([wrong_method], self.sources)[0]
        self.assertEqual(row['operations'], [])
        self.assertIn('stored_method_absent_from_exact_official_operation', row['gaps'])

    def test_only_static_official_sources_and_no_duplicate_namespace(self):
        self.assertTrue(static_url(SOURCE_URL))
        self.assertTrue(static_url('https://api-dashboard.search.brave.com/api-reference/web/search/get/__data.json'))
        for url in ['https://api.parallel.ai/v1/search', 'https://api.search.brave.com/res/v1/web/search',
                    'https://docs.parallel.ai/public-openapi.json?token=secret',
                    'https://api-dashboard.search.brave.com/api-reference/../../business/__data.json']:
            self.assertFalse(static_url(url))
        with self.assertRaisesRegex(ValueError, 'duplicate public'):
            candidate_rows([self.bindings[0], self.bindings[0]], self.sources)
        a, b = copy.deepcopy(self.bindings[:2])
        b['frozen_proposed_identity'] = a['frozen_proposed_identity']
        with self.assertRaisesRegex(ValueError, 'duplicate proposed'):
            candidate_rows([a, b], self.sources)

    def test_full_schema_hash_and_literals_are_not_changed_or_inferred(self):
        sources = copy.deepcopy(self.sources)
        before = digest(sources)
        rows = candidate_rows(self.bindings, sources)
        self.assertEqual(before, digest(sources))
        for row in rows:
            document = sources[row['source_file']]
            for op in row['operations']:
                self.assertEqual(op['schema_hash'], digest({'operation': op['operation'], 'components': op['components']}))
                for name, value in op['components'].get('schemas', {}).items():
                    self.assertEqual(digest(value), digest(document['components']['schemas'][name]))
                self.assertEqual(op['upstream_security'], op['operation'].get('security', document.get('security', [])))

    def test_sanitized_metadata_is_complete_but_does_not_prove_strict_binding_or_approval(self):
        # Synthetic sanitized readback exercises the join against immutable W0
        # routes. Live receipts stay outside the code-only commit/CI inputs.
        current = {'rows': []}
        for index, binding in enumerate(self.bindings, 1):
            row = {key: 'fixture' for key in CURRENT_FIELDS}
            row.update(endpoint_id=index, provider_key=binding['provider_key'],
                public_path=binding['public_path'], contract_method=binding['contract_method'],
                upstream_path=binding['upstream_path'], target_has_query=False,
                target_matches_endpoint=True, authority_equal_expected=True,
                profile_binding_metadata_matches=True, profile_revision=4, compiled_contract_revision=4,
                endpoint_status='enabled', provider_status='enabled', profile_status='verified',
                upstream_origin_sha256=hashlib.sha256(EXPECTED_ORIGINS[binding['provider_key']].encode()).hexdigest(),
                private_token='DO_NOT_COPY_PRIVATE_FIELD')
            current['rows'].append(row)
        joined = current_bindings(self.bindings, current)
        self.assertEqual(len(joined), 33)
        self.assertNotIn('DO_NOT_COPY_PRIVATE_FIELD', json.dumps(joined))
        self.assertTrue(all(r['frozen_mapping_equal_current'] for r in joined))
        self.assertTrue(all(r['current_mapping_metadata_verified'] and r['authority_origin_verified'] for r in joined))
        rows = candidate_rows(joined, self.sources)
        self.assertEqual(sum(len(r['operations']) for r in rows), 37)
        for row in rows:
            self.assertFalse(row['strict_profile_binding_validated'])
            self.assertFalse(row['identity_approved'])
            self.assertFalse(row['source_approved'])
            self.assertFalse(row['activatable'])
            self.assertIn('full_strict_profile_ValidateBinding_not_performed', row['gaps'])
        bad = copy.deepcopy(current)
        bad['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'complete bounded'):
            current_bindings(self.bindings, bad)
        bad = copy.deepcopy(current)
        bad['rows'][0]['authority_equal_expected'] = False
        joined_bad = current_bindings(self.bindings, bad)
        self.assertEqual(sum(not r['authority_origin_verified'] for r in joined_bad), 1)
        for invalid in (0, -1, True, '1'):
            wrong = copy.deepcopy(current)
            wrong['rows'][0]['endpoint_id'] = invalid
            with self.assertRaisesRegex(ValueError, 'positive integer'):
                current_bindings(self.bindings, wrong)
        bad['rows'].append(bad['rows'][0])
        with self.assertRaisesRegex(ValueError, 'duplicate current'):
            current_bindings(self.bindings, bad)
        bad = copy.deepcopy(current)
        bad['rows'].append({'provider_key': 'foreign-provider', 'endpoint_id': bad['rows'][0]['endpoint_id']})
        with self.assertRaisesRegex(ValueError, 'duplicate current endpoint'):
            current_bindings(self.bindings, bad)
        bad = copy.deepcopy(current)
        bad['rows'][0]['upstream_origin_sha256'] = hashlib.sha256(b'https://untrusted.example').hexdigest()
        self.assertEqual(sum(not r['authority_origin_verified'] for r in current_bindings(self.bindings, bad)), 1)
        for field, value in [('endpoint_status', 'disabled'), ('provider_status', 'disabled'),
                             ('profile_status', 'pending'), ('profile_revision', True),
                             ('profile_revision', 0), ('profile_revision', -4)]:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(current)
                bad['rows'][0][field] = value
                if field == 'profile_revision':
                    bad['rows'][0]['compiled_contract_revision'] = value
                joined = current_bindings(self.bindings, bad)
                failed = [r for r in joined if not r['current_mapping_metadata_verified']]
                self.assertEqual(len(failed), 1)
                self.assertIn('current_runtime_target_and_revision_not_verified',
                              candidate_rows(failed, self.sources)[0]['gaps'])

    def test_redirect_destination_is_rejected_before_following_it(self):
        handler = StaticRedirectHandler()
        request = Request('https://docs.parallel.ai/public-openapi.json')
        for url in ['https://api.parallel.ai/v1/search', 'https://untrusted.example/schema.json',
                    'https://api-dashboard.search.brave.com/api-reference/%2e%2e/__data.json']:
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'redirect destination'):
                handler.redirect_request(request, None, 302, 'Found', {}, url)
        redirect = handler.redirect_request(request, None, 302, 'Found', {}, SOURCE_URLS['docs-latest-openapi'])
        self.assertEqual(redirect.full_url, SOURCE_URLS['docs-latest-openapi'])

    def test_effective_server_origin_prefix_and_overrides_fail_closed(self):
        binding = self.bindings[0]
        for level in ['root', 'path', 'operation']:
            for server in ['https://untrusted.example', 'https://api.parallel.ai/wrong-prefix',
                           'https://api.parallel.ai?query=1', 'https://api.parallel.ai:443',
                           'https://userinfo@api.parallel.ai']:
                with self.subTest(level=level, server=server):
                    sources = copy.deepcopy(self.sources)
                    document = sources['parallel-public-openapi.json']
                    item = document['paths'][binding['upstream_path']]
                    place = document if level == 'root' else item if level == 'path' else item['post']
                    place['servers'] = [{'url': server}]
                    with self.assertRaisesRegex(ValueError, 'source server'):
                        candidate_rows([binding], sources)
        sources = copy.deepcopy(self.sources)
        document = sources['parallel-public-openapi.json']
        document['servers'] = [{'url': 'https://untrusted.example'}]
        document['paths'][binding['upstream_path']]['post']['servers'] = [{'url': 'https://api.parallel.ai'}]
        self.assertEqual(len(candidate_rows([binding], sources)[0]['operations']), 1)
        document['paths'][binding['upstream_path']]['post']['servers'] = [{
            'url': 'https://{host}', 'variables': {'host': {'default': 'api.parallel.ai'}}}]
        with self.assertRaisesRegex(ValueError, 'source server'):
            candidate_rows([binding], sources)
        for malformed in [None, {}, ['https://api.parallel.ai'], [{'url': None}]]:
            document['paths'][binding['upstream_path']]['post']['servers'] = malformed
            with self.subTest(malformed=malformed), self.assertRaisesRegex(ValueError, 'invalid source server'):
                candidate_rows([binding], sources)

    def test_capture_receipt_detects_mutated_source_bytes_and_converter_output(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = Path(directory)
            folder = packet / 'candidates'
            folder.mkdir()
            receipts = []
            for name, url in SOURCE_URLS.items():
                raw = json.dumps(self.sources['parallel-public-openapi.json']).encode()
                (folder / ('parallel-' + name + '.json')).write_bytes(raw)
                receipts.append({'url': url, 'source_sha256': hashlib.sha256(raw).hexdigest()})
            raw = json.dumps(self.sources['parallel-archived-events.json']).encode()
            (folder / 'parallel-archived-events-source.json').write_bytes(raw)
            (folder / 'parallel-archived-events.json').write_text(json.dumps(extract(raw)))
            receipts.append({'url': SOURCE_URL, 'source_sha256': hashlib.sha256(raw).hexdigest()})
            url = 'https://api-dashboard.search.brave.com/api-reference/search/get'
            rows = {url: spec()}
            receipts.append({'url': url + '/__data.json', 'source_sha256': 'fixture-raw-graph-hash'})
            (packet / 'source-get-receipts.json').write_text(json.dumps(receipts))
            (packet / 'brave-structured-sources.json').write_text(json.dumps(rows))
            (packet / 'brave-source-provenance.json').write_text(json.dumps({
                'structured_source_hash': digest(rows),
                'source_pages': [{'url': url + '/__data.json', 'content_hash': digest(rows[url])}]}))
            (folder / 'brave-official.json').write_text(json.dumps(convert_specs(rows)))
            verify_capture(packet)
            altered = folder / 'parallel-public-openapi.json'
            original = altered.read_bytes()
            altered.write_bytes(original + b' ')
            with self.assertRaisesRegex(ValueError, 'byte hash mismatch'):
                verify_capture(packet)
            altered.write_bytes(original)
            altered = folder / 'brave-official.json'
            document = json.loads(altered.read_text())
            document['paths']['/v1/search']['get']['responses']['200']['content']['application/json']['schema'] = True
            altered.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'converter output mismatch'):
                verify_capture(packet)


if __name__ == '__main__':
    unittest.main()

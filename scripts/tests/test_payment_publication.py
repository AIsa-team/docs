import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError, HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_payment_discovery import candidate, verify_payment_catalog
from payment_catalog import build_publication, canonical_json, digest
from refresh_payment_publication import collect, refresh, ChallengeReader
from fetch_runtime_release import acquire, save, NoRedirect
import test_payment_catalog


class PublicationTests(unittest.TestCase):
    def setUp(self):
        test_payment_catalog.CatalogTests.setUp(self)
        (self.root / 'openapi').mkdir()
        (self.root / 'discovery').mkdir()
        for op in self.allowlist:
            old = self.root / op['source']
            op['source'] = 'openapi/' + op['source']
            old.rename(self.root / op['source'])
        self.scope = [{k: row[k] for k in ('provider', 'method', 'path', 'target', 'source')} for row in self.allowlist]
        self.facts = self.root / 'facts'
        self.make_facts()
        self.probe = lambda op: copy.deepcopy(next(row for row in self.observed if row['provider'] == op['provider']))
        self.bundle = self.collect()
        (self.root / 'discovery/payment-evidence.json').write_bytes(canonical_json(self.bundle))
        (self.root / 'discovery/openapi.json').write_bytes(canonical_json(build_publication(self.root, self.bundle)[0]))

    def make_facts(self):
        import shutil
        if self.facts.exists():
            shutil.rmtree(self.facts)
        providers, content = [], {}
        for spec in self.scope:
            document = json.loads((self.root / spec['source']).read_bytes())
            facts_hash = digest(canonical_json(document))
            document['info'] = {'x-aisa-document': {'facts_hash': facts_hash}}
            content['providers/' + spec['provider'] + '.json'] = canonical_json(document)
            providers.append({'id': spec['provider'], 'facts_hash': facts_hash})
        content['index.json'] = canonical_json({'pending_endpoints': [], 'pending_providers': [], 'providers': providers,
            'coverage': {'selected_endpoint_count': 2, 'projected_endpoint_count': 2, 'pending_endpoint_count': 0, 'inventory_endpoint_count': 2}})
        files = [{'name': name, 'media_type': 'application/json', 'sha256': digest(raw)} for name, raw in sorted(content.items())]
        manifest = {'schema_version': 1, 'source_digest': 'a' * 64, 'compiler_revision': 'b' * 40, 'files': files}
        revision = digest(json.dumps(manifest, separators=(',', ':')).encode())
        self.current = {**manifest, 'artifact_revision': revision, 'fresh': True, 'generation': 3, 'published_generation': 3}
        def reader(path):
            if path == '/public/api-contract/current': return canonical_json(self.current), {}
            if path == '/info/apis/category': return canonical_json({'apis': providers}), {}
            raw = content[path.split('/' + revision + '/', 1)[1]]
            return raw, {'etag': '"' + digest(raw) + '"'}
        save(self.facts, acquire(revision, 'b' * 40, reader))
        self.current_reader = lambda path: (canonical_json(self.current), {})

    def collect(self):
        return collect(self.root, self.facts, self.scope, self.current_reader, self.probe)

    def change_source(self, change):
        path = self.root / self.allowlist[0]['source']
        source = json.loads(path.read_bytes())
        change(source, source['paths']['/apis/v1/alpha']['get'])
        path.write_bytes(canonical_json(source))

    def test_default_generation_and_check_use_entire_reviewed_subset(self):
        result = candidate(self.root)
        self.assertEqual(set(result['paths']), {'/apis/v1/alpha', '/apis/v1/beta'})
        self.assertEqual(verify_payment_catalog(self.root)['operations'], 2)
        del result['paths']['/apis/v1/beta']
        (self.root / 'discovery/openapi.json').write_bytes(canonical_json(result))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            verify_payment_catalog(self.root)
        self.assertNotIn('quote_plan', self.bundle)
        self.assertNotIn('runtime_plan_sha256', self.bundle['challenge_evidence'])

    def test_metadata_and_unselected_operations_are_not_payment_dependencies(self):
        def change(source, op):
            source['info'] = {'version': 'new-composer'}
            source['paths']['/unrelated'] = {'get': {'responses': {}}}
            op['description'] = 'Editorial update'
            op['x-aisa-source'] = {'fetched_at': 'later'}
        self.change_source(change)
        doc, _ = build_publication(self.root, self.bundle)
        self.assertEqual(len(doc['paths']), 2)

    def test_offline_contract_changes_fail_closed_until_actual_refresh(self):
        original = (self.root / 'openapi/alpha.json').read_bytes()
        mutations = [lambda s, o: o['parameters'][0].update(required=False),
                     lambda s, o: o['x-aisa-capabilities'].pop('mpp_methods'),
                     lambda s, o: o['x-aisa-revision'].update(profile_ref='changed'),
                     lambda s, o: o.update(security=[{'new': []}]),
                     lambda s, o: s['components']['schemas']['Input']['properties']['q'].update(type='number')]
        for mutate in mutations:
            (self.root / 'openapi/alpha.json').write_bytes(original)
            self.change_source(mutate)
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, KeyError)):
                build_publication(self.root, self.bundle)

    def test_missing_evidence_scope_and_terms_fail_closed(self):
        mutations = [lambda b: b['challenge_evidence']['operations'].pop(),
                     lambda b: b['challenge_evidence']['operations'][0].update(error='404'),
                     lambda b: b['challenge_evidence']['source_contracts'].clear(),
                     lambda b: b['challenge_evidence']['operations'][0]['offer'].update(amount='-166'),
                     lambda b: b['challenge_evidence']['operations'][0].update(expires='2026-10-11T00:00:00Z'),
                     lambda b: b['allowlist'].append(copy.deepcopy(b['allowlist'][0])),
                     lambda b: b['challenge_evidence'].update(fresh_before_and_after=False)]
        for mutate in mutations:
            bundle = copy.deepcopy(self.bundle)
            mutate(bundle)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                build_publication(self.root, bundle)

    def test_instances_extensions_and_discriminator_reference_closure(self):
        def change(source, op):
            op['x-client-data'] = {'$ref': 'https://example.test/not-a-contract'}
            schema = source['components']['schemas']['Input']
            schema['example'] = {'$ref': '#/components/schemas/DoesNotExist'}
            schema['discriminator'] = {'propertyName': 'kind', 'mapping': {'q': '#/components/schemas/Extra'}}
            source['components']['schemas']['Extra'] = {'type': 'object'}
            source['components']['responses']['Result']['links'] = {'next': {'$ref': '#/components/links/Next'}}
            source['components']['links'] = {'Next': {'operationId': 'search', 'parameters': {'q': {'$ref': 'literal-data'}}}}
        self.change_source(change)
        bundle = self.collect()
        doc, _ = build_publication(self.root, bundle)
        op = doc['paths']['/apis/v1/alpha']['get']
        self.assertEqual(op['x-client-data']['$ref'], 'https://example.test/not-a-contract')
        inputs = [value for name, value in doc['components']['schemas'].items() if name.startswith('alpha_') and name.endswith('__Input')]
        self.assertEqual(inputs[0]['example']['$ref'], '#/components/schemas/DoesNotExist')
        self.assertIn(inputs[0]['discriminator']['mapping']['q'].split('/')[-1], doc['components']['schemas'])
        link = next(value for name, value in doc['components']['links'].items() if name.endswith('__Next'))
        self.assertEqual(link['parameters']['q'], {'$ref': 'literal-data'})

    def test_price_change_uses_actual_402_and_rebinds_without_new_plan(self):
        self.change_source(lambda s, o: o['x-aisa-revision'].update(customer_pricing_ref='price@2'))
        self.make_facts()
        self.observed[0]['offer']['amount'] = '288'
        result = refresh(self.root, self.facts, self.current_reader, self.probe)
        self.assertTrue(result['publication_changed'])
        generated = candidate(self.root)
        self.assertEqual(generated['paths']['/apis/v1/alpha']['get']['x-payment-info']['price']['amount'], '0.000288')

    def test_fresh_observation_does_not_renew_unchanged_publication(self):
        original = (self.root / 'discovery/payment-evidence.json').read_bytes()
        self.observed[0].update(observed_at='2026-10-15T00:00:00Z', expires='2026-10-15T00:05:00Z')
        result = refresh(self.root, self.facts, self.current_reader, self.probe)
        self.assertFalse(result['publication_changed'])
        self.assertEqual((self.root / 'discovery/payment-evidence.json').read_bytes(), original)
        self.assertEqual(result['observation']['challenge_evidence']['operations'][0]['observed_at'], '2026-10-15T00:00:00Z')

    def test_failures_preserve_both_last_good_files(self):
        before = {name: (self.root / 'discovery' / name).read_bytes() for name in ('payment-evidence.json', 'openapi.json')}
        def changed_during(path):
            changed_during.calls += 1
            value = copy.deepcopy(self.current)
            if changed_during.calls == 2: value['fresh'] = False
            return canonical_json(value), {}
        changed_during.calls = 0
        bad_terms = lambda op: {**self.probe(op), 'chain_id': 1}
        failed = Mock(side_effect=URLError('network failed'))
        for reader, probe in ((changed_during, self.probe), (self.current_reader, bad_terms), (self.current_reader, failed)):
            with self.assertRaises((ValueError, URLError)):
                refresh(self.root, self.facts, reader, probe)
            self.assertEqual(before, {name: (self.root / 'discovery' / name).read_bytes() for name in before})

    def test_scope_target_and_runtime_disable_fail_before_probing(self):
        self.scope[0]['target'] = '/unexpected'
        probe = Mock()
        with self.assertRaisesRegex(ValueError, 'target changed'):
            collect(self.root, self.facts, self.scope, self.current_reader, probe)
        probe.assert_not_called()
        self.scope[0]['target'] = '/search'
        self.change_source(lambda source, op: op['x-aisa-capabilities'].update(mpp=False))
        self.make_facts()
        with self.assertRaisesRegex(ValueError, 'no longer enables'):
            collect(self.root, self.facts, self.scope, self.current_reader, probe)
        probe.assert_not_called()

    def test_workflow_refresh_is_explicit_and_offline_generation_is_separate(self):
        import yaml
        repo = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((repo / '.github/workflows/pull-openapi.yml').read_text())
        steps = workflow['jobs']['compose']['steps']
        step = next(row for row in steps if row.get('name') == 'Generate payment discovery from the same staged contracts')
        self.assertLess(step['run'].index('refresh_payment_publication.py'), step['run'].index('generate_payment_discovery.py'))
        self.assertNotIn('--scope', step['run'])
        self.assertTrue(any(row.get('with', {}).get('name') == 'payment-observation' and row.get('if') == 'always()' for row in steps))

    def test_transport_has_no_credentials_and_rejects_non_402(self):
        reader = ChallengeReader(float('inf'))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock()
        response.status, response.headers = 200, {}
        reader.opener = Mock()
        reader.opener.open.return_value = response
        with self.assertRaisesRegex(ValueError, 'HTTP 402'):
            reader(self.scope[0])
        request = reader.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('X-mpp-discovery'), 'true')
        self.assertIsNone(request.get_header('Authorization'))
        self.assertIsNone(request.get_header('X-api-key'))

    def test_transport_rejects_redirect_401_malicious_path_and_timeout(self):
        from urllib.request import Request
        reader = ChallengeReader(float('inf'))
        redirect = next(handler for handler in reader.opener.handlers if isinstance(handler, NoRedirect))
        with self.assertRaisesRegex(ValueError, 'redirect rejected'):
            redirect.redirect_request(Request('https://api.aisa.one/apis/v1/alpha'), None, 302, 'Found', {}, 'https://other.invalid/')
        reader.opener = Mock()
        reader.opener.open.side_effect = HTTPError('https://api.aisa.one/apis/v1/alpha', 401, 'Unauthorized', {}, None)
        with self.assertRaisesRegex(ValueError, 'received HTTP 401') as rejected:
            reader(self.scope[0])
        self.assertIn('method=GET, path=/apis/v1/alpha', str(rejected.exception))
        reader.opener.open.side_effect = TimeoutError('timeout')
        with self.assertRaises(TimeoutError):
            reader(self.scope[0])
        for path in ('https://other.invalid/', '//other.invalid/', '/apis/v1/../admin',
                     '/apis/v1/x?access_token=private', '/apis/v1/%2e%2e/admin', '/apis/v1/x\r\nHeader: value'):
            reader.opener.reset_mock()
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Unsupported payment route'):
                reader({**self.scope[0], 'path': path})
            reader.opener.open.assert_not_called()
        expired = ChallengeReader(0)
        expired.opener = Mock()
        with self.assertRaisesRegex(ValueError, 'deadline exceeded'):
            expired(self.scope[0])
        expired.opener.open.assert_not_called()


if __name__ == '__main__':
    unittest.main()

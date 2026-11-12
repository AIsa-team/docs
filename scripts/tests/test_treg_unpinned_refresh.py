"""Spec #1285 R1: unpinned gateway declarations, no upstream notes, drift classification."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_treg_declarations as capture_module  # noqa: E402
import prepare_treg_public_reference as treg  # noqa: E402
import refresh_upstream  # noqa: E402
from source_governance import policy_errors  # noqa: E402
from upstream_semantics import classify_drift, drift_document  # noqa: E402
import vocab_scan  # noqa: E402

REV_A, REV_B = 'a' * 40, 'b' * 40
RULES = vocab_scan.load_rules(terms=['acmefeeds'])


def catalog_yaml(*, required_company=False, note='Internal: PRICE DIAL, shared tier absorbs it.'):
    body = {'domain': {'type': 'string', 'required': True, 'note': note},
            'limit': {'type': 'integer', 'min': 1, 'max': 10}}
    if required_company:
        body['company_linkedin_url'] = {'type': 'string', 'required': True}
    return yaml.safe_dump({'provider': 'widgets', 'endpoints': [
        {'id': 'widgets.jobs.company', 'method': 'POST', 'path': '/jobs', 'name': 'Jobs', 'note': 'op-level guidance',
         'bill': {'per': 'call'}, 'input': {'body': body, 'note': 'Provide domain. Costs 1 credit per call.'}}]}).encode()


def fake_get(files):
    def get(url):
        if url.startswith('https://api.github.com/'):
            return json.dumps([{'type': 'file', 'path': 'src/treg/catalog/' + n} for n in files]).encode()
        return files[url.rsplit('/', 1)[1]]
    return get


def take(revision, files):
    captured, raw = capture_module.capture(revision, fake_get(files), acquired_at='2026-11-12T00:00:00+00:00')
    return captured, raw, hashlib.sha256(capture_module.encode(captured)).hexdigest()


def previous_document():
    return {'openapi': '3.1.0', 'info': {'x-aisa-source': {'operation_map': {'/apis/v1/widgets/jobs-company': 'widgets.jobs.company'}}},
            'paths': {'/apis/v1/widgets/jobs-company': {'post': {'operationId': 'widgets.jobs-company', 'summary': 'Company jobs'}}}}


class UnpinnedDeclarationTests(unittest.TestCase):
    def test_capture_binds_files_and_operations(self):
        captured, raw, _ = take(REV_A, {'widgets.yaml': catalog_yaml()})
        self.assertEqual(captured['revision'], REV_A)
        self.assertEqual(captured['files'][0]['url'], capture_module.raw_base(REV_A) + 'src/treg/catalog/widgets.yaml')
        with tempfile.TemporaryDirectory() as directory:
            for name, content in raw.items():
                (Path(directory) / name).write_bytes(content)
            treg.validate_capture(captured, Path(directory))
            (Path(directory) / 'widgets.yaml').write_bytes(catalog_yaml(required_company=True))
            with self.assertRaises(ValueError):
                treg.validate_capture(captured, Path(directory))
        with self.assertRaises(ValueError):
            capture_module.raw_base('main')

    def test_resolve_revision_uses_ls_remote(self):
        runner = mock.Mock(return_value=REV_B + '\trefs/heads/main\n')
        self.assertEqual(capture_module.resolve_revision(runner=runner), REV_B)
        with self.assertRaises(ValueError):
            capture_module.resolve_revision(runner=mock.Mock(return_value=''))

    def test_refresh_document_never_copies_upstream_notes(self):
        captured, _, digest = take(REV_A, {'widgets.yaml': catalog_yaml()})
        document, report = treg.refresh_document(previous_document(), captured, capture_sha256=digest, rules=RULES)
        text = json.dumps(document['paths'])
        for fragment in ('PRICE DIAL', 'shared tier', 'credit per call', 'op-level guidance'):
            self.assertNotIn(fragment, text)
        self.assertEqual(len(report['internal_notes']['widgets.jobs-company']), 3)
        operation = document['paths']['/apis/v1/widgets/jobs-company']['post']
        self.assertEqual((operation['operationId'], operation['summary']), ('widgets.jobs-company', 'Company jobs'))
        self.assertNotIn('description', operation)

    def test_source_policy_is_automatic_every_twelve_hours_with_stable_authority(self):
        captured, _, digest = take(REV_A, {'widgets.yaml': catalog_yaml()})
        a, _ = treg.refresh_document(previous_document(), captured, capture_sha256=digest, rules=RULES)
        captured_b, _, digest_b = take(REV_B, {'widgets.yaml': catalog_yaml()})
        b, _ = treg.refresh_document(a, captured_b, capture_sha256=digest_b, rules=RULES)
        source_a, source_b = a['info']['x-aisa-source'], b['info']['x-aisa-source']
        self.assertEqual(policy_errors(source_a), [])
        self.assertEqual((source_a['refresh_policy'], source_a['refresh_interval_hours']), ('automatic', 12))
        self.assertEqual(source_a['url'], treg.TREG_CATALOG_URL)
        self.assertEqual(source_a['policy_revision'], source_b['policy_revision'])
        self.assertEqual(source_b['source_git_revision'], REV_B)
        self.assertEqual(source_b['operation_map'], source_a['operation_map'])

    def test_descriptions_failing_the_vocabulary_scan_are_dropped(self):
        document = {'paths': {'/x': {'post': {'operationId': 'x', 'requestBody': {'content': {'application/json': {'schema': {
            'properties': {'a': {'description': 'Hosted by AcmeFeeds'}, 'b': {'description': 'Company domain'}}}}}}}}}}
        pending = treg.scrub_descriptions(document, RULES)
        properties = document['paths']['/x']['post']['requestBody']['content']['application/json']['schema']['properties']
        self.assertEqual(properties, {'a': {}, 'b': {'description': 'Company domain'}})
        self.assertEqual(pending, [('x', '/paths/~1x/post/requestBody/content/application~1json/schema/properties/a/description')])

    def test_missing_upstream_operation_is_omitted_for_retention(self):
        captured, _, digest = take(REV_A, {'other.yaml': yaml.safe_dump({'endpoints': []}).encode()})
        document, report = treg.refresh_document(previous_document(), captured, capture_sha256=digest, rules=RULES)
        self.assertEqual(document['paths'], {})
        self.assertEqual(report['omitted'][0]['reason'], 'exact_source_missing')

    def test_required_field_drift_is_classified(self):
        captured, _, digest = take(REV_A, {'widgets.yaml': catalog_yaml()})
        before, _ = treg.refresh_document(previous_document(), captured, capture_sha256=digest, rules=RULES)
        captured, _, digest = take(REV_B, {'widgets.yaml': catalog_yaml(required_company=True)})
        after, _ = treg.refresh_document(before, captured, capture_sha256=digest, rules=RULES)
        rows = classify_drift(before, after)
        self.assertEqual(rows, [{'operation_id': 'widgets.jobs-company', 'path': '/apis/v1/widgets/jobs-company',
                                 'method': 'POST', 'kind': 'required_added', 'field': 'company_linkedin_url'}])
        doc = drift_document(rows, None, now='2026-11-12T00:00:00+00:00')
        self.assertEqual(doc['operations'][0]['catalog'], 'widgets')
        later = drift_document(rows, doc, now='2026-11-13T00:00:00+00:00')
        self.assertEqual(later['operations'][0]['first_seen_at'], '2026-11-12T00:00:00+00:00')
        self.assertEqual(drift_document([], later, now='x')['operations'], [])
        self.assertNotIn('raw.githubusercontent', json.dumps(doc))

    def test_type_any_of_and_removed_fields(self):
        def doc(properties, required=()):
            return {'openapi': '3.1.0', 'paths': {'/apis/v1/w/x': {'post': {'operationId': 'w.x', 'requestBody': {
                'content': {'application/json': {'schema': {'type': 'object', 'properties': properties, 'required': list(required)}}}}}}}}
        before = doc({'a': {'type': 'string'}, 'b': {'type': 'string'}, 'c': {'type': 'string'}})
        after = doc({'a': {'type': 'integer'}, 'c': {'anyOf': [{'type': 'string'}, {'type': 'integer'}]}})
        kinds = sorted((row['kind'], row['field']) for row in classify_drift(before, after))
        self.assertEqual(kinds, [('any_of_added', 'c'), ('field_removed', 'b'), ('type_changed', 'a')])

    def test_refresh_records_drift_only_for_assessed_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'openapi/upstream').mkdir(parents=True)
            captured, _, digest = take(REV_A, {'widgets.yaml': catalog_yaml()})
            committed, _ = treg.refresh_document(previous_document(), captured, capture_sha256=digest, rules=RULES)
            (root / 'openapi/upstream/treg-public.json').write_text(json.dumps(committed))
            captured_b, _, digest_b = take(REV_B, {'widgets.yaml': catalog_yaml(required_company=True)})
            updated, _ = treg.refresh_document(committed, captured_b, capture_sha256=digest_b, rules=RULES)
            changes, report = refresh_upstream.refresh(root, fetch=lambda name, url: copy.deepcopy(updated))
            self.assertEqual([row['kind'] for row in report['drift']['treg-public']], ['required_added'])
            target = root / 'out/upstream-drift.json'
            self.assertTrue(refresh_upstream.write_drift(target, report, root / 'docs/publication/upstream-drift.json'))
            self.assertEqual(json.loads(target.read_text())['operations'][0]['field'], 'company_linkedin_url')
            def broken(name, url):
                raise OSError('offline')
            _, failed = refresh_upstream.refresh(root, fetch=broken)
            self.assertFalse(refresh_upstream.write_drift(root / 'out/other.json', failed, target))
            self.assertFalse((root / 'out/other.json').exists())

    def test_importer_is_registered_for_the_unpinned_source(self):
        import import_upstream
        with mock.patch.object(treg, 'import_treg_public', return_value={'sentinel': True}) as importer:
            self.assertEqual(import_upstream.import_source('treg-public', treg.TREG_CATALOG_URL), {'sentinel': True})
        importer.assert_called_once_with()

    def test_committed_declaration_is_unpinned_and_note_free(self):
        root = Path(__file__).resolve().parents[2]
        document = json.loads((root / 'openapi/upstream/treg-public.json').read_text())
        source = document['info']['x-aisa-source']
        self.assertEqual(policy_errors(source), [])
        self.assertEqual((source['refresh_policy'], source['refresh_interval_hours']), ('automatic', 12))
        self.assertEqual(set(source['operation_map']), set(document['paths']))
        self.assertEqual(vocab_scan.scan_json(document['paths'], vocab_scan.load_rules(), 'treg-public'), [])


if __name__ == '__main__':
    unittest.main()

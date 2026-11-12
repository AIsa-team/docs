"""Spec #1285 R1: reviewed customer-facing treg field descriptions."""
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_treg_public_reference as treg  # noqa: E402
import vocab_scan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / 'openapi/upstream/treg-public.json'
# Same placeholder patterns as release_gate.py G3, plus internal identities.
PLACEHOLDERS = re.compile(r'\bexample\.com\b|\b(?:hello|person|jane)@|linkedin\.com/in/example\b|\bJane Doe\b|'
                          r'\bYOUR_[A-Z_]+|\bnobody-', re.I)
# Upstream source identities that must never appear in customer text.
UPSTREAM = re.compile(r'(?<![a-z0-9])(?:treg|superdesign|superdesigndev)(?![a-z0-9])', re.I)


def reviewed_texts(document):
    for name, text in document['by_name'].items():
        yield 'by_name/' + name, text
    for operation_id, fields in document['by_operation'].items():
        for location, text in fields.items():
            yield f'by_operation/{operation_id}/{location}', text


def committed():
    return json.loads(COMMITTED.read_text())


class ReviewedFileTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(treg.FIELD_DESCRIPTIONS.read_text())

    def test_every_entry_passes_public_vocabulary_rules(self):
        rules = vocab_scan.load_rules(public_names=vocab_scan.public_catalog_ids(ROOT))
        for where, text in reviewed_texts(self.raw):
            self.assertEqual(vocab_scan.scan_text(text, rules), [], where)
        # The loader enforces the same scan.
        treg.load_field_descriptions(rules=rules)

    def test_no_placeholders_upstream_names_or_catalog_vendors(self):
        operation_map = committed()['info']['x-aisa-source']['operation_map']
        # Catalog prefixes of the declarations (vendor ids behind each route).
        vendors = {slug.split('.')[0] for slug in operation_map.values()} | {
            route.split('/')[3] for route in operation_map}
        vendor = re.compile(r'(?<![a-z0-9])(?:' + '|'.join(sorted(map(re.escape, vendors))) + r')(?![a-z0-9])', re.I)
        for where, text in reviewed_texts(self.raw):
            self.assertIsNone(PLACEHOLDERS.search(text), where)
            self.assertIsNone(UPSTREAM.search(text), where)
            self.assertIsNone(vendor.search(text), where)

    def test_internal_note_is_rejected_loudly(self):
        rules = vocab_scan.load_rules()
        broken = copy.deepcopy(self.raw)
        broken['by_name']['limit'] = 'THIS IS THE PRICE DIAL: 1 credit per call.'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'descriptions.json'
            path.write_text(json.dumps(broken))
            with self.assertRaises(ValueError) as caught:
                treg.load_field_descriptions(path, rules=rules)
        self.assertIn('by_name/limit', str(caught.exception))
        self.assertNotIn('PRICE', str(caught.exception))

    def test_secret_supplier_term_is_rejected_without_echo(self):
        rules = vocab_scan.load_rules(terms=['acmefeeds'])
        broken = copy.deepcopy(self.raw)
        broken['by_operation'].setdefault('x.op', {})['query/q'] = 'Query sent to Acmefeeds.'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'descriptions.json'
            path.write_text(json.dumps(broken))
            with self.assertRaises(ValueError) as caught:
                treg.load_field_descriptions(path, rules=rules)
        self.assertNotIn('cmefeeds', str(caught.exception).lower())

    def test_invalid_location_is_rejected(self):
        broken = {'schema_version': 1, 'by_name': {}, 'by_operation': {'x.op': {'header/q': 'Text.'}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'descriptions.json'
            path.write_text(json.dumps(broken))
            with self.assertRaises(ValueError):
                treg.load_field_descriptions(path)


class ApplyTests(unittest.TestCase):
    def document(self):
        return {'paths': {'/apis/v1/widgets/jobs': {'post': {
            'operationId': 'widgets.jobs',
            'parameters': [{'name': 'limit', 'in': 'query', 'required': False,
                            'schema': {'type': 'integer', 'description': 'upstream text'}}],
            'requestBody': {'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                'lead': {'type': 'object', 'properties': {'email': {'type': 'string'}}},
                'mode': {'type': 'string'}}}}}}}}}}

    def test_operation_entry_wins_over_name_and_replaces_upstream(self):
        reviewed = {'by_name': {'limit': 'Generic limit.', 'email': 'Email address.'},
                    'by_operation': {'widgets.jobs': {'query/limit': 'Jobs to return.', 'body/mode': 'Mode.',
                                                      'body/missing': 'Not declared.'},
                                     'other.op': {'query/q': 'Elsewhere.'}}}
        document = self.document()
        applied, total, pending, unknown = treg.apply_field_descriptions(document, reviewed)
        operation = document['paths']['/apis/v1/widgets/jobs']['post']
        parameter = operation['parameters'][0]
        self.assertEqual(parameter['description'], 'Jobs to return.')
        self.assertNotIn('description', parameter['schema'])
        properties = operation['requestBody']['content']['application/json']['schema']['properties']
        self.assertEqual(properties['lead']['properties']['email']['description'], 'Email address.')
        self.assertEqual(properties['mode']['description'], 'Mode.')
        self.assertEqual((applied, total), (3, 4))
        self.assertEqual(pending, [{'operation_id': 'widgets.jobs', 'location': 'body/lead'}])
        self.assertEqual(unknown, [{'operation_id': 'other.op', 'location': 'query/q'},
                                   {'operation_id': 'widgets.jobs', 'location': 'body/missing'}])

    def test_finish_reports_and_hashes_descriptions(self):
        reviewed = {'by_name': {'limit': 'Generic limit.'}, 'by_operation': {}}
        capture = {'revision': 'a' * 40, 'acquired_at': '2026-11-12T00:00:00+00:00'}
        rules = vocab_scan.load_rules()
        paths = {'/apis/v1/widgets/jobs': {'post': {'operationId': 'widgets.jobs', 'parameters': [
            {'name': 'limit', 'in': 'query', 'required': False, 'schema': {'type': 'integer'}},
            {'name': 'cursor', 'in': 'query', 'required': False, 'schema': {'type': 'string'}}]}}}
        document, report = treg.finish(copy.deepcopy(paths), capture, 'b' * 64, {}, {}, rules, {},
                                       field_descriptions=reviewed)
        bare, _ = treg.finish(copy.deepcopy(paths), capture, 'b' * 64, {}, {}, rules, {},
                              field_descriptions={'by_name': {}, 'by_operation': {}})
        self.assertEqual(document['paths']['/apis/v1/widgets/jobs']['post']['parameters'][0]['description'], 'Generic limit.')
        self.assertEqual(report['field_descriptions'], {'applied': 1, 'fields': 2})
        self.assertEqual(report['field_description_pending'], [{'operation_id': 'widgets.jobs', 'location': 'query/cursor'}])
        self.assertNotEqual(document['info']['x-aisa-source']['content_hash'], bare['info']['x-aisa-source']['content_hash'])


class CommittedDeclarationTests(unittest.TestCase):
    def test_every_committed_field_has_a_reviewed_description(self):
        reviewed = treg.load_field_descriptions()
        document = committed()
        missing, total = [], 0
        for path, item in document['paths'].items():
            for method, operation in item.items():
                overrides = reviewed['by_operation'].get(operation['operationId'], {})
                for location, name, holder in treg.request_fields(operation):
                    total += 1
                    expected = overrides.get(location, reviewed['by_name'].get(name))
                    if not holder.get('description') or holder['description'] != expected:
                        missing.append((operation['operationId'], location))
        self.assertGreater(total, 1000)
        self.assertEqual(missing, [])

    def test_no_reviewed_entry_is_orphaned(self):
        reviewed = treg.load_field_descriptions()
        _, _, pending, unknown = treg.apply_field_descriptions(committed(), reviewed)
        self.assertEqual(pending, [])
        self.assertEqual(unknown, [])

    def test_committed_declaration_equals_regeneration(self):
        document = committed()
        reviewed = treg.load_field_descriptions(rules=vocab_scan.load_rules(public_names=vocab_scan.public_catalog_ids(ROOT)))
        self.assertEqual(treg.reapply_field_descriptions(document, reviewed), document)

    def test_content_hash_covers_the_importer_view(self):
        document = committed()
        source = document['info'].pop('x-aisa-source')
        document.pop('components', None)
        for row in source.get('retained_operations', []):
            method, path = row.split(' ', 1)
            document['paths'][path].pop(method.lower())
            if not document['paths'][path]:
                document['paths'].pop(path)
        self.assertEqual(treg.digest(document), source['content_hash'])

    def test_committed_declaration_passes_vocabulary_scan(self):
        rules = vocab_scan.load_rules(public_names=vocab_scan.public_catalog_ids(ROOT))
        self.assertEqual(vocab_scan.scan_json(committed(), rules, 'treg-public.json'), [])


if __name__ == '__main__':
    unittest.main()

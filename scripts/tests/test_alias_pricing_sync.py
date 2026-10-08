"""Bounded pricing repair against all 27 real immutable locale identity proofs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from identity_compatibility import published_history, operations
import runtime_localize_openapi_zh as localization

REPO = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((Path(__file__).with_name('fixtures') / 'published-locale-identities.json').read_text())
REF = FIXTURE['published_ref']


class AliasPricingSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'candidate'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', '-q', str(REPO), str(self.root)], check=True)
        self.history = published_history(self.root, REF)
        for filename in {row['proof'][key] for row in FIXTURE['aliases']
                         for key in ('source_file', 'canonical_source_file')}:
            document, _ = self.history.read(REF, filename)
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
        self.originals = self.snapshot()

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in (self.root / 'openapi').rglob('*.json')}

    def sync(self, write=False, ref=REF):
        with patch.object(localization, 'ROOT', self.root):
            return localization.sync_alias_pricing(ref, write=write)

    def mutate_operation(self, row, change):
        proof = row['proof']
        path = self.root / proof['source_file']
        document = json.loads(path.read_text())
        operation = next(op for route, method, op in operations(document)
                         if (route, method) == (proof['public_path'], proof['method']))
        change(operation)
        path.write_text(json.dumps(document))

    def test_all_27_dry_run_write_idempotence_and_only_pricing_changes(self):
        result = self.sync()
        self.assertEqual((result['aliases_checked'], result['pricing_added']), (27, 27))
        self.assertEqual(len(result['changed_files']), 5)
        self.assertEqual(self.snapshot(), self.originals)
        self.sync(write=True)
        changed = self.snapshot()
        for path, raw in self.originals.items():
            original = json.loads(raw)
            current = json.loads(changed[path])
            if not str(path).startswith('openapi/zh/'):
                self.assertEqual(raw, changed[path])
                continue
            for row in FIXTURE['aliases']:
                proof = row['proof']
                if str(path) != proof['source_file']:
                    continue
                root = json.loads(changed[Path(proof['canonical_source_file'])])
                expected = next(op for route, method, op in operations(root)
                                if (route, method) == (proof['public_path'], proof['method']))
                actual = next(op for route, method, op in operations(current)
                              if (route, method) == (proof['public_path'], proof['method']))
                self.assertEqual(actual['x-aisa-pricing'], expected['x-aisa-pricing'])
                self.assertEqual(actual['operationId'], proof['operation_id'])
                actual.pop('x-aisa-pricing')
                # Immutable historical bytes still verify after current mirror repair.
                self.history.verify(row['canonical_operation_id'], proof)
            self.assertEqual(current, original)
        result = self.sync(write=True)
        self.assertEqual((result['aliases_checked'], result['pricing_added'], result['changed_files']), (27, 0, []))
        self.assertEqual(self.snapshot(), changed)

    def test_conflicting_pricing_or_late_wire_drift_reject_whole_batch(self):
        # Reddit sorts last, so earlier candidates have already been considered.
        row = next(row for row in FIXTURE['aliases'] if row['proof']['source_file'] == 'openapi/zh/reddit.json')
        for mutation in (
            lambda op: op.update({'x-aisa-pricing': {'model': 'unexpected'}}),
            lambda op: op['responses'].update({'599': {'description': 'Different status'}}),
            lambda op: op.update({'operationId': 'invented_alias'}),
            lambda op: op.update({'x-aisa-identity': {'invented': True}}),
            lambda op: op.update({'example': {'description': 'wire literal'}}),
            lambda op: op.update({'enum': [{'description': 'wire literal'}]}),
            lambda op: op.update({'const': {'description': 'wire literal'}}),
            lambda op: op.update({'default': {'description': 'wire literal'}}),
        ):
            with self.subTest(mutation=mutation):
                for filename, raw in self.originals.items():
                    (self.root / filename).write_bytes(raw)
                self.mutate_operation(row, mutation)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.sync(write=True)
                self.assertEqual(self.snapshot(), before)

    def test_global_wire_context_drift_and_missing_root_price_fail_closed(self):
        root_file = self.root / 'openapi/apollo.json'
        row = next(row for row in FIXTURE['aliases'] if row['proof']['canonical_source_file'] == 'openapi/apollo.json')
        def remove_selected_price(doc):
            proof = row['proof']
            next(op for route, method, op in operations(doc)
                 if (route, method) == (proof['public_path'], proof['method'])).pop('x-aisa-pricing')
        for change in (
            lambda doc: doc.update({'security': [{'unexpected': []}]}),
            remove_selected_price,
        ):
            with self.subTest(change=change):
                root_file.write_bytes(self.originals[Path('openapi/apollo.json')])
                doc = json.loads(root_file.read_text())
                change(doc)
                root_file.write_text(json.dumps(doc))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.sync(write=True)
                self.assertEqual(self.snapshot(), before)

    def test_explicit_immutable_base_is_required(self):
        for ref in (None, 'HEAD', REF[:12]):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.sync(write=True, ref=ref)
        self.assertEqual(self.snapshot(), self.originals)

    def test_boolean_number_wire_mismatches_reject_whole_batch(self):
        row = next(row for row in FIXTURE['aliases'] if row['proof']['source_file'] == 'openapi/zh/reddit.json')
        proof = row['proof']
        for field in ('x-aisa-pricing', 'example', 'default', 'enum', 'const'):
            with self.subTest(field=field):
                for filename, raw in self.originals.items():
                    (self.root / filename).write_bytes(raw)
                for filename, literal in ((proof['canonical_source_file'], True), (proof['source_file'], 1)):
                    path = self.root / filename
                    doc = json.loads(path.read_text())
                    op = next(op for route, method, op in operations(doc)
                              if (route, method) == (proof['public_path'], proof['method']))
                    value = {'description': literal}
                    op[field] = [value] if field == 'enum' else value
                    path.write_text(json.dumps(doc))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.sync(write=True)
                self.assertEqual(self.snapshot(), before)

    def test_non_json_numeric_constants_reject_whole_batch(self):
        path = self.root / 'openapi/zh/reddit.json'
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(token=token):
                doc = json.loads(self.originals[Path('openapi/zh/reddit.json')])
                raw = json.dumps(doc)
                path.write_text(raw[:-1] + ', "invalid": ' + token + '}')
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, 'non-JSON numeric constant'):
                    self.sync(write=True)
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()

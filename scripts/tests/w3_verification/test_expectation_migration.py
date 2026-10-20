"""Reject every drift outside the reviewed conservative W0 diagnostic change."""
import copy
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_fixture import ARCHIVE, catalog_root
import w0_expectation_migration as migration
from prepare_full_catalog import reconcile


class ExpectationMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proof = migration.load_migration()
        with tarfile.open(ARCHIVE) as archive:
            cls.previous_raw = archive.extractfile('expected/openapi/coverage.json').read()
        cls.previous = json.loads(cls.previous_raw)

    def candidate(self):
        evidence = migration.load_diagnostic_evidence(self.proof)
        return evidence['coverage'], evidence['pending']

    def test_exact_reviewed_transition_binds_real_immutable_source_and_facts(self):
        current, pending = self.candidate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'expected/openapi').mkdir(parents=True)
            (root / 'candidate/openapi').mkdir(parents=True)
            (root / 'expected/openapi/coverage.json').write_bytes(self.previous_raw)
            (root / 'candidate/openapi/pending.json').write_text(json.dumps(pending))
            result = migration.verify_migration(root / 'expected', root / 'candidate', current, catalog_root())
            self.assertEqual((result['removed_rows'], result['added_rows']), (178, 174))
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(len(result['retained_providers']), 9)
            (root / 'expected/openapi/coverage.json').write_bytes(self.previous_raw + b' ')
            with self.assertRaisesRegex(ValueError, 'immutable W0 oracle'):
                migration.verify_migration(root / 'expected', root / 'candidate', current, catalog_root())
            (root / 'expected/openapi/coverage.json').write_bytes(self.previous_raw)
            with self.assertRaisesRegex(ValueError, 'source/facts bindings'):
                migration.verify_migration(root / 'expected', root / 'candidate', current, root)
            policy = root / 'changed-policy.json'; policy.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'policy fixture'):
                migration.verify_migration(root / 'expected', root / 'candidate', current, catalog_root(), policy)

    def test_unknown_missing_promoted_or_changed_coverage_is_rejected(self):
        for variant in ('extra', 'missing', 'promoted', 'binding', 'reason', 'duplicate', 'runtime_method', 'unchanged_row_binding'):
            with self.subTest(variant=variant):
                current, pending = self.candidate()
                provider = self.proof['added_coverage'][0]['provider']
                selected = next(row for row in current['providers'][provider]
                                if row == self.proof['added_coverage'][0]['row'])
                if variant == 'extra':
                    extra = copy.deepcopy(selected); extra['path'] += '/unreviewed'
                    current['providers'][provider].append(extra)
                elif variant == 'missing': current['providers'][provider].remove(selected)
                elif variant == 'promoted': selected['status'] = 'composed'
                elif variant == 'binding': selected['source_binding_hash'] = 'sha256:' + 'a' * 64
                elif variant == 'reason': selected['reason'] = 'unreviewed failure'
                elif variant == 'duplicate': current['providers'][provider].append(copy.deepcopy(selected))
                elif variant == 'unchanged_row_binding':
                    current['providers']['agentmail'][0]['source_binding_hash'] = 'sha256:' + 'f' * 64
                else: selected['method'] = 'ANY' if selected['method'] != 'ANY' else 'GET'
                with self.assertRaises(ValueError):
                    migration.verify_transition(self.previous, current, pending, self.proof)

    def test_missing_extra_changed_or_unrelated_retention_root_is_rejected(self):
        for variant in ('missing', 'extra', 'reason', 'retention', 'other_provider', 'unrelated_pending'):
            with self.subTest(variant=variant):
                current, pending = self.candidate()
                rows = pending['providers']['apollo']
                if variant == 'missing': rows.pop(0)
                elif variant == 'extra': rows.append(copy.deepcopy(rows[0]))
                elif variant == 'reason': rows[0]['reason'] += ',unreviewed'
                elif variant == 'retention': rows[-1]['reason'] = 'ignored identity failure'
                elif variant == 'other_provider': pending['providers']['another'] = [copy.deepcopy(rows[-1])]
                else:
                    other = next(entries for provider, entries in pending['providers'].items()
                                 if provider not in self.proof['provider_pending'] and entries)
                    other[0]['reason'] = 'unreviewed change outside retained providers'
                with self.assertRaises(ValueError):
                    migration.verify_transition(self.previous, current, pending, self.proof)

    def test_fixture_bytes_cannot_be_implicitly_refreshed(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / 'changed.json'
            changed.write_bytes(migration.FIXTURE.read_bytes() + b' ')
            with patch.object(migration, 'FIXTURE', changed), self.assertRaisesRegex(ValueError, 'migration hash'):
                migration.load_migration()

    def test_old_optimistic_statuses_cannot_disable_stricter_expectation(self):
        _, pending = self.candidate()
        with self.assertRaisesRegex(ValueError, 'coverage transition'):
            migration.verify_transition(self.previous, self.previous, pending, self.proof)

    def test_operation_identities_and_execution_metadata_remain_mandatory(self):
        current, pending = self.candidate()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('expected', 'candidate'):
                (root / name / 'openapi').mkdir(parents=True)
            (root / 'expected/openapi/coverage.json').write_bytes(self.previous_raw)
            (root / 'candidate/openapi/pending.json').write_text(json.dumps(pending))
            document = {'info': {'x-aisa-document': {'composer_version': 'fixture'}},
                        'paths': {'/retained': {'get': {'operationId': 'retained',
                                    'x-aisa-pricing': {'price': 1}}}}}
            (root / 'expected/openapi/fixture.json').write_text(json.dumps(document))
            for variant in ('unchanged', 'identity', 'method', 'pricing', 'query', 'status'):
                changed = copy.deepcopy(document)
                operation = changed['paths']['/retained']['get']
                if variant == 'identity': operation['operationId'] = 'changed'
                elif variant == 'method': changed['paths']['/retained']['post'] = changed['paths']['/retained'].pop('get')
                elif variant == 'pricing': operation['x-aisa-pricing']['price'] = 2
                elif variant == 'query': operation['x-aisa-query-policy'] = {'request_wins': False}
                elif variant == 'status': operation['x-aisa-status'] = 'enabled'
                (root / 'candidate/openapi/fixture.json').write_text(json.dumps(changed))
                with self.subTest(variant=variant):
                    result = reconcile(root / 'expected', root / 'candidate', current, catalog_root())
                    self.assertEqual(result['status'], 'passed' if variant == 'unchanged' else 'failed')

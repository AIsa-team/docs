import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).parent)]
import canonical_formal as formal
import formal_assessment as shape
import publication_origin as origin
from export_contract_publication import prepare, canonical, retained_publication
from schema_input_bundle import REVIEWED_BASELINE, REBINDING_PATH
import test_contract_publication as fixtures


def canonical_report(report, files=None):
    report = copy.deepcopy(report)
    report.pop('composed_candidate', None)
    report.update(evaluation=shape.CANONICAL, scope=shape.FORMAL_SCOPE, baseline_ref=REVIEWED_BASELINE)
    artifact = report['publication_artifact']
    if files is not None:
        artifact['files_sha256'] = files
    native = {name[8:-5]: value for name, value in artifact['files_sha256'].items()
              if name.startswith('openapi/') and name.count('/') == 1 and name.endswith('.json')}
    artifact['files_sha256']['openapi/openapi.json'] = 'a' * 64
    artifact.update(assessment_scope=shape.ARTIFACT_SCOPE, published_ref='b' * 40)
    inputs = {'schema_version': 1, 'status': 'passed', 'scope': shape.INPUT_SCOPE,
        'compiler_inputs': {'protocol_version': 'aisa-runtime-canonical-v1', 'docs_ref': 'd' * 40,
            'bundle_manifest_sha256': 'e' * 64, 'composer_revision': 'f' * 40, 'source_manifest_sha256': 'a' * 64},
        'source_formal_provenance': {'expected_docs_ref': 'd' * 40},
        'runtime': report['runtime'], 'runtime_acquisition_sha256': report['runtime_acquisition_sha256'],
        'canonical_manifest_sha256': 'c' * 64, 'current_before_sha256': '1' * 64,
        'current_after_sha256': '2' * 64, 'source_pointer_sha256': '3' * 64, 'source_receipts_sha256': '4' * 64,
        'source_checked_at': report['source_governance']['checked_at'],
        'source_observations': copy.deepcopy(report['source_governance']['sources']),
        'frozen_input_files_sha256': {'openapi/registry.yaml': '5' * 64},
        'current_input_files_sha256': {'openapi/registry.yaml': '5' * 64}}
    report['canonical_runtime_import'] = {'status': 'passed', 'scope': shape.IMPORT_SCOPE,
        'inputs': inputs, 'native_sha256': native, 'aggregate_sha256': 'a' * 64,
        'assessed_base': 'b' * 40, 'previous_formal_ref': 'c' * 40,
        'registry_lineage': {'previous_formal_provenance': {'expected_docs_ref': 'c' * 40},
            'previous_registry_sha256': '6' * 64, 'fixed_registry_sha256': '5' * 64}}
    return report


class CanonicalShapeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PublicationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.report = canonical_report(self.fixture.report)
        self.receipt = json.loads((self.fixture.facts / 'acquisition-receipt.json').read_bytes())
        imported = self.report['canonical_runtime_import']
        rows = [{'name': 'contracts/native/' + name + '.json', 'sha256': digest}
                for name, digest in imported['native_sha256'].items()]
        rows += [{'name': 'contracts/openapi.json', 'sha256': imported['aggregate_sha256']},
                 {'name': 'contracts/manifest.json', 'sha256': imported['inputs']['canonical_manifest_sha256']},
                 {'name': 'contracts/readiness.json', 'sha256': '7' * 64}]
        self.receipt['manifest_files'] += rows
        self.receipt['canonical_validation'] = {'protocol_version': 'aisa-runtime-canonical-v1'}

    def test_both_modes_preserve_existing_origin_legacy_payment_boundary(self):
        legacy = copy.deepcopy(self.fixture.report)
        legacy.pop('payment_discovery')
        self.assertEqual(shape.validate_formal_assessment(legacy), shape.COMPOSED)
        self.assertEqual(shape.validate_formal_assessment(self.report, self.receipt), shape.CANONICAL)

    def test_unknown_mode_candidate_or_missing_mandatory_subgate_rejected(self):
        mutations = [lambda r: r.update(evaluation='anything'),
            lambda r: r.update(scope='candidate_only_not_accepted_by_production_formal_export'),
            lambda r: r.update(candidate_source_authorization={}),
            lambda r: r.update(composed_candidate={'status': 'passed'})]
        for key in ('canonical_runtime_import', 'publication_surfaces', 'payment_discovery'):
            mutations.append(lambda r, key=key: r.pop(key))
        mutations.append(lambda r: r['canonical_runtime_import'].pop('inputs'))
        for mutation in mutations:
            bad = copy.deepcopy(self.report); mutation(bad)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                shape.validate_formal_assessment(bad)

    def test_bindings_wrong_missing_extra_or_scalar_type_cannot_pass(self):
        def runtime_missing(r):
            r.pop('runtime'); r['canonical_runtime_import']['inputs'].pop('runtime')
        mutations = [runtime_missing,
            lambda r: r['runtime'].update(generation=True),
            lambda r: r['runtime'].update(generation=0),
            lambda r: r['runtime'].update(extra='unknown'),
            lambda r: r['canonical_runtime_import'].update(previous_formal_ref='d' * 40),
            lambda r: r['canonical_runtime_import'].update(assessed_base='a' * 40),
            lambda r: r['canonical_runtime_import']['inputs']['compiler_inputs'].update(extra='unknown'),
            lambda r: r['canonical_runtime_import']['inputs']['compiler_inputs'].update(docs_ref='b' * 40),
            lambda r: r['canonical_runtime_import']['inputs'].update(current_after_sha256='bad'),
            lambda r: r['canonical_runtime_import']['inputs'].update(runtime_acquisition_sha256='a' * 64),
            lambda r: r['canonical_runtime_import']['inputs'].update(source_checked_at='2099-01-01T00:00:00Z'),
            lambda r: r['canonical_runtime_import']['inputs'].update(source_observations={}),
            lambda r: r['canonical_runtime_import']['inputs']['current_input_files_sha256'].update({'unknown.json': 'd' * 64}),
            lambda r: r['canonical_runtime_import']['registry_lineage'].update(fixed_registry_sha256='a' * 64),
            lambda r: r['canonical_runtime_import']['native_sha256'].pop(next(iter(r['canonical_runtime_import']['native_sha256']))),
            lambda r: r['canonical_runtime_import'].update(aggregate_sha256='d' * 64)]
        for mutation in mutations:
            bad = copy.deepcopy(self.report); mutation(bad)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                shape.validate_formal_assessment(bad)

    def test_receipt_native_member_set_and_original_hashes_are_exact(self):
        for mutate in (lambda r: r['manifest_files'].pop(),
                       lambda r: r['manifest_files'].append(copy.deepcopy(r['manifest_files'][-1])),
                       lambda r: r['manifest_files'][-2].update(sha256='0' * 64),
                       lambda r: r.update(generation=999),
                       lambda r: r.pop('canonical_validation')):
            bad = copy.deepcopy(self.receipt); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                shape.validate_formal_assessment(self.report, bad)

    def test_reviewed_input_provenance_is_explicit_and_backwards_compatible(self):
        report = copy.deepcopy(self.report)
        inputs = report['canonical_runtime_import']['inputs']
        inputs['schema_version'] = 2
        inputs.pop('source_formal_provenance')
        inputs['input_context_sha256'] = inputs.pop('source_pointer_sha256')
        inputs['source_input_provenance'] = provenance = {
            'kind': 'reviewed_git_input', 'expected_docs_ref': inputs['compiler_inputs']['docs_ref'],
            'bundle_manifest_sha256': inputs['compiler_inputs']['bundle_manifest_sha256'],
            'historical_formal_ref': '6' * 40, 'input_context_sha256': inputs['input_context_sha256'],
            'input_source_receipts_sha256': '7' * 64}
        for path, key in (('docs/schema-inputs/context.json', 'input_context_sha256'),
                          ('docs/schema-inputs/source-receipts.json', 'input_source_receipts_sha256')):
            for field in ('frozen_input_files_sha256', 'current_input_files_sha256'):
                inputs[field][path] = provenance[key]
        self.assertEqual(shape.validate_formal_assessment(report, self.receipt), shape.CANONICAL)
        mutations = [lambda i: i.update(schema_version=1),
            lambda i: i.update(source_formal_provenance={'expected_docs_ref': 'd' * 40}),
            lambda i: i.update(source_pointer_sha256='1' * 64),
            lambda i: i['source_input_provenance'].update(kind='formal'),
            lambda i: i['source_input_provenance'].update(extra=True),
            lambda i: i['source_input_provenance'].update(expected_docs_ref='9' * 40),
            lambda i: i['source_input_provenance'].update(bundle_manifest_sha256='9' * 64),
            lambda i: i['source_input_provenance'].update(historical_formal_ref='main'),
            lambda i: i['source_input_provenance'].update(input_context_sha256='9' * 64),
            lambda i: i['current_input_files_sha256'].pop('docs/schema-inputs/context.json'),
            lambda i: i['frozen_input_files_sha256'].pop('docs/schema-inputs/source-receipts.json')]
        for mutate in mutations:
            bad = copy.deepcopy(report); mutate(bad['canonical_runtime_import']['inputs'])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                shape.validate_formal_assessment(bad, self.receipt)
        legacy = copy.deepcopy(self.report)
        legacy['canonical_runtime_import']['inputs']['source_input_provenance'] = provenance
        with self.assertRaises(ValueError): shape.validate_formal_assessment(legacy)

    def test_export_replays_before_touching_a_saved_pointer(self):
        previous = self.fixture.root / 'docs/publication/current.json'
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(b'last-good')
        with patch('canonical_formal.replay_formal_canonical', side_effect=ValueError('replay rejected')) as replay:
            with self.assertRaisesRegex(ValueError, 'replay rejected'):
                prepare(self.fixture.root, self.fixture.facts, canonical(self.report), self.fixture.now)
        replay.assert_called_once()
        self.assertEqual(previous.read_bytes(), b'last-good')

    def test_complete_replay_comparison_does_not_ignore_extra_or_typed_fields(self):
        with patch.object(formal, 'assess_formal_canonical', return_value=self.report):
            formal.replay_formal_canonical(self.fixture.root, self.fixture.facts, self.report)
            for bad in (dict(self.report, unreviewed=True), dict(self.report, unreviewed=1)):
                with self.assertRaisesRegex(ValueError, 'cannot be reproduced'):
                    formal.replay_formal_canonical(self.fixture.root, self.fixture.facts, bad)

    def prepare_real_graph(self):
        root = self.fixture.root
        (root / 'openapi/openapi.json').write_bytes(b'{"openapi":"3.1.0","paths":{}}')
        digest = origin.sha((root / 'openapi/openapi.json').read_bytes())
        self.report['publication_artifact']['files_sha256']['openapi/openapi.json'] = digest
        self.report['canonical_runtime_import']['aggregate_sha256'] = digest
        for row in self.receipt['manifest_files']:
            if row['name'] == 'contracts/openapi.json':
                row['sha256'] = digest
        receipt_raw = canonical(self.receipt)
        self.report['runtime_acquisition_sha256'] = origin.sha(receipt_raw)
        self.report['canonical_runtime_import']['inputs']['runtime_acquisition_sha256'] = origin.sha(receipt_raw)
        with patch.object(formal, 'replay_formal_canonical') as replay, \
             patch('export_contract_publication.acquired_input', return_value=(self.receipt, receipt_raw)):
            outputs = prepare(root, self.fixture.facts, canonical(self.report), self.fixture.now)
        replay.assert_called_once()
        return outputs

    def test_origin_accepts_exact_new_graph_but_not_receipt_or_scope_tampering(self):
        outputs = self.prepare_real_graph()
        root = self.fixture.root
        destination = root / 'docs/publication'; destination.mkdir(parents=True, exist_ok=True)
        for name, raw in outputs.items():
            (destination / name).write_bytes(raw)
        current = json.loads(outputs['current.json'])
        declaration = {'current_sha256': origin.sha(outputs['current.json']),
            'contract_release': current['contract_release'], 'assessed_base': 'b' * 40}
        self.assertEqual(origin.verify_graph(root, declaration,
            outputs['formal-contract-readiness.json'], self.fixture.now), current)
        report_path = destination / 'formal-contract-readiness.json'
        bad = copy.deepcopy(self.report); bad['scope'] = 'candidate_only_not_accepted_by_production_formal_export'
        report_path.write_bytes(canonical(bad))
        with self.assertRaisesRegex(ValueError, 'not a formal'):
            origin.verify_graph(root, declaration, report_path.read_bytes(), self.fixture.now)

    def test_new_mode_metadata_publication_keeps_first_contract_clock(self):
        root = self.fixture.root
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
        git('init', '-q'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
        git('add', '.'); git('commit', '-qm', 'base')
        first, contract = None, None
        for number in (1, 2):
            assessed = git('rev-parse', 'HEAD')
            self.report['publication_artifact']['published_ref'] = assessed
            self.report['canonical_runtime_import']['assessed_base'] = assessed
            if first:
                self.report['canonical_runtime_import']['previous_formal_ref'] = first
                self.report['canonical_runtime_import']['registry_lineage']['previous_formal_provenance']['expected_docs_ref'] = first
            outputs = self.prepare_real_graph()
            destination = root / 'docs/publication'; destination.mkdir(parents=True, exist_ok=True)
            if first:
                # Nested lineage changed, so conservative retention rejects reuse;
                # publishing an equivalent C must still preserve its first clock.
                self.assertIsNone(retained_publication(root, destination, outputs, self.fixture.now))
            for name, raw in outputs.items():
                (destination / name).write_bytes(raw)
            git('add', '.')
            recorded = origin.record(root, str(number), 1, self.fixture.now + timedelta(seconds=number))
            git('add', origin.ORIGIN); git('commit', '-qm', 'publication ' + str(number))
            if first is None:
                first, contract = git('rev-parse', 'HEAD'), recorded['contract_release']
            self.assertEqual(recorded['contract_release'], contract)
            self.assertEqual(origin.first_contract_ref(root, contract), first)


class FormalBaseTests(unittest.TestCase):
    def test_reconstructs_assessed_git_inputs_not_modified_projected_registry(self):
        fixture = fixtures.PublicationTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        root = fixture.root
        (root / 'openapi/registry.yaml').write_text('providers: {}\n')
        (root / REBINDING_PATH).parent.mkdir(parents=True, exist_ok=True)
        (root / REBINDING_PATH).write_text('{}')
        from schema_input_bundle import INPUT_CONTEXT_PATH, INPUT_RECEIPTS_PATH
        evidence = {INPUT_CONTEXT_PATH: b'{"recipe":"original fixture bytes"}',
                    INPUT_RECEIPTS_PATH: b'{"receipt":"original fixture clock"}'}
        for name, raw in evidence.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(raw)
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
        git('init', '-q'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
        git('add', '.'); git('commit', '-qm', 'assessed base')
        head = git('rev-parse', 'HEAD')
        (root / 'openapi/registry.yaml').write_text('providers: {derived: {}}\n')
        report = canonical_report(fixture.report)
        report['candidate_source_authorization'] = {}
        def assess(repository, view, projected, acquired, **kwargs):
            self.assertEqual((view / 'openapi/registry.yaml').read_text(), 'providers: {}\n')
            self.assertEqual(projected, root)
            self.assertEqual(kwargs['previous_ref'], head)
            for name, raw in evidence.items():
                self.assertEqual((view / name).read_bytes(), raw)
            return copy.deepcopy(report)
        with patch.object(formal, 'assess_canonical_candidate', side_effect=assess), \
             patch.object(formal, 'validate_formal_assessment'):
            result = formal.assess_formal_canonical(root, fixture.facts,
                previous_formal_ref=head, assessed_base=head, checked_at=fixture.now)
            self.assertEqual(result['publication_artifact']['published_ref'], head)
            self.assertEqual(result['canonical_runtime_import']['previous_formal_ref'], head)
            self.assertNotIn('candidate_source_authorization', result)
            git('commit', '--allow-empty', '-qm', 'concurrent main update')
            with self.assertRaisesRegex(ValueError, 'current Git HEAD'):
                formal.assess_formal_canonical(root, fixture.facts,
                    previous_formal_ref=head, assessed_base=head)


if __name__ == '__main__':
    unittest.main()

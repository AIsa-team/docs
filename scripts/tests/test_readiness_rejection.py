import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import internal_publication_snapshot as adapter
import readiness_rejection as rejection
import shadow_compile_bundle as core
from schema_input_bundle import canonical
from test_runtime_contracts import facts
from test_contract_readiness import index

FIXTURE = Path(__file__).parent / 'fixtures/readiness-rejection-v1.json'


class RejectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_bytes())
        self.report, self.summary = self.fixture['report'], self.fixture['summary']

    def diagnostic(self):
        return rejection.complete_diagnostic(self.report, self.summary)

    def test_cross_language_fixture_and_private_frame_whitelist(self):
        self.assertEqual(self.diagnostic(), self.fixture['diagnostic'])
        proof = rejection.snapshot_proof(self.diagnostic(), self.fixture['bundle'], self.fixture['runtime'])
        raw = canonical(proof)
        self.assertEqual(proof, self.fixture['proof'])
        self.assertEqual(raw, FIXTURE.with_name('readiness-rejection-v1-frame.json').read_bytes())
        self.assertLessEqual(len(raw), 4096)
        for private in ('x-example', '/apis/v1', 'first', 'second', 'request_cost_drivers'):
            self.assertNotIn(private.encode(), raw)
        self.assertNotIn('expected_manifest_sha256', proof)
        self.assertNotIn('original_source_snapshot_sha256', proof)

    def test_only_declared_multisets_sort_and_multiplicity_is_preserved(self):
        row = self.report['providers']['example']['new_pending'][0]
        other = {**row, 'operation_id': 'another'}
        self.report['providers']['example']['new_pending'].append(other)
        before = self.diagnostic()
        self.report['providers']['example']['new_pending'].reverse()
        self.assertEqual(self.diagnostic(), before)
        self.report['providers']['example']['new_pending'].append(other)
        self.assertNotEqual(self.diagnostic()['diagnostic_sha256'], before['diagnostic_sha256'])

    def test_nested_metadata_order_and_error_tuple_order_change_digest(self):
        before = self.diagnostic()['diagnostic_sha256']
        self.report['providers']['example']['new_pending'][0]['runtime_binding']['pricing']['request_cost_drivers'].reverse()
        self.assertNotEqual(self.diagnostic()['diagnostic_sha256'], before)
        self.report['global_errors'] = [{'code': 'duplicate_operation_id', 'previous': ['p', '/path', 'GET']}]
        before = self.diagnostic()['diagnostic_sha256']
        self.report['global_errors'][0]['previous'].reverse()
        self.assertNotEqual(self.diagnostic()['diagnostic_sha256'], before)

    def test_all_closure_and_exact_identity_values_affect_digest(self):
        original = self.diagnostic()['diagnostic_sha256']
        for mode in ('global', 'missing', 'blocked', 'policy', 'reason', 'method', 'operation', 'path', 'summary'):
            with self.subTest(mode=mode):
                self.setUp()
                pending = self.report['providers']['example']['new_pending'][0]
                if mode == 'global': self.report['global_errors'].append({'code': 'missing_operation_id'})
                if mode == 'missing': self.report['missing_inputs'].append('provider_inputs')
                if mode == 'blocked': self.report['blocked_providers'].append('example')
                if mode == 'policy': self.report['deferred_definitions'] = {
                    'policy_id': 'fixture', 'path': 'fixture.json', 'sha256': 'a' * 64,
                    'scope': {'request': 0, 'response': 0}}
                if mode == 'reason': pending['reason'] += ', another header'
                if mode == 'method': pending['method'] = 'POST'
                if mode == 'operation': pending['operation_id'] += '_changed'
                if mode == 'path': pending['path'] += '/changed'
                if mode == 'summary': self.summary['example']['blocked'] += ': changed'
                self.assertNotEqual(self.diagnostic()['diagnostic_sha256'], original)

    def test_unknown_or_partial_report_never_creates_typed_rejection(self):
        for mode in ('top', 'provider', 'pending', 'reason', 'error', 'missing-response', 'null', 'nonfinite', 'summary', 'bool'):
            with self.subTest(mode=mode):
                self.setUp()
                provider = self.report['providers']['example']
                if mode == 'top': self.report['unknown'] = True
                if mode == 'provider': provider['unknown'] = []
                if mode == 'pending': provider['new_pending'][0]['unknown'] = True
                if mode == 'reason': provider['new_pending'][0]['reason_code'] = 'unknown'
                if mode == 'error': provider['errors'].append({'code': 'unknown'})
                if mode == 'missing-response': del provider['new_response_pending']
                if mode == 'null': self.report['global_errors'] = None
                if mode == 'nonfinite': provider['new_pending'][0]['runtime_binding']['price'] = float('nan')
                if mode == 'summary': self.summary['example']['unknown'] = True
                if mode == 'bool': self.report['schema_version'] = True
                with self.assertRaises(ValueError) as caught:
                    self.diagnostic()
                self.assertNotIsInstance(caught.exception, rejection.ReadinessRejected)

    def test_unclassified_is_descriptive_and_preserves_full_collateral_reason(self):
        pending = self.report['providers']['example']['new_pending'][0]
        pending['reason_code'] = 'unclassified_contract_error'
        before = self.diagnostic()['diagnostic_sha256']
        pending['reason'] = 'published identity changed or disappeared: fixture'
        self.assertNotEqual(self.diagnostic()['diagnostic_sha256'], before)
        self.assertNotIn('root_count', self.diagnostic())

    def test_policy_metadata_and_runtime_metadata_shapes_fail_closed(self):
        for bad in (None, 42, 'unexpected', [], {'unknown_field': True},
                    {'policy_id': 'p', 'path': 'p', 'sha256': 'a' * 64,
                     'scope': {'request': True, 'response': 53}}):
            with self.subTest(policy=bad):
                self.report['deferred_definitions'] = bad
                with self.assertRaises(ValueError):
                    self.diagnostic()
        del self.report['deferred_definitions']
        pending = self.report['providers']['example']['new_pending'][0]
        for field, bad in (('pricing', []), ('revision', 'unexpected'), ('provider', {})):
            with self.subTest(field=field):
                previous = copy.deepcopy(pending['runtime_binding'])
                pending['runtime_binding'][field] = bad
                with self.assertRaises(ValueError):
                    self.diagnostic()
                pending['runtime_binding'] = previous

    def test_actual_core_stage_completion_rejects_before_any_output(self):
        bundle = SimpleNamespace(contents={'baseline/openapi/coverage.json': b'{"providers":{}}'}, history=None)
        def stage(*args, **kwargs):
            kwargs['readiness_context']['report'] = self.report
            return {}, self.summary
        with tempfile.TemporaryDirectory() as temp, patch.object(core, 'published_documents', return_value={}), \
                patch.object(core, 'stage', side_effect=stage), patch.object(core, 'build_unified_spec') as aggregate:
            output = Path(temp) / 'output'
            with self.assertRaises(rejection.ReadinessRejected):
                core.compile_verified_inputs(bundle, {}, {}, output=output)
            self.assertFalse(output.exists())
            aggregate.assert_not_called()

    def test_stage_io_parse_and_cleanup_failures_are_not_readiness_proof(self):
        bundle = SimpleNamespace(contents={'baseline/openapi/coverage.json': b'{"providers":{}}'}, history=None)
        for exc in (OSError('PRIVATE'), ValueError('PRIVATE'), ImportError('PRIVATE'), TimeoutError('PRIVATE')):
            with self.subTest(exc=type(exc).__name__), tempfile.TemporaryDirectory() as temp, \
                    patch.object(core, 'published_documents', return_value={}), \
                    patch.object(core, 'stage', side_effect=exc):
                with self.assertRaises(type(exc)) as caught:
                    core.compile_verified_inputs(bundle, {}, {}, output=Path(temp) / 'out')
                self.assertNotIsInstance(caught.exception, rejection.ReadinessRejected)

    def test_real_stage_positive_artifact_and_uri_rejection(self):
        fact = facts()
        public_path = '/apis/v1/similarweb/test'
        fact['paths'][public_path]['post']['responses']['200']['content'] = {
            'application/json': {'schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}}}
        runtime_index = index([public_path])
        runtime_index['providers'][0]['id'] = 'similarweb'
        runtime_index['coverage']['projected_endpoints'][0]['provider'] = 'similarweb'
        bundle = SimpleNamespace(contents={
            'baseline/openapi/coverage.json': canonical({'providers': {}}),
            'input/openapi/registry.yaml': b'auto_register: false\nproviders:\n  similarweb: {}\n'},
            history=None, validation={})
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'ready'
            result = core.compile_verified_inputs(bundle, {
                'similarweb.json': canonical(fact), 'index.json': canonical(runtime_index)}, {}, output=output)
            self.assertEqual(result['status'], 'passed')
            self.assertTrue((output / 'manifest.json').is_file())
            self.assertEqual(json.loads((output / 'readiness.json').read_bytes())['status'], 'passed')
            changed_path = public_path + '/{id}'
            fact['paths'][changed_path] = fact['paths'].pop(public_path)
            runtime_index['coverage']['projected_endpoints'][0]['path'] = changed_path
            rejected = Path(temp) / 'rejected'
            with self.assertRaises(rejection.ReadinessRejected) as caught:
                core.compile_verified_inputs(bundle, {
                    'similarweb.json': canonical(fact), 'index.json': canonical(runtime_index)}, {}, output=rejected)
            self.assertEqual(caught.exception.diagnostic['provider_count'], 1)
            self.assertFalse(rejected.exists())

    def test_cleanup_failure_masks_readiness_error_without_any_proof(self):
        real_temporary = tempfile.TemporaryDirectory
        class CleanupFails:
            def __init__(self, **kwargs):
                self.temp = real_temporary(**kwargs)
            def __enter__(self):
                return self.temp.__enter__()
            def __exit__(self, *args):
                self.temp.__exit__(*args)
                raise OSError('PRIVATE cleanup')
        bundle = SimpleNamespace(contents={'baseline/openapi/coverage.json': b'{"providers":{}}'}, history=None)
        def stage(*args, **kwargs):
            kwargs['readiness_context']['report'] = self.report
            return {}, self.summary
        with real_temporary() as temp, patch.object(core, 'published_documents', return_value={}), \
                patch.object(core, 'stage', side_effect=stage), \
                patch.object(core.tempfile, 'TemporaryDirectory', CleanupFails):
            with self.assertRaises(OSError) as caught:
                core.compile_verified_inputs(bundle, {}, {}, output=Path(temp) / 'out')
            self.assertNotIsInstance(caught.exception, rejection.ReadinessRejected)
            self.assertFalse((Path(temp) / 'out').exists())

    def test_private_cli_exit_and_no_private_exception_output(self):
        args = ['--bundle', 'b', '--bundle-sha256', 'a' * 64, '--docs-ref', 'b' * 40,
                '--snapshot', 's', '--snapshot-sha256', 'c' * 64, '--generation', '917',
                '--source-digest', 'd' * 64, '--compiler-revision', 'e' * 40, '--output', 'out']
        for exc, code in ((rejection.SnapshotReadinessRejected(self.fixture['proof']), 78),
                          (ValueError('PRIVATE'), 1), (OSError('PRIVATE'), 1)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(code=code), patch.object(adapter, 'compile_snapshot', side_effect=exc), \
                    redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
                adapter.main(args)
            self.assertEqual(caught.exception.code, code)
            if code == 78:
                self.assertEqual(stdout.getvalue().encode(), canonical(self.fixture['proof']))
                self.assertEqual(stderr.getvalue(), '')
            else:
                self.assertEqual(stdout.getvalue(), '')
            self.assertNotIn('PRIVATE', stdout.getvalue() + stderr.getvalue())


if __name__ == '__main__':
    unittest.main()

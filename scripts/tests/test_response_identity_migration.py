"""Synthetic v2 identity values exercise the finite existing-debt transition.

These fixtures do not authorize actual public response evidence; production loading
must separately authenticate the complete rebinding record's exact fixed SHA.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
from deferred_definitions import (_apply_response_identity_v2, canonical_key,
                                  load_deferred_definitions, POLICY_SHA256, POLICY_PATH, REBINDING_PATH,
                                  RESPONSE_IDENTITY_MIGRATION_SHA256, FRED_MIGRATION_SHA256,
                                  validate_report_deferrals, RELAYER_DEFERRAL,
                                  FASTMOSS_DEFERRAL)
from formal_assessment import CANONICAL

ROOT = Path(__file__).resolve().parents[2]


class ResponseIdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_deferred_definitions(ROOT)
        # Build from the logical old keys only, even after ROOT activates v2.
        self.rows = []
        for value in sorted(self.policy.keys):
            provider, kind, old = json.loads(value)
            if kind == 'response':
                self.rows.append(self.binding(provider, old, 'deferred_enabled_response'))
        # The reviewed disabled baseline is the exact pair recorded by the
        # authenticated migration, not every response gap whose runtime status
        # is disabled today: a publication may disable further operations later
        # (their debt is reported as disabled_response_pending, not migrated).
        record = json.loads((ROOT / REBINDING_PATH).read_text())['response_identity_migration']
        for row in record['bindings']:
            if row['scope'] == 'reviewed_disabled_response_baseline':
                self.rows.append(self.binding(row['provider'], list(row['old_gate_identity']), 'reviewed_disabled_response_baseline'))
        self.migration = {
            'schema_version': 1, 'original_policy_sha256': POLICY_SHA256,
            'baseline_ref': '78ef376841ead8cde10a79651958790be5a0531c',
            'baseline_sha256': 'e0ef2fdf591d0f6b400d6bf1107bf32a31cc1a3453784dc3962cb66a15d16dbd',
            'deferred_response_count': sum(r['scope'] == 'deferred_enabled_response' for r in self.rows),
            'baseline_response_count': sum(r['scope'] == 'reviewed_disabled_response_baseline' for r in self.rows),
            'bindings': self.rows,
        }
        self.policy.response_v2_keys = frozenset()
        self.policy.response_baseline_rebindings = {}

    def test_loader_authenticates_third_exact_record_and_keeps_prior_inputs_compatible(self):
        raw = (ROOT / REBINDING_PATH).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), RESPONSE_IDENTITY_MIGRATION_SHA256)
        current = load_deferred_definitions(ROOT)
        self.assertEqual(len(current.response_v2_keys), 53)
        self.assertEqual(len(current.response_baseline_rebindings), 2)
        self.assertEqual(len(current.keys), 60 + len(RELAYER_DEFERRAL["items"]) + len(FASTMOSS_DEFERRAL["items"]))  # CR003 + CR004 + CR005
        self.assertEqual(current.metadata['scope'], {'request': 10, 'response': 50})
        self.assertEqual(current.metadata['effective_scope'], {'request': 7, 'response': 53})
        prior = json.loads(raw)
        prior.pop('response_identity_migration')
        prior_raw = (json.dumps(prior, indent=2, ensure_ascii=False) + '\n').encode()
        self.assertEqual(hashlib.sha256(prior_raw).hexdigest(), FRED_MIGRATION_SHA256)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, content in ((POLICY_PATH, (ROOT / POLICY_PATH).read_bytes()),
                                  (REBINDING_PATH, prior_raw)):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            old = load_deferred_definitions(root)
            self.assertEqual(old.keys, current.keys)
            self.assertFalse(old.response_v2_keys)
            self.assertFalse(old.response_baseline_rebindings)
            for changed in (raw + b' ', raw.replace(b'response-v2', b'response-v3', 1)):
                (root / REBINDING_PATH).write_bytes(changed)
                with self.assertRaisesRegex(ValueError, 'reviewed exact bytes'):
                    load_deferred_definitions(root)

    @staticmethod
    def binding(provider, old, scope):
        new = copy.deepcopy(old)
        new[4] = 'response-v2'
        for index in (5, 6):
            new[index] = 'sha256:' + hashlib.sha256(f'synthetic-v2-{provider}-{old}-{index}'.encode()).hexdigest()
        return {'provider': provider, 'scope': scope, 'old_gate_identity': old, 'new_gate_identity': new}

    def test_same_logical_response_set_legacy_exact_and_new_exact_only(self):
        before = self.policy.keys
        for row in self.rows:
            self.assertFalse(self.policy.matches(row['provider'], 'response', row['new_gate_identity']))
        _apply_response_identity_v2(self.policy, self.migration)
        self.assertEqual(self.policy.keys, before)
        self.assertEqual(len(before), 60 + len(RELAYER_DEFERRAL["items"]) + len(FASTMOSS_DEFERRAL["items"]))  # CR003 + CR004 + CR005
        for row in self.rows:
            provider, old, new = row['provider'], row['old_gate_identity'], row['new_gate_identity']
            if old[-1] == 'enabled':
                self.assertTrue(self.policy.matches(provider, 'response', old))
                self.assertTrue(self.policy.matches(provider, 'response', new))
                self.assertFalse(self.policy.matches(provider, 'request', new))
                self.assertFalse(self.policy.matches(provider + '-other', 'response', new))
                for index in range(len(new)):
                    changed = copy.deepcopy(new)
                    changed[index] = ['201'] if isinstance(changed[index], list) else 'changed'
                    self.assertFalse(self.policy.matches(provider, 'response', changed), (provider, index))

    def test_disabled_baseline_requires_independently_supplied_original_key(self):
        _apply_response_identity_v2(self.policy, self.migration)
        for row in self.rows:
            if row['scope'] != 'reviewed_disabled_response_baseline':
                continue
            provider, old, new = row['provider'], row['old_gate_identity'], row['new_gate_identity']
            self.assertTrue(self.policy.response_baseline_matches(provider, new, [old]))
            self.assertFalse(self.policy.response_baseline_matches(provider, new, []))
            self.assertFalse(self.policy.response_baseline_matches(provider + '-other', new, [old]))
            self.assertFalse(self.policy.matches(provider, 'response', new))

    def test_exporter_cannot_double_count_legacy_and_v2_identity_for_one_response(self):
        _apply_response_identity_v2(self.policy, self.migration)
        selected = next(row for row in self.rows if row['scope'] == 'deferred_enabled_response')
        old, new = selected['old_gate_identity'], selected['new_gate_identity']
        row = dict(zip(('operation_id', 'path', 'method', 'reason_code', 'binding_hash',
                        'source_binding_hash', 'response_source_binding_hash', 'response_binding_hash',
                        'statuses', 'runtime_status'), old))
        v2 = {**row, 'response_runtime_binding_hash': new[5], 'response_source_binding_hash': new[6]}
        result = {'deferred_response_pending': [row]}
        report = {'evaluation': CANONICAL, 'deferred_definitions': self.policy.metadata,
                  'providers': {selected['provider']: result}}
        with patch('deferred_definitions.load_deferred_definitions', return_value=self.policy):
            validate_report_deferrals(ROOT, report)
            result['deferred_response_pending'] = [v2]
            validate_report_deferrals(ROOT, report)
            result['deferred_response_pending'] = [row, v2]
            with self.assertRaisesRegex(ValueError, 'duplicate deferral'):
                validate_report_deferrals(ROOT, report)

    def test_no_additions_removals_duplicates_or_changed_protected_response(self):
        candidates = []
        value = copy.deepcopy(self.migration); value['bindings'].pop(0); candidates.append(value)
        value = copy.deepcopy(self.migration); value['bindings'].append(copy.deepcopy(value['bindings'][0])); candidates.append(value)
        for index in (0, 1, 2, 3, 4, 7, 8, 9):
            value = copy.deepcopy(self.migration)
            new = value['bindings'][0]['new_gate_identity']
            new[index] = ['201'] if isinstance(new[index], list) else 'changed'
            candidates.append(value)
        value = copy.deepcopy(self.migration); value['bindings'][0]['provider'] = 'new-provider'; candidates.append(value)
        value = copy.deepcopy(self.migration); value['original_policy_sha256'] = '0' * 64; candidates.append(value)
        value = copy.deepcopy(self.migration); value['deferred_response_count'] += 1; candidates.append(value)
        value = copy.deepcopy(self.migration); value['bindings'][0]['new_gate_identity'][5] = 'bad'; candidates.append(value)
        for index, candidate in enumerate(candidates):
            with self.subTest(index=index), self.assertRaises(ValueError):
                _apply_response_identity_v2(self.policy, candidate)
        self.assertFalse(self.policy.response_v2_keys)


if __name__ == '__main__':
    unittest.main()

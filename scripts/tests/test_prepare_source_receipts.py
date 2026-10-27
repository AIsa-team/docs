import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_source_receipts import merge_evidence, prepare
from source_governance import acquisition_receipt, initial_policy, receipt_key, source_report
from contract_change_scope import requires_artifact_check


class ReceiptPreparationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 5, tzinfo=timezone.utc)
        self.source = initial_policy({'kind': 'provider_openapi', 'url': 'https://example.org/api.json',
                                      'content_hash': 'sha256:' + 'a' * 64})
        self.key = receipt_key(self.source)
        self.receipt = acquisition_receipt(self.source, self.now - timedelta(hours=1))
        self.packet = {'schema_version': 1, 'receipts': {self.key: self.receipt}, 'attempts': {}}

    def report(self, packet):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'openapi/upstream').mkdir(parents=True)
            (root / 'openapi/upstream/source.json').write_text(json.dumps({'info': {'x-aisa-source': self.source}}))
            return source_report(root, packet['receipts'], self.now, packet['attempts'])

    def test_newer_failed_fetch_survives_and_blocks_even_with_reviewed_seed(self):
        cache = {'schema_version': 1, 'attempts': {self.key: {
            'checked_at': self.now.isoformat(), 'status': 'fetch_failed'}}}
        for packets in ((self.packet, cache), (cache, self.packet)):
            merged = merge_evidence(*packets)
            self.assertEqual(merged['receipts'][self.key], self.receipt)
            self.assertEqual(self.report(merged)['status'], 'failed')

    def test_newer_actual_success_supersedes_failure_without_refreshing_seed(self):
        prior = self.now - timedelta(minutes=20)
        cache = {'schema_version': 1,
                 'receipts': {self.key: acquisition_receipt(self.source, self.now)},
                 'attempts': {self.key: {'checked_at': prior.isoformat(), 'status': 'fetch_failed'}}}
        merged = merge_evidence(cache, self.packet)
        self.assertEqual(merged['receipts'][self.key], cache['receipts'][self.key])
        self.assertEqual(self.report(merged)['status'], 'passed')
        self.assertEqual(self.packet['receipts'][self.key], self.receipt)

    def test_stale_and_wrong_source_receipts_never_become_current(self):
        stale = copy.deepcopy(self.packet)
        stale['receipts'][self.key] = acquisition_receipt(self.source, self.now - timedelta(days=2))
        self.assertEqual(self.report(merge_evidence(stale))['status'], 'failed')
        self.source['content_hash'] = 'sha256:' + 'b' * 64
        self.assertEqual(self.report(merge_evidence(self.packet))['status'], 'not_assessed')

    def test_malformed_or_equal_time_conflicting_input_rejects_without_cache_write(self):
        bad_packets = [{'schema_version': 2}, {'schema_version': 1, 'receipts': []}]
        conflict = copy.deepcopy(self.packet)
        conflict['receipts'][self.key]['reviewer'] = 'not the same observation'
        bad_packets.append(conflict)
        bad = copy.deepcopy(self.packet)
        bad['receipts'][self.key]['last_successful_review_at'] = 'no timestamp'
        bad_packets.append(bad)
        bad = copy.deepcopy(self.packet)
        bad['receipts'][self.key]['source_hash'] = 'wrong hash'
        bad_packets.append(bad)
        for bad in bad_packets:
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temp:
                reviewed, cache = Path(temp) / 'reviewed.json', Path(temp) / 'cache.json'
                reviewed.write_text(json.dumps(self.packet)); cache.write_text(json.dumps(bad))
                original = cache.read_bytes()
                with self.assertRaises(ValueError):
                    prepare(reviewed, cache)
                self.assertEqual(cache.read_bytes(), original)

    def test_cold_cache_reproduces_all_reviewed_receipts_and_is_idempotent(self):
        root = Path(__file__).resolve().parents[2]
        reviewed = root / 'docs/current-source-review-20261009/merged-source-reviews.json'
        expected = json.loads(reviewed.read_text())
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / 'nested/cache.json'
            self.assertEqual(prepare(reviewed, cache), expected)
            first = cache.read_bytes()
            self.assertEqual(prepare(reviewed, cache), expected)
            self.assertEqual(cache.read_bytes(), first)

    def test_all_workflows_prepare_receipts_before_consuming_and_receipt_changes_require_gate(self):
        root = Path(__file__).resolve().parents[2]
        for name, job, consumer in [('test-runtime-contracts.yml', 'artifact-contracts', 'Check actual candidate readiness'),
                                    ('pull-openapi.yml', 'compose', 'Stage contracts'),
                                    ('refresh-upstream.yml', 'refresh', 'Stage source updates and comparison evidence')]:
            workflow = yaml.safe_load((root / '.github/workflows' / name).read_text())
            steps = workflow['jobs'][job]['steps']
            prepare_step = next(i for i, step in enumerate(steps) if 'prepare_source_receipts.py' in step.get('run', ''))
            consume_step = next(i for i, step in enumerate(steps) if step.get('name') == consumer)
            self.assertLess(prepare_step, consume_step)
            self.assertNotIn('continue-on-error', steps[prepare_step])
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        triggers = workflow.get('on', workflow.get(True))
        for path in ('docs/current-source-review-20261009/merged-source-reviews.json',
                     'docs/response-source-review-receipts.json'):
            self.assertTrue(requires_artifact_check([path]))
        for event in ('push', 'pull_request'):
            self.assertIn('docs/current-source-review-20261009/**', triggers[event]['paths'])
            self.assertIn('docs/response-source-review-receipts.json', triggers[event]['paths'])


if __name__ == '__main__':
    unittest.main()

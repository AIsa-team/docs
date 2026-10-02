from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pull_openapi import main
from source_governance import initial_policy, acquisition_receipt, receipt_key, observation


class PullAcquisitionEvidenceTests(unittest.TestCase):
    def run_blocked_candidate(self, write):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = initial_policy({'kind': 'provider_openapi', 'url': 'https://official.example.invalid/spec',
                                     'content_hash': 'sha256:acquired'})
            now = datetime.now(timezone.utc)
            key = receipt_key(source)
            evidence = {'schema_version': 1, 'receipts': {key: acquisition_receipt(source, now)},
                        'attempts': {key: {'checked_at': now.isoformat(), 'status': 'confirmed'}}}
            candidate = root / 'openapi/provider.json'
            receipt = root / '.cache/source-reviews.json'
            def stage(*args):
                args[-1]['report'] = {'status': 'not_assessed', 'global_errors': [],
                                     'missing_inputs': ['independently approved baseline'], 'providers': {}}
                return {candidate: '{}', receipt: json.dumps(evidence)}, {}
            argv = ['pull', '--root', str(root)] + (['--write'] if write else [])
            with patch('pull_openapi.stage', side_effect=stage), patch.object(sys, 'argv', argv), patch('builtins.print'):
                result = main()
            self.assertEqual(3, result)
            self.assertFalse(candidate.exists())
            self.assertEqual(write, receipt.exists())
            if write:
                saved = json.loads(receipt.read_text())
                self.assertEqual(evidence, saved)
                self.assertEqual('fresh', observation(source, saved['receipts'], now)['freshness'])

    def test_blocked_publication_retains_only_real_acquisition_evidence(self):
        self.run_blocked_candidate(True)

    def test_dry_run_does_not_persist_acquisition_evidence_or_candidate(self):
        self.run_blocked_candidate(False)


if __name__ == '__main__':
    unittest.main()

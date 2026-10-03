"""Keep offline policy proposals separate from source reviews and approvals."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from prepare_full_catalog import ARCHIVE_SHA256, apply_policy_fixture


class PolicyFixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'openapi/upstream/source.json'
        self.path.parent.mkdir(parents=True)
        self.source = {'content_hash': 'sha256:frozen', 'url': 'https://provider.example/docs'}
        self.document = {'info': {'x-aisa-source': self.source}, 'paths': {'/unchanged': {'get': {}}}}
        self.path.write_text(json.dumps(self.document))
        self.original = self.path.read_bytes()
        self.fixture = {'schema_version': 1, 'scope': 'offline proposal', 'archive_sha256': ARCHIVE_SHA256,
                        'sources': {'source.json': {'source_hash': 'sha256:frozen',
                                                  'authority_url': self.source['url'],
                                                  'policy': {'owner': 'fixture-owner'}}}}

    def apply(self, fixture):
        apply_policy_fixture(self.root, fixture, ('owner',), lambda metadata: [])

    def rejected_without_writes(self, fixture):
        with self.assertRaises(ValueError):
            self.apply(fixture)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_only_proposed_policy_changes(self):
        self.apply(self.fixture)
        expected = copy.deepcopy(self.document)
        expected['info']['x-aisa-source']['owner'] = 'fixture-owner'
        self.assertEqual(json.loads(self.path.read_text()), expected)

    def test_cannot_smuggle_review_receipt(self):
        self.fixture['sources']['source.json']['reviewer'] = 'not-a-real-review'
        self.rejected_without_writes(self.fixture)

    def test_cannot_change_source_authority_or_content(self):
        for key, value in [('source_hash', 'sha256:changed'), ('authority_url', 'https://different.example')]:
            fixture = copy.deepcopy(self.fixture)
            fixture['sources']['source.json'][key] = value
            self.rejected_without_writes(fixture)

    def test_cannot_add_approval_as_policy(self):
        self.fixture['sources']['source.json']['policy']['last_successful_review_at'] = '2026-10-03T00:00:00Z'
        self.rejected_without_writes(self.fixture)

    def test_archive_and_inventory_binding_are_required(self):
        wrong_archive = copy.deepcopy(self.fixture)
        wrong_archive['archive_sha256'] = 'changed'
        self.rejected_without_writes(wrong_archive)
        self.fixture['sources']['extra.json'] = self.fixture['sources']['source.json']
        self.rejected_without_writes(self.fixture)


if __name__ == '__main__':
    unittest.main()
